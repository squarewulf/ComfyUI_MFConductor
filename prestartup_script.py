"""
MF Conductor Prestartup Script
Runs before ComfyUI loads custom nodes so profile-excluded packages
appear uninstalled to importlib.util.find_spec() and to import.
"""
import os
import sys
import importlib.metadata


def _patch_stream(stream):
    """Swallow Windows pipe EINVAL/EBADF without replacing stdout/stderr objects."""
    if stream is None or getattr(stream, '_mf_safe_stdio', False):
        return
    orig_write = stream.write
    orig_flush = stream.flush

    def write(data):
        try:
            return orig_write(data)
        except OSError as exc:
            if getattr(exc, 'errno', None) not in (9, 22):
                raise
            return len(data) if isinstance(data, (str, bytes, bytearray)) else 0

    def flush():
        try:
            orig_flush()
        except OSError as exc:
            if getattr(exc, 'errno', None) not in (9, 22):
                raise

    try:
        stream.write = write
        stream.flush = flush
        stream._mf_safe_stdio = True
    except (AttributeError, TypeError):
        return
    _patch_stream(getattr(stream, 'buffer', None))


def _harden_stdio():
    _patch_stream(getattr(sys, 'stdout', None))
    _patch_stream(getattr(sys, 'stderr', None))


_harden_stdio()

# IndexTTS / librosa: SVML-patched llvmlite aborts on AMD without svml_dispmd.dll
os.environ.setdefault("NUMBA_DISABLE_INTEL_SVML", "1")


# Keep in sync with workflow_analyzer.CORE_PIP_PACKAGES / COMFY_INTERNAL_MODULES.
# Do not import that module here — prestartup must stay tiny.
_CORE_PIP = frozenset({
    'torch', 'torchvision', 'torchaudio', 'numpy', 'pillow', 'pil',
    'safetensors', 'transformers', 'aiohttp', 'yarl', 'requests',
    'tqdm', 'psutil', 'scipy', 'einops', 'kornia', 'comfy', 'comfyui',
    'tokenizers', 'huggingface-hub', 'huggingface_hub', 'sentencepiece',
    'protobuf', 'pyyaml', 'yaml', 'typing-extensions', 'typing_extensions',
    'filelock', 'packaging', 'regex', 'fsspec', 'networkx', 'jinja2',
    'markupsafe', 'sympy', 'mpmath', 'pip', 'setuptools', 'wheel',
})
_COMFY_INTERNAL = frozenset({
    'nodes', 'folder_paths', 'execution', 'server', 'app',
    'comfy', 'comfy_api', 'comfy_extras', 'comfy_execution',
    'latent_preview', 'cuda_malloc', 'utils', 'protocol',
    'new_updater', 'hook_breaker_ac10a0',
})


def _never_block_name(name):
    if not name:
        return True
    raw = name.strip().lower()
    key = raw.split('.')[0].replace('-', '_')
    if key in _CORE_PIP or raw in _CORE_PIP:
        return True
    if key in _COMFY_INTERNAL:
        return True
    return key in getattr(sys, 'stdlib_module_names', ()) or key in sys.builtin_module_names


def _is_blocked(fullname, blocked):
    parts = fullname.split('.')
    for i in range(len(parts)):
        if '.'.join(parts[:i + 1]) in blocked:
            return True
    return False


def _distribution_modules(distribution):
    """Use owned import paths so shared namespace parents remain available."""
    candidates = set()
    for file in distribution.files or ():
        if not str(file).endswith(('.py', '.pyd', '.so')):
            continue
        parts = list(file.parts)
        parts[-1] = parts[-1].split('.')[0]
        if parts[-1] == '__init__':
            parts.pop()
        if parts and all(part.isidentifier() and part != '__pycache__' for part in parts):
            candidates.add('.'.join(parts))
    if not candidates:
        candidates.update((distribution.read_text('top_level.txt') or '').split())
    modules = set()
    for name in sorted(candidates, key=lambda value: (value.count('.'), value)):
        if not _is_blocked(name, modules):
            modules.add(name)
    return modules


def _resolve_blocked_modules(packages):
    modules = set()
    for name in packages:
        name = name.strip().split('[')[0]
        if _never_block_name(name):
            continue
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            # Explicit import names are also accepted (e.g. cv2).
            names = {name}
        else:
            names = _distribution_modules(distribution)
            if not names:
                print(f"[MF Conductor] Cannot resolve import names for {name}; exclusion skipped")
        modules.update(
            module for module in names
            if all(part.isidentifier() for part in module.split('.'))
            and not _never_block_name(module)
        )
    return modules


class WrappedFinder:
    """Delegates to an existing meta_path finder, hiding blocked names."""

    def __init__(self, original, blocked):
        object.__setattr__(self, '_original', original)
        object.__setattr__(self, '_blocked', blocked)

    def find_spec(self, fullname, path=None, target=None):
        if _is_blocked(fullname, self._blocked) and not _never_block_name(fullname.split('.')[0]):
            return None
        orig = self._original
        finder = getattr(orig, 'find_spec', None)
        if finder is None:
            return None
        return finder(fullname, path, target)

    def find_module(self, fullname, path=None):
        if _is_blocked(fullname, self._blocked) and not _never_block_name(fullname.split('.')[0]):
            return None
        orig = self._original
        finder = getattr(orig, 'find_module', None)
        if finder is None:
            return None
        return finder(fullname, path)

    def invalidate_caches(self):
        orig = self._original
        fn = getattr(orig, 'invalidate_caches', None)
        if fn:
            fn()

    def __getattr__(self, name):
        return getattr(self._original, name)


def _blocked_from_persist():
    path = os.path.join(os.path.dirname(__file__), 'data', 'blocked_packages.txt')
    try:
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as handle:
                return handle.read().strip()
    except OSError:
        pass
    return ''


def block_packages_from_env():
    blocked_raw = os.environ.get('MFCONDUCTOR_BLOCKED_PACKAGES', '')
    source = 'MFCONDUCTOR_BLOCKED_PACKAGES'
    if not blocked_raw:
        blocked_raw = _blocked_from_persist()
        source = 'data/blocked_packages.txt (apply a profile without exclusions to clear)'
    if not blocked_raw:
        return

    packages = [
        p.strip() for p in blocked_raw.split(',')
        if p.strip() and not _never_block_name(p)
    ]
    if not packages:
        return

    blocked = _resolve_blocked_modules(packages)
    if not blocked:
        return
    print(f"[MF Conductor] Blocking {len(blocked)} imports from {source}: {', '.join(sorted(blocked))}")
    wrapped = []
    for finder in sys.meta_path:
        if isinstance(finder, WrappedFinder):
            wrapped.append(finder)
        else:
            wrapped.append(WrappedFinder(finder, blocked))
    sys.meta_path[:] = wrapped

    for pkg in blocked:
        to_remove = [key for key in list(sys.modules) if key == pkg or key.startswith(f"{pkg}.")]
        for key in to_remove:
            del sys.modules[key]


block_packages_from_env()

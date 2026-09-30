"""
List and analyze ComfyUI workflows under user/default/workflows.
Maps graph nodes to installed custom-node folders for isolated launch.
"""

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

try:
    from .node_scanner import CustomNode, normalize_name, parse_requirement_line
    from .security_utils import resolve_under, valid_pip_package
    from .user_data import UserDataManager, is_required_node_folder, merge_required_folders
except ImportError:
    from node_scanner import CustomNode, normalize_name, parse_requirement_line
    from security_utils import resolve_under, valid_pip_package
    from user_data import UserDataManager, is_required_node_folder, merge_required_folders

WORKFLOWS_REL = ('user', 'default', 'workflows')
MAX_WORKFLOWS = 500
MAX_LAUNCH_WORKFLOWS = 25
MAX_PATH_LEN = 400
PENDING_WORKFLOW_FILE = Path(__file__).parent / 'data' / 'pending_workflow.json'
INDEX_CACHE_FILE = Path(__file__).parent / 'data' / 'workflow_index_cache.json'
INDEX_CACHE_VERSION = 1

CORE_CNR_IDS = frozenset({'comfy-core', 'comfyui-core'})
FRONTEND_TYPES = frozenset({
    'PrimitiveNode', 'Reroute', 'Note', 'MarkdownNote',
    'Primitive float', 'Primitive integer', 'Primitive string', 'Primitive boolean',
})
TYPE_FOLDER_HINTS = {
    'GetNode': 'ComfyUI-KJNodes',
    'SetNode': 'ComfyUI-KJNodes',
    'EasyCache': 'ComfyUI-KJNodes',
    'ComfyUILTX25MSRICLoRALoader': 'ComfyUI-LTX2.5-MSR',
    'ComfyUILTX25MSRMultiReferenceGuide': 'ComfyUI-LTX2.5-MSR',
    'Hy3DBakeFromMultiview': 'ComfyUI-Hunyuan3DWrapper',
    'Hy3DRenderMultiView': 'ComfyUI-Hunyuan3DWrapper',
    'DownloadAndLoadHy3DPaintModel': 'ComfyUI-Hunyuan3DWrapper',
    'Trellis2ExportMesh': 'ComfyUI-Trellis2',
    'Trellis2FillHolesWithMeshlib': 'ComfyUI-Trellis2',
    'Trellis2LoadImageWithTransparency': 'ComfyUI-Trellis2',
    'Trellis2LoadModel': 'ComfyUI-Trellis2',
    'Trellis2MeshWithVoxelMultiViewGenerator': 'ComfyUI-Trellis2',
    'Trellis2MeshWithVoxelToTrimesh': 'ComfyUI-Trellis2',
    'Trellis2PreProcessImage': 'ComfyUI-Trellis2',
    'Trellis2RemeshWithQuad': 'ComfyUI-Trellis2',
    'Trellis2SimplifyMesh': 'ComfyUI-Trellis2',
}
CNR_FOLDER_ALIASES = {
    'comfyui-hunyan3dwrapper': 'ComfyUI-Hunyuan3DWrapper',
    'comfyui-hunyuan3dwrapper': 'ComfyUI-Hunyuan3DWrapper',
    'image-fitlers': 'ComfyUI-Image-Filters',
}
UUID_RE = re.compile(
    r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
)

CORE_PIP_PACKAGES = frozenset({
    'torch', 'torchvision', 'torchaudio', 'numpy', 'pillow', 'pil',
    'safetensors', 'transformers', 'aiohttp', 'yarl', 'requests',
    'tqdm', 'psutil', 'scipy', 'einops', 'kornia', 'comfy', 'comfyui',
    'tokenizers', 'huggingface-hub', 'huggingface_hub', 'sentencepiece',
    'protobuf', 'pyyaml', 'yaml', 'typing-extensions', 'typing_extensions',
    'filelock', 'packaging', 'regex', 'fsspec', 'networkx', 'jinja2',
    'markupsafe', 'sympy', 'mpmath', 'pip', 'setuptools', 'wheel',
})
COMFY_INTERNAL_MODULES = frozenset({
    'nodes', 'folder_paths', 'execution', 'server', 'app',
    'comfy', 'comfy_api', 'comfy_extras', 'comfy_execution',
    'latent_preview', 'cuda_malloc', 'utils', 'protocol',
    'new_updater', 'hook_breaker_ac10a0',
})


def is_never_block_package(name: str) -> bool:
    """True for stdlib, ComfyUI internals, and core pip names that must stay importable."""
    if not name:
        return True
    key = name.strip().lower().split('.')[0].replace('-', '_')
    if key in CORE_PIP_PACKAGES or name.strip().lower() in CORE_PIP_PACKAGES:
        return True
    if key in COMFY_INTERNAL_MODULES:
        return True
    if key in getattr(sys, 'stdlib_module_names', ()) or key in sys.builtin_module_names:
        return True
    return False


def _compact_name(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (name or '').lower())


def _type_aliases(node_type: str) -> List[str]:
    names = [node_type]
    if node_type and '|' in node_type:
        names.append(node_type.split('|', 1)[0])
    aliases = []
    seen = set()
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        aliases.append(name)
        if name.endswith('Node'):
            alt = name[:-4]
        else:
            alt = name + 'Node'
        if alt and alt not in seen:
            seen.add(alt)
            aliases.append(alt)
    return aliases


def _shared_stem_len(left: str, right: str) -> int:
    if len(left) > len(right):
        left, right = right, left
    for size in range(len(left), 7, -1):
        for start in range(0, len(left) - size + 1):
            if left[start:start + size] in right:
                return size
    return 0


def _load_index_cache() -> Dict[str, Any]:
    empty = {'version': INDEX_CACHE_VERSION, 'files': {}}
    if not INDEX_CACHE_FILE.is_file():
        return empty
    try:
        data = json.loads(INDEX_CACHE_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return empty
    if not isinstance(data, dict) or data.get('version') != INDEX_CACHE_VERSION:
        return empty
    files = data.get('files')
    if not isinstance(files, dict):
        return empty
    return data


def _save_index_cache(cache: Dict[str, Any]) -> None:
    INDEX_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = INDEX_CACHE_FILE.with_suffix('.tmp')
    tmp_path.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
    tmp_path.replace(INDEX_CACHE_FILE)


def _index_workflow_dict(workflow: Any) -> Dict[str, Any]:
    if not isinstance(workflow, dict):
        return {'error': 'Invalid workflow JSON'}
    entries = []
    node_types: Set[str] = set()
    node_count = 0
    for node in _iter_graph_nodes(workflow):
        node_type = node.get('type') or node.get('class_type') or ''
        properties = node.get('properties') if isinstance(node.get('properties'), dict) else {}
        cnr_id = properties.get('cnr_id') or ''
        aux_id = properties.get('aux_id') or ''
        if not node_type and not cnr_id:
            continue
        if _is_frontend_type(node_type) and not cnr_id:
            continue
        node_count += 1
        if node_type and not _is_frontend_type(node_type):
            node_types.add(node_type)
        entries.append([node_type, cnr_id, aux_id])
    return {
        'node_count': node_count,
        'node_types': sorted(node_types, key=str.lower),
        'entries': entries,
    }


def _index_workflow_file(file_path: Path) -> Dict[str, Any]:
    try:
        with open(file_path, 'r', encoding='utf-8') as handle:
            workflow = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {'error': 'Invalid workflow JSON'}
    return _index_workflow_dict(workflow)


def _is_frontend_type(node_type: str) -> bool:
    if not node_type:
        return True
    if node_type in FRONTEND_TYPES:
        return True
    if UUID_RE.match(node_type):
        return True
    if node_type.startswith('workflow>'):
        return True
    return False


def _iter_graph_nodes(data: Any) -> Iterable[Dict[str, Any]]:
    if not isinstance(data, dict):
        return
    nodes = data.get('nodes')
    walked_nodes = False
    if isinstance(nodes, list):
        walked_nodes = True
        for node in nodes:
            if isinstance(node, dict):
                yield node
    elif isinstance(nodes, dict):
        walked_nodes = True
        for value in nodes.values():
            if isinstance(value, dict):
                yield value
    definitions = data.get('definitions')
    if isinstance(definitions, dict):
        subgraphs = definitions.get('subgraphs')
        if isinstance(subgraphs, list):
            for subgraph in subgraphs:
                yield from _iter_graph_nodes(subgraph)
        elif isinstance(subgraphs, dict):
            for subgraph in subgraphs.values():
                yield from _iter_graph_nodes(subgraph)
    extra = data.get('extra')
    if isinstance(extra, dict):
        group_nodes = extra.get('groupNodes')
        if isinstance(group_nodes, dict):
            for group in group_nodes.values():
                yield from _iter_graph_nodes(group)
    if walked_nodes:
        return
    for value in data.values():
        if isinstance(value, dict) and isinstance(value.get('class_type'), str):
            yield {
                'type': value['class_type'],
                'properties': value.get('properties') or {},
            }


def _requirement_names(folder_path: Path) -> List[str]:
    req_file = folder_path / 'requirements.txt'
    if not req_file.is_file():
        return []
    names = []
    try:
        text = req_file.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return []
    for line in text.splitlines():
        parsed = parse_requirement_line(line)
        if not parsed or parsed.get('is_git'):
            continue
        name = parsed.get('name') or ''
        if valid_pip_package(name):
            names.append(name)
    return names


def _node_dir(custom_nodes_path: Path, folder: str) -> Optional[Path]:
    active = custom_nodes_path / folder
    if active.is_dir():
        return active
    disabled = custom_nodes_path / f'{folder}.disabled'
    if disabled.is_dir():
        return disabled
    return None


def _folder_has_type(folder_path: Path, node_type: str) -> bool:
    if not node_type or len(node_type) < 3:
        return False
    needles = (f'"{node_type}"', f"'{node_type}'")
    candidates: List[Path] = []
    init_file = folder_path / '__init__.py'
    if init_file.is_file():
        candidates.append(init_file)
    for name in ('web', 'js'):
        root = folder_path / name
        if root.is_dir():
            try:
                candidates.extend(path for path in root.rglob('*.js') if path.is_file())
            except OSError:
                pass
    skip_dirs = {'.git', '__pycache__', 'node_modules', 'venv', '.venv'}
    try:
        for path in folder_path.rglob('*.py'):
            if not path.is_file() or path.name.startswith('test_'):
                continue
            parts = {p.lower() for p in path.relative_to(folder_path).parts}
            if parts & skip_dirs:
                continue
            candidates.append(path)
            if len(candidates) >= 40:
                break
    except OSError:
        pass
    seen = set()
    for path in candidates[:60]:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')[:200000]
        except OSError:
            continue
        if any(needle in text for needle in needles):
            return True
    return False


def normalize_workflow_paths(rel_path: Any = None, rel_paths: Any = None) -> List[str]:
    raw = []
    if isinstance(rel_paths, list):
        raw.extend(rel_paths)
    if rel_path:
        raw.insert(0, rel_path)
    out = []
    seen = set()
    for item in raw:
        path = str(item or '').replace('\\', '/').strip().lstrip('/')
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
        if len(out) >= MAX_LAUNCH_WORKFLOWS:
            break
    return out


def persist_pending_workflow(rel_path: str, extra_paths: Optional[Iterable[str]] = None) -> None:
    paths = normalize_workflow_paths(rel_path, list(extra_paths or []))
    if not paths:
        return
    PENDING_WORKFLOW_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_WORKFLOW_FILE.write_text(
        json.dumps({'path': paths[0], 'paths': paths}, ensure_ascii=False),
        encoding='utf-8',
    )


def read_pending_workflow_path() -> Optional[str]:
    paths = read_pending_workflow_paths()
    return paths[0] if paths else None


def read_pending_workflow_paths() -> List[str]:
    if not PENDING_WORKFLOW_FILE.is_file():
        return []
    try:
        data = json.loads(PENDING_WORKFLOW_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    return normalize_workflow_paths(data.get('path'), data.get('paths'))


def clear_pending_workflow() -> None:
    try:
        if PENDING_WORKFLOW_FILE.exists():
            PENDING_WORKFLOW_FILE.unlink()
    except OSError:
        pass


def apply_enabled_folders(scanner, enabled_folders: Iterable[str]) -> Dict[str, List[str]]:
    """Enable the given folders plus always-on packs; disable the rest."""
    results = {'enabled': [], 'disabled': [], 'kept': [], 'errors': []}
    enabled_folders = merge_required_folders(enabled_folders, scanner.list_folder_names())
    enabled_set = {
        str(name).removesuffix('.disabled').lower()
        for name in enabled_folders if name
    }
    for folder in scanner.list_folder_names():
        if folder.lower() in enabled_set or is_required_node_folder(folder):
            ok, msg = scanner.activate_node(folder)
            if ok:
                results['enabled'].append(folder)
            elif 'already' in msg.lower():
                results['kept'].append(folder)
            elif 'not found' not in msg.lower():
                results['errors'].append(f'{folder}: {msg}')
        else:
            ok, msg = scanner.deactivate_node(folder)
            if ok:
                results['disabled'].append(folder)
            elif 'already' not in msg.lower() and 'not found' not in msg.lower():
                results['errors'].append(f'{folder}: {msg}')
    return results


def folders_for_workflow_launch(analysis: Dict[str, Any], all_folders: Iterable[str], extra_folders=()) -> List[str]:
    """Isolation set for a launched workflow: mapped packs plus always-on folders."""
    all_folders = list(all_folders)
    known = {name.lower(): name for name in all_folders}
    if not isinstance(extra_folders, (list, tuple)) or any(not isinstance(name, str) for name in extra_folders):
        raise ValueError('Extra nodes must be a list of installed folder names')
    extra = []
    for name in extra_folders:
        key = name.removesuffix('.disabled').lower()
        if key not in known:
            raise ValueError(f'Extra node is not installed: {name}')
        extra.append(known[key])
    return merge_required_folders(list(analysis.get('required_folders') or []) + extra, all_folders)


def folders_for_profile(profile: dict, all_folders: Iterable[str]) -> List[str]:
    """Enabled set for a profile. Empty enabled means all folders minus disabled."""
    enabled_list = [str(f).removesuffix('.disabled') for f in (profile.get('enabled') or []) if f]
    disabled_list = [str(f).removesuffix('.disabled') for f in (profile.get('disabled') or []) if f]
    if enabled_list:
        return merge_required_folders(enabled_list, all_folders)
    disabled_set = {name.lower() for name in disabled_list}
    return merge_required_folders(
        [folder for folder in all_folders if folder.lower() not in disabled_set],
        all_folders,
    )


class WorkflowAnalyzer:
    def __init__(self, comfy_root: Path, scanner):
        self.comfy_root = Path(comfy_root)
        self.scanner = scanner
        self.custom_nodes_path = Path(scanner.custom_nodes_path)
        self.workflows_root = self.comfy_root.joinpath(*WORKFLOWS_REL)
        self._enriched_nodes = None
        self._type_search_cache = {}

    def reset_maps(self) -> None:
        self._enriched_nodes = None
        self._type_search_cache = {}

    def resolve_workflow(self, rel_path: str) -> Tuple[Optional[Path], str]:
        if not rel_path or not isinstance(rel_path, str):
            return None, 'Workflow path required'
        rel_path = rel_path.replace('\\', '/').strip().lstrip('/')
        if not rel_path or len(rel_path) > MAX_PATH_LEN or rel_path.startswith('-'):
            return None, 'Invalid workflow path'
        if not rel_path.lower().endswith('.json'):
            return None, 'Workflow must be a .json file'
        if not self.workflows_root.is_dir():
            return None, 'Workflows folder not found'
        resolved = resolve_under(self.workflows_root, *rel_path.split('/'))
        if resolved is None or not resolved.is_file():
            return None, 'Workflow not found'
        return resolved, ''

    def list_workflows(self, installed_nodes: Optional[List[Dict]] = None) -> Dict[str, Any]:
        if not self.workflows_root.is_dir():
            return {
                'success': True,
                'root': '/'.join(WORKFLOWS_REL),
                'exists': False,
                'workflows': [],
            }

        mapping = self._build_maps(installed_nodes or [])
        cache = _load_index_cache()
        cached_files = cache.setdefault('files', {})
        listed = []
        missing_indexes = []
        files = sorted(self.workflows_root.rglob('*.json'))
        for file_path in files[:MAX_WORKFLOWS]:
            if not file_path.is_file():
                continue
            try:
                rel = file_path.relative_to(self.workflows_root).as_posix()
            except ValueError:
                continue
            try:
                stat = file_path.stat()
            except OSError:
                continue
            mtime = int(stat.st_mtime)
            size = stat.st_size
            hit = cached_files.get(rel)
            if (
                isinstance(hit, dict)
                and hit.get('mtime') == mtime
                and hit.get('size') == size
                and 'entries' in hit
            ):
                listed.append((rel, file_path, hit))
            else:
                missing_indexes.append((rel, file_path, mtime, size))

        if missing_indexes:
            def _index_one(item):
                rel, file_path, mtime, size = item
                index = _index_workflow_file(file_path)
                index['mtime'] = mtime
                index['size'] = size
                return rel, file_path, index

            workers = min(8, len(missing_indexes))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for rel, file_path, index in pool.map(_index_one, missing_indexes):
                    cached_files[rel] = index
                    listed.append((rel, file_path, index))
            keep = {rel for rel, _path, _index in listed}
            cache['files'] = {key: value for key, value in cached_files.items() if key in keep}
            try:
                _save_index_cache(cache)
            except OSError:
                pass

        workflows = []
        for rel, file_path, index in listed:
            summary = self._summarize_index(index, mapping, include_packages=False)
            workflows.append({
                'name': file_path.stem,
                'filename': file_path.name,
                'path': rel,
                'folder': str(Path(rel).parent).replace('\\', '/') if Path(rel).parent.as_posix() != '.' else '',
                'mtime': index.get('mtime') or 0,
                'size': index.get('size') or 0,
                'node_count': summary.get('node_count', 0),
                'custom_folders': summary.get('required_folders', []),
                'missing_folders': summary.get('missing_folders', []),
                'unmapped_types': summary.get('unmapped_types', []),
            })

        return {
            'success': True,
            'root': '/'.join(WORKFLOWS_REL),
            'exists': True,
            'workflows': workflows,
        }

    def analyze(self, rel_path: str, installed_nodes: Optional[List[Dict]] = None,
                include_packages: bool = True) -> Dict[str, Any]:
        file_path, error = self.resolve_workflow(rel_path)
        if file_path is None:
            return {'success': False, 'message': error}

        mapping = self._build_maps(self._enrich_installed_nodes(installed_nodes or [], live=False))
        rel = rel_path.replace('\\', '/').strip().lstrip('/')
        result = self._summarize_index(
            self._index_for_file(file_path, rel), mapping, include_packages, search_unmapped=False
        )
        result['path'] = rel
        result['name'] = file_path.stem
        if result.get('error'):
            result['success'] = False
            result['message'] = result['error']
            return result
        result['success'] = True
        return result

    def analyze_many(self, rel_paths: List[str], installed_nodes: Optional[List[Dict]] = None,
                     include_packages: bool = False) -> Dict[str, Any]:
        mapping = self._build_maps(self._enrich_installed_nodes(installed_nodes or [], live=False))
        cache = _load_index_cache()
        analyses = []
        for rel_path in rel_paths:
            file_path, error = self.resolve_workflow(rel_path)
            if file_path is None:
                return {'success': False, 'message': error, 'path': rel_path}
            rel = rel_path.replace('\\', '/').strip().lstrip('/')
            result = self._summarize_index(
                self._index_for_file(file_path, rel, cache), mapping, include_packages, search_unmapped=False
            )
            result['path'] = rel
            result['name'] = file_path.stem
            if result.get('error'):
                result['success'] = False
                result['message'] = result['error']
                return result
            result['success'] = True
            analyses.append(result)
        return {'success': True, 'analyses': analyses}

    def _index_for_file(self, file_path: Path, rel: str, cache: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            stat = file_path.stat()
        except OSError:
            return _index_workflow_file(file_path)
        cache = cache if cache is not None else _load_index_cache()
        hit = (cache.get('files') or {}).get(rel)
        if (
            isinstance(hit, dict)
            and hit.get('mtime') == int(stat.st_mtime)
            and hit.get('size') == stat.st_size
            and 'entries' in hit
        ):
            return hit
        index = _index_workflow_file(file_path)
        index['mtime'] = int(stat.st_mtime)
        index['size'] = stat.st_size
        return index

    def pending_workflow_payload(self) -> Dict[str, Any]:
        rel_path = read_pending_workflow_path()
        if not rel_path:
            return {'success': True, 'pending': False}
        file_path, error = self.resolve_workflow(rel_path)
        if file_path is None:
            return {'success': False, 'pending': True, 'message': error, 'path': rel_path}
        try:
            with open(file_path, 'r', encoding='utf-8') as handle:
                workflow = json.load(handle)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {'success': False, 'pending': True, 'message': 'Invalid workflow JSON', 'path': rel_path}
        if not isinstance(workflow, dict):
            return {'success': False, 'pending': True, 'message': 'Invalid workflow JSON', 'path': rel_path}
        return {
            'success': True,
            'pending': True,
            'path': rel_path,
            'paths': read_pending_workflow_paths(),
            'name': file_path.stem,
            'workflow': workflow,
        }

    def _enrich_installed_nodes(self, installed_nodes: List[Dict], live: bool = True) -> List[Dict]:
        if not live:
            return list(installed_nodes)
        if self._enriched_nodes is not None:
            return self._enriched_nodes
        enriched = []
        for node in installed_nodes:
            provided = node.get('provided_nodes') or node.get('node_types') or []
            if provided:
                enriched.append(node)
                continue
            folder = str(node.get('base_folder_name') or node.get('folder_name') or '')
            folder = folder.removesuffix('.disabled')
            path = _node_dir(self.custom_nodes_path, folder) if folder else None
            live = []
            if path is not None:
                try:
                    live = CustomNode(str(path)).provided_nodes
                except Exception:
                    live = []
            if live:
                copy = dict(node)
                copy['provided_nodes'] = live
                enriched.append(copy)
            else:
                enriched.append(node)
        self._enriched_nodes = enriched
        return enriched

    def _build_maps(self, installed_nodes: List[Dict]) -> Dict[str, Any]:
        folders = self.scanner.list_folder_names()
        folder_exact = {name.lower(): name for name in folders}
        folder_norm = {}
        for name in folders:
            key = normalize_name(name)
            if key and key not in folder_norm:
                folder_norm[key] = name

        type_to_folders: Dict[str, Set[str]] = {}
        type_to_folders_ci: Dict[str, Set[str]] = {}
        for node in installed_nodes:
            folder = node.get('base_folder_name') or node.get('folder_name') or ''
            folder = str(folder).removesuffix('.disabled')
            if not folder:
                continue
            for node_type in node.get('provided_nodes') or node.get('node_types') or []:
                if not node_type:
                    continue
                type_to_folders.setdefault(node_type, set()).add(folder)
                type_to_folders_ci.setdefault(node_type.lower(), set()).add(folder)

        type_unique = {
            node_type: next(iter(folders_for_type))
            for node_type, folders_for_type in type_to_folders.items()
            if len(folders_for_type) == 1
        }
        type_unique_ci = {
            node_type: next(iter(folders_for_type))
            for node_type, folders_for_type in type_to_folders_ci.items()
            if len(folders_for_type) == 1
        }

        required_folders = []
        for name in UserDataManager.REQUIRED_NODES:
            actual = folder_exact.get(name.lower())
            if actual:
                required_folders.append(actual)

        return {
            'folders': folders,
            'folder_exact': folder_exact,
            'folder_norm': folder_norm,
            'type_unique': type_unique,
            'type_unique_ci': type_unique_ci,
            'type_to_folders': type_to_folders,
            'type_to_folders_ci': type_to_folders_ci,
            'required_folders': required_folders,
        }

    def _map_cnr(self, cnr_id: str, mapping: Dict[str, Any]) -> Optional[str]:
        if not cnr_id or cnr_id.lower() in CORE_CNR_IDS:
            return None
        alias = CNR_FOLDER_ALIASES.get(cnr_id.lower())
        if alias:
            mapped = mapping['folder_exact'].get(alias.lower())
            if mapped:
                return mapped
            mapped = mapping['folder_norm'].get(normalize_name(alias))
            if mapped:
                return mapped
        exact = mapping['folder_exact'].get(cnr_id.lower())
        if exact:
            return exact
        return mapping['folder_norm'].get(normalize_name(cnr_id))

    def _map_aux(self, aux_id: str, mapping: Dict[str, Any]) -> Optional[str]:
        folders = self._folders_for_aux(aux_id, mapping)
        return folders[0] if folders else None

    def _folders_for_aux(self, aux_id: str, mapping: Dict[str, Any]) -> List[str]:
        if not aux_id:
            return []
        name = str(aux_id).replace('\\', '/').rstrip('/').split('/')[-1]
        return self._folders_for_cnr(name, mapping)

    def _folders_for_cnr(self, cnr_id: str, mapping: Dict[str, Any]) -> List[str]:
        mapped = self._map_cnr(cnr_id, mapping)
        if mapped:
            return [mapped]
        needle = _compact_name(normalize_name(cnr_id))
        if len(needle) < 8:
            return []
        hits = []
        for folder in mapping.get('folders') or []:
            hay = _compact_name(normalize_name(folder))
            if len(hay) < 6:
                continue
            if needle in hay or hay in needle or _shared_stem_len(needle, hay) >= 8:
                hits.append(folder)
        return hits

    def _lookup_type(self, node_type: str, mapping: Dict[str, Any]) -> Optional[str]:
        return mapping['type_unique'].get(node_type) or mapping['type_unique_ci'].get(node_type.lower())

    def _map_type(self, node_type: str, mapping: Dict[str, Any]) -> Optional[str]:
        if not node_type:
            return None
        hint = TYPE_FOLDER_HINTS.get(node_type)
        if hint:
            mapped = self._map_cnr(hint, mapping)
            if mapped:
                return mapped
        for alias in _type_aliases(node_type):
            mapped = self._lookup_type(alias, mapping)
            if mapped:
                return mapped
        if node_type.endswith(' (rgthree)'):
            mapped = self._map_cnr('rgthree-comfy', mapping)
            if mapped:
                return mapped
        return None

    def _folders_for_type(self, node_type: str, mapping: Dict[str, Any]) -> List[str]:
        mapped = self._map_type(node_type, mapping)
        if mapped:
            return [mapped]
        folders = mapping.get('type_to_folders') or {}
        folders_ci = mapping.get('type_to_folders_ci') or {}
        found = set()
        for alias in _type_aliases(node_type):
            found.update(folders.get(alias) or ())
            found.update(folders_ci.get(alias.lower()) or ())
        return sorted(found, key=str.lower)

    def _search_type_in_folders(self, node_type: str, folders: Iterable[str]) -> List[str]:
        if not node_type or _is_frontend_type(node_type):
            return []
        cached = self._type_search_cache.get(node_type)
        if cached is not None:
            return list(cached)
        hits = []
        for folder in folders:
            path = _node_dir(self.custom_nodes_path, folder)
            if path is not None and _folder_has_type(path, node_type):
                hits.append(folder)
        self._type_search_cache[node_type] = hits
        return hits

    def _summarize_index(self, index: Dict[str, Any], mapping: Dict[str, Any],
                         include_packages: bool, search_unmapped: bool = False) -> Dict[str, Any]:
        required: Set[str] = set(mapping['required_folders'])
        missing: Set[str] = set()
        unmapped: Set[str] = set()
        cnr_ids: Set[str] = set()

        if index.get('error'):
            return {
                'node_count': 0,
                'node_types': [],
                'required_folders': [],
                'missing_folders': [],
                'unmapped_types': [],
                'cnr_ids': [],
                'pip_requirements': [],
                'blockable_packages': [],
                'error': index['error'],
            }

        for entry in index.get('entries') or []:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            node_type = entry[0] or ''
            cnr_id = entry[1] or ''
            aux_id = entry[2] if len(entry) > 2 else ''
            mapped_folders: Set[str] = set()
            core_cnr = bool(cnr_id) and cnr_id.lower() in CORE_CNR_IDS
            if cnr_id and not core_cnr:
                cnr_ids.add(cnr_id)
                mapped_folders.update(self._folders_for_cnr(cnr_id, mapping))
            if aux_id:
                mapped_folders.update(self._folders_for_aux(aux_id, mapping))
            if node_type and not _is_frontend_type(node_type):
                mapped_folders.update(self._folders_for_type(node_type, mapping))
            if mapped_folders:
                required.update(mapped_folders)
                continue
            if core_cnr or _is_frontend_type(node_type):
                continue
            found = []
            if search_unmapped:
                found = self._search_type_in_folders(node_type, mapping.get('folders') or [])
            if found:
                required.update(found)
            elif cnr_id:
                missing.add(cnr_id)
            elif node_type:
                unmapped.add(node_type)

        pip_requirements = []
        blockable = []
        if include_packages:
            enabled_pip: Set[str] = set()
            disabled_pip: Set[str] = set()
            for folder in mapping['folders']:
                folder_path = _node_dir(self.custom_nodes_path, folder)
                if folder_path is None:
                    continue
                names = _requirement_names(folder_path)
                if folder in required:
                    enabled_pip.update(names)
                    pip_requirements.extend(names)
                else:
                    disabled_pip.update(names)
            seen = set()
            unique_reqs = []
            for name in pip_requirements:
                key = name.lower()
                if key not in seen:
                    seen.add(key)
                    unique_reqs.append(name)
            pip_requirements = sorted(unique_reqs, key=str.lower)
            enabled_keys = {n.lower() for n in enabled_pip}
            blockable = sorted(
                {
                    name for name in disabled_pip
                    if name.lower() not in enabled_keys
                    and not is_never_block_package(name)
                },
                key=str.lower,
            )

        return {
            'node_count': index.get('node_count', 0),
            'node_types': list(index.get('node_types') or []),
            'required_folders': sorted(required, key=str.lower),
            'missing_folders': sorted(missing, key=str.lower),
            'unmapped_types': sorted(unmapped, key=str.lower),
            'cnr_ids': sorted(cnr_ids, key=str.lower),
            'pip_requirements': pip_requirements,
            'blockable_packages': blockable,
        }

    def _analyze_file(self, file_path: Path, mapping: Dict[str, Any],
                      include_packages: bool) -> Dict[str, Any]:
        return self._summarize_index(
            _index_workflow_file(file_path), mapping, include_packages, search_unmapped=False
        )


_analyzer: Optional[WorkflowAnalyzer] = None


def get_workflow_analyzer(comfy_root: Path, scanner) -> WorkflowAnalyzer:
    global _analyzer
    if _analyzer is None or _analyzer.scanner is not scanner:
        _analyzer = WorkflowAnalyzer(comfy_root, scanner)
    return _analyzer

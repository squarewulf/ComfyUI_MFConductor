"""
Input, path, and request checks for MF Conductor API operations.
"""

import ipaddress
import re
import sys
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

NODE_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+ -]{0,200}$')
PIP_NAME_RE = re.compile(
    r'^[A-Za-z0-9][A-Za-z0-9._-]{0,80}(?:\[[A-Za-z0-9,_-]{1,40}\])?$'
)
PIP_VERSION_RE = re.compile(r'^[A-Za-z0-9._+-]{1,40}$')
COMMIT_RE = re.compile(r'^[0-9a-fA-F]{7,40}$')
GIT_SSH_RE = re.compile(r'^git@[\w.-]+:[\w./-]+(?:\.git)?$')

ALLOWED_USAGE_FOLDERS = frozenset({'output', 'input', 'user', 'temp'})
ALLOWED_FILE_FOLDERS = frozenset({'output', 'input', 'temp', 'both'})
ALLOWED_PIP_SUBCOMMANDS = frozenset({'list', 'show', 'freeze', 'check'})
MAX_PNG_CHUNK = 8 * 1024 * 1024

LOOPBACK_HOSTS = frozenset({
    '127.0.0.1', '::1', 'localhost', '::ffff:127.0.0.1',
})


def safe_node_name(folder_name: str) -> Tuple[bool, str]:
    """Return (ok, base_name_or_error). Strips a trailing .disabled suffix."""
    if not folder_name or not isinstance(folder_name, str):
        return False, 'Folder name required'
    name = folder_name.strip()
    if name.endswith('.disabled'):
        name = name[:-9]
    if not name or name in {'.', '..'} or '/' in name or '\\' in name:
        return False, 'Invalid folder name'
    if name.startswith('-') or name.startswith('.'):
        return False, 'Invalid folder name'
    if not NODE_NAME_RE.match(name):
        return False, 'Invalid folder name'
    return True, name


def contained_path(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def resolve_under(root: Path, *parts: str) -> Optional[Path]:
    try:
        candidate = root.joinpath(*parts).resolve()
    except (OSError, ValueError):
        return None
    if not contained_path(candidate, root):
        return None
    return candidate


def resolve_desktop_shortcut(save_path: Optional[str], default_name: str) -> Tuple[Optional[Path], str]:
    """Resolve a desktop shortcut path. Stays on Desktop when that folder exists."""
    desktop = Path.home() / 'Desktop'
    if not desktop.is_dir():
        desktop = Path.home()
    if not save_path:
        return desktop / default_name, ''
    name = Path(str(save_path)).name.strip()
    if not name or name in {'.', '..'}:
        return None, 'Invalid shortcut name'
    suffix = Path(default_name).suffix
    if suffix and not name.lower().endswith(suffix.lower()):
        name = name + suffix
    resolved = resolve_under(desktop, name)
    if resolved is None:
        return None, 'Shortcut must be saved on the Desktop'
    return resolved, ''


def read_bounded(file_obj, length: int, limit: int = MAX_PNG_CHUNK):
    """Read length bytes, or skip and return None when length exceeds limit."""
    if not isinstance(length, int) or length < 0:
        return None
    if length > limit:
        remaining = length
        while remaining > 0:
            chunk = file_obj.read(min(remaining, 65536))
            if not chunk:
                break
            remaining -= len(chunk)
        return None
    data = file_obj.read(length)
    if len(data) < length:
        return None
    return data


def valid_git_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if len(url) > 500 or url.startswith('-'):
        return False
    if url.startswith('git@'):
        return bool(GIT_SSH_RE.match(url))
    parsed = urlparse(url)
    if parsed.scheme not in ('https', 'http'):
        return False
    if not parsed.netloc or parsed.netloc.startswith('-'):
        return False
    if parsed.username or parsed.password:
        return False
    return True


def valid_pip_package(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    name = name.strip()
    if name.startswith('-') or '/' in name or '\\' in name or '://' in name:
        return False
    return bool(PIP_NAME_RE.match(name))


def valid_pip_version(version: str) -> bool:
    if not version:
        return True
    if not isinstance(version, str) or version.startswith('-'):
        return False
    return bool(PIP_VERSION_RE.match(version.strip()))


def valid_commit_hash(value: str) -> bool:
    return bool(value and isinstance(value, str) and COMMIT_RE.match(value.strip()))


def escape_ps_string(value: str) -> str:
    """Escape a value for embedding inside a PowerShell double-quoted string."""
    return str(value).replace('`', '``').replace('"', '`"').replace('$', '`$')


def _http_origin(url: str):
    try:
        parsed = urlparse(url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.params or parsed.query or parsed.fragment):
            return None
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == 'https' else 80)
        return parsed.scheme, parsed.hostname.lower(), port
    except ValueError:
        return None


def is_loopback_host(host: str) -> bool:
    origin = _http_origin('http://' + host)
    return origin is not None and origin[1] in LOOPBACK_HOSTS


def is_loopback_addr(addr: str) -> bool:
    if not addr:
        return False
    try:
        address = ipaddress.ip_address(addr.split('%')[0].strip('[]'))
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_loopback


def is_local_api_request(peer: str, host: str, headers, scheme: str = 'http') -> bool:
    if not is_loopback_addr(peer) or not is_loopback_host(host):
        return False
    if headers.get('Sec-Fetch-Site', '').lower() not in ('', 'same-origin', 'none'):
        return False
    origin = headers.get('Origin')
    if origin is not None:
        expected = _http_origin(f'{scheme}://{host}')
        if expected is None or _http_origin(origin) != expected:
            return False
    return True


def is_local_request(request) -> bool:
    """Require a loopback peer/Host and same-origin browser requests."""
    peer = getattr(request, 'remote', None) or ''
    host = getattr(request, 'host', None) or ''
    return is_local_api_request(peer, host, request.headers, request.scheme)


def find_comfy_python(comfy_root: Path) -> Path:
    portable = Path(comfy_root).parent
    for candidate in (
        portable / 'python_embeded' / 'python.exe',
        portable / 'python' / 'python.exe',
        Path(sys.executable),
    ):
        if candidate.exists():
            return candidate
    return Path(sys.executable)

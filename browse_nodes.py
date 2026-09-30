"""
MF_Conductor - Browse/Discover New Nodes
Allows browsing available nodes from ComfyUI-Manager database
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime
import urllib.request
import urllib.error

try:
    from .node_scanner import normalize_name
    from .security_utils import valid_git_url
except ImportError:
    from node_scanner import normalize_name
    from security_utils import valid_git_url


# ComfyUI-Manager custom node list URL
MANAGER_NODE_LIST_URL = "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/custom-node-list.json"

# Cache for the node database
_available_nodes_cache: Optional[List[Dict]] = None
_github_stats_cache: Optional[Dict] = None
_cache_timestamp: Optional[datetime] = None
CACHE_DURATION_HOURS = 6
MAX_MISSING_INSTALL = 40
PACK_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._\-]{1,120}$')
PACK_ALIASES = {
    'comfyui-hunyan3dwrapper': 'ComfyUI-Hunyuan3DWrapper',
    'comfyui-hunyuan3dwrapper': 'ComfyUI-Hunyuan3DWrapper',
    'image-fitlers': 'ComfyUI-Image-Filters',
}


def _load_github_stats() -> Dict:
    """Load GitHub star data from ComfyUI-Manager's github-stats.json"""
    global _github_stats_cache
    
    if _github_stats_cache is not None:
        return _github_stats_cache
    
    try:
        current_dir = Path(__file__).parent
        custom_nodes_dir = current_dir.parent
        
        # Check for ComfyUI-Manager's github-stats.json
        stats_paths = [
            custom_nodes_dir / 'ComfyUI-Manager' / 'github-stats.json',
            custom_nodes_dir / 'comfyui-manager' / 'github-stats.json',
        ]
        
        for path in stats_paths:
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    _github_stats_cache = json.load(f)
                    print(f"[MF Conductor] Loaded {len(_github_stats_cache)} GitHub stats entries")
                    return _github_stats_cache
        
        _github_stats_cache = {}
        return _github_stats_cache
    except Exception as e:
        print(f"[MF Conductor] Error loading GitHub stats: {e}")
        _github_stats_cache = {}
        return _github_stats_cache


def _load_local_manager_db() -> Optional[List[Dict]]:
    """Load node list from local ComfyUI-Manager installation"""
    try:
        current_dir = Path(__file__).parent
        custom_nodes_dir = current_dir.parent
        
        # Check for ComfyUI-Manager
        manager_paths = [
            custom_nodes_dir / 'ComfyUI-Manager' / 'custom-node-list.json',
            custom_nodes_dir / 'comfyui-manager' / 'custom-node-list.json',
        ]
        
        for path in manager_paths:
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'custom_nodes' in data:
                        return data['custom_nodes']
        
        return None
    except Exception as e:
        print(f"[MF Conductor] Error loading local manager DB: {e}")
        return None


def _fetch_remote_node_list() -> Optional[List[Dict]]:
    """Fetch node list from GitHub"""
    try:
        req = urllib.request.Request(
            MANAGER_NODE_LIST_URL,
            headers={'User-Agent': 'MF_Conductor/1.0'}
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            if 'custom_nodes' in data:
                return data['custom_nodes']
        
        return None
    except Exception as e:
        print(f"[MF Conductor] Error fetching remote node list: {e}")
        return None


def get_available_nodes(force_refresh: bool = False) -> List[Dict]:
    """Get list of all available nodes from ComfyUI-Manager database"""
    global _available_nodes_cache, _cache_timestamp
    
    # Check cache
    if not force_refresh and _available_nodes_cache is not None:
        if _cache_timestamp:
            age = datetime.now() - _cache_timestamp
            if age.total_seconds() < CACHE_DURATION_HOURS * 3600:
                return _available_nodes_cache
    
    # Try local first, then remote
    nodes = _load_local_manager_db()
    
    if not nodes:
        nodes = _fetch_remote_node_list()
    
    if nodes:
        _available_nodes_cache = nodes
        _cache_timestamp = datetime.now()
        return nodes
    
    return _available_nodes_cache or []


def get_installed_node_folders(custom_nodes_path: Optional[Path] = None) -> List[str]:
    """Get list of currently installed node folder names"""
    if custom_nodes_path is None:
        custom_nodes_path = Path(__file__).parent.parent
    
    installed = []
    for item in custom_nodes_path.iterdir():
        if item.is_dir() and not item.name.startswith('.'):
            installed.append(item.name.lower())
            # Also add without comfyui prefix
            name_lower = item.name.lower()
            if name_lower.startswith('comfyui-'):
                installed.append(name_lower[8:])
            elif name_lower.startswith('comfyui_'):
                installed.append(name_lower[8:])
    
    return installed


def _extract_repo_name(url: str) -> Optional[str]:
    """Extract repository name from GitHub URL"""
    if not url:
        return None
    
    match = re.search(r'github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$', url)
    if match:
        return match.group(2).lower()
    return None


def browse_nodes(
    search: str = '',
    category: str = '',
    installed_only: bool = False,
    not_installed_only: bool = False,
    sort_by: str = 'stars',
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """Browse available nodes with filtering and pagination"""
    
    all_nodes = get_available_nodes()
    installed_folders = get_installed_node_folders()
    github_stats = _load_github_stats()
    
    # Process and filter nodes
    results = []
    
    for node in all_nodes:
        # Determine if installed
        reference = node.get('reference', '')
        repo_name = _extract_repo_name(reference)
        
        is_installed = False
        if repo_name:
            is_installed = repo_name.lower() in installed_folders
            # Also check full URL-based folder names
            if not is_installed:
                for folder in installed_folders:
                    if repo_name.lower() in folder or folder in repo_name.lower():
                        is_installed = True
                        break
        
        # Apply installed filters
        if installed_only and not is_installed:
            continue
        if not_installed_only and is_installed:
            continue
        
        # Apply search filter
        if search:
            search_lower = search.lower()
            title = node.get('title', '').lower()
            description = node.get('description', '').lower()
            author = node.get('author', '').lower()
            
            if not (search_lower in title or search_lower in description or search_lower in author):
                continue
        
        # Apply category filter
        if category:
            node_cats = [c.lower() for c in node.get('categories', [])]
            if category.lower() not in node_cats:
                continue
        
        # Get star count from github-stats.json
        stars = 0
        if reference:
            # Try exact match first
            stats = github_stats.get(reference)
            if stats:
                stars = stats.get('stars', 0)
            else:
                # Try without trailing .git or /
                ref_clean = reference.rstrip('/').rstrip('.git').rstrip('/')
                stats = github_stats.get(ref_clean)
                if stats:
                    stars = stats.get('stars', 0)
        
        # Build result object
        result = {
            'title': node.get('title', 'Unknown'),
            'author': node.get('author', 'Unknown'),
            'description': node.get('description', ''),
            'reference': reference,
            'install_type': node.get('install_type', 'git-clone'),
            'categories': node.get('categories', []),
            'stars': stars,
            'is_installed': is_installed,
            'pip_packages': node.get('pip', []) if isinstance(node.get('pip'), list) else [],
        }
        
        results.append(result)
    
    # Sort results
    if sort_by == 'stars':
        results.sort(key=lambda x: x.get('stars', 0) or 0, reverse=True)
    elif sort_by == 'name':
        results.sort(key=lambda x: x.get('title', '').lower())
    elif sort_by == 'author':
        results.sort(key=lambda x: x.get('author', '').lower())
    
    # Get all unique categories for filtering UI
    all_categories = set()
    for node in all_nodes:
        for cat in node.get('categories', []):
            all_categories.add(cat)
    
    # Paginate
    total = len(results)
    results = results[offset:offset + limit]
    
    return {
        'nodes': results,
        'total': total,
        'offset': offset,
        'limit': limit,
        'categories': sorted(list(all_categories))
    }


def get_node_details(reference_url: str) -> Optional[Dict]:
    """Get detailed info for a specific node by its reference URL"""
    all_nodes = get_available_nodes()
    github_stats = _load_github_stats()
    
    for node in all_nodes:
        if node.get('reference') == reference_url:
            # Get star count
            stars = 0
            stats = github_stats.get(reference_url)
            if stats:
                stars = stats.get('stars', 0)
            else:
                ref_clean = reference_url.rstrip('/').rstrip('.git').rstrip('/')
                stats = github_stats.get(ref_clean)
                if stats:
                    stars = stats.get('stars', 0)
            
            return {
                'title': node.get('title', 'Unknown'),
                'author': node.get('author', 'Unknown'),
                'description': node.get('description', ''),
                'reference': reference_url,
                'install_type': node.get('install_type', 'git-clone'),
                'categories': node.get('categories', []),
                'stars': stars,
                'pip_packages': node.get('pip', []) if isinstance(node.get('pip'), list) else [],
                'files': node.get('files', []),
            }
    
    return None


def get_categories() -> List[str]:
    """Get list of all available node categories"""
    all_nodes = get_available_nodes()
    categories = set()
    
    for node in all_nodes:
        for cat in node.get('categories', []):
            categories.add(cat)
    
    return sorted(list(categories))


def refresh_node_database() -> bool:
    """Force refresh the node database from remote"""
    global _available_nodes_cache, _github_stats_cache, _cache_timestamp
    
    # Clear caches
    _github_stats_cache = None
    
    nodes = _fetch_remote_node_list()
    if nodes:
        _available_nodes_cache = nodes
        _cache_timestamp = datetime.now()
        # Reload github stats
        _load_github_stats()
        return True
    return False


def _clean_pack_names(names: Optional[List[str]]) -> List[str]:
    cleaned = []
    seen = set()
    for raw in names or []:
        name = str(raw or '').strip()
        if not name or not PACK_NAME_RE.match(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(name)
        if len(cleaned) >= MAX_MISSING_INSTALL:
            break
    return cleaned


def _entry_install_url(node: Dict[str, Any]) -> str:
    files = node.get('files') or []
    if files and isinstance(files[0], str) and files[0].strip():
        return files[0].strip()
    return (node.get('reference') or '').strip()


def _entry_folder_name(url: str, fallback: str) -> str:
    repo = url.rstrip('/').split('/')[-1]
    if repo.endswith('.git'):
        repo = repo[:-4]
    return repo or fallback


def resolve_missing_packs(names: Optional[List[str]]) -> Dict[str, Any]:
    """Map workflow CNR ids to Manager git-clone entries. Exact/unique matches only."""
    cleaned = _clean_pack_names(names)
    nodes = get_available_nodes()
    by_id: Dict[str, Dict[str, Any]] = {}
    by_repo: Dict[str, Dict[str, Any]] = {}
    by_norm: Dict[str, List[Dict[str, Any]]] = {}
    by_compact: Dict[str, List[Dict[str, Any]]] = {}

    def _add_index(index, key, node):
        if not key:
            return
        bucket = index.setdefault(key, [])
        if node not in bucket:
            bucket.append(node)

    for node in nodes:
        nid = (node.get('id') or '').strip().lower()
        title = node.get('title') or ''
        url = _entry_install_url(node)
        repo = _extract_repo_name(url) or _extract_repo_name(node.get('reference') or '') or ''
        if nid:
            by_id[nid] = node
        if repo:
            by_repo[repo.lower()] = node
        for raw in (nid, repo, title):
            _add_index(by_norm, normalize_name(raw), node)
            _add_index(by_compact, re.sub(r'[^a-z0-9]', '', raw.lower()), node)

    def _unique_hit(hits):
        refs = []
        unique = []
        for hit in hits or []:
            ref = (hit.get('reference') or _entry_install_url(hit)).lower()
            if ref in refs:
                continue
            refs.append(ref)
            unique.append(hit)
        return unique[0] if len(unique) == 1 else None

    installable = []
    unresolved = []
    for name in cleaned:
        key = name.lower()
        alias = PACK_ALIASES.get(key)
        node = by_id.get(key) or by_repo.get(key)
        if node is None and alias:
            node = by_id.get(alias.lower()) or by_repo.get(alias.lower())
            if node is None:
                node = _unique_hit(by_norm.get(normalize_name(alias)))
            compact_alias = re.sub(r'[^a-z0-9]', '', alias.lower())
            if node is None and len(compact_alias) >= 8:
                node = _unique_hit(by_compact.get(compact_alias))
        if node is None:
            node = _unique_hit(by_norm.get(normalize_name(name)))
        compact = re.sub(r'[^a-z0-9]', '', key)
        if node is None and len(compact) >= 8:
            node = _unique_hit(by_compact.get(compact))
        if node is None:
            unresolved.append({'name': name, 'reason': 'Not in the ComfyUI-Manager list'})
            continue
        url = _entry_install_url(node)
        install_type = node.get('install_type') or 'git-clone'
        if install_type != 'git-clone' or not valid_git_url(url):
            unresolved.append({
                'name': name,
                'title': node.get('title') or name,
                'reason': f'Unsupported install type: {install_type}',
            })
            continue
        folder = _entry_folder_name(url, name)
        installable.append({
            'name': name,
            'id': node.get('id') or '',
            'title': node.get('title') or name,
            'url': url,
            'folder': folder,
        })
    return {'success': True, 'installable': installable, 'unresolved': unresolved}


def install_missing_packs(
    git,
    pip,
    scanner,
    names: Optional[List[str]],
    log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Clone Manager-resolved packs and install their requirements.txt."""
    resolved = resolve_missing_packs(names)
    installed = []
    failed = []
    for item in resolved['installable']:
        title = item['title']
        folder = item['folder']
        if log:
            log(f'Installing {title}...')
        success, message = git.clone_repo(item['url'], folder)
        already = (not success) and 'already exists' in message.lower()
        if not success and not already:
            if log:
                log(f'Failed {title}: {message}')
            failed.append({**item, 'success': False, 'message': message})
            continue
        if success:
            req_path = Path(scanner.custom_nodes_path) / folder / 'requirements.txt'
            if req_path.is_file():
                pip_ok, pip_msg = pip.install_requirements(str(req_path.parent))
                if not pip_ok:
                    message = f'{message} (Warning: {pip_msg})'
        if log:
            log(f'Installed {title}' if success else f'Already present {title}')
        installed.append({**item, 'success': True, 'already': already, 'message': message})
    return {
        'success': True,
        'installed': installed,
        'failed': failed,
        'unresolved': resolved['unresolved'],
    }


# Test
if __name__ == '__main__':
    print("Fetching available nodes...")
    result = browse_nodes(limit=10)
    print(f"Total available: {result['total']}")
    print(f"Categories: {result['categories'][:10]}...")
    print("\nTop 10 by stars:")
    for node in result['nodes']:
        status = "[INSTALLED]" if node['is_installed'] else ""
        print(f"  - {node['title']} by {node['author']} - {node['stars']} stars {status}")




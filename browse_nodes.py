"""
MF_Conductor - Browse/Discover New Nodes
Allows browsing available nodes from ComfyUI-Manager database
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import urllib.request
import urllib.error


# ComfyUI-Manager custom node list URL
MANAGER_NODE_LIST_URL = "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/custom-node-list.json"

# Cache for the node database
_available_nodes_cache: Optional[List[Dict]] = None
_github_stats_cache: Optional[Dict] = None
_cache_timestamp: Optional[datetime] = None
CACHE_DURATION_HOURS = 6


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




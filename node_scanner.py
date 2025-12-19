"""
MF_Conductor - Node Scanner Module
Scans and parses ComfyUI custom node directories
"""

import os
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
import subprocess
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import ssl
import importlib.metadata


# Simple GitHub stars cache to avoid hitting rate limits
_github_stars_cache = {}
_github_stats_file_cache = None

# Cache for ComfyUI-Manager node database
_manager_node_db = None


def _load_github_stats_file() -> Dict:
    """Load GitHub star data from ComfyUI-Manager's github-stats.json"""
    global _github_stats_file_cache
    
    if _github_stats_file_cache is not None:
        return _github_stats_file_cache
    
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
                    _github_stats_file_cache = json.load(f)
                    return _github_stats_file_cache
        
        _github_stats_file_cache = {}
        return _github_stats_file_cache
    except Exception:
        _github_stats_file_cache = {}
        return _github_stats_file_cache


def clear_manager_db_cache():
    """Clear the manager database cache to force reload"""
    global _manager_node_db, _github_stats_file_cache
    _manager_node_db = None
    _github_stats_file_cache = None

# Cache for installed packages
_installed_packages = None


def get_installed_packages() -> Dict[str, str]:
    """Get dict of installed packages and their versions"""
    global _installed_packages
    
    if _installed_packages is not None:
        return _installed_packages
    
    _installed_packages = {}
    try:
        for dist in importlib.metadata.distributions():
            name = dist.metadata['Name']
            if name:
                _installed_packages[name.lower()] = dist.version
    except Exception as e:
        print(f"[MF Conductor] Error getting installed packages: {e}")
    
    return _installed_packages


def refresh_installed_packages():
    """Force refresh the installed packages cache"""
    global _installed_packages
    _installed_packages = None
    return get_installed_packages()


def parse_requirement_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single requirement line into name, version spec, etc."""
    line = line.strip()
    
    # Skip empty lines and comments
    if not line or line.startswith('#') or line.startswith('-'):
        return None
    
    # Handle git URLs
    if line.startswith('git+') or 'github.com' in line:
        # Extract package name from git URL if possible
        if '#egg=' in line:
            name = line.split('#egg=')[-1].split('&')[0]
            return {'name': name, 'version_spec': '', 'raw': line, 'is_git': True}
        return {'name': line, 'version_spec': '', 'raw': line, 'is_git': True}
    
    # Handle local paths
    if line.startswith('.') or line.startswith('/') or '\\' in line:
        return None
    
    # Parse version specifiers
    version_spec = ''
    name = line
    
    # Common version specifiers
    for op in ['>=', '<=', '==', '!=', '~=', '>', '<']:
        if op in line:
            parts = line.split(op, 1)
            name = parts[0].strip()
            version_spec = op + parts[1].split(';')[0].split('[')[0].strip()
            break
    
    # Handle extras like package[extra]
    if '[' in name:
        name = name.split('[')[0]
    
    # Handle environment markers like ; python_version
    if ';' in name:
        name = name.split(';')[0].strip()
    
    name = name.strip()
    if not name:
        return None
    
    return {
        'name': name,
        'version_spec': version_spec,
        'raw': line,
        'is_git': False
    }


def check_requirement_status(req: Dict[str, Any]) -> Dict[str, Any]:
    """Check if a requirement is installed and matches version spec"""
    installed = get_installed_packages()
    name = req['name'].lower()
    
    # Normalize common package name variations
    name_variations = [
        name,
        name.replace('-', '_'),
        name.replace('_', '-'),
    ]
    
    installed_version = None
    for variation in name_variations:
        if variation in installed:
            installed_version = installed[variation]
            break
    
    result = {
        'name': req['name'],
        'version_spec': req['version_spec'],
        'raw': req['raw'],
        'installed_version': installed_version,
        'status': 'missing'  # missing, installed, warning
    }
    
    if req.get('is_git'):
        # For git requirements, we can't easily check
        result['status'] = 'warning'
        result['message'] = 'Git dependency - status unknown'
        return result
    
    if installed_version is None:
        result['status'] = 'missing'
        result['message'] = 'Not installed'
        return result
    
    # Check version if specified
    if req['version_spec']:
        try:
            from packaging import version as pkg_version
            from packaging.specifiers import SpecifierSet
            
            spec = SpecifierSet(req['version_spec'])
            if pkg_version.parse(installed_version) in spec:
                result['status'] = 'installed'
                result['message'] = f'v{installed_version}'
            else:
                result['status'] = 'warning'
                result['message'] = f'v{installed_version} (requires {req["version_spec"]})'
        except Exception:
            # If we can't parse, just mark as installed
            result['status'] = 'installed'
            result['message'] = f'v{installed_version}'
    else:
        result['status'] = 'installed'
        result['message'] = f'v{installed_version}'
    
    return result


def get_node_requirements(folder_path: Path) -> List[Dict[str, Any]]:
    """Get and check all requirements for a node"""
    req_file = folder_path / 'requirements.txt'
    
    if not req_file.exists():
        return []
    
    requirements = []
    try:
        with open(req_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                req = parse_requirement_line(line)
                if req:
                    req_status = check_requirement_status(req)
                    requirements.append(req_status)
    except Exception as e:
        print(f"Error parsing requirements: {e}")
    
    return requirements


def normalize_name(name: str) -> str:
    """Normalize a name for comparison by removing prefixes and standardizing format"""
    name = name.lower().strip()
    # Remove common prefixes
    for prefix in ['comfyui-', 'comfyui_', 'comfy-', 'comfy_', 'comfyui']:
        if name.startswith(prefix):
            name = name[len(prefix):]
    # Remove common suffixes
    for suffix in ['-comfyui', '_comfyui', '-comfy', '_comfy']:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    # Normalize separators
    name = name.replace('_', '-').replace(' ', '-')
    # Remove multiple dashes
    while '--' in name:
        name = name.replace('--', '-')
    return name.strip('-')


def load_manager_node_database(custom_nodes_path: Path) -> dict:
    """Load the ComfyUI-Manager node database to get GitHub URLs"""
    global _manager_node_db
    
    if _manager_node_db is not None:
        return _manager_node_db
    
    _manager_node_db = {
        'by_repo_name': {},      # repo name from URL -> node_info
        'by_normalized': {},      # normalized name -> node_info  
        'by_title': {},           # normalized title -> node_info
        'all_nodes': []           # list of all nodes for fuzzy matching
    }
    
    # Ensure path is a Path object
    if isinstance(custom_nodes_path, str):
        custom_nodes_path = Path(custom_nodes_path)
    
    # Try multiple possible locations for the database
    db_paths = [
        custom_nodes_path / 'ComfyUI-Manager' / 'custom-node-list.json',
        custom_nodes_path / 'ComfyUI-Manager' / 'node_db' / 'new' / 'custom-node-list.json',
    ]
    
    print(f"[MF Conductor] Looking for database in: {custom_nodes_path}")
    
    for db_path in db_paths:
        if db_path.exists():
            try:
                with open(db_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                for node in data.get('custom_nodes', []):
                    reference = node.get('reference', '')
                    if reference and 'github.com' in reference:
                        node_info = {
                            'url': reference,
                            'author': node.get('author', ''),
                            'title': node.get('title', ''),
                            'description': node.get('description', ''),
                            'id': node.get('id', '')
                        }
                        
                        # Extract repo name from URL
                        url_parts = reference.rstrip('/').split('/')
                        if len(url_parts) >= 1:
                            repo_name = url_parts[-1]
                            repo_name_lower = repo_name.lower()
                            
                            # Store by exact repo name (lowercase)
                            _manager_node_db['by_repo_name'][repo_name_lower] = node_info
                            
                            # Also store with underscores converted to hyphens and vice versa
                            _manager_node_db['by_repo_name'][repo_name_lower.replace('_', '-')] = node_info
                            _manager_node_db['by_repo_name'][repo_name_lower.replace('-', '_')] = node_info
                            
                            # Store by normalized repo name
                            normalized = normalize_name(repo_name)
                            if normalized:
                                _manager_node_db['by_normalized'][normalized] = node_info
                                # Also without any separators
                                no_sep = normalized.replace('-', '').replace('_', '')
                                _manager_node_db['by_normalized'][no_sep] = node_info
                            
                            # Store by normalized title
                            title = node.get('title', '')
                            if title:
                                normalized_title = normalize_name(title)
                                if normalized_title:
                                    _manager_node_db['by_title'][normalized_title] = node_info
                                # Also store title with spaces replaced by hyphens
                                title_as_slug = title.lower().replace(' ', '-').replace('_', '-')
                                _manager_node_db['by_title'][title_as_slug] = node_info
                            
                            # Store by ID
                            node_id = node.get('id', '')
                            if node_id:
                                _manager_node_db['by_normalized'][node_id.lower()] = node_info
                        
                        _manager_node_db['all_nodes'].append(node_info)
                
                total = len(_manager_node_db['all_nodes'])
                by_repo = len(_manager_node_db['by_repo_name'])
                by_norm = len(_manager_node_db['by_normalized'])
                print(f"[MF Conductor] Loaded {total} nodes from ComfyUI-Manager database")
                print(f"[MF Conductor] Index sizes: by_repo={by_repo}, by_normalized={by_norm}")
                break
            except Exception as e:
                print(f"[MF Conductor] Error loading manager database: {e}")
                import traceback
                traceback.print_exc()
    
    if not _manager_node_db.get('all_nodes'):
        print(f"[MF Conductor] WARNING: No nodes loaded from database!")
        print(f"[MF Conductor] Checked paths: {[str(p) for p in db_paths]}")
    
    return _manager_node_db


def similarity_score(s1: str, s2: str) -> float:
    """Calculate similarity between two strings (0.0 to 1.0)"""
    if not s1 or not s2:
        return 0.0
    
    s1, s2 = s1.lower(), s2.lower()
    
    # Exact match
    if s1 == s2:
        return 1.0
    
    # One contains the other
    if s1 in s2 or s2 in s1:
        return 0.9
    
    # Normalize and compare
    n1, n2 = normalize_name(s1), normalize_name(s2)
    if n1 == n2:
        return 0.95
    if n1 in n2 or n2 in n1:
        return 0.85
    
    # Word overlap
    words1 = set(n1.replace('-', ' ').split())
    words2 = set(n2.replace('-', ' ').split())
    
    if words1 and words2:
        overlap = len(words1 & words2)
        total = max(len(words1), len(words2))
        if overlap > 0:
            return 0.5 + (0.4 * overlap / total)
    
    # Character-level similarity (simple)
    common = sum(1 for c in set(n1) if c in n2)
    total_chars = len(set(n1) | set(n2))
    if total_chars > 0:
        return 0.3 * (common / total_chars)
    
    return 0.0


def lookup_node_in_db(folder_name: str, custom_nodes_path: Path) -> Optional[dict]:
    """Look up a node in the ComfyUI-Manager database with aggressive matching"""
    db = load_manager_node_database(custom_nodes_path)
    
    if not db.get('all_nodes'):
        print(f"[MF Conductor] WARNING: Database not loaded for lookup of '{folder_name}'")
        return None
    
    folder_lower = folder_name.lower()
    normalized_folder = normalize_name(folder_name)
    folder_no_sep = normalized_folder.replace('-', '').replace('_', '')
    
    # Debug first few lookups
    if folder_lower.startswith('comfyui-a') or folder_lower.startswith('audio'):
        print(f"[MF Conductor] DEBUG: Looking up '{folder_name}'")
        print(f"[MF Conductor]   folder_lower: '{folder_lower}'")
        print(f"[MF Conductor]   normalized: '{normalized_folder}'")
        print(f"[MF Conductor]   In by_repo_name: {folder_lower in db['by_repo_name']}")
    
    # Generate variations to try
    variations = [
        folder_lower,
        folder_lower.replace('_', '-'),
        folder_lower.replace('-', '_'),
        normalized_folder,
        folder_no_sep,
    ]
    
    # Strategy 1: Exact repo name match (try variations)
    for var in variations:
        if var in db['by_repo_name']:
            return db['by_repo_name'][var]
    
    # Strategy 2: Normalized name match (try variations)
    for var in variations:
        if var in db['by_normalized']:
            return db['by_normalized'][var]
    
    # Strategy 3: Title match (try variations)
    for var in variations:
        if var in db['by_title']:
            return db['by_title'][var]
    
    # Strategy 4: Find best match using similarity scoring
    best_match = None
    best_score = 0.0
    
    for node_info in db['all_nodes']:
        url = node_info['url']
        repo_name = url.rstrip('/').split('/')[-1]
        title = node_info.get('title', '')
        
        # Score against repo name
        score1 = similarity_score(folder_name, repo_name)
        
        # Score against title  
        score2 = similarity_score(folder_name, title) if title else 0
        
        # Score against normalized versions
        score3 = similarity_score(normalized_folder, normalize_name(repo_name))
        
        # Take best score
        score = max(score1, score2, score3)
        
        if score > best_score:
            best_score = score
            best_match = node_info
    
    # Return match if score is good enough (lowered threshold)
    if best_score >= 0.4:
        return best_match
    
    return None


def fetch_github_stars(url: str) -> int:
    """Fetch star count - first from cached github-stats.json, then API"""
    if not url or 'github.com' not in url:
        return 0
    
    # Check runtime cache first
    if url in _github_stars_cache:
        return _github_stars_cache[url]
    
    # Try loading from github-stats.json (much faster, no rate limits)
    stats_file = _load_github_stats_file()
    if stats_file:
        # Try exact match
        stats = stats_file.get(url)
        if stats:
            stars = stats.get('stars', 0)
            _github_stars_cache[url] = stars
            return stars
        
        # Try without trailing .git or /
        url_clean = url.rstrip('/').rstrip('.git').rstrip('/')
        stats = stats_file.get(url_clean)
        if stats:
            stars = stats.get('stars', 0)
            _github_stars_cache[url] = stars
            return stars
        
        # Try with .git suffix
        stats = stats_file.get(url_clean + '.git')
        if stats:
            stars = stats.get('stars', 0)
            _github_stars_cache[url] = stars
            return stars
    
    # Fallback to API (rate limited - only if not found in cache file)
    try:
        # Extract owner/repo from URL
        parts = url.replace('https://github.com/', '').replace('http://github.com/', '').split('/')
        if len(parts) < 2:
            return 0
        
        owner, repo = parts[0], parts[1].rstrip('.git')
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        
        headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'MF_Conductor/1.0'
        }
        
        request = Request(api_url, headers=headers)
        ctx = ssl.create_default_context()
        
        with urlopen(request, context=ctx, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            stars = data.get('stargazers_count', 0)
            _github_stars_cache[url] = stars
            return stars
    except Exception:
        _github_stars_cache[url] = 0
        return 0


class CustomNode:
    """Represents a single custom node package"""
    
    def __init__(self, folder_path: str):
        self.folder_path = Path(folder_path)
        self.folder_name = self.folder_path.name
        self.display_name = self._clean_display_name()
        self.git_url: Optional[str] = None
        self.author: Optional[str] = None
        self.description: Optional[str] = None
        self.date_added: Optional[datetime] = None
        self.last_updated: Optional[datetime] = None
        self.stars: int = 0
        self.has_requirements: bool = False
        self.is_git_repo: bool = False
        self.enabled: bool = True
        self.provided_nodes: List[str] = []  # List of node names this package provides
        
        self._scan()
    
    def _clean_display_name(self) -> str:
        """Remove ComfyUI- prefixes and clean up the display name"""
        name = self.folder_name
        
        # Remove common prefixes (case-insensitive)
        prefixes_to_remove = [
            r'^comfyui[-_]',
            r'^comfy[-_]',
            r'^ComfyUI[-_]',
            r'^Comfy[-_]',
            r'^COMFYUI[-_]',
        ]
        
        for pattern in prefixes_to_remove:
            name = re.sub(pattern, '', name, flags=re.IGNORECASE)
        
        # Clean up remaining formatting
        # Replace underscores/hyphens with spaces for readability in some cases
        # But keep the technical name intact
        return name if name else self.folder_name
    
    def _scan(self):
        """Scan the node folder for metadata"""
        self._check_git_repo()
        self._check_requirements()
        self._get_folder_dates()
        self._parse_metadata_files()
        self._extract_provided_nodes()
        # Try to find GitHub URL from ComfyUI-Manager database first
        if not self.git_url:
            self._lookup_in_manager_db()
        # Then try to find GitHub URL from other sources if still not found
        if not self.git_url:
            self._find_github_url_from_files()
    
    def _lookup_in_manager_db(self):
        """Look up node info in ComfyUI-Manager database"""
        node_info = lookup_node_in_db(self.folder_name, self.folder_path.parent)
        
        if node_info:
            self.git_url = node_info['url']
            if node_info.get('author') and not self.author:
                self.author = node_info['author']
            if node_info.get('description') and not self.description:
                desc = node_info['description']
                self.description = desc[:200] + ('...' if len(desc) > 200 else '')
            self._parse_github_info()
            print(f"[MF Conductor] Matched '{self.folder_name}' -> {self.git_url}")
    
    def _check_git_repo(self):
        """Check if folder is a git repository and extract remote URL"""
        git_dir = self.folder_path / '.git'
        if git_dir.exists():
            self.is_git_repo = True
            self.git_url = self._get_git_remote_url()
            if self.git_url:
                self._parse_github_info()
    
    def _get_git_remote_url(self) -> Optional[str]:
        """Get the remote URL from git config"""
        git_config = self.folder_path / '.git' / 'config'
        if git_config.exists():
            try:
                with open(git_config, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    # Parse git config for remote URL
                    match = re.search(r'\[remote\s+"origin"\].*?url\s*=\s*(.+)', content, re.DOTALL)
                    if match:
                        url = match.group(1).split('\n')[0].strip()
                        # Convert SSH URLs to HTTPS
                        if url.startswith('git@github.com:'):
                            url = url.replace('git@github.com:', 'https://github.com/')
                        if url.endswith('.git'):
                            url = url[:-4]
                        return url
            except Exception:
                pass
        
        # Try running git command as fallback
        try:
            result = subprocess.run(
                ['git', 'config', '--get', 'remote.origin.url'],
                cwd=str(self.folder_path),
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                if url.startswith('git@github.com:'):
                    url = url.replace('git@github.com:', 'https://github.com/')
                if url.endswith('.git'):
                    url = url[:-4]
                return url
        except Exception:
            pass
        
        return None
    
    def _parse_github_info(self):
        """Extract author and stars from GitHub URL"""
        if self.git_url and 'github.com' in self.git_url:
            parts = self.git_url.replace('https://github.com/', '').replace('http://github.com/', '').split('/')
            if len(parts) >= 1:
                self.author = parts[0]
            # Fetch star count
            self.stars = fetch_github_stars(self.git_url)
    
    def _check_requirements(self):
        """Check if requirements.txt exists"""
        req_file = self.folder_path / 'requirements.txt'
        self.has_requirements = req_file.exists()
    
    def _get_folder_dates(self):
        """Get creation and modification dates of the folder"""
        try:
            stat = self.folder_path.stat()
            self.date_added = datetime.fromtimestamp(stat.st_ctime)
            self.last_updated = datetime.fromtimestamp(stat.st_mtime)
            
            # Try to get more accurate last update from git
            if self.is_git_repo:
                try:
                    result = subprocess.run(
                        ['git', 'log', '-1', '--format=%ct'],
                        cwd=str(self.folder_path),
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        timestamp = int(result.stdout.strip())
                        self.last_updated = datetime.fromtimestamp(timestamp)
                except Exception:
                    pass
        except Exception:
            pass
    
    def _parse_metadata_files(self):
        """Parse various metadata files (pyproject.toml, setup.py, etc.)"""
        # Check for pyproject.toml
        pyproject = self.folder_path / 'pyproject.toml'
        if pyproject.exists():
            self._parse_pyproject(pyproject)
        
        # Check for package.json (some nodes use it)
        package_json = self.folder_path / 'package.json'
        if package_json.exists():
            self._parse_package_json(package_json)
        
        # Check for README for description
        for readme_name in ['README.md', 'readme.md', 'README.txt', 'README']:
            readme = self.folder_path / readme_name
            if readme.exists():
                self._parse_readme(readme)
                break
    
    def _parse_pyproject(self, path: Path):
        """Parse pyproject.toml for metadata"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Simple parsing for description and author
                desc_match = re.search(r'description\s*=\s*["\'](.+?)["\']', content)
                if desc_match and not self.description:
                    self.description = desc_match.group(1)
                
                # Try multiple author formats:
                # 1. authors = [{name = "Author"}] (TOML inline table)
                # 2. authors = ["Author Name"] (simple list)
                # 3. author = "Author Name" (single value)
                if not self.author:
                    # Format: authors = [{name = "Author Name", ...}]
                    # Look for 'authors' section first, then extract name from it
                    authors_match = re.search(r'authors\s*=\s*\[(.*?)\]', content, re.DOTALL)
                    if authors_match:
                        authors_content = authors_match.group(1)
                        # Now look for name = "..." within the authors block
                        name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', authors_content)
                        if name_match:
                            self.author = name_match.group(1).split('<')[0].strip()
                        else:
                            # Format: authors = ["Author Name"] (simple string in list)
                            simple_match = re.search(r'["\']([^"\']+)["\']', authors_content)
                            if simple_match:
                                self.author = simple_match.group(1).split('<')[0].strip()
                    
                    # Fallback: author = "Author Name" (single value, not in list)
                    if not self.author:
                        author_match = re.search(r'^author\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
                        if author_match:
                            self.author = author_match.group(1).split('<')[0].strip()
        except Exception:
            pass
    
    def _parse_package_json(self, path: Path):
        """Parse package.json for metadata"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not self.description and 'description' in data:
                    self.description = data['description']
                if not self.author and 'author' in data:
                    author = data['author']
                    if isinstance(author, dict):
                        self.author = author.get('name', '')
                    else:
                        self.author = str(author)
        except Exception:
            pass
    
    def _parse_readme(self, path: Path):
        """Extract first paragraph from README as description"""
        if self.description:
            return
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                # Skip header lines and get first paragraph
                lines = content.split('\n')
                paragraph_lines = []
                in_paragraph = False
                
                for line in lines:
                    stripped = line.strip()
                    # Skip headers and empty lines at start
                    if not in_paragraph:
                        if stripped and not stripped.startswith('#') and not stripped.startswith('!'):
                            in_paragraph = True
                            paragraph_lines.append(stripped)
                    else:
                        if stripped:
                            paragraph_lines.append(stripped)
                        else:
                            break
                
                if paragraph_lines:
                    self.description = ' '.join(paragraph_lines)[:200]
                    if len(' '.join(paragraph_lines)) > 200:
                        self.description += '...'
        except Exception:
            pass
    
    def _find_github_url_from_files(self):
        """Try to find GitHub URL from various files when git remote is not available"""
        github_url_pattern = r'https?://github\.com/[\w\-\.]+/[\w\-\.]+'
        
        # Files to check for GitHub URLs
        files_to_check = [
            'README.md', 'readme.md', 'README.txt', 'README',
            'pyproject.toml', 'setup.py', 'setup.cfg',
            'package.json', '__init__.py'
        ]
        
        for filename in files_to_check:
            filepath = self.folder_path / filename
            if filepath.exists():
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        # Find GitHub URLs
                        matches = re.findall(github_url_pattern, content)
                        if matches:
                            # Prefer URLs that match the folder name
                            folder_lower = self.folder_name.lower().replace('comfyui-', '').replace('comfyui_', '').replace('comfy-', '').replace('comfy_', '')
                            for url in matches:
                                url_lower = url.lower()
                                if folder_lower in url_lower or url_lower.split('/')[-1] in self.folder_name.lower():
                                    self.git_url = url.rstrip('/')
                                    self._parse_github_info()
                                    return
                            # Fall back to first GitHub URL found
                            self.git_url = matches[0].rstrip('/')
                            self._parse_github_info()
                            return
                except Exception:
                    pass
        
        # Try to construct URL from folder name patterns
        # Many ComfyUI nodes follow patterns like: ComfyUI-{NodeName} or comfyui_{nodename}
        self._try_construct_github_url()
    
    def _try_construct_github_url(self):
        """Try to construct GitHub URL by checking if common URL patterns exist"""
        # Known author mappings for popular nodes (expand as needed)
        # Format: normalized_name -> github_url
        known_repos = {
            # ltdrdata nodes
            'impact-pack': 'https://github.com/ltdrdata/ComfyUI-Impact-Pack',
            'inspire-pack': 'https://github.com/ltdrdata/ComfyUI-Inspire-Pack',
            'manager': 'https://github.com/ltdrdata/ComfyUI-Manager',
            'impact-subpack': 'https://github.com/ltdrdata/ComfyUI-Impact-Subpack',
            
            # Popular nodes
            'controlnet-aux': 'https://github.com/Fannovel16/comfyui_controlnet_aux',
            'controlnet_aux': 'https://github.com/Fannovel16/comfyui_controlnet_aux',
            'advanced-controlnet': 'https://github.com/Kosinkadink/ComfyUI-Advanced-ControlNet',
            'animatediff-evolved': 'https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved',
            'videohelpersuite': 'https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite',
            'was-node-suite': 'https://github.com/WASasquatch/was-node-suite-comfyui',
            'efficiency-nodes': 'https://github.com/jags111/efficiency-nodes-comfyui',
            'rgthree-comfy': 'https://github.com/rgthree/rgthree-comfy',
            'rgthree': 'https://github.com/rgthree/rgthree-comfy',
            'custom-scripts': 'https://github.com/pythongosssss/ComfyUI-Custom-Scripts',
            'ipadapter-plus': 'https://github.com/cubiq/ComfyUI_IPAdapter_plus',
            'instantid': 'https://github.com/cubiq/ComfyUI_InstantID',
            'essentials': 'https://github.com/cubiq/ComfyUI_essentials',
            'kj-nodes': 'https://github.com/kijai/ComfyUI-KJNodes',
            'kjnodes': 'https://github.com/kijai/ComfyUI-KJNodes',
            'segment-anything': 'https://github.com/storyicon/comfyui_segment_anything',
            'audio-separation-nodes': 'https://github.com/Christian-Stieber/audio-separation-nodes-comfyui',
            'art-venture': 'https://github.com/artventure/art-venture',
            'cg-use-everywhere': 'https://github.com/chrisgoringe/cg-use-everywhere',
            'use-everywhere': 'https://github.com/chrisgoringe/cg-use-everywhere',
            '3d-pack': 'https://github.com/MrForExample/ComfyUI-3D-Pack',
            'advancedliveportrait': 'https://github.com/PowerHouseMan/ComfyUI-AdvancedLivePortrait',
            'birefnet': 'https://github.com/viperyl/ComfyUI-BiRefNet',
            'birefnet-ll': 'https://github.com/viperyl/ComfyUI-BiRefNet',
            'chatterboxtts': 'https://github.com/AIFSH/ChatterboxTTS-ComfyUI',
            'cotracker-node': 'https://github.com/kijai/ComfyUI-CoTracker-Nodes',
            'cotracker': 'https://github.com/kijai/ComfyUI-CoTracker-Nodes',
            'crt-nodes': 'https://github.com/crt-nodes/crt-nodes',
            'custom-nodes-alekpet': 'https://github.com/AlekPet/ComfyUI_Custom_Nodes_AlekPet',
            'alekpet': 'https://github.com/AlekPet/ComfyUI_Custom_Nodes_AlekPet',
            'detail-daemon': 'https://github.com/muerrilla/ComfyUI-detail-daemon',
            'distributed': 'https://github.com/city96/ComfyUI-Distributed',
            'facerestore': 'https://github.com/ltdrdata/ComfyUI-FaceRestore',
            'frame-interpolation': 'https://github.com/Fannovel16/ComfyUI-Frame-Interpolation',
            'gguf': 'https://github.com/city96/ComfyUI-GGUF',
            'layerdiffuse': 'https://github.com/huchenlei/ComfyUI-layerdiffuse',
            'layerstyle': 'https://github.com/chflame163/ComfyUI_LayerStyle',
            'easy-use': 'https://github.com/yolain/ComfyUI-Easy-Use',
            'dynamicprompts': 'https://github.com/adieyal/comfyui-dynamicprompts',
            'reactor': 'https://github.com/Gourieff/ComfyUI-ReActor-Node',
            'pulid': 'https://github.com/cubiq/PuLID_ComfyUI',
            'florence2': 'https://github.com/kijai/ComfyUI-Florence2',
            'wd14-tagger': 'https://github.com/pythongosssss/ComfyUI-WD14-Tagger',
            'ollama': 'https://github.com/stavsap/comfyui-ollama',
            'copilot': 'https://github.com/JEONG-JIWOO/ComfyUI_Copilot',
            'tensorrt': 'https://github.com/comfyanonymous/ComfyUI_TensorRT',
            'experiments': 'https://github.com/comfyanonymous/ComfyUI_experiments',
            'marigold': 'https://github.com/kijai/ComfyUI-Marigold',
            'depth-anything': 'https://github.com/kijai/ComfyUI-DepthAnythingV2',
            'depthanythingv2': 'https://github.com/kijai/ComfyUI-DepthAnythingV2',
            'flux': 'https://github.com/kijai/ComfyUI-FluxTrainer',
            'lcm': 'https://github.com/0xbitches/ComfyUI-LCM',
            'comfyroll': 'https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes',
            'comfyroll-customnodes': 'https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes',
            'failfast': 'https://github.com/failfast-comfyui/failfast-comfyui-sns',
            'asset-downloader': 'https://github.com/comfy-asset/comfy-asset-downloader',
        }
        
        # Normalize folder name and try lookup
        normalized = normalize_name(self.folder_name)
        
        if normalized in known_repos:
            self.git_url = known_repos[normalized]
            self._parse_github_info()
            return
        
        # Also try with the raw lowercase name
        folder_lower = self.folder_name.lower()
        if folder_lower in known_repos:
            self.git_url = known_repos[folder_lower]
            self._parse_github_info()
    
    def _extract_provided_nodes(self):
        """Extract the list of nodes this package provides from NODE_CLASS_MAPPINGS"""
        self.provided_nodes = []
        
        init_file = self.folder_path / '__init__.py'
        if not init_file.exists():
            return
        
        try:
            with open(init_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Method 1: Look for NODE_CLASS_MAPPINGS = { ... } with quoted string keys
            # Match "NodeName": ClassName or 'NodeName': ClassName
            mapping_match = re.search(
                r'NODE_CLASS_MAPPINGS\s*=\s*\{([^}]+)\}',
                content,
                re.DOTALL
            )
            
            if mapping_match:
                mapping_content = mapping_match.group(1)
                
                # Pattern A: Quoted string keys -> "NodeName": ClassName
                quoted_keys = re.findall(r'["\']([^"\']+)["\']\s*:', mapping_content)
                if quoted_keys:
                    self.provided_nodes = quoted_keys
                
                # Pattern B: ClassName.NAME: ClassName pattern (extract class names)
                if not self.provided_nodes:
                    class_name_keys = re.findall(r'(\w+)\.NAME\s*:', mapping_content)
                    if class_name_keys:
                        self.provided_nodes = class_name_keys
            
            # Method 2: Look for NODE_DISPLAY_NAME_MAPPINGS for prettier names
            display_match = re.search(
                r'NODE_DISPLAY_NAME_MAPPINGS\s*=\s*\{([^}]+)\}',
                content,
                re.DOTALL
            )
            
            if display_match and not self.provided_nodes:
                display_content = display_match.group(1)
                # Get the values (display names) from: "key": "Display Name"
                pairs = re.findall(r':\s*["\']([^"\']+)["\']', display_content)
                if pairs:
                    self.provided_nodes = pairs
            
            # Method 3: Check if NODE_CLASS_MAPPINGS is imported from another module
            if not self.provided_nodes:
                import_match = re.search(
                    r'from\s+\.(\S+)\s+import.*NODE_CLASS_MAPPINGS',
                    content
                )
                if import_match:
                    # Try to read the source module
                    submodule = import_match.group(1).replace('.', '/')
                    for ext in ['.py', '/__init__.py']:
                        subfile = self.folder_path / (submodule + ext)
                        if subfile.exists():
                            self.provided_nodes = self._extract_nodes_from_file(subfile)
                            break
            
            # Method 4: Look for dynamic NODE_CLASS_MAPPINGS updates
            if not self.provided_nodes:
                dynamic_nodes = re.findall(
                    r'NODE_CLASS_MAPPINGS\s*\[\s*["\']([^"\']+)["\']\s*\]',
                    content
                )
                if dynamic_nodes:
                    self.provided_nodes.extend(dynamic_nodes)
            
            # Method 5: Search all .py files for class definitions with ComfyUI markers
            if not self.provided_nodes:
                self.provided_nodes = self._find_node_classes_in_package()
            
            # Remove duplicates while preserving order
            seen = set()
            unique_nodes = []
            for node in self.provided_nodes:
                if node not in seen and not node.startswith('_'):
                    seen.add(node)
                    unique_nodes.append(node)
            self.provided_nodes = unique_nodes
            
        except Exception as e:
            # Silently fail - node extraction is non-critical
            pass
    
    def _extract_nodes_from_file(self, file_path: Path) -> List[str]:
        """Extract node names from a specific Python file"""
        nodes = []
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Look for NODE_CLASS_MAPPINGS dict
            mapping_match = re.search(
                r'NODE_CLASS_MAPPINGS\s*=\s*\{([^}]+)\}',
                content,
                re.DOTALL
            )
            
            if mapping_match:
                mapping_content = mapping_match.group(1)
                # Quoted string keys
                quoted = re.findall(r'["\']([^"\']+)["\']\s*:', mapping_content)
                if quoted:
                    nodes = quoted
                else:
                    # ClassName.NAME pattern
                    class_names = re.findall(r'(\w+)\.NAME\s*:', mapping_content)
                    if class_names:
                        nodes = class_names
        except:
            pass
        return nodes
    
    def _find_node_classes_in_package(self) -> List[str]:
        """Search for ComfyUI node classes in all Python files"""
        nodes = []
        try:
            for py_file in self.folder_path.rglob('*.py'):
                # Skip test files and hidden directories
                if 'test' in str(py_file).lower() or '/.' in str(py_file) or '\\.' in str(py_file):
                    continue
                
                try:
                    with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    # Look for classes with ComfyUI markers
                    # Pattern: class ClassName: followed by CATEGORY = or INPUT_TYPES
                    class_matches = re.findall(
                        r'class\s+(\w+)[^:]*:.*?(?:CATEGORY\s*=|INPUT_TYPES|RETURN_TYPES)',
                        content,
                        re.DOTALL
                    )
                    nodes.extend(class_matches)
                except:
                    continue
        except:
            pass
        return nodes
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'folder_name': self.folder_name,
            'folder_path': str(self.folder_path),
            'display_name': self.display_name,
            'git_url': self.git_url,
            'author': self.author or 'Unknown',
            'description': self.description or '',
            'date_added': self.date_added.isoformat() if self.date_added else None,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
            'stars': self.stars,
            'has_requirements': self.has_requirements,
            'is_git_repo': self.is_git_repo,
            'enabled': self.enabled,
            'provided_nodes': self.provided_nodes,
            'node_count': len(self.provided_nodes),
        }


class NodeScanner:
    """Scans and manages custom nodes directory"""
    
    def __init__(self, custom_nodes_path: Optional[str] = None):
        if custom_nodes_path:
            self.custom_nodes_path = Path(custom_nodes_path)
        else:
            # Auto-detect custom_nodes path
            self.custom_nodes_path = self._find_custom_nodes_path()
        
        self.nodes: List[CustomNode] = []
        self._cache_file = self.custom_nodes_path / 'ComfyUI_MFConductor' / 'nodes_cache.json'
    
    def _find_custom_nodes_path(self) -> Path:
        """Find the custom_nodes directory"""
        # Check relative to this file first
        current_dir = Path(__file__).parent
        if current_dir.name == 'ComfyUI_MFConductor':
            return current_dir.parent
        
        # Check common locations
        possible_paths = [
            Path(__file__).parent.parent,
            Path.cwd() / 'ComfyUI' / 'custom_nodes',
            Path.cwd() / 'custom_nodes',
        ]
        
        for path in possible_paths:
            if path.exists() and path.is_dir():
                return path
        
        raise FileNotFoundError("Could not locate custom_nodes directory")
    
    def scan(self, use_cache: bool = False) -> List[Dict[str, Any]]:
        """Scan all custom nodes and return as list of dicts"""
        if use_cache and self._cache_file.exists():
            try:
                with open(self._cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                    if cache.get('version') == '1.1':
                        return cache.get('nodes', [])
            except Exception:
                pass
        
        self.nodes = []
        
        # Items to skip
        skip_items = {
            '__pycache__',
            '.git',
            'example_node.py.example',
        }
        
        for item in self.custom_nodes_path.iterdir():
            # Skip files and special directories
            if not item.is_dir():
                continue
            if item.name in skip_items:
                continue
            if item.name.startswith('.'):
                continue
            
            # Check if it looks like a custom node (has __init__.py or .py files)
            has_python = any(
                f.suffix == '.py' for f in item.iterdir() if f.is_file()
            ) if item.is_dir() else False
            
            if has_python or (item / '__init__.py').exists():
                try:
                    node = CustomNode(str(item))
                    self.nodes.append(node)
                except Exception as e:
                    print(f"Error scanning {item}: {e}")
        
        # Sort by display name by default
        self.nodes.sort(key=lambda n: n.display_name.lower())
        
        # Save cache
        self._save_cache()
        
        return [node.to_dict() for node in self.nodes]
    
    def _save_cache(self):
        """Save scanned nodes to cache file"""
        try:
            cache_data = {
                'version': '1.1',
                'scanned_at': datetime.now().isoformat(),
                'nodes': [node.to_dict() for node in self.nodes]
            }
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            print(f"Failed to save cache: {e}")
    
    def get_node_by_folder(self, folder_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific node by its folder name"""
        for node in self.nodes:
            if node.folder_name == folder_name:
                return node.to_dict()
        return None
    
    def refresh(self) -> List[Dict[str, Any]]:
        """Force refresh the node list"""
        return self.scan(use_cache=False)
    
    def remove_node(self, folder_name: str) -> tuple:
        """Remove (delete) a custom node folder"""
        import shutil
        
        target_path = self.custom_nodes_path / folder_name
        
        if not target_path.exists():
            return False, f"Folder not found: {folder_name}"
        
        # Safety check - make sure it's in custom_nodes
        try:
            target_resolved = target_path.resolve()
            custom_resolved = self.custom_nodes_path.resolve()
            if not str(target_resolved).startswith(str(custom_resolved)):
                return False, "Security error: Invalid path"
        except Exception as e:
            return False, f"Path error: {e}"
        
        try:
            shutil.rmtree(str(target_path))
            # Clear cache
            self._cached_nodes = None
            return True, f"Successfully removed {folder_name}"
        except PermissionError:
            return False, f"Permission denied. Close any applications using files in {folder_name}"
        except Exception as e:
            return False, f"Failed to remove: {e}"
    
    def deactivate_node(self, folder_name: str) -> tuple:
        """Deactivate a custom node by renaming with .disabled suffix"""
        target_path = self.custom_nodes_path / folder_name
        disabled_path = self.custom_nodes_path / f"{folder_name}.disabled"
        
        if not target_path.exists():
            return False, f"Folder not found: {folder_name}"
        
        if disabled_path.exists():
            return False, f"Disabled version already exists: {folder_name}.disabled"
        
        try:
            target_path.rename(disabled_path)
            # Clear cache
            self._cached_nodes = None
            return True, f"Deactivated {folder_name} (renamed to {folder_name}.disabled)"
        except PermissionError:
            return False, f"Permission denied. Close any applications using files in {folder_name}"
        except Exception as e:
            return False, f"Failed to deactivate: {e}"
    
    def activate_node(self, folder_name: str) -> tuple:
        """Reactivate a disabled custom node by removing .disabled suffix"""
        # Handle both cases: with and without .disabled suffix
        if folder_name.endswith('.disabled'):
            disabled_path = self.custom_nodes_path / folder_name
            active_name = folder_name[:-9]  # Remove .disabled
        else:
            disabled_path = self.custom_nodes_path / f"{folder_name}.disabled"
            active_name = folder_name
        
        active_path = self.custom_nodes_path / active_name
        
        if not disabled_path.exists():
            return False, f"Disabled folder not found: {disabled_path.name}"
        
        if active_path.exists():
            return False, f"Active version already exists: {active_name}"
        
        try:
            disabled_path.rename(active_path)
            # Clear cache
            self._cached_nodes = None
            return True, f"Activated {active_name}"
        except PermissionError:
            return False, f"Permission denied. Close any applications using files in {disabled_path.name}"
        except Exception as e:
            return False, f"Failed to activate: {e}"
    
    def get_disk_usage(self, folder_name: str) -> Dict[str, Any]:
        """Calculate disk usage for a node"""
        target_path = self.custom_nodes_path / folder_name
        
        if not target_path.exists():
            return {'size_bytes': 0, 'size_formatted': '0 B', 'file_count': 0}
        
        total_size = 0
        file_count = 0
        
        try:
            for root, dirs, files in os.walk(target_path):
                # Skip .git directory for accurate code size
                if '.git' in dirs:
                    dirs.remove('.git')
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        total_size += os.path.getsize(fp)
                        file_count += 1
                    except (OSError, IOError):
                        pass
        except Exception:
            pass
        
        return {
            'size_bytes': total_size,
            'size_formatted': self._format_size(total_size),
            'file_count': file_count
        }
    
    def _format_size(self, size_bytes: int) -> str:
        """Format bytes into human readable string"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"
    
    def check_for_updates(self, folder_name: str) -> Dict[str, Any]:
        """Check if a git repo has updates available"""
        target_path = self.custom_nodes_path / folder_name
        git_dir = target_path / '.git'
        
        result = {
            'has_updates': False,
            'commits_behind': 0,
            'current_commit': None,
            'remote_commit': None,
            'error': None
        }
        
        if not git_dir.exists():
            result['error'] = 'Not a git repository'
            return result
        
        try:
            import subprocess
            
            # Fetch latest from remote (without merging)
            fetch_result = subprocess.run(
                ['git', 'fetch', '--quiet'],
                cwd=str(target_path),
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Get current commit
            current = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=str(target_path),
                capture_output=True,
                text=True,
                timeout=10
            )
            if current.returncode == 0:
                result['current_commit'] = current.stdout.strip()[:8]
            
            # Get remote commit
            remote = subprocess.run(
                ['git', 'rev-parse', '@{u}'],
                cwd=str(target_path),
                capture_output=True,
                text=True,
                timeout=10
            )
            if remote.returncode == 0:
                result['remote_commit'] = remote.stdout.strip()[:8]
            
            # Count commits behind
            behind = subprocess.run(
                ['git', 'rev-list', '--count', 'HEAD..@{u}'],
                cwd=str(target_path),
                capture_output=True,
                text=True,
                timeout=10
            )
            if behind.returncode == 0:
                commits_behind = int(behind.stdout.strip())
                result['commits_behind'] = commits_behind
                result['has_updates'] = commits_behind > 0
            
        except subprocess.TimeoutExpired:
            result['error'] = 'Timeout checking for updates'
        except FileNotFoundError:
            result['error'] = 'Git not found'
        except Exception as e:
            result['error'] = str(e)
        
        return result
    
    def batch_check_updates(self) -> Dict[str, Dict[str, Any]]:
        """Check for updates on all git-based nodes"""
        results = {}
        for node in self.nodes:
            if node.is_git_repo:
                results[node.folder_name] = self.check_for_updates(node.folder_name)
        return results
    
    def update_node(self, folder_name: str) -> tuple:
        """Update a node via git pull"""
        target_path = self.custom_nodes_path / folder_name
        git_dir = target_path / '.git'
        
        if not git_dir.exists():
            return False, "Not a git repository"
        
        try:
            import subprocess
            
            # Git pull
            result = subprocess.run(
                ['git', 'pull', '--ff-only'],
                cwd=str(target_path),
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if 'Already up to date' in output:
                    return True, "Already up to date"
                return True, f"Updated successfully:\n{output}"
            else:
                return False, f"Git pull failed: {result.stderr}"
                
        except subprocess.TimeoutExpired:
            return False, "Update timed out"
        except FileNotFoundError:
            return False, "Git not found"
        except Exception as e:
            return False, f"Update failed: {e}"
    
    def batch_update(self, folder_names: Optional[List[str]] = None) -> Dict[str, tuple]:
        """Update multiple nodes"""
        results = {}
        
        if folder_names is None:
            # Update all git repos
            folder_names = [n.folder_name for n in self.nodes if n.is_git_repo]
        
        for folder_name in folder_names:
            results[folder_name] = self.update_node(folder_name)
        
        return results
    
    def get_git_log(self, folder_name: str, count: int = 10) -> List[Dict[str, str]]:
        """Get recent git commits for a node"""
        target_path = self.custom_nodes_path / folder_name
        git_dir = target_path / '.git'
        
        if not git_dir.exists():
            return []
        
        try:
            import subprocess
            
            result = subprocess.run(
                ['git', 'log', f'-{count}', '--pretty=format:%H|%h|%s|%an|%ai'],
                cwd=str(target_path),
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                commits = []
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split('|', 4)
                        if len(parts) >= 5:
                            commits.append({
                                'hash': parts[0],
                                'short_hash': parts[1],
                                'message': parts[2],
                                'author': parts[3],
                                'date': parts[4]
                            })
                return commits
        except Exception:
            pass
        
        return []
    
    def rollback_node(self, folder_name: str, commit_hash: str) -> tuple:
        """Rollback a node to a specific commit"""
        target_path = self.custom_nodes_path / folder_name
        git_dir = target_path / '.git'
        
        if not git_dir.exists():
            return False, "Not a git repository"
        
        try:
            import subprocess
            
            # Checkout specific commit
            result = subprocess.run(
                ['git', 'checkout', commit_hash],
                cwd=str(target_path),
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return True, f"Rolled back to commit {commit_hash[:8]}"
            else:
                return False, f"Rollback failed: {result.stderr}"
                
        except Exception as e:
            return False, f"Rollback failed: {e}"
    
    def detect_broken_nodes(self) -> List[Dict[str, Any]]:
        """Detect nodes that may have issues"""
        broken_nodes = []
        
        for node in self.nodes:
            issues = []
            node_path = self.custom_nodes_path / node.folder_name
            
            # Check for __init__.py
            if not (node_path / '__init__.py').exists():
                issues.append("Missing __init__.py")
            
            # Check for syntax errors in Python files
            init_file = node_path / '__init__.py'
            if init_file.exists():
                try:
                    with open(init_file, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    compile(content, str(init_file), 'exec')
                except SyntaxError as e:
                    issues.append(f"Syntax error in __init__.py: line {e.lineno}")
                except Exception:
                    pass
            
            # Check for missing requirements
            req_file = node_path / 'requirements.txt'
            if req_file.exists():
                try:
                    from . import requirements_checker
                    reqs = requirements_checker.get_node_requirements(node.folder_name, str(self.custom_nodes_path))
                    missing = [r for r in reqs if r.get('status') == 'missing']
                    if missing:
                        issues.append(f"Missing {len(missing)} required packages")
                except Exception:
                    pass
            
            if issues:
                broken_nodes.append({
                    'folder_name': node.folder_name,
                    'display_name': node.display_name,
                    'issues': issues
                })
        
        return broken_nodes


# Standalone test
if __name__ == '__main__':
    scanner = NodeScanner()
    nodes = scanner.scan()
    print(f"Found {len(nodes)} custom nodes:")
    for node in nodes[:10]:  # Print first 10
        print(f"  - {node['display_name']} ({node['folder_name']})")
        if node['git_url']:
            print(f"    Git: {node['git_url']}")
        if node['author'] != 'Unknown':
            print(f"    Author: {node['author']}")


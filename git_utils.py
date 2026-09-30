"""
MF_Conductor - Git Utilities Module
Handles Git operations for custom node management
"""

import os
import subprocess
import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

try:
    from .security_utils import contained_path, safe_node_name, valid_git_url
except ImportError:
    from security_utils import contained_path, safe_node_name, valid_git_url
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import ssl


class GitUtils:
    """Utility class for Git operations"""
    
    def __init__(self, custom_nodes_path: Optional[str] = None):
        if custom_nodes_path:
            self.custom_nodes_path = Path(custom_nodes_path)
        else:
            self.custom_nodes_path = Path(__file__).parent.parent
        
        # Find git executable
        self.git_path = self._find_git()
    
    def _find_git(self) -> Optional[str]:
        """Find git executable"""
        try:
            result = subprocess.run(
                ['where', 'git'] if os.name == 'nt' else ['which', 'git'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
        except Exception:
            pass
        
        # Common paths on Windows
        common_paths = [
            r'C:\Program Files\Git\bin\git.exe',
            r'C:\Program Files (x86)\Git\bin\git.exe',
            os.path.expandvars(r'%LOCALAPPDATA%\Programs\Git\bin\git.exe'),
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def is_git_available(self) -> bool:
        """Check if git is available"""
        return self.git_path is not None
    
    def run_git(self, args: list, cwd: Optional[str] = None) -> Tuple[bool, str]:
        """Run a git command and return (success, output)"""
        if not self.git_path:
            return False, "Git not found"
        
        try:
            cmd = [self.git_path] + args
            result = subprocess.run(
                cmd,
                cwd=cwd or str(self.custom_nodes_path),
                capture_output=True,
                text=True,
                timeout=120  # 2 minute timeout for clone operations
            )
            
            if result.returncode == 0:
                return True, result.stdout
            else:
                return False, result.stderr or result.stdout
        except subprocess.TimeoutExpired:
            return False, "Git operation timed out"
        except Exception as e:
            return False, str(e)
    
    def _safe_node_dir(self, folder_name: str, must_exist: bool = True):
        ok, name = safe_node_name(folder_name)
        if not ok:
            return None, name
        root = self.custom_nodes_path.resolve()
        for cand in (root / name, root / f"{name}.disabled"):
            if cand.exists():
                if not contained_path(cand, root):
                    return None, 'Invalid path'
                return cand, name
        if must_exist:
            return None, f"Folder not found: {name}"
        dest = root / name
        if not contained_path(dest, root):
            return None, 'Invalid path'
        return dest, name

    def clone_repo(self, url: str, folder_name: Optional[str] = None) -> Tuple[bool, str]:
        """Clone a git repository into custom_nodes"""
        if not valid_git_url(url):
            return False, "Invalid git URL"

        if not folder_name:
            folder_name = url.rstrip('/').split('/')[-1]
            if folder_name.endswith('.git'):
                folder_name = folder_name[:-4]
        
        target_path, name = self._safe_node_dir(folder_name, must_exist=False)
        if target_path is None:
            return False, name
        if target_path.exists() or (target_path.parent / f"{name}.disabled").exists():
            return False, f"Folder already exists: {name}"
        
        success, output = self.run_git(['clone', '--', url.strip(), str(target_path)])
        
        if success:
            # Check for requirements.txt and offer to install
            return True, f"Successfully cloned to {folder_name}"
        else:
            return False, f"Clone failed: {output}"
    
    def pull_updates(self, folder_name: str) -> Tuple[bool, str]:
        """Pull updates for a specific node"""
        target_path, name = self._safe_node_dir(folder_name)
        if target_path is None:
            return False, name
        
        if not (target_path / '.git').exists():
            return False, f"Not a git repository: {name}"
        
        success, output = self.run_git(['pull'], cwd=str(target_path))
        
        if success:
            if 'Already up to date' in output or 'Already up-to-date' in output:
                return True, "Already up to date"
            return True, f"Updated successfully"
        else:
            return False, f"Pull failed: {output}"
    
    def get_remote_url(self, folder_name: str) -> Optional[str]:
        """Get remote URL for a node folder"""
        target_path, _name = self._safe_node_dir(folder_name)
        if target_path is None:
            return None
        
        if not (target_path / '.git').exists():
            return None
        
        success, output = self.run_git(
            ['config', '--get', 'remote.origin.url'],
            cwd=str(target_path)
        )
        
        if success:
            url = output.strip()
            # Convert SSH to HTTPS
            if url.startswith('git@github.com:'):
                url = url.replace('git@github.com:', 'https://github.com/')
            if url.endswith('.git'):
                url = url[:-4]
            return url
        
        return None
    
    def get_current_branch(self, folder_name: str) -> Optional[str]:
        """Get current branch for a node folder"""
        target_path, _name = self._safe_node_dir(folder_name)
        if target_path is None:
            return None
        
        success, output = self.run_git(
            ['branch', '--show-current'],
            cwd=str(target_path)
        )
        
        if success:
            return output.strip()
        return None
    
    def get_commit_info(self, folder_name: str) -> Dict[str, str]:
        """Get latest commit info for a node folder"""
        target_path, _name = self._safe_node_dir(folder_name)
        if target_path is None:
            return {'hash': '', 'short_hash': '', 'message': '', 'date': '', 'author': ''}
        
        info = {
            'hash': '',
            'short_hash': '',
            'message': '',
            'date': '',
            'author': ''
        }
        
        success, output = self.run_git(
            ['log', '-1', '--format=%H|%h|%s|%ci|%an'],
            cwd=str(target_path)
        )
        
        if success and output.strip():
            parts = output.strip().split('|')
            if len(parts) >= 5:
                info['hash'] = parts[0]
                info['short_hash'] = parts[1]
                info['message'] = parts[2]
                info['date'] = parts[3]
                info['author'] = parts[4]
        
        return info
    
    def check_for_updates(self, folder_name: str) -> Tuple[bool, int]:
        """Check if updates are available (returns has_updates, commit_count)"""
        target_path, _name = self._safe_node_dir(folder_name)
        if target_path is None:
            return False, 0
        
        # Fetch without merging
        self.run_git(['fetch'], cwd=str(target_path))
        
        # Check commits behind
        success, output = self.run_git(
            ['rev-list', '--count', 'HEAD..@{u}'],
            cwd=str(target_path)
        )
        
        if success:
            try:
                count = int(output.strip())
                return count > 0, count
            except ValueError:
                pass
        
        return False, 0


class GitHubAPI:
    """GitHub API utilities for fetching repo metadata"""
    
    API_BASE = "https://api.github.com"
    
    def __init__(self, token: Optional[str] = None):
        self.token = token
        # Create SSL context that doesn't verify (for corporate environments)
        self.ssl_context = ssl.create_default_context()
    
    def _make_request(self, url: str) -> Optional[Dict[str, Any]]:
        """Make an API request"""
        headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'MF_Conductor/1.0'
        }
        
        if self.token:
            headers['Authorization'] = f'token {self.token}'
        
        try:
            request = Request(url, headers=headers)
            with urlopen(request, context=self.ssl_context, timeout=10) as response:
                return json.loads(response.read().decode('utf-8'))
        except (URLError, HTTPError, json.JSONDecodeError) as e:
            print(f"GitHub API error: {e}")
            return None
    
    def get_repo_info(self, owner: str, repo: str) -> Optional[Dict[str, Any]]:
        """Get repository information"""
        url = f"{self.API_BASE}/repos/{owner}/{repo}"
        data = self._make_request(url)
        
        if data:
            return {
                'name': data.get('name', ''),
                'full_name': data.get('full_name', ''),
                'description': data.get('description', ''),
                'stars': data.get('stargazers_count', 0),
                'forks': data.get('forks_count', 0),
                'open_issues': data.get('open_issues_count', 0),
                'created_at': data.get('created_at', ''),
                'updated_at': data.get('updated_at', ''),
                'pushed_at': data.get('pushed_at', ''),
                'default_branch': data.get('default_branch', 'main'),
                'license': data.get('license', {}).get('spdx_id', ''),
                'topics': data.get('topics', []),
                'html_url': data.get('html_url', ''),
            }
        
        return None
    
    def parse_github_url(self, url: str) -> Optional[Tuple[str, str]]:
        """Parse GitHub URL to extract owner and repo name"""
        if not url:
            return None
        
        # Handle various GitHub URL formats
        patterns = [
            r'github\.com[/:]([^/]+)/([^/\s\.]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1), match.group(2)
        
        return None
    
    def get_stars_for_repo(self, url: str) -> int:
        """Get star count for a GitHub repository URL"""
        parsed = self.parse_github_url(url)
        if parsed:
            owner, repo = parsed
            info = self.get_repo_info(owner, repo)
            if info:
                return info.get('stars', 0)
        return 0


class PipUtils:
    """Utility class for pip operations"""
    
    def __init__(self, python_path: Optional[str] = None):
        if python_path:
            self.python_path = python_path
        else:
            self.python_path = self._find_python()
    
    def _find_python(self) -> str:
        """Find the Python executable"""
        # Check for embedded Python first (ComfyUI portable)
        possible_paths = [
            Path(__file__).parent.parent.parent.parent / 'python_embeded' / 'python.exe',
            Path(__file__).parent.parent.parent.parent.parent / 'python_embeded' / 'python.exe',
        ]
        
        for path in possible_paths:
            if path.exists():
                return str(path)
        
        # Fall back to system Python
        import sys
        return sys.executable
    
    def install_requirements(self, folder_path: str) -> Tuple[bool, str]:
        """Install requirements.txt for a node"""
        req_file = Path(folder_path) / 'requirements.txt'
        
        if not req_file.exists():
            return False, "No requirements.txt found"
        
        try:
            result = subprocess.run(
                [self.python_path, '-m', 'pip', 'install', '-r', str(req_file)],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                return True, "Requirements installed successfully"
            else:
                return False, f"Installation failed: {result.stderr}"
        except subprocess.TimeoutExpired:
            return False, "Installation timed out"
        except Exception as e:
            return False, str(e)


# Standalone test
if __name__ == '__main__':
    git = GitUtils()
    print(f"Git available: {git.is_git_available()}")
    if git.git_path:
        print(f"Git path: {git.git_path}")
    
    api = GitHubAPI()
    print("\nTesting GitHub API:")
    info = api.get_repo_info('comfyanonymous', 'ComfyUI')
    if info:
        print(f"  ComfyUI stars: {info['stars']}")




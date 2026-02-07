"""
MF_Conductor - Shared API Core Module
Contains the core business logic used by both standalone and integrated modes.
This eliminates code duplication between standalone_server.py and __init__.py
"""

import os
import sys
import json
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import ssl

# Import local modules
from node_scanner import (
    NodeScanner, 
    get_node_requirements, 
    refresh_installed_packages, 
    clear_manager_db_cache
)
from git_utils import GitUtils, PipUtils
from user_data import get_user_data
from browse_nodes import browse_nodes, get_categories, refresh_node_database, get_node_details
from shortcut_utils import get_shortcut_creator


class APIResponse:
    """Standardized API response builder"""
    
    @staticmethod
    def success(data: Any = None, message: str = None) -> dict:
        response = {'success': True}
        if message:
            response['message'] = message
        if data is not None:
            if isinstance(data, dict):
                response.update(data)
            else:
                response['data'] = data
        return response
    
    @staticmethod
    def error(message: str, status: int = 400, data: Any = None) -> dict:
        response = {'success': False, 'message': message}
        if data is not None:
            if isinstance(data, dict):
                response.update(data)
            else:
                response['data'] = data
        return response


class MFConductorCore:
    """
    Core API logic for MF Conductor.
    Used by both standalone_server.py and __init__.py (integrated mode).
    """
    
    def __init__(self, custom_nodes_path: str = None):
        self.scanner = NodeScanner(custom_nodes_path)
        self.git = GitUtils(custom_nodes_path)
        self.pip = PipUtils()
        self.custom_nodes_path = self.scanner.custom_nodes_path
        
        # Node cache
        self._cached_nodes = None
        self._cache_time = None
        
        # Backend log buffer for frontend console
        self.backend_logs = []
        self.backend_log_lock = threading.Lock()
        self.backend_log_index = 0
        self.max_backend_logs = 1000
    
    # ==================== LOGGING ====================
    
    def add_log(self, message: str, log_type: str = 'info'):
        """Add a log message to the backend log buffer"""
        with self.backend_log_lock:
            self.backend_logs.append({
                'message': message,
                'type': log_type,
                'time': time.time()
            })
            if len(self.backend_logs) > self.max_backend_logs:
                self.backend_logs.pop(0)
    
    def get_logs(self, since_index: int = 0) -> List[dict]:
        """Get backend logs since the given index"""
        with self.backend_log_lock:
            return self.backend_logs[since_index:]
    
    def get_logs_with_index(self, since_index: int = 0) -> dict:
        """Get backend logs with current index for polling"""
        with self.backend_log_lock:
            logs = self.backend_logs[since_index:]
            return {
                'logs': logs,
                'next_index': len(self.backend_logs)
            }
    
    # ==================== NODE OPERATIONS ====================
    
    def get_nodes(self, refresh: bool = False) -> dict:
        """Get list of all custom nodes"""
        if refresh or self._cached_nodes is None:
            nodes = self.scanner.scan(use_cache=not refresh)
            self._cached_nodes = nodes
            self._cache_time = datetime.now().isoformat()
        
        return APIResponse.success({
            'nodes': self._cached_nodes,
            'scanned_at': self._cache_time,
            'total': len(self._cached_nodes)
        })
    
    def refresh_nodes(self) -> dict:
        """Force refresh the node list"""
        clear_manager_db_cache()
        self._cached_nodes = None
        return self.get_nodes(refresh=True)
    
    def get_node(self, folder_name: str) -> dict:
        """Get details for a specific node"""
        if self._cached_nodes is None:
            self.get_nodes()
        
        for node in self._cached_nodes:
            if node['folder_name'] == folder_name:
                return APIResponse.success({'node': node})
        
        return APIResponse.error('Node not found', 404)
    
    def update_node(self, folder_name: str) -> dict:
        """Pull updates for a node via git"""
        self.add_log(f"Updating node: {folder_name}")
        success, message = self.git.pull_updates(folder_name)
        
        if success:
            self.add_log(f"Updated {folder_name}: {message}", 'success')
            self._cached_nodes = None
        else:
            self.add_log(f"Failed to update {folder_name}: {message}", 'error')
        
        return APIResponse.success(message=message) if success else APIResponse.error(message)
    
    def install_node(self, url: str, folder_name: str = None, install_deps: bool = True) -> dict:
        """Clone a new node from git"""
        self.add_log(f"Installing node from: {url}")
        
        success, message = self.git.clone_repo(url, folder_name)
        
        if not success:
            self.add_log(f"Failed to clone: {message}", 'error')
            return APIResponse.error(message)
        
        # Determine the actual folder name
        if not folder_name:
            folder_name = url.rstrip('/').split('/')[-1]
            if folder_name.endswith('.git'):
                folder_name = folder_name[:-4]
        
        # Install requirements if requested
        if install_deps:
            req_path = self.custom_nodes_path / folder_name / 'requirements.txt'
            if req_path.exists():
                self.add_log(f"Installing requirements for {folder_name}")
                pip_success, pip_msg = self.pip.install_requirements(
                    str(self.custom_nodes_path / folder_name)
                )
                if not pip_success:
                    message += f" (Warning: {pip_msg})"
                    self.add_log(f"Warning installing deps: {pip_msg}", 'warning')
        
        self._cached_nodes = None
        self.add_log(f"Installed {folder_name}", 'success')
        return APIResponse.success(message=message)
    
    def remove_node(self, folder_name: str) -> dict:
        """Remove (delete) a custom node"""
        self.add_log(f"Removing node: {folder_name}")
        success, message = self.scanner.remove_node(folder_name)
        
        if success:
            self._cached_nodes = None
            self.add_log(f"Removed {folder_name}", 'success')
        else:
            self.add_log(f"Failed to remove {folder_name}: {message}", 'error')
        
        return APIResponse.success(message=message) if success else APIResponse.error(message)
    
    def deactivate_node(self, folder_name: str) -> dict:
        """Deactivate a custom node (rename to .disabled)"""
        self.add_log(f"Deactivating node: {folder_name}")
        success, message = self.scanner.deactivate_node(folder_name)
        
        if success:
            self._cached_nodes = None
            self.add_log(f"Deactivated {folder_name}", 'success')
        
        return APIResponse.success(message=message) if success else APIResponse.error(message)
    
    def activate_node(self, folder_name: str) -> dict:
        """Activate a disabled custom node"""
        self.add_log(f"Activating node: {folder_name}")
        success, message = self.scanner.activate_node(folder_name)
        
        if success:
            self._cached_nodes = None
            self.add_log(f"Activated {folder_name}", 'success')
        
        return APIResponse.success(message=message) if success else APIResponse.error(message)
    
    def open_folder(self, folder_name: str) -> dict:
        """Open the node folder in file explorer"""
        folder_path = self.custom_nodes_path / folder_name
        
        if not folder_path.exists():
            return APIResponse.error('Folder not found', 404)
        
        try:
            if sys.platform == 'win32':
                os.startfile(str(folder_path))
            elif sys.platform == 'darwin':
                subprocess.run(['open', str(folder_path)])
            else:
                subprocess.run(['xdg-open', str(folder_path)])
            
            return APIResponse.success(message='Folder opened')
        except Exception as e:
            return APIResponse.error(str(e))
    
    def get_requirements(self, folder_name: str) -> dict:
        """Get requirements for a specific node"""
        folder_path = self.custom_nodes_path / folder_name
        
        if not folder_path.exists():
            return APIResponse.error('Folder not found', 404, {'requirements': []})
        
        requirements = get_node_requirements(folder_path)
        return APIResponse.success({
            'requirements': requirements,
            'total': len(requirements),
            'installed': sum(1 for r in requirements if r['status'] == 'installed'),
            'missing': sum(1 for r in requirements if r['status'] == 'missing'),
            'warnings': sum(1 for r in requirements if r['status'] == 'warning')
        })
    
    # ==================== PACKAGE OPERATIONS ====================
    
    def install_package(self, package_name: str) -> dict:
        """Install a specific package"""
        self.add_log(f"Installing package: {package_name}")
        
        try:
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'install', package_name],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            refresh_installed_packages()
            
            if result.returncode == 0:
                self.add_log(f"Installed {package_name}", 'success')
                return APIResponse.success(message=f'Successfully installed {package_name}')
            else:
                self.add_log(f"Failed to install {package_name}", 'error')
                return APIResponse.error(f'Installation failed: {result.stderr}')
        except subprocess.TimeoutExpired:
            return APIResponse.error('Installation timed out')
        except Exception as e:
            return APIResponse.error(str(e))
    
    def uninstall_package(self, package_name: str) -> dict:
        """Uninstall a specific package"""
        self.add_log(f"Uninstalling package: {package_name}")
        
        try:
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'uninstall', '-y', package_name],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            refresh_installed_packages()
            
            if result.returncode == 0:
                self.add_log(f"Uninstalled {package_name}", 'success')
                return APIResponse.success(message=f'Successfully uninstalled {package_name}')
            else:
                return APIResponse.error(f'Uninstall failed: {result.stderr}')
        except subprocess.TimeoutExpired:
            return APIResponse.error('Uninstall timed out')
        except Exception as e:
            return APIResponse.error(str(e))
    
    def upgrade_package(self, package_name: str) -> dict:
        """Upgrade a specific package"""
        self.add_log(f"Upgrading package: {package_name}")
        
        try:
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'install', '--upgrade', package_name],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            refresh_installed_packages()
            
            if result.returncode == 0:
                self.add_log(f"Upgraded {package_name}", 'success')
                return APIResponse.success(message=f'Successfully upgraded {package_name}')
            else:
                return APIResponse.error(f'Upgrade failed: {result.stderr}')
        except subprocess.TimeoutExpired:
            return APIResponse.error('Upgrade timed out')
        except Exception as e:
            return APIResponse.error(str(e))
    
    def reinstall_package(self, package_name: str) -> dict:
        """Reinstall a specific package"""
        self.add_log(f"Reinstalling package: {package_name}")
        
        try:
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'install', '--force-reinstall', package_name],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            refresh_installed_packages()
            
            if result.returncode == 0:
                self.add_log(f"Reinstalled {package_name}", 'success')
                return APIResponse.success(message=f'Successfully reinstalled {package_name}')
            else:
                return APIResponse.error(f'Reinstall failed: {result.stderr}')
        except subprocess.TimeoutExpired:
            return APIResponse.error('Reinstall timed out')
        except Exception as e:
            return APIResponse.error(str(e))
    
    def get_packages(self) -> dict:
        """Get list of installed packages"""
        self.add_log("Loading installed packages")
        
        try:
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'list', '--format=json', '--disable-pip-version-check'],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                packages = json.loads(result.stdout)
                self.add_log(f"Loaded {len(packages)} packages", 'success')
                return APIResponse.success({'packages': packages, 'total': len(packages)})
            else:
                return APIResponse.error(f'Failed to list packages: {result.stderr}')
        except subprocess.TimeoutExpired:
            return APIResponse.error('Package list timed out')
        except Exception as e:
            return APIResponse.error(str(e))
    
    def check_package_updates(self, packages: List[str] = None) -> dict:
        """Check for package updates using PyPI API (parallel)"""
        self.add_log("Checking for package updates")
        
        # Get installed packages
        result = self.get_packages()
        if not result.get('success'):
            return result
        
        installed = {p['name'].lower(): p['version'] for p in result.get('packages', [])}
        
        # If specific packages requested, filter
        if packages:
            installed = {k: v for k, v in installed.items() if k in [p.lower() for p in packages]}
        
        updates = []
        
        def check_single(pkg_name, current_version):
            try:
                ctx = ssl.create_default_context()
                
                req = Request(
                    f'https://pypi.org/pypi/{pkg_name}/json',
                    headers={'User-Agent': 'MFConductor/1.0'}
                )
                
                with urlopen(req, timeout=5, context=ctx) as response:
                    data = json.loads(response.read().decode())
                    latest = data.get('info', {}).get('version', '')
                    
                    if latest and latest != current_version:
                        return {
                            'name': pkg_name,
                            'current': current_version,
                            'latest': latest
                        }
            except (URLError, HTTPError, json.JSONDecodeError, TimeoutError, OSError):
                pass
            return None
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(check_single, name, ver): name 
                for name, ver in installed.items()
            }
            
            for future in as_completed(futures, timeout=30):
                try:
                    result = future.result()
                    if result:
                        updates.append(result)
                except (TimeoutError, Exception):
                    pass
        
        self.add_log(f"Found {len(updates)} packages with updates", 'success' if updates else 'info')
        return APIResponse.success({
            'updates': updates,
            'total_checked': len(installed),
            'updates_available': len(updates)
        })
    
    def check_single_package_update(self, package_name: str) -> dict:
        """Check for updates for a single package"""
        try:
            # Get current version
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'show', package_name, '--disable-pip-version-check'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            current_version = None
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if line.startswith('Version:'):
                        current_version = line.split(':', 1)[1].strip()
                        break
            
            if not current_version:
                return APIResponse.error(f'Package {package_name} not found')
            
            # Check PyPI
            ctx = ssl.create_default_context()
            
            req = Request(
                f'https://pypi.org/pypi/{package_name}/json',
                headers={'User-Agent': 'MFConductor/1.0'}
            )
            
            with urlopen(req, timeout=5, context=ctx) as response:
                data = json.loads(response.read().decode())
                latest = data.get('info', {}).get('version', '')
                
                has_update = latest and latest != current_version
                
                return APIResponse.success({
                    'name': package_name,
                    'current': current_version,
                    'latest': latest,
                    'has_update': has_update
                })
        except Exception as e:
            return APIResponse.error(str(e))
    
    # ==================== USER DATA OPERATIONS ====================
    
    def get_user_data_all(self) -> dict:
        """Get all user data (favorites, tags, notes, usage)"""
        user_data = get_user_data()
        return APIResponse.success({
            'favorites': user_data.get_favorites(),
            'tags': dict(user_data._tags),
            'notes': user_data.get_all_notes(),
            'usage': user_data.get_usage_stats()
        })
    
    def get_favorites(self) -> dict:
        """Get list of favorite nodes"""
        user_data = get_user_data()
        return APIResponse.success({'favorites': user_data.get_favorites()})
    
    def toggle_favorite(self, folder_name: str) -> dict:
        """Toggle favorite status for a node"""
        user_data = get_user_data()
        is_favorite = user_data.toggle_favorite(folder_name)
        return APIResponse.success({'is_favorite': is_favorite, 'folder_name': folder_name})
    
    def get_tags(self, folder_name: str = None) -> dict:
        """Get tags for a node or all tags"""
        user_data = get_user_data()
        if folder_name:
            return APIResponse.success({'tags': user_data.get_tags(folder_name)})
        return APIResponse.success({
            'all_tags': user_data.get_all_tags(),
            'node_tags': dict(user_data._tags)
        })
    
    def set_tags(self, folder_name: str, tags: List[str]) -> dict:
        """Set tags for a node"""
        user_data = get_user_data()
        user_data.set_tags(folder_name, tags)
        return APIResponse.success({'tags': tags, 'folder_name': folder_name})
    
    def get_note(self, folder_name: str) -> dict:
        """Get note for a node"""
        user_data = get_user_data()
        return APIResponse.success({'note': user_data.get_note(folder_name)})
    
    def set_note(self, folder_name: str, note: str) -> dict:
        """Set note for a node"""
        user_data = get_user_data()
        user_data.set_note(folder_name, note)
        return APIResponse.success({'note': note, 'folder_name': folder_name})
    
    # ==================== PROFILE OPERATIONS ====================
    
    def get_profiles(self) -> dict:
        """Get all profiles"""
        user_data = get_user_data()
        return APIResponse.success({'profiles': user_data.get_profiles()})
    
    def get_profile(self, name: str) -> dict:
        """Get a specific profile"""
        user_data = get_user_data()
        profile = user_data.get_profile(name)
        if profile:
            return APIResponse.success({'profile': profile, 'name': name})
        return APIResponse.error('Profile not found', 404)
    
    def save_profile(self, name: str, data: dict) -> dict:
        """Save a profile"""
        user_data = get_user_data()
        user_data.save_profile(
            name,
            enabled_nodes=data.get('enabled', []),
            disabled_nodes=data.get('disabled', []),
            flags=data.get('flags', {}),
            custom_flags=data.get('custom_flags', ''),
            custom_flags_list=data.get('custom_flags_list', []),
            excluded_packages=data.get('excluded_packages', []),
            description=data.get('description', ''),
            avatar=data.get('avatar', 'default.svg')
        )
        self.add_log(f"Saved profile: {name}", 'success')
        return APIResponse.success(message=f'Profile "{name}" saved')
    
    def delete_profile(self, name: str) -> dict:
        """Delete a profile"""
        user_data = get_user_data()
        if user_data.delete_profile(name):
            self.add_log(f"Deleted profile: {name}", 'success')
            return APIResponse.success(message=f'Profile "{name}" deleted')
        return APIResponse.error('Profile not found', 404)
    
    def set_default_profile(self, name: str) -> dict:
        """Set a profile as default"""
        user_data = get_user_data()
        profiles = user_data._profiles
        
        if name not in profiles:
            return APIResponse.error('Profile not found', 404)
        
        # Clear existing default
        for pname in profiles:
            profiles[pname]['is_default'] = (pname == name)
        
        user_data._save_json(user_data.profiles_file, profiles)
        self.add_log(f"Set default profile: {name}", 'success')
        return APIResponse.success(message=f'"{name}" is now the default profile')
    
    def apply_profile(self, name: str) -> dict:
        """Apply a profile (enable/disable nodes)"""
        user_data = get_user_data()
        profile = user_data.get_profile(name)
        
        if not profile:
            return APIResponse.error('Profile not found', 404)
        
        enabled = profile.get('enabled', [])
        disabled = profile.get('disabled', [])
        
        self.add_log(f"Applying profile: {name}")
        
        results = {'enabled': [], 'disabled': [], 'errors': []}
        
        # Enable nodes
        for folder in enabled:
            try:
                success, msg = self.scanner.activate_node(folder)
                if success:
                    results['enabled'].append(folder)
            except Exception as e:
                results['errors'].append(f"Failed to enable {folder}: {e}")
        
        # Disable nodes
        for folder in disabled:
            try:
                success, msg = self.scanner.deactivate_node(folder)
                if success:
                    results['disabled'].append(folder)
            except Exception as e:
                results['errors'].append(f"Failed to disable {folder}: {e}")
        
        self._cached_nodes = None
        self.add_log(f"Applied profile {name}: {len(results['enabled'])} enabled, {len(results['disabled'])} disabled", 'success')
        
        return APIResponse.success({
            'results': results,
            'message': f'Profile "{name}" applied'
        })
    
    def load_preset_profiles(self) -> dict:
        """Load/reset preset profiles"""
        user_data = get_user_data()
        count = user_data.load_preset_profiles()
        self.add_log(f"Loaded {count} preset profiles", 'success')
        return APIResponse.success(message=f'Loaded {count} preset profiles')
    
    # ==================== BROWSE/COMMUNITY OPERATIONS ====================
    
    def browse_available_nodes(self, query: str = '', category: str = '', 
                               page: int = 1, per_page: int = 50,
                               installed_only: bool = False) -> dict:
        """Browse available nodes from ComfyUI-Manager database"""
        try:
            # Get installed node folders for comparison
            installed_folders = set()
            if self._cached_nodes:
                installed_folders = {n['folder_name'] for n in self._cached_nodes}
            
            results = browse_nodes(
                query=query,
                category=category,
                page=page,
                per_page=per_page,
                installed_folders=installed_folders,
                installed_only=installed_only
            )
            
            return APIResponse.success(results)
        except Exception as e:
            return APIResponse.error(str(e))
    
    def get_browse_categories(self) -> dict:
        """Get available categories for browsing"""
        try:
            categories = get_categories()
            return APIResponse.success({'categories': categories})
        except Exception as e:
            return APIResponse.error(str(e))
    
    def refresh_browse_database(self) -> dict:
        """Refresh the browse node database"""
        try:
            self.add_log("Refreshing node database")
            count = refresh_node_database()
            self.add_log(f"Loaded {count} nodes from database", 'success')
            return APIResponse.success(message=f'Refreshed database with {count} nodes')
        except Exception as e:
            return APIResponse.error(str(e))
    
    def get_browse_node_details(self, reference: str) -> dict:
        """Get detailed info for a node from the browse database"""
        try:
            details = get_node_details(reference)
            if details:
                return APIResponse.success({'node': details})
            return APIResponse.error('Node not found', 404)
        except Exception as e:
            return APIResponse.error(str(e))
    
    # ==================== SETTINGS OPERATIONS ====================
    
    def get_settings(self) -> dict:
        """Get user settings"""
        user_data = get_user_data()
        return APIResponse.success({'settings': user_data.get_settings()})
    
    def save_settings(self, settings: dict) -> dict:
        """Save user settings"""
        user_data = get_user_data()
        for key, value in settings.items():
            user_data.set_setting(key, value)
        return APIResponse.success(message='Settings saved')
    
    def reset_settings(self) -> dict:
        """Reset settings to defaults"""
        user_data = get_user_data()
        defaults = {'theme': 'dark', 'auto_update': False, 'show_disk_usage': True}
        for key, value in defaults.items():
            user_data.set_setting(key, value)
        return APIResponse.success(message='Settings reset to defaults')
    
    # ==================== BACKUP OPERATIONS ====================
    
    def export_backup(self) -> dict:
        """Export all user data as backup"""
        user_data = get_user_data()
        backup = user_data.export_backup()
        return APIResponse.success({'backup': backup})
    
    def import_backup(self, data: dict, merge: bool = False) -> dict:
        """Import user data from backup"""
        user_data = get_user_data()
        if user_data.import_backup(data, merge=merge):
            self.add_log("Imported backup successfully", 'success')
            return APIResponse.success(message='Backup imported successfully')
        return APIResponse.error('Failed to import backup')
    
    # ==================== SYSTEM OPERATIONS ====================
    
    def get_desktop_path(self) -> dict:
        """Get the user's desktop path"""
        desktop = str(Path.home() / 'Desktop')
        return APIResponse.success({'path': desktop})
    
    def get_system_info(self) -> dict:
        """Get system information"""
        import platform
        
        return APIResponse.success({
            'platform': sys.platform,
            'python_version': platform.python_version(),
            'custom_nodes_path': str(self.custom_nodes_path),
            'git_available': self.git.is_git_available(),
            'pip_path': self.pip.python_path
        })
    
    # ==================== SHORTCUT OPERATIONS ====================
    
    def create_conductor_shortcut(self, save_path: str, avatar: str = 'default') -> dict:
        """Create a shortcut to launch MF Conductor"""
        shortcut = get_shortcut_creator()
        success, message = shortcut.create_conductor_shortcut(save_path, avatar)
        
        if success:
            self.add_log(f"Created conductor shortcut: {save_path}", 'success')
        else:
            self.add_log(f"Failed to create shortcut: {message}", 'error')
        
        return APIResponse.success(message=message) if success else APIResponse.error(message)
    
    # ==================== FILE BROWSER OPERATIONS ====================
    
    def get_comfy_folder_path(self, folder_type: str) -> Path:
        """Get path to a ComfyUI folder"""
        comfy_root = self.custom_nodes_path.parent
        
        folder_map = {
            'output': comfy_root / 'output',
            'input': comfy_root / 'input',
            'models': comfy_root / 'models',
            'temp': comfy_root / 'temp',
        }
        
        return folder_map.get(folder_type, comfy_root / 'output')
    
    def get_files(self, folder_type: str = 'output', subfolder: str = '', 
                  sort_by: str = 'date', sort_dir: str = 'desc',
                  file_type: str = '', search: str = '') -> dict:
        """Get files from a ComfyUI folder"""
        try:
            folder_path = self.get_comfy_folder_path(folder_type)
            
            if subfolder:
                folder_path = folder_path / subfolder
            
            if not folder_path.exists():
                return APIResponse.success({
                    'files': [],
                    'path': str(folder_path),
                    'total': 0,
                    'total_size': 0
                })
            
            files = []
            total_size = 0
            
            # Image extensions
            image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff'}
            video_exts = {'.mp4', '.webm', '.mov', '.avi', '.mkv', '.gif'}
            audio_exts = {'.mp3', '.wav', '.ogg', '.flac', '.m4a'}
            
            for item in folder_path.iterdir():
                if item.name.startswith('.'):
                    continue
                
                ext = item.suffix.lower()
                
                # Determine file type
                if item.is_dir():
                    ftype = 'folder'
                elif ext in image_exts:
                    ftype = 'image'
                elif ext in video_exts:
                    ftype = 'video'
                elif ext in audio_exts:
                    ftype = 'audio'
                else:
                    ftype = 'other'
                
                # Apply type filter
                if file_type and ftype != file_type and ftype != 'folder':
                    continue
                
                # Apply search filter
                if search and search.lower() not in item.name.lower():
                    continue
                
                try:
                    stat = item.stat()
                    size = stat.st_size if item.is_file() else 0
                    mtime = stat.st_mtime
                except (OSError, PermissionError):
                    size = 0
                    mtime = 0
                
                total_size += size
                
                files.append({
                    'name': item.name,
                    'path': str(item.relative_to(self.get_comfy_folder_path(folder_type))),
                    'type': ftype,
                    'extension': ext,
                    'size': size,
                    'modified': mtime,
                    'is_dir': item.is_dir()
                })
            
            # Sort files
            sort_key_map = {
                'name': lambda x: x['name'].lower(),
                'date': lambda x: x['modified'],
                'size': lambda x: x['size'],
                'type': lambda x: (x['type'], x['name'].lower())
            }
            
            sort_key = sort_key_map.get(sort_by, sort_key_map['date'])
            files.sort(key=sort_key, reverse=(sort_dir == 'desc'))
            
            # Folders first
            files.sort(key=lambda x: (0 if x['is_dir'] else 1))
            
            return APIResponse.success({
                'files': files,
                'path': str(folder_path),
                'folder_type': folder_type,
                'subfolder': subfolder,
                'total': len(files),
                'total_size': total_size
            })
        except Exception as e:
            return APIResponse.error(str(e))
    
    def get_file_thumbnail(self, folder_type: str, file_path: str) -> Tuple[bytes, str]:
        """Get thumbnail for an image file"""
        try:
            full_path = self.get_comfy_folder_path(folder_type) / file_path
            
            if not full_path.exists():
                return None, None
            
            ext = full_path.suffix.lower()
            
            content_types = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.webp': 'image/webp',
                '.bmp': 'image/bmp',
            }
            
            content_type = content_types.get(ext, 'application/octet-stream')
            
            with open(full_path, 'rb') as f:
                data = f.read()
            
            return data, content_type
        except Exception:
            return None, None
    
    def delete_file(self, folder_type: str, file_path: str) -> dict:
        """Delete a file from a ComfyUI folder"""
        try:
            full_path = self.get_comfy_folder_path(folder_type) / file_path
            
            if not full_path.exists():
                return APIResponse.error('File not found', 404)
            
            # Security check - ensure path is within the folder
            try:
                full_path.relative_to(self.get_comfy_folder_path(folder_type))
            except ValueError:
                return APIResponse.error('Invalid path', 403)
            
            if full_path.is_dir():
                import shutil
                shutil.rmtree(full_path)
                self.add_log(f"Deleted folder: {file_path}", 'success')
            else:
                full_path.unlink()
                self.add_log(f"Deleted file: {file_path}", 'success')
            
            return APIResponse.success(message=f'Deleted: {file_path}')
        except Exception as e:
            return APIResponse.error(str(e))
    
    def open_file_location(self, folder_type: str, file_path: str = '') -> dict:
        """Open file location in file explorer"""
        try:
            folder_path = self.get_comfy_folder_path(folder_type)
            
            if file_path:
                full_path = folder_path / file_path
                if full_path.exists():
                    if full_path.is_file():
                        folder_path = full_path.parent
                    else:
                        folder_path = full_path
            
            if not folder_path.exists():
                return APIResponse.error('Folder not found', 404)
            
            if sys.platform == 'win32':
                os.startfile(str(folder_path))
            elif sys.platform == 'darwin':
                subprocess.run(['open', str(folder_path)])
            else:
                subprocess.run(['xdg-open', str(folder_path)])
            
            return APIResponse.success(message='Folder opened')
        except Exception as e:
            return APIResponse.error(str(e))
    
    def create_profile_shortcut(self, profile_name: str, save_path: str) -> dict:
        """Create a shortcut to launch a specific profile"""
        user_data = get_user_data()
        profile = user_data.get_profile(profile_name)
        
        if not profile:
            return APIResponse.error('Profile not found', 404)
        
        shortcut = get_shortcut_creator()
        success, message = shortcut.create_profile_shortcut(profile_name, save_path, profile)
        
        if success:
            self.add_log(f"Created profile shortcut: {save_path}", 'success')
        else:
            self.add_log(f"Failed to create shortcut: {message}", 'error')
        
        return APIResponse.success(message=message) if success else APIResponse.error(message)


# Global instance
_core_instance: Optional[MFConductorCore] = None


def get_core() -> MFConductorCore:
    """Get global MFConductorCore instance"""
    global _core_instance
    if _core_instance is None:
        _core_instance = MFConductorCore()
    return _core_instance


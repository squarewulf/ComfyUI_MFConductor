"""
MF_Conductor - Standalone Server
Can run independently of ComfyUI for offline node management
"""

import os
import sys
import json
import subprocess
import webbrowser
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from node_scanner import NodeScanner, get_node_requirements, refresh_installed_packages, clear_manager_db_cache
from git_utils import GitUtils, PipUtils
from user_data import get_user_data
from browse_nodes import browse_nodes, get_categories, refresh_node_database, get_node_details


class MFConductorAPI:
    """API handler for MF Conductor operations"""
    
    def __init__(self, custom_nodes_path: str = None):
        self.scanner = NodeScanner(custom_nodes_path)
        self.git = GitUtils(custom_nodes_path)
        self.pip = PipUtils()
        self.custom_nodes_path = self.scanner.custom_nodes_path
        self._cached_nodes = None
        self._cache_time = None
        
        # ComfyUI process management
        self.comfy_process = None
        self.comfy_output_buffer = []
        self.comfy_output_index = 0  # Track what output has been sent to client
        self.output_lock = threading.Lock()
    
    def get_nodes(self, refresh: bool = False) -> dict:
        """Get list of all custom nodes"""
        if refresh or self._cached_nodes is None:
            nodes = self.scanner.scan(use_cache=not refresh)
            self._cached_nodes = nodes
            self._cache_time = datetime.now().isoformat()
        
        return {
            'nodes': self._cached_nodes,
            'scanned_at': self._cache_time,
            'total': len(self._cached_nodes)
        }
    
    def refresh_nodes(self) -> dict:
        """Force refresh the node list"""
        # Clear all caches to force fresh scan
        clear_manager_db_cache()
        return self.get_nodes(refresh=True)
    
    def get_node(self, folder_name: str) -> dict:
        """Get details for a specific node"""
        if self._cached_nodes is None:
            self.get_nodes()
        
        for node in self._cached_nodes:
            if node['folder_name'] == folder_name:
                return {'success': True, 'node': node}
        
        return {'success': False, 'message': 'Node not found'}
    
    def update_node(self, folder_name: str) -> dict:
        """Pull updates for a node"""
        success, message = self.git.pull_updates(folder_name)
        return {'success': success, 'message': message}
    
    def install_node(self, url: str, folder_name: str = None, install_deps: bool = True) -> dict:
        """Clone a new node from git"""
        # Clone the repository
        success, message = self.git.clone_repo(url, folder_name)
        
        if not success:
            return {'success': False, 'message': message}
        
        # Determine the actual folder name
        if not folder_name:
            folder_name = url.rstrip('/').split('/')[-1]
            if folder_name.endswith('.git'):
                folder_name = folder_name[:-4]
        
        # Install requirements if requested
        if install_deps:
            req_path = self.custom_nodes_path / folder_name / 'requirements.txt'
            if req_path.exists():
                pip_success, pip_msg = self.pip.install_requirements(
                    str(self.custom_nodes_path / folder_name)
                )
                if not pip_success:
                    message += f" (Warning: {pip_msg})"
        
        # Refresh the cache
        self.refresh_nodes()
        
        return {'success': True, 'message': message}
    
    def open_folder(self, folder_name: str) -> dict:
        """Open the node folder in file explorer"""
        folder_path = self.custom_nodes_path / folder_name
        
        if not folder_path.exists():
            return {'success': False, 'message': 'Folder not found'}
        
        try:
            if sys.platform == 'win32':
                os.startfile(str(folder_path))
            elif sys.platform == 'darwin':
                subprocess.run(['open', str(folder_path)])
            else:
                subprocess.run(['xdg-open', str(folder_path)])
            
            return {'success': True, 'message': 'Folder opened'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def remove_node(self, folder_name: str) -> dict:
        """Remove (delete) a custom node"""
        success, message = self.scanner.remove_node(folder_name)
        if success:
            self._cached_nodes = None
        return {'success': success, 'message': message}
    
    def deactivate_node(self, folder_name: str) -> dict:
        """Deactivate a custom node"""
        success, message = self.scanner.deactivate_node(folder_name)
        if success:
            self._cached_nodes = None
        return {'success': success, 'message': message}
    
    def activate_node(self, folder_name: str) -> dict:
        """Activate a disabled custom node"""
        success, message = self.scanner.activate_node(folder_name)
        if success:
            self._cached_nodes = None
        return {'success': success, 'message': message}
    
    def get_requirements(self, folder_name: str) -> dict:
        """Get requirements for a specific node"""
        folder_path = self.custom_nodes_path / folder_name
        
        if not folder_path.exists():
            return {'success': False, 'message': 'Folder not found', 'requirements': []}
        
        requirements = get_node_requirements(folder_path)
        return {
            'success': True,
            'requirements': requirements,
            'total': len(requirements),
            'installed': sum(1 for r in requirements if r['status'] == 'installed'),
            'missing': sum(1 for r in requirements if r['status'] == 'missing'),
            'warnings': sum(1 for r in requirements if r['status'] == 'warning')
        }
    
    def install_package(self, package_name: str) -> dict:
        """Install a specific package"""
        try:
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'install', package_name],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            # Refresh the package cache
            refresh_installed_packages()
            
            if result.returncode == 0:
                return {'success': True, 'message': f'Successfully installed {package_name}'}
            else:
                return {'success': False, 'message': f'Installation failed: {result.stderr}'}
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'Installation timed out'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    # ==================== USER DATA FEATURES ====================
    
    def get_favorites(self) -> dict:
        """Get list of favorite nodes"""
        user_data = get_user_data()
        return {'success': True, 'favorites': user_data.get_favorites()}
    
    def toggle_favorite(self, folder_name: str) -> dict:
        """Toggle favorite status for a node"""
        user_data = get_user_data()
        is_favorite = user_data.toggle_favorite(folder_name)
        return {'success': True, 'is_favorite': is_favorite}
    
    def get_tags(self, folder_name: str = None) -> dict:
        """Get tags for a node or all tags"""
        user_data = get_user_data()
        if folder_name:
            return {'success': True, 'tags': user_data.get_tags(folder_name)}
        return {'success': True, 'all_tags': user_data.get_all_tags()}
    
    def set_tags(self, folder_name: str, tags: list) -> dict:
        """Set tags for a node"""
        user_data = get_user_data()
        user_data.set_tags(folder_name, tags)
        return {'success': True, 'tags': tags}
    
    def get_note(self, folder_name: str) -> dict:
        """Get note for a node"""
        user_data = get_user_data()
        return {'success': True, 'note': user_data.get_note(folder_name)}
    
    def set_note(self, folder_name: str, note: str) -> dict:
        """Set note for a node"""
        user_data = get_user_data()
        user_data.set_note(folder_name, note)
        return {'success': True, 'note': note}
    
    def get_all_user_data(self) -> dict:
        """Get all user data (favorites, tags, notes) for enriching node list"""
        user_data = get_user_data()
        return {
            'success': True,
            'favorites': user_data.get_favorites(),
            'tags': {k: v for k, v in user_data._tags.items()},
            'notes': user_data.get_all_notes(),
            'usage': user_data.get_usage_stats()
        }
    
    # ==================== PROFILES ====================
    
    def get_profiles(self) -> dict:
        """Get all profiles"""
        user_data = get_user_data()
        return {'success': True, 'profiles': user_data.get_profiles()}
    
    def save_profile(self, name: str, enabled: list, disabled: list, 
                     flags: dict = None, custom_flags: str = '',
                     custom_flags_list: list = None,
                     excluded_packages: list = None,
                     description: str = '', avatar: str = 'default.svg') -> dict:
        """Save a profile"""
        user_data = get_user_data()
        user_data.save_profile(name, enabled, disabled, flags, custom_flags, custom_flags_list, excluded_packages, description, avatar)
        return {'success': True, 'message': f'Profile "{name}" saved'}
    
    def launch_profile(self, name: str) -> dict:
        """Launch a profile by creating and running its batch file"""
        import subprocess
        user_data = get_user_data()
        profile = user_data.get_profile(name)
        if not profile:
            return {'success': False, 'message': 'Profile not found'}
        
        # Create batch file for this profile
        profiles_dir = Path(__file__).parent / 'profiles'
        profiles_dir.mkdir(exist_ok=True)
        bat_path = profiles_dir / f'{name}.bat'
        
        # Build command line flags
        flags = []
        for key, value in (profile.get('flags') or {}).items():
            if value:
                flags.append(value)
        if profile.get('custom_flags'):
            flags.append(profile.get('custom_flags'))
        
        flags_str = ' '.join(flags)
        
        # Find ComfyUI run script
        comfy_root = Path(__file__).parent.parent.parent
        run_script = comfy_root.parent / 'run_nvidia_gpu.bat'
        if not run_script.exists():
            run_script = comfy_root / 'main.py'
        
        # Create batch file content
        if run_script.suffix == '.bat':
            bat_content = f'@echo off\ncd /d "{comfy_root.parent}"\ncall "{run_script}" {flags_str}\n'
        else:
            python_path = comfy_root.parent / 'python_embeded' / 'python.exe'
            if not python_path.exists():
                import sys
                python_path = sys.executable
            bat_content = f'@echo off\ncd /d "{comfy_root}"\n"{python_path}" "{run_script}" {flags_str}\n'
        
        with open(bat_path, 'w') as f:
            f.write(bat_content)
        
        # Launch the batch file
        subprocess.Popen(['cmd', '/c', str(bat_path)], shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE)
        
        return {'success': True, 'message': f'Launching profile {name}...'}
    
    def set_default_profile(self, name: str) -> dict:
        """Set a profile as the default"""
        user_data = get_user_data()
        profiles = user_data.get_profiles()
        
        if name not in profiles:
            return {'success': False, 'message': 'Profile not found'}
        
        # Clear default from all profiles, set on this one
        for pname, profile in profiles.items():
            profile['is_default'] = (pname == name)
        
        user_data._profiles = profiles
        user_data._save_json(user_data.profiles_file, profiles)
        
        return {'success': True, 'message': f'{name} set as default'}
    
    def clear_default_profile(self) -> dict:
        """Clear the default profile"""
        user_data = get_user_data()
        profiles = user_data.get_profiles()
        
        # Clear default from all profiles
        for profile in profiles.values():
            profile['is_default'] = False
        
        user_data._profiles = profiles
        user_data._save_json(user_data.profiles_file, profiles)
        
        return {'success': True, 'message': 'Default profile cleared'}
    
    def delete_profile(self, name: str) -> dict:
        """Delete a profile"""
        user_data = get_user_data()
        if user_data.delete_profile(name):
            return {'success': True, 'message': f'Profile "{name}" deleted'}
        return {'success': False, 'message': 'Profile not found'}
    
    def apply_profile(self, name: str) -> dict:
        """Apply a profile (enable/disable nodes)"""
        user_data = get_user_data()
        profile = user_data.get_profile(name)
        
        if not profile:
            return {'success': False, 'message': 'Profile not found'}
        
        results = {'enabled': [], 'disabled': [], 'errors': []}
        
        enabled_list = profile.get('enabled', [])
        disabled_list = profile.get('disabled', [])
        
        # Get all node folders
        all_nodes = self.scanner.scan()
        all_folders = [n['folder_name'] for n in all_nodes]
        
        # If enabled list is empty, treat as "all nodes enabled"
        # Otherwise, only enable nodes in the list and disable the rest
        if not enabled_list and not disabled_list:
            # Empty lists = use all nodes (enable everything)
            for folder in all_folders:
                success, msg = self.scanner.activate_node(folder)
                if success:
                    results['enabled'].append(folder)
                # Don't log errors for already-enabled nodes
        else:
            # Specific selection - enable only selected, disable others
            enabled_set = set(enabled_list) if enabled_list else set(all_folders)
            
            for folder in all_folders:
                if folder in enabled_set:
                    success, msg = self.scanner.activate_node(folder)
                    if success:
                        results['enabled'].append(folder)
                    elif 'already' not in msg.lower():
                        results['errors'].append(f"{folder}: {msg}")
                else:
                    success, msg = self.scanner.deactivate_node(folder)
                    if success:
                        results['disabled'].append(folder)
                    elif 'already' not in msg.lower():
                        results['errors'].append(f"{folder}: {msg}")
        
        self._cached_nodes = None
        return {'success': True, 'results': results}
    
    # ==================== BACKUP/RESTORE ====================
    
    def export_backup(self) -> dict:
        """Export user data backup"""
        user_data = get_user_data()
        return {'success': True, 'backup': user_data.export_backup()}
    
    def import_backup(self, data: dict, merge: bool = False) -> dict:
        """Import user data backup"""
        user_data = get_user_data()
        if user_data.import_backup(data, merge):
            return {'success': True, 'message': 'Backup imported successfully'}
        return {'success': False, 'message': 'Failed to import backup'}
    
    def export_node_list(self) -> dict:
        """Export list of installed nodes for reinstallation"""
        user_data = get_user_data()
        nodes = self.get_nodes()['nodes']
        return {'success': True, 'data': user_data.export_node_list(nodes)}
    
    # ==================== UPDATE MANAGEMENT ====================
    
    def check_updates(self, folder_name: str = None) -> dict:
        """Check for updates (single node or all)"""
        if folder_name:
            result = self.scanner.check_for_updates(folder_name)
            return {'success': True, 'folder_name': folder_name, **result}
        else:
            results = self.scanner.batch_check_updates()
            updates_available = {k: v for k, v in results.items() if v.get('has_updates')}
            return {
                'success': True,
                'updates_available': len(updates_available),
                'total_checked': len(results),
                'nodes': results
            }
    
    def batch_update(self, folder_names: list = None) -> dict:
        """Update multiple nodes"""
        results = self.scanner.batch_update(folder_names)
        successes = sum(1 for v in results.values() if v[0])
        self._cached_nodes = None
        return {
            'success': True,
            'updated': successes,
            'total': len(results),
            'results': {k: {'success': v[0], 'message': v[1]} for k, v in results.items()}
        }
    
    # ==================== DISK USAGE ====================
    
    def get_disk_usage(self, folder_name: str = None) -> dict:
        """Get disk usage for a node or all nodes"""
        if folder_name:
            return {'success': True, **self.scanner.get_disk_usage(folder_name)}
        else:
            results = {}
            total_size = 0
            for node in self.scanner.nodes:
                usage = self.scanner.get_disk_usage(node.folder_name)
                results[node.folder_name] = usage
                total_size += usage['size_bytes']
            
            return {
                'success': True,
                'total_size_bytes': total_size,
                'total_size_formatted': self.scanner._format_size(total_size),
                'nodes': results
            }
    
    # ==================== GIT HISTORY ====================
    
    def get_git_log(self, folder_name: str, count: int = 10) -> dict:
        """Get git commit history for a node"""
        commits = self.scanner.get_git_log(folder_name, count)
        return {'success': True, 'commits': commits}
    
    def rollback_node(self, folder_name: str, commit_hash: str) -> dict:
        """Rollback a node to a specific commit"""
        success, message = self.scanner.rollback_node(folder_name, commit_hash)
        return {'success': success, 'message': message}
    
    # ==================== BROKEN NODE DETECTION ====================
    
    def detect_broken_nodes(self) -> dict:
        """Detect nodes with issues"""
        if not self.scanner.nodes:
            self.get_nodes()
        broken = self.scanner.detect_broken_nodes()
        return {'success': True, 'broken_nodes': broken, 'count': len(broken)}
    
    # ==================== BROWSE NEW NODES ====================
    
    def browse_available_nodes(self, search: str = '', category: str = '', 
                                installed_only: bool = False, not_installed_only: bool = False,
                                sort_by: str = 'stars', limit: int = 100, offset: int = 0) -> dict:
        """Browse available nodes from ComfyUI-Manager database"""
        result = browse_nodes(
            search=search,
            category=category,
            installed_only=installed_only,
            not_installed_only=not_installed_only,
            sort_by=sort_by,
            limit=limit,
            offset=offset
        )
        return {'success': True, **result}
    
    def get_browse_categories(self) -> dict:
        """Get all available categories for browsing"""
        return {'success': True, 'categories': get_categories()}
    
    def refresh_browse_database(self) -> dict:
        """Refresh the browse node database"""
        if refresh_node_database():
            return {'success': True, 'message': 'Database refreshed'}
        return {'success': False, 'message': 'Failed to refresh database'}
    
    # ==================== PACKAGES ====================
    
    def get_packages(self) -> dict:
        """Get list of installed Python packages"""
        import subprocess
        try:
            # Use python -m pip to list packages
            python_path = self.pip.python_path if self.pip else 'python'
            result = subprocess.run(
                [python_path, '-m', 'pip', 'list', '--format=json'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                packages = json.loads(result.stdout)
                # Add location info
                for pkg in packages:
                    pkg['location'] = ''  # pip list --format=json doesn't include location
                return {'success': True, 'packages': packages}
            else:
                return {'success': False, 'message': result.stderr or 'Failed to list packages'}
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'Timeout listing packages'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def check_package_updates(self) -> dict:
        """Check which packages have updates available"""
        import subprocess
        try:
            python_path = self.pip.python_path if self.pip else 'python'
            result = subprocess.run(
                [python_path, '-m', 'pip', 'list', '--outdated', '--format=json'],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                outdated = json.loads(result.stdout) if result.stdout.strip() else []
                updates = []
                for pkg in outdated:
                    updates.append({
                        'name': pkg.get('name', ''),
                        'current_version': pkg.get('version', ''),
                        'latest_version': pkg.get('latest_version', '')
                    })
                return {'success': True, 'updates': updates}
            else:
                return {'success': False, 'message': result.stderr or 'Failed to check updates'}
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'Timeout checking updates'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def uninstall_package(self, package_name: str) -> dict:
        """Uninstall a specific package"""
        try:
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'uninstall', '-y', package_name],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            # Refresh the package cache
            refresh_installed_packages()
            
            if result.returncode == 0:
                return {'success': True, 'message': f'Successfully uninstalled {package_name}'}
            else:
                return {'success': False, 'message': f'Uninstall failed: {result.stderr}'}
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'Uninstall timed out'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def upgrade_package(self, package_name: str) -> dict:
        """Upgrade a specific package to the latest version"""
        try:
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'install', '--upgrade', package_name],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            # Refresh the package cache
            refresh_installed_packages()
            
            if result.returncode == 0:
                return {'success': True, 'message': f'Successfully upgraded {package_name}'}
            else:
                return {'success': False, 'message': f'Upgrade failed: {result.stderr}'}
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'Upgrade timed out'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def reinstall_package(self, package_name: str) -> dict:
        """Force reinstall a specific package"""
        try:
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'install', '--force-reinstall', '--no-deps', package_name],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            # Refresh the package cache
            refresh_installed_packages()
            
            if result.returncode == 0:
                return {'success': True, 'message': f'Successfully reinstalled {package_name}'}
            else:
                return {'success': False, 'message': f'Reinstall failed: {result.stderr}'}
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'Reinstall timed out'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    # ==================== SETTINGS ====================
    
    def get_settings(self) -> dict:
        """Get user settings"""
        user_data = get_user_data()
        return {'success': True, 'settings': user_data.get_settings()}
    
    def update_settings(self, settings: dict) -> dict:
        """Update user settings"""
        user_data = get_user_data()
        for key, value in settings.items():
            user_data.set_setting(key, value)
        return {'success': True, 'settings': user_data.get_settings()}
    
    # ==================== COMFYUI PROCESS MANAGEMENT ====================
    
    def get_comfy_status(self) -> dict:
        """Get the current status of ComfyUI process"""
        # First check if we have a managed process
        if self.comfy_process is not None:
            poll = self.comfy_process.poll()
            if poll is None:
                return {'success': True, 'status': 'running', 'managed': True}
            else:
                # Process ended
                self.comfy_process = None
        
        # Check if ComfyUI is running externally by trying to connect to its API
        try:
            import urllib.request
            import urllib.error
            
            # Try common ComfyUI ports
            for port in [8188, 8189, 8190]:
                try:
                    req = urllib.request.Request(f'http://127.0.0.1:{port}/system_stats', method='GET')
                    with urllib.request.urlopen(req, timeout=1) as response:
                        if response.status == 200:
                            return {'success': True, 'status': 'running', 'managed': False, 'port': port}
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionRefusedError):
                    continue
                except Exception:
                    continue
        except Exception:
            pass
        
        return {'success': True, 'status': 'stopped'}
    
    def launch_comfy(self, profile_name: str = None) -> dict:
        """Launch ComfyUI with optional profile"""
        if self.comfy_process is not None and self.comfy_process.poll() is None:
            return {'success': False, 'message': 'ComfyUI is already running'}
        
        # Clear output buffer
        with self.output_lock:
            self.comfy_output_buffer = []
            self.comfy_output_index = 0
        
        # Apply profile first (enable/disable nodes)
        if profile_name:
            with self.output_lock:
                self.comfy_output_buffer.append({
                    'text': f'Applying profile "{profile_name}" - enabling/disabling nodes...',
                    'type': 'info'
                })
            
            apply_result = self.apply_profile(profile_name)
            if apply_result.get('success'):
                results = apply_result.get('results', {})
                enabled_count = len(results.get('enabled', []))
                disabled_count = len(results.get('disabled', []))
                errors = results.get('errors', [])
                
                with self.output_lock:
                    self.comfy_output_buffer.append({
                        'text': f'Profile applied: {enabled_count} nodes enabled, {disabled_count} nodes disabled',
                        'type': 'success'
                    })
                    for err in errors:
                        self.comfy_output_buffer.append({'text': f'Warning: {err}', 'type': 'warning'})
            else:
                with self.output_lock:
                    self.comfy_output_buffer.append({
                        'text': f'Warning: Could not apply profile - {apply_result.get("message", "unknown error")}',
                        'type': 'warning'
                    })
        
        # Find ComfyUI paths
        comfy_root = Path(__file__).parent.parent.parent  # custom_nodes/MF_Conductor -> ComfyUI
        portable_root = comfy_root.parent  # ComfyUI -> ComfyUI_windows_portable
        
        # Find Python executable - check multiple locations
        python_path = None
        possible_paths = [
            portable_root / 'python_embeded' / 'python.exe',
            portable_root / 'python' / 'python.exe',
            Path(sys.executable)
        ]
        for p in possible_paths:
            if p.exists():
                python_path = p
                break
        
        if python_path is None:
            return {'success': False, 'message': 'Could not find Python executable'}
        
        # Build flags from profile
        flags = []
        if profile_name:
            user_data = get_user_data()
            profile = user_data.get_profile(profile_name)
            if profile:
                for key, value in (profile.get('flags') or {}).items():
                    if value:
                        flags.append(value)
                if profile.get('custom_flags'):
                    flags.extend(profile.get('custom_flags').split())
        
        # Build command
        main_script = comfy_root / 'main.py'
        if not main_script.exists():
            return {'success': False, 'message': f'ComfyUI main.py not found at {main_script}'}
        
        cmd = [str(python_path), '-u', str(main_script)] + flags  # -u for unbuffered output
        
        print(f"[MF Conductor] Launching ComfyUI: {' '.join(cmd)}")
        
        with self.output_lock:
            self.comfy_output_buffer.append({
                'text': f'Command: {" ".join(cmd)}',
                'type': 'info'
            })
        
        try:
            # Start process with output capture
            # Use CREATE_NEW_PROCESS_GROUP on Windows to allow proper termination
            creation_flags = 0
            if os.name == 'nt':
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
            
            # Set up environment for UTF-8 output
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUTF8'] = '1'
            
            self.comfy_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(comfy_root),
                env=env,
                creationflags=creation_flags
            )
            
            # Start output reader thread
            reader_thread = threading.Thread(target=self._read_comfy_output, daemon=True)
            reader_thread.start()
            
            return {'success': True, 'message': 'ComfyUI started', 'pid': self.comfy_process.pid}
        except Exception as e:
            print(f"[MF Conductor] Error launching ComfyUI: {e}")
            return {'success': False, 'message': str(e)}
    
    def _decode_line(self, line_bytes):
        """Decode a line of bytes trying multiple encodings"""
        # Try UTF-8 first (most likely for modern Python output)
        try:
            return line_bytes.decode('utf-8')
        except UnicodeDecodeError:
            pass
        
        # Try Windows codepage (common on Windows console)
        try:
            return line_bytes.decode('cp1252')
        except UnicodeDecodeError:
            pass
        
        # Try cp437 (DOS/console codepage)
        try:
            return line_bytes.decode('cp437')
        except UnicodeDecodeError:
            pass
        
        # Fallback: decode as UTF-8 replacing invalid chars
        return line_bytes.decode('utf-8', errors='replace')
    
    def _read_comfy_output(self):
        """Background thread to read ComfyUI output"""
        try:
            if self.comfy_process is None or self.comfy_process.stdout is None:
                return
            
            # Read binary and decode ourselves
            while True:
                line_bytes = self.comfy_process.stdout.readline()
                if not line_bytes:
                    break
                
                line = self._decode_line(line_bytes).rstrip('\n\r')
                if not line:
                    continue
                
                # Determine line type based on content
                line_type = 'normal'
                line_lower = line.lower()
                if 'error' in line_lower or 'exception' in line_lower or 'traceback' in line_lower:
                    line_type = 'error'
                elif 'warning' in line_lower or 'warn' in line_lower:
                    line_type = 'warning'
                elif 'success' in line_lower or 'loaded' in line_lower or 'total vram' in line_lower:
                    line_type = 'success'
                elif line.startswith('Starting') or 'listening' in line_lower or 'http://' in line_lower:
                    line_type = 'info'
                
                with self.output_lock:
                    self.comfy_output_buffer.append({'text': line, 'type': line_type})
                    
            # Process ended
            with self.output_lock:
                if self.comfy_process and self.comfy_process.poll() is not None:
                    exit_code = self.comfy_process.poll()
                    self.comfy_output_buffer.append({
                        'text': f'Process exited with code {exit_code}',
                        'type': 'error' if exit_code != 0 else 'info'
                    })
        except Exception as e:
            with self.output_lock:
                self.comfy_output_buffer.append({'text': f'[Output reader error: {e}]', 'type': 'error'})
    
    def get_comfy_output(self) -> dict:
        """Get new console output since last call"""
        with self.output_lock:
            new_output = self.comfy_output_buffer[self.comfy_output_index:]
            self.comfy_output_index = len(self.comfy_output_buffer)
        
        status = self.get_comfy_status()
        
        return {
            'success': True,
            'output': new_output,
            'status': status.get('status', 'stopped')
        }
    
    def stop_comfy(self) -> dict:
        """Stop the ComfyUI process"""
        if self.comfy_process is None or self.comfy_process.poll() is not None:
            self.comfy_process = None
            return {'success': False, 'message': 'ComfyUI is not running'}
        
        try:
            print("[MF Conductor] Stopping ComfyUI process...")
            
            if os.name == 'nt':
                # On Windows, send CTRL+BREAK to the process group
                import signal
                try:
                    self.comfy_process.send_signal(signal.CTRL_BREAK_EVENT)
                except Exception:
                    self.comfy_process.terminate()
            else:
                self.comfy_process.terminate()
            
            # Wait for graceful shutdown
            try:
                self.comfy_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print("[MF Conductor] Process not responding, force killing...")
                self.comfy_process.kill()
                self.comfy_process.wait()
            
            with self.output_lock:
                self.comfy_output_buffer.append({'text': 'ComfyUI process stopped', 'type': 'info'})
            
            self.comfy_process = None
            return {'success': True, 'message': 'ComfyUI stopped'}
        except Exception as e:
            print(f"[MF Conductor] Error stopping ComfyUI: {e}")
            self.comfy_process = None
            return {'success': False, 'message': str(e)}
    
    def restart_comfy(self) -> dict:
        """Restart ComfyUI"""
        # Get current profile from settings or use default
        profile_name = None
        user_data = get_user_data()
        profiles = user_data.get_profiles()
        for name, profile in profiles.items():
            if profile.get('is_default'):
                profile_name = name
                break
        
        # Stop if running
        if self.comfy_process is not None and self.comfy_process.poll() is None:
            stop_result = self.stop_comfy()
            if not stop_result['success']:
                return stop_result
        
        # Launch again
        return self.launch_comfy(profile_name)
    
    def run_python_command(self, command: str) -> dict:
        """Run a Python command in the ComfyUI environment"""
        # Find Python executable
        comfy_root = Path(__file__).parent.parent.parent
        portable_root = comfy_root.parent
        
        python_path = portable_root / 'python_embeded' / 'python.exe'
        if not python_path.exists():
            python_path = Path(sys.executable)
        
        # Split command into parts
        cmd_parts = command.split()
        
        try:
            result = subprocess.run(
                [str(python_path), '-m'] + cmd_parts,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(comfy_root)
            )
            
            return {
                'success': True,
                'output': result.stdout if result.stdout else None,
                'error': result.stderr if result.stderr else None,
                'return_code': result.returncode
            }
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'Command timed out after 120 seconds'}
        except Exception as e:
            return {'success': False, 'message': str(e)}


class MFConductorHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for the standalone server"""
    
    api: MFConductorAPI = None
    web_dir: Path = None
    
    def __init__(self, *args, **kwargs):
        # Set the directory to serve static files from
        self.directory = str(self.web_dir)
        super().__init__(*args, directory=self.directory, **kwargs)
    
    def log_message(self, format, *args):
        """Custom log format"""
        print(f"[MF Conductor] {args[0]}")
    
    def send_json(self, data: dict, status: int = 200):
        """Send a JSON response"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def do_GET(self):
        """Handle GET requests"""
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        
        # API routes
        if path == '/api/nodes':
            data = self.api.get_nodes()
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/details'):
            folder_name = path.split('/')[3]
            data = self.api.get_node(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/requirements'):
            folder_name = path.split('/')[3]
            data = self.api.get_requirements(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/disk-usage'):
            folder_name = path.split('/')[3]
            data = self.api.get_disk_usage(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/git-log'):
            folder_name = path.split('/')[3]
            count = int(query.get('count', ['10'])[0])
            data = self.api.get_git_log(folder_name, count)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/check-updates'):
            folder_name = path.split('/')[3]
            data = self.api.check_updates(folder_name)
            self.send_json(data)
            return
        
        # User data endpoints
        if path == '/api/favorites':
            data = self.api.get_favorites()
            self.send_json(data)
            return
        
        if path == '/api/tags':
            data = self.api.get_tags()
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/tags'):
            folder_name = path.split('/')[3]
            data = self.api.get_tags(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/note'):
            folder_name = path.split('/')[3]
            data = self.api.get_note(folder_name)
            self.send_json(data)
            return
        
        if path == '/api/user-data':
            data = self.api.get_all_user_data()
            self.send_json(data)
            return
        
        # Profiles
        if path == '/api/profiles':
            data = self.api.get_profiles()
            self.send_json(data)
            return
        
        # Backup/Export
        if path == '/api/backup':
            data = self.api.export_backup()
            self.send_json(data)
            return
        
        if path == '/api/export-nodes':
            data = self.api.export_node_list()
            self.send_json(data)
            return
        
        # Update checking
        if path == '/api/check-updates':
            data = self.api.check_updates()
            self.send_json(data)
            return
        
        # Disk usage
        if path == '/api/disk-usage':
            data = self.api.get_disk_usage()
            self.send_json(data)
            return
        
        # Broken nodes
        if path == '/api/broken-nodes':
            data = self.api.detect_broken_nodes()
            self.send_json(data)
            return
        
        # Browse nodes
        if path == '/api/browse':
            search = query.get('search', [''])[0]
            category = query.get('category', [''])[0]
            sort_by = query.get('sort', ['stars'])[0]
            limit = int(query.get('limit', ['100'])[0])
            offset = int(query.get('offset', ['0'])[0])
            installed_only = query.get('installed', ['false'])[0] == 'true'
            not_installed_only = query.get('not_installed', ['false'])[0] == 'true'
            
            data = self.api.browse_available_nodes(
                search=search,
                category=category,
                installed_only=installed_only,
                not_installed_only=not_installed_only,
                sort_by=sort_by,
                limit=limit,
                offset=offset
            )
            self.send_json(data)
            return
        
        if path == '/api/browse/categories':
            data = self.api.get_browse_categories()
            self.send_json(data)
            return
        
        # Settings
        if path == '/api/settings':
            data = self.api.get_settings()
            self.send_json(data)
            return
        
        # Packages
        if path == '/api/packages':
            data = self.api.get_packages()
            self.send_json(data)
            return
        
        # ComfyUI Process Management
        if path == '/api/comfy/status':
            data = self.api.get_comfy_status()
            self.send_json(data)
            return
        
        if path == '/api/comfy/output':
            data = self.api.get_comfy_output()
            self.send_json(data)
            return
        
        # Serve static files
        if path == '/' or path == '':
            self.path = '/index.html'
        
        return super().do_GET()
    
    def do_POST(self):
        """Handle POST requests"""
        parsed = urlparse(self.path)
        path = parsed.path
        # Debug: print(f"[MF Conductor] POST request: {path}")
        
        # Read request body
        content_length = int(self.headers.get('Content-Length', 0))
        body = {}
        if content_length > 0:
            try:
                raw_body = self.rfile.read(content_length).decode('utf-8')
                body = json.loads(raw_body)
            except json.JSONDecodeError as e:
                print(f"[MF Conductor] JSON decode error: {e}")
                self.send_json({'success': False, 'message': f'Invalid JSON: {str(e)}'}, 400)
                return
            except Exception as e:
                print(f"[MF Conductor] Body read error: {e}")
                self.send_json({'success': False, 'message': f'Error reading request: {str(e)}'}, 400)
                return
        
        # API routes
        if path == '/api/nodes/refresh':
            data = self.api.refresh_nodes()
            self.send_json(data)
            return
        
        if path == '/api/nodes/install':
            url = body.get('url', '')
            folder_name = body.get('folder_name')
            install_deps = body.get('install_deps', True)
            
            if not url:
                self.send_json({'success': False, 'message': 'URL is required'}, 400)
                return
            
            data = self.api.install_node(url, folder_name, install_deps)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/update'):
            folder_name = path.split('/')[3]
            data = self.api.update_node(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/open-folder'):
            folder_name = path.split('/')[3]
            data = self.api.open_folder(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/remove'):
            folder_name = path.split('/')[3]
            data = self.api.remove_node(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/deactivate'):
            folder_name = path.split('/')[3]
            data = self.api.deactivate_node(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/activate'):
            folder_name = path.split('/')[3]
            data = self.api.activate_node(folder_name)
            self.send_json(data)
            return
        
        if path == '/api/install-package':
            package_name = body.get('package_name', '')
            if not package_name:
                self.send_json({'success': False, 'message': 'Package name is required'}, 400)
                return
            data = self.api.install_package(package_name)
            self.send_json(data)
            return
        
        # Package management endpoints
        if path == '/api/packages/install':
            package_name = body.get('package_name', '')
            if not package_name:
                self.send_json({'success': False, 'message': 'Package name is required'}, 400)
                return
            data = self.api.install_package(package_name)
            self.send_json(data)
            return
        
        if path == '/api/packages/uninstall':
            package_name = body.get('package_name', '')
            if not package_name:
                self.send_json({'success': False, 'message': 'Package name is required'}, 400)
                return
            data = self.api.uninstall_package(package_name)
            self.send_json(data)
            return
        
        if path == '/api/packages/upgrade':
            package_name = body.get('package_name', '')
            if not package_name:
                self.send_json({'success': False, 'message': 'Package name is required'}, 400)
                return
            data = self.api.upgrade_package(package_name)
            self.send_json(data)
            return
        
        if path == '/api/packages/reinstall':
            package_name = body.get('package_name', '')
            if not package_name:
                self.send_json({'success': False, 'message': 'Package name is required'}, 400)
                return
            data = self.api.reinstall_package(package_name)
            self.send_json(data)
            return
        
        if path == '/api/packages/check-updates':
            data = self.api.check_package_updates()
            self.send_json(data)
            return
        
        # Favorites
        if path.startswith('/api/nodes/') and path.endswith('/toggle-favorite'):
            folder_name = path.split('/')[3]
            data = self.api.toggle_favorite(folder_name)
            self.send_json(data)
            return
        
        # Tags
        if path.startswith('/api/nodes/') and path.endswith('/tags'):
            folder_name = path.split('/')[3]
            tags = body.get('tags', [])
            data = self.api.set_tags(folder_name, tags)
            self.send_json(data)
            return
        
        # Notes
        if path.startswith('/api/nodes/') and path.endswith('/note'):
            folder_name = path.split('/')[3]
            note = body.get('note', '')
            data = self.api.set_note(folder_name, note)
            self.send_json(data)
            return
        
        # Profiles
        if path == '/api/profiles/save':
            name = body.get('name', '')
            old_name = body.get('old_name', '')  # For renaming profiles
            enabled = body.get('enabled', [])
            disabled = body.get('disabled', [])
            flags = body.get('flags', {})
            custom_flags = body.get('custom_flags', '')
            custom_flags_list = body.get('custom_flags_list', [])
            excluded_packages = body.get('excluded_packages', [])
            description = body.get('description', '')
            avatar = body.get('avatar', 'default.svg')
            
            if not name:
                self.send_json({'success': False, 'message': 'Profile name is required'}, 400)
                return
            
            # If renaming (old_name provided and different), delete the old profile first
            if old_name and old_name != name:
                user_data = get_user_data()
                user_data.delete_profile(old_name)
            
            data = self.api.save_profile(name, enabled, disabled, flags, custom_flags, custom_flags_list, excluded_packages, description, avatar)
            self.send_json(data)
            return
        
        if path == '/api/profiles/delete':
            name = body.get('name', '')
            if not name:
                self.send_json({'success': False, 'message': 'Profile name is required'}, 400)
                return
            data = self.api.delete_profile(name)
            self.send_json(data)
            return
        
        if path == '/api/profiles/load-presets':
            user_data = get_user_data()
            count = user_data.load_preset_profiles()
            self.send_json({'success': True, 'message': f'Loaded {count} preset profiles', 'count': count})
            return
        
        if path == '/api/profiles/apply':
            name = body.get('name', '')
            if not name:
                self.send_json({'success': False, 'message': 'Profile name is required'}, 400)
                return
            data = self.api.apply_profile(name)
            self.send_json(data)
            return
        
        if path == '/api/profiles/launch':
            name = body.get('name', '')
            if not name:
                self.send_json({'success': False, 'message': 'Profile name is required'}, 400)
                return
            data = self.api.launch_profile(name)
            self.send_json(data)
            return
        
        if path == '/api/profiles/set-default':
            name = body.get('name', '')
            if not name:
                self.send_json({'success': False, 'message': 'Profile name is required'}, 400)
                return
            data = self.api.set_default_profile(name)
            self.send_json(data)
            return
        
        if path == '/api/profiles/clear-default':
            data = self.api.clear_default_profile()
            self.send_json(data)
            return
        
        # Backup/Restore
        if path == '/api/backup/import':
            backup_data = body.get('data', {})
            merge = body.get('merge', False)
            data = self.api.import_backup(backup_data, merge)
            self.send_json(data)
            return
        
        # Batch updates
        if path == '/api/batch-update':
            folder_names = body.get('folder_names')  # None = update all
            data = self.api.batch_update(folder_names)
            self.send_json(data)
            return
        
        # Rollback
        if path.startswith('/api/nodes/') and path.endswith('/rollback'):
            folder_name = path.split('/')[3]
            commit_hash = body.get('commit_hash', '')
            if not commit_hash:
                self.send_json({'success': False, 'message': 'Commit hash is required'}, 400)
                return
            data = self.api.rollback_node(folder_name, commit_hash)
            self.send_json(data)
            return
        
        # Browse database refresh
        if path == '/api/browse/refresh':
            data = self.api.refresh_browse_database()
            self.send_json(data)
            return
        
        # Settings
        if path == '/api/settings':
            settings = body.get('settings', {})
            data = self.api.update_settings(settings)
            self.send_json(data)
            return
        
        # ComfyUI Process Management
        if path == '/api/comfy/launch':
            profile = body.get('profile', '')
            data = self.api.launch_comfy(profile)
            self.send_json(data)
            return
        
        if path == '/api/comfy/stop':
            data = self.api.stop_comfy()
            self.send_json(data)
            return
        
        if path == '/api/comfy/restart':
            data = self.api.restart_comfy()
            self.send_json(data)
            return
        
        if path == '/api/comfy/run-command':
            command = body.get('command', '')
            if not command:
                self.send_json({'success': False, 'message': 'Command is required'}, 400)
                return
            data = self.api.run_python_command(command)
            self.send_json(data)
            return
        
        self.send_json({'success': False, 'message': 'Not found'}, 404)


def run_server(host: str = 'localhost', port: int = 8199, custom_nodes_path: str = None, open_browser: bool = True):
    """Run the standalone MF Conductor server"""
    
    # Initialize API
    MFConductorHandler.api = MFConductorAPI(custom_nodes_path)
    MFConductorHandler.web_dir = Path(__file__).parent / 'web'
    
    # Create server
    server = HTTPServer((host, port), MFConductorHandler)
    
    print("=" * 60)
    print("  MF Conductor - Custom Node Manager")
    print("=" * 60)
    print(f"  Server running at: http://{host}:{port}")
    print(f"  Custom nodes path: {MFConductorHandler.api.custom_nodes_path}")
    print("-" * 60)
    print("  Press Ctrl+C to stop the server")
    print("=" * 60)
    
    # Open browser
    if open_browser:
        def open_browser_delayed():
            import time
            time.sleep(0.5)
            webbrowser.open(f'http://{host}:{port}')
        
        threading.Thread(target=open_browser_delayed, daemon=True).start()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.shutdown()


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='MF Conductor - Custom Node Manager')
    parser.add_argument('--host', default='localhost', help='Host to bind to (default: localhost)')
    parser.add_argument('--port', type=int, default=8199, help='Port to bind to (default: 8199)')
    parser.add_argument('--path', help='Path to custom_nodes directory')
    parser.add_argument('--no-browser', action='store_true', help='Do not open browser automatically')
    
    args = parser.parse_args()
    
    run_server(
        host=args.host,
        port=args.port,
        custom_nodes_path=args.path,
        open_browser=not args.no_browser
    )


if __name__ == '__main__':
    main()


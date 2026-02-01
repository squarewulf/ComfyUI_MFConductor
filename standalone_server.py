"""
MF_Conductor - Standalone Server
Can run independently of ComfyUI for offline node management
"""

import os
import sys
import json
import subprocess
import struct
import webbrowser
import time
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
import threading

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from node_scanner import NodeScanner, get_node_requirements, refresh_installed_packages, clear_manager_db_cache, CACHE_VERSION
from git_utils import GitUtils, PipUtils
from user_data import get_user_data
from browse_nodes import browse_nodes, get_categories, refresh_node_database, get_node_details
from usage_tracker import get_usage_tracker


class MFConductorAPI:
    """API handler for MF Conductor operations"""
    
    def __init__(self, custom_nodes_path: str = None):
        self.scanner = NodeScanner(custom_nodes_path)
        self.git = GitUtils(custom_nodes_path)
        self.pip = PipUtils()
        self.custom_nodes_path = self.scanner.custom_nodes_path
        self._cached_nodes = None
        self._cache_time = None
        
        # ComfyUI root path (parent of custom_nodes)
        self.comfy_root = Path(self.custom_nodes_path).parent
        
        # ComfyUI process management
        self.comfy_process = None
        self.comfy_output_buffer = []
        self.comfy_output_index = 0  # Track what output has been sent to client
        self.output_lock = threading.Lock()
        
        # Backend log buffer for frontend console
        self.backend_logs = []
        self.backend_log_lock = threading.Lock()
        self.backend_log_index = 0  # Track what logs have been sent to client
        self.max_backend_logs = 1000
        
        # Console output buffer limits
        self.max_comfy_output = 5000

    def _extract_png_workflow_prompt_pil(self, file_path: Path):
        """Best-effort extraction of workflow/prompt strings from PNG via Pillow (img.text/img.info)."""
        try:
            from PIL import Image

            img = Image.open(file_path)
            try:
                info = getattr(img, 'info', {}) or {}
                text = getattr(img, 'text', None)

                def _get(src, key: str):
                    if not src or not hasattr(src, 'get'):
                        return None
                    v = src.get(key)
                    if v is None:
                        return None
                    if isinstance(v, (bytes, bytearray)):
                        return v.decode('utf-8', errors='ignore')
                    return v

                # Prefer Pillow PNG text chunks if available
                workflow_data = (
                    _get(text, 'workflow') or _get(text, 'Workflow') or _get(text, 'comfyui_workflow') or
                    _get(info, 'workflow') or _get(info, 'Workflow') or _get(info, 'comfyui_workflow')
                )
                prompt_data = (
                    _get(text, 'prompt') or _get(text, 'Prompt') or
                    _get(info, 'prompt') or _get(info, 'Prompt')
                )

                # Some exporters store a JSON-ish payload in "parameters"
                if not prompt_data:
                    prompt_data = _get(text, 'parameters') or _get(info, 'parameters')

                return workflow_data, prompt_data
            finally:
                try:
                    img.close()
                except Exception:
                    pass
        except Exception:
            return None, None

    def _decode_exif_user_comment(self, value):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if not isinstance(value, (bytes, bytearray)):
            return None
        data = bytes(value)
        if len(data) >= 8:
            prefix = data[:8]
            payload = data[8:]
            if prefix.startswith(b'ASCII'):
                return payload.decode('ascii', errors='ignore').strip('\x00')
            if prefix.startswith(b'UNICODE'):
                try:
                    return payload.decode('utf-16', errors='ignore').strip('\x00')
                except Exception:
                    return payload.decode('utf-16-be', errors='ignore').strip('\x00')
            if prefix.startswith(b'JIS'):
                return payload.decode('shift_jis', errors='ignore').strip('\x00')
        return data.decode('utf-8', errors='ignore')

    def _find_exif_tag_value(self, exif_data: bytes, tag_id: int):
        if not exif_data:
            return None
        data = exif_data
        if data[:6] == b'Exif\x00\x00':
            data = data[6:]
        if len(data) < 8:
            return None
        endian = data[:2]
        if endian == b'II':
            fmt = '<'
        elif endian == b'MM':
            fmt = '>'
        else:
            return None
        if struct.unpack(fmt + 'H', data[2:4])[0] != 42:
            return None
        ifd0_offset = struct.unpack(fmt + 'I', data[4:8])[0]

        def read_ifd(offset):
            if offset + 2 > len(data):
                return []
            count = struct.unpack(fmt + 'H', data[offset:offset + 2])[0]
            entries = []
            pos = offset + 2
            for _ in range(count):
                if pos + 12 > len(data):
                    break
                tag, typ, num, value_offset = struct.unpack(fmt + 'HHII', data[pos:pos + 12])
                entries.append((tag, typ, num, value_offset, pos))
                pos += 12
            return entries

        def value_bytes(typ, num, value_offset, entry_pos):
            type_sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
            size = type_sizes.get(typ, 1) * num
            if size <= 4:
                return data[entry_pos + 8:entry_pos + 12]
            if value_offset + size > len(data):
                return None
            return data[value_offset:value_offset + size]

        entries0 = read_ifd(ifd0_offset)
        exif_ifd_offset = None
        for tag, typ, num, value_offset, pos in entries0:
            if tag == tag_id:
                return value_bytes(typ, num, value_offset, pos)
            if tag == 0x8769:
                exif_ifd_offset = value_offset
        if exif_ifd_offset is not None:
            entries_exif = read_ifd(exif_ifd_offset)
            for tag, typ, num, value_offset, pos in entries_exif:
                if tag == tag_id:
                    return value_bytes(typ, num, value_offset, pos)
        return None

    def _extract_exif_user_comment(self, img, exif_data):
        try:
            exif = img.getexif()
            if exif:
                text = self._decode_exif_user_comment(exif.get(0x9286))
                if text:
                    return text
        except Exception:
            pass
        if exif_data:
            try:
                import piexif
                exif_dict = piexif.load(exif_data)
                text = self._decode_exif_user_comment(
                    exif_dict.get('Exif', {}).get(piexif.ExifIFD.UserComment)
                )
                if text:
                    return text
            except ImportError:
                pass
            except Exception:
                pass
            try:
                raw = self._find_exif_tag_value(exif_data, 0x9286)
                text = self._decode_exif_user_comment(raw)
                if text:
                    return text
            except Exception:
                pass
        return None
    
    def add_backend_log(self, message: str, log_type: str = 'info'):
        """Add a log message to the backend log buffer"""
        with self.backend_log_lock:
            self.backend_logs.append({
                'message': message,
                'type': log_type,
                'time': time.time()
            })
            # Keep only last N logs
            if len(self.backend_logs) > self.max_backend_logs:
                self.backend_logs.pop(0)
    
    def get_backend_logs(self, since_index: int = 0) -> list:
        """Get backend logs since the given index"""
        with self.backend_log_lock:
            return list(self.backend_logs[since_index:])  # Return copy to avoid race condition
    
    def get_nodes(self, refresh: bool = False, fast: bool = False) -> dict:
        """Get list of all custom nodes"""
        if not refresh and fast:
            cache = self.scanner.get_cached_nodes(allow_stale=True)
            if cache and cache.get('nodes') is not None:
                cache_version = cache.get('version')
                stale = cache_version != CACHE_VERSION
                self._cached_nodes = cache.get('nodes', [])
                self._cache_time = cache.get('scanned_at')
                if stale:
                    threading.Thread(target=self.scanner.refresh, daemon=True).start()
                return {
                    'nodes': self._cached_nodes,
                    'scanned_at': self._cache_time,
                    'total': len(self._cached_nodes),
                    'cache_used': True,
                    'cache_stale': stale
                }
        
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
        
        return {'success': True, 'message': message, 'folder_name': folder_name}
    
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
        
        # Get all node folders (fast - no full scan needed)
        all_folders = self.scanner.list_folder_names()
        
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
                    # Ignore "not found" and "already" messages - these are normal
                    elif 'already' not in msg.lower() and 'not found' not in msg.lower():
                        results['errors'].append(f"{folder}: {msg}")
                else:
                    success, msg = self.scanner.deactivate_node(folder)
                    if success:
                        results['disabled'].append(folder)
                    # Ignore "not found" and "already" messages - these are normal
                    elif 'already' not in msg.lower() and 'not found' not in msg.lower():
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
        """Check which packages have updates available - FAST version using PyPI API"""
        import subprocess
        import urllib.request
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        try:
            python_path = self.pip.python_path if self.pip else 'python'
            
            # Step 1: Get list of installed packages (FAST - just reads local metadata)
            result = subprocess.run(
                [python_path, '-m', 'pip', 'list', '--format=json'],
                capture_output=True,
                text=True,
                timeout=10  # Should be very fast
            )
            
            if result.returncode != 0:
                return {'success': False, 'message': 'Failed to get installed packages list'}
            
            installed_packages = json.loads(result.stdout) if result.stdout.strip() else []
            if not installed_packages:
                return {'success': True, 'updates': []}
            
            # Step 2: Check PyPI API for each package in parallel (MUCH faster than pip list --outdated)
            updates = []
            lock = threading.Lock()
            
            def check_package(pkg_info):
                """Check a single package against PyPI"""
                package_name = pkg_info.get('name', '').lower()
                current_version = pkg_info.get('version', '')
                
                if not package_name:
                    return None
                
                try:
                    # Skip packages that are not from PyPI (local, editable installs, etc.)
                    if not current_version or current_version.startswith('file://'):
                        return None
                    
                    # Check PyPI JSON API (fast HTTP request)
                    url = f'https://pypi.org/pypi/{package_name}/json'
                    with urllib.request.urlopen(url, timeout=3) as response:
                        data = json.loads(response.read())
                        latest_version = data.get('info', {}).get('version', '')
                        
                        if latest_version and latest_version != current_version:
                            # Compare versions properly
                            try:
                                from packaging import version
                                if version.parse(latest_version) > version.parse(current_version):
                                    return {
                                        'name': package_name,
                                        'current_version': current_version,
                                        'latest_version': latest_version
                                    }
                            except (ImportError, Exception):
                                # Fallback: simple string comparison if packaging not available
                                if latest_version > current_version:
                                    return {
                                        'name': package_name,
                                        'current_version': current_version,
                                        'latest_version': latest_version
                                    }
                except urllib.error.HTTPError as e:
                    # Package not found on PyPI (might be local/private)
                    if e.code != 404:
                        pass  # Other errors we can ignore
                except Exception:
                    # Network error, timeout, etc. - skip this package
                    pass
                
                return None
            
            # Check packages in parallel (20 concurrent requests)
            with ThreadPoolExecutor(max_workers=20) as executor:
                futures = {executor.submit(check_package, pkg): pkg for pkg in installed_packages}
                
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        with lock:
                            updates.append(result)
            
            return {'success': True, 'updates': updates}
            
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'Timeout getting installed packages list'}
        except json.JSONDecodeError as e:
            return {'success': False, 'message': f'Invalid response from pip: {str(e)}'}
        except Exception as e:
            return {'success': False, 'message': f'Error: {str(e)}'}
    
    def check_single_package_update(self, package_name: str) -> dict:
        """Check if a single package has updates available - FAST version using PyPI API"""
        import subprocess
        import urllib.request
        
        try:
            python_path = self.pip.python_path if self.pip else 'python'
            
            # Get current version (fast)
            current_result = subprocess.run(
                [python_path, '-m', 'pip', 'show', package_name],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            current = 'unknown'
            if current_result.returncode == 0:
                for line in current_result.stdout.split('\n'):
                    if line.startswith('Version:'):
                        current = line.split(':', 1)[1].strip()
                        break
            
            # Check PyPI API directly (much faster than pip install --dry-run)
            try:
                url = f'https://pypi.org/pypi/{package_name}/json'
                with urllib.request.urlopen(url, timeout=3) as response:
                    data = json.loads(response.read())
                    latest = data.get('info', {}).get('version', current)
                    
                    # Get list of available versions (newer than current)
                    available_versions = []
                    releases = data.get('releases', {})
                    try:
                        from packaging import version as pkg_version
                        current_parsed = pkg_version.parse(current) if current != 'unknown' else None
                        
                        for ver in releases.keys():
                            try:
                                ver_parsed = pkg_version.parse(ver)
                                # Only include versions newer than current
                                if current_parsed and ver_parsed > current_parsed:
                                    # Check if release has files (not yanked/empty)
                                    if releases[ver]:
                                        available_versions.append(ver)
                            except (ValueError, TypeError, KeyError):
                                continue
                        
                        # Sort versions descending (newest first)
                        available_versions.sort(key=lambda v: pkg_version.parse(v), reverse=True)
                    except (ImportError, ValueError, KeyError):
                        # Fallback: just include latest if different
                        if latest != current:
                            available_versions = [latest]
                    
                    # Compare versions properly
                    has_update = False
                    if latest and latest != 'unknown' and latest != current:
                        try:
                            from packaging import version
                            has_update = version.parse(latest) > version.parse(current)
                        except (ImportError, ValueError, TypeError):
                            # Fallback: simple string comparison
                            has_update = latest > current
                    
                    return {
                        'success': True,
                        'name': package_name,
                        'current_version': current,
                        'latest_version': latest,
                        'has_update': has_update,
                        'available_versions': available_versions[:10]  # Limit to 10 most recent
                    }
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    # Package not on PyPI (local/private)
                    return {
                        'success': True,
                        'name': package_name,
                        'current_version': current,
                        'latest_version': current,
                        'has_update': False
                    }
                raise
            except Exception:
                # Network error - assume up to date
                return {
                    'success': True,
                    'name': package_name,
                    'current_version': current,
                    'latest_version': current,
                    'has_update': False
                }
                
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'Check timed out'}
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
    
    def upgrade_package(self, package_name: str, version: str = None) -> dict:
        """Upgrade a specific package to a specific version or latest"""
        try:
            if version:
                package_spec = f'{package_name}=={version}'
            else:
                package_spec = package_name
            
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'install', '--upgrade', package_spec],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            # Refresh the package cache
            refresh_installed_packages()
            
            if result.returncode == 0:
                version_msg = f' to {version}' if version else ''
                return {'success': True, 'message': f'Successfully upgraded {package_name}{version_msg}'}
            else:
                return {'success': False, 'message': f'Upgrade failed: {result.stderr}'}
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'Upgrade timed out'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    # ==================== FILE BROWSER OPERATIONS ====================
    
    def get_comfy_folder_path(self, folder_type: str) -> Path:
        """Get path to a ComfyUI folder (../../output, ../../input, etc. from this module)"""
        # Simple relative paths from this module's directory
        module_dir = Path(__file__).parent
        comfy_root = (module_dir / '../..').resolve()
        
        folder_map = {
            'output': comfy_root / 'output',
            'input': comfy_root / 'input',
            'models': comfy_root / 'models',
            'temp': comfy_root / 'temp',
        }
        
        return folder_map.get(folder_type, comfy_root / 'output')
    
    def get_files(self, folder_type: str = 'output', subfolder: str = '', 
                  sort_by: str = 'date', sort_dir: str = 'desc',
                  file_type: str = '', search: str = '', recursive: bool = False,
                  with_workflow: bool = False) -> dict:
        """Get files from a ComfyUI folder"""
        try:
            # Handle 'both' folder type - combine output and input
            if folder_type == 'both':
                output_result = self.get_files('output', subfolder, sort_by, sort_dir, file_type, search, recursive, with_workflow)
                input_result = self.get_files('input', subfolder, sort_by, sort_dir, file_type, search, recursive, with_workflow)
                
                all_files = []
                if output_result.get('success'):
                    for f in output_result.get('files', []):
                        f['source'] = 'output'
                    all_files.extend(output_result.get('files', []))
                if input_result.get('success'):
                    for f in input_result.get('files', []):
                        f['source'] = 'input'
                    all_files.extend(input_result.get('files', []))
                
                # Re-sort combined results
                sort_key_map = {
                    'name': lambda x: x['name'].lower(),
                    'date': lambda x: x['modified'],
                    'size': lambda x: x['size'],
                    'type': lambda x: (x['type'], x['name'].lower()),
                    'workflow': lambda x: (x.get('workflow') or '', x['name'].lower())
                }
                sort_key = sort_key_map.get(sort_by, sort_key_map['date'])
                all_files.sort(key=sort_key, reverse=(sort_dir == 'desc'))
                
                total_size = sum(f.get('size', 0) for f in all_files)
                return {
                    'success': True,
                    'files': all_files[:500],  # Limit
                    'path': 'output + input',
                    'folder_type': 'both',
                    'subfolder': subfolder,
                    'total': len(all_files),
                    'total_size': total_size
                }
            
            folder_path = self.get_comfy_folder_path(folder_type)
            
            if subfolder and not recursive:
                folder_path = folder_path / subfolder
            
            if not folder_path.exists():
                return {
                    'success': True,
                    'files': [],
                    'path': str(folder_path),
                    'total': 0,
                    'total_size': 0
                }
            
            files = []
            total_size = 0
            max_files = 500  # Limit for performance
            
            # File type extensions
            image_exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff'}
            video_exts = {'.mp4', '.webm', '.mov', '.avi', '.mkv', '.gif'}
            audio_exts = {'.mp3', '.wav', '.ogg', '.flac', '.m4a'}
            
            base_path = self.get_comfy_folder_path(folder_type)
            
            # Use rglob for recursive, iterdir for non-recursive
            items_iter = folder_path.rglob('*') if recursive else folder_path.iterdir()
            
            items_processed = 0
            for item in items_iter:
                items_processed += 1
                if item.name.startswith('.'):
                    continue
                
                # Skip directories in recursive mode
                if recursive and item.is_dir():
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
                except Exception as stat_error:
                    print(f"[MF Conductor] Warning: Could not stat {item}: {stat_error}")
                    size = 0
                    mtime = 0
                
                total_size += size
                
                try:
                    rel_path = str(item.relative_to(base_path)).replace('\\', '/')
                except ValueError:
                    rel_path = item.name
                
                # Extract workflow name from image metadata (PNG and WebP) - only if requested
                workflow_name = None
                if with_workflow and ext in ['.png', '.webp'] and item.is_file():
                    workflow_name = self._get_workflow_name(item)
                
                files.append({
                    'name': item.name,
                    'path': rel_path,
                    'type': ftype,
                    'extension': ext,
                    'size': size,
                    'modified': mtime,
                    'is_dir': item.is_dir(),
                    'workflow': workflow_name
                })
                
                # Limit files for performance
                if len(files) >= max_files:
                    break
            
            # Sort files
            sort_key_map = {
                'name': lambda x: x['name'].lower(),
                'date': lambda x: x['modified'],
                'size': lambda x: x['size'],
                'type': lambda x: (x['type'], x['name'].lower()),
                'workflow': lambda x: (x.get('workflow') or '', x['name'].lower())
            }
            
            sort_key = sort_key_map.get(sort_by, sort_key_map['date'])
            files.sort(key=sort_key, reverse=(sort_dir == 'desc'))
            
            return {
                'success': True,
                'files': files,
                'path': str(folder_path),
                'folder_type': folder_type,
                'subfolder': subfolder,
                'total': len(files),
                'total_size': total_size
            }
        except Exception as e:
            import traceback
            error_msg = f"[MF Conductor] get_files error: {str(e)}\n{traceback.format_exc()}"
            print(error_msg)
            return {'success': False, 'message': str(e)}
    
    def _get_workflow_name(self, file_path: Path) -> str:
        """Extract workflow name from image metadata (PNG/WebP) - returns a descriptive name or 'Workflow' if one exists"""
        ext = file_path.suffix.lower()
        
        # Handle WebP files
        if ext == '.webp':
            return self._get_webp_workflow_name(file_path)
        
        # Try PIL first (most reliable for PNG metadata)
        workflow_data = None
        prompt_data = None
        
        try:
            workflow_data, prompt_data = self._extract_png_workflow_prompt_pil(file_path)
        except OSError:
            pass # File might be locked or truncated
        except Exception:
            pass
        
        # Fallback to manual chunk parsing if PIL didn't find anything
        if not workflow_data and not prompt_data:
            try:
                import zlib
                
                with open(file_path, 'rb') as f:
                    sig = f.read(8)
                    if sig != b'\x89PNG\r\n\x1a\n':
                        return None
                    
                    while True:
                        length_bytes = f.read(4)
                        if len(length_bytes) < 4:
                            break
                        
                        length = int.from_bytes(length_bytes, 'big')
                        # Read chunk type safely
                        chunk_type_bytes = f.read(4)
                        if len(chunk_type_bytes) < 4:
                            break
                        chunk_type = chunk_type_bytes.decode('ascii', errors='ignore')
                        
                        if chunk_type == 'tEXt':
                            data = f.read(length)
                            if b'\x00' in data:
                                keyword, text = data.split(b'\x00', 1)
                                keyword = keyword.decode('latin-1', errors='ignore').strip().lower()
                                if keyword in ('workflow', 'comfyui_workflow'):
                                    workflow_data = text.decode('utf-8', errors='ignore')
                                elif keyword in ('prompt', 'parameters'):
                                    prompt_data = text.decode('utf-8', errors='ignore')
                        
                        elif chunk_type == 'zTXt':
                            data = f.read(length)
                            try:
                                null_idx = data.index(b'\x00')
                                keyword = data[:null_idx].decode('latin-1', errors='ignore').strip().lower()
                                compression_method = data[null_idx + 1]
                                compressed_data = data[null_idx + 2:]
                                if compression_method == 0:
                                    text = zlib.decompress(compressed_data).decode('utf-8', errors='ignore')
                                    if keyword in ('workflow', 'comfyui_workflow'):
                                        workflow_data = text
                                    elif keyword in ('prompt', 'parameters'):
                                        prompt_data = text
                            except Exception:
                                pass
                        
                        elif chunk_type == 'iTXt':
                            data = f.read(length)
                            try:
                                null_idx = data.index(b'\x00')
                                keyword = data[:null_idx].decode('utf-8', errors='ignore').strip().lower()
                                rest = data[null_idx + 1:]
                                
                                if len(rest) >= 2:
                                    compression_flag = rest[0]
                                    rest = rest[2:]
                                    
                                    null_idx = rest.index(b'\x00')
                                    rest = rest[null_idx + 1:]
                                    null_idx = rest.index(b'\x00')
                                    text_data = rest[null_idx + 1:]
                                    
                                    if compression_flag == 1:
                                        text_data = zlib.decompress(text_data)
                                    
                                    text = text_data.decode('utf-8', errors='ignore')
                                    
                                    if keyword in ('workflow', 'comfyui_workflow'):
                                        workflow_data = text
                                    elif keyword in ('prompt', 'parameters'):
                                        prompt_data = text
                            except Exception:
                                pass
                        
                        elif chunk_type == 'IEND':
                            break
                        else:
                            f.read(length)
                        
                        f.read(4)  # CRC
            except Exception:
                pass
        
        # Now extract a descriptive workflow name from the data we found
        if workflow_data:
            try:
                wf = json.loads(workflow_data) if isinstance(workflow_data, str) else workflow_data
                
                # 1. Check extra fields for explicit titles
                extra = wf.get('extra', {})
                if isinstance(extra, dict):
                    for key in ['title', 'workflow_name', 'name']:
                        if extra.get(key) and len(str(extra[key])) < 60:
                            return str(extra[key])
                    if isinstance(extra.get('ds'), dict):
                        for key in ['title', 'workflow_name', 'name']:
                            if extra['ds'].get(key) and len(str(extra['ds'][key])) < 60:
                                return str(extra['ds'][key])
                
                # 2. Look for Note nodes with workflow info
                nodes = wf.get('nodes', [])
                for node in nodes:
                    node_type = node.get('type', '')
                    
                    if node_type == 'Note':
                        vals = node.get('widgets_values', [])
                        if vals and isinstance(vals[0], str):
                            note_text = vals[0].strip()
                            if len(note_text) < 60 and '\n' not in note_text[:50]:
                                first_line = note_text.split('\n')[0].strip()
                                if len(first_line) > 3 and len(first_line) < 60:
                                    return first_line
                
                # 3. Get checkpoint name as workflow identifier
                for node in nodes:
                    node_type = node.get('type', '')
                    if node_type in ['CheckpointLoaderSimple', 'CheckpointLoader', 'UNETLoader']:
                        vals = node.get('widgets_values', [])
                        if vals and isinstance(vals[0], str) and vals[0]:
                            ckpt_name = vals[0]
                            ckpt_name = ckpt_name.replace('.safetensors', '').replace('.ckpt', '').replace('.pt', '')
                            ckpt_name = ckpt_name.split('/')[-1].split('\\')[-1]
                            if len(ckpt_name) < 50:
                                return ckpt_name
                
                # 4. If we have workflow data but couldn't extract a name, return generic
                return "Workflow"
                
            except (json.JSONDecodeError, TypeError, AttributeError):
                return "Workflow"
        
        # Try prompt data as fallback
        if prompt_data:
            try:
                prompt = json.loads(prompt_data) if isinstance(prompt_data, str) else prompt_data
                for node_id, node_data in prompt.items():
                    if isinstance(node_data, dict):
                        class_type = node_data.get('class_type', '')
                        if class_type in ['CheckpointLoaderSimple', 'CheckpointLoader', 'UNETLoader']:
                            inputs = node_data.get('inputs', {})
                            ckpt = inputs.get('ckpt_name', '') or inputs.get('unet_name', '')
                            if ckpt:
                                ckpt = ckpt.replace('.safetensors', '').replace('.ckpt', '').replace('.pt', '')
                                ckpt = ckpt.split('/')[-1].split('\\')[-1]
                                if len(ckpt) < 50:
                                    return ckpt
                return "Workflow"
            except Exception:
                return "Workflow"
        
        return None
    
    def _get_webp_workflow_name(self, file_path: Path) -> str:
        """Extract workflow name from WebP EXIF metadata"""
        try:
            from PIL import Image
            
            img = Image.open(file_path)
            workflow_data = None
            prompt_data = None
            
            # Check EXIF data
            exif_data = img.info.get('exif')
            user_comment = self._extract_exif_user_comment(img, exif_data)
            if user_comment:
                workflow_data = user_comment
            
            # Check metadata dict
            if not workflow_data and 'workflow' in img.info:
                workflow_data = img.info['workflow']
            if not prompt_data and 'prompt' in img.info:
                prompt_data = img.info['prompt']
            if not prompt_data and 'parameters' in img.info:
                prompt_data = img.info['parameters']
            
            # Try to extract name from workflow data
            if workflow_data:
                try:
                    wf = json.loads(workflow_data) if isinstance(workflow_data, str) else workflow_data
                    
                    # Check extra fields
                    extra = wf.get('extra', {})
                    if isinstance(extra, dict):
                        for key in ['title', 'workflow_name', 'name']:
                            if extra.get(key) and len(str(extra[key])) < 60:
                                return str(extra[key])
                    
                    # Check nodes for checkpoint name
                    nodes = wf.get('nodes', [])
                    for node in nodes:
                        if node.get('type') in ['CheckpointLoaderSimple', 'CheckpointLoader', 'UNETLoader']:
                            vals = node.get('widgets_values', [])
                            if vals and isinstance(vals[0], str) and vals[0]:
                                ckpt = vals[0].replace('.safetensors', '').replace('.ckpt', '')
                                return ckpt.split('/')[-1].split('\\')[-1][:50]
                    
                    return "Workflow"
                except (json.JSONDecodeError, KeyError, TypeError, IndexError):
                    return "Workflow"
            
            if prompt_data:
                return "Workflow"
            
            return None
        except Exception:
            return None
    
    def get_file_workflow(self, folder_type: str, file_path: str) -> dict:
        """Get full workflow JSON from PNG metadata (supports tEXt, zTXt, iTXt chunks)"""
        import zlib
        
        try:
            full_path = self._validate_file_path(folder_type, file_path)
            
            if not full_path.exists():
                return {'success': False, 'message': 'File not found'}
            
            ext = full_path.suffix.lower()
            
            # Handle WebP files (EXIF UserComment)
            if ext == '.webp':
                return self._extract_webp_workflow(full_path)
            
            if ext != '.png':
                return {'success': False, 'message': 'Only PNG and WebP files contain workflow data'}
            
            workflow_data = None
            prompt_data = None

            # Try Pillow first (handles iTXt/zTXt/tEXt via img.text on many builds)
            pil_workflow, pil_prompt = self._extract_png_workflow_prompt_pil(full_path)
            workflow_data = pil_workflow or workflow_data
            prompt_data = pil_prompt or prompt_data

            # If Pillow found something usable, return early
            if workflow_data:
                try:
                    workflow = json.loads(workflow_data) if isinstance(workflow_data, str) else workflow_data
                    return {'success': True, 'workflow': workflow, 'type': 'workflow'}
                except Exception:
                    pass
            if prompt_data:
                try:
                    prompt = json.loads(prompt_data) if isinstance(prompt_data, str) else prompt_data
                    return {'success': True, 'workflow': prompt, 'type': 'prompt'}
                except Exception:
                    pass
            
            with open(full_path, 'rb') as f:
                sig = f.read(8)
                if sig != b'\x89PNG\r\n\x1a\n':
                    return {'success': False, 'message': 'Invalid PNG file'}
                
                while True:
                    length_bytes = f.read(4)
                    if len(length_bytes) < 4:
                        break
                    
                    length = int.from_bytes(length_bytes, 'big')
                    chunk_type = f.read(4).decode('ascii', errors='ignore')
                    
                    if chunk_type == 'tEXt':
                        data = f.read(length)
                        if b'\x00' in data:
                            keyword, text = data.split(b'\x00', 1)
                            keyword = keyword.decode('latin-1', errors='ignore').strip().lower()
                            if keyword in ('workflow', 'comfyui_workflow'):
                                workflow_data = text.decode('utf-8', errors='ignore')
                            elif keyword in ('prompt', 'parameters'):
                                prompt_data = text.decode('utf-8', errors='ignore')
                    
                    elif chunk_type == 'zTXt':
                        data = f.read(length)
                        try:
                            null_idx = data.index(b'\x00')
                            keyword = data[:null_idx].decode('latin-1', errors='ignore').strip().lower()
                            compression_method = data[null_idx + 1]
                            compressed_data = data[null_idx + 2:]
                            if compression_method != 0:
                                raise ValueError("Unsupported zTXt compression method")
                            text = zlib.decompress(compressed_data).decode('utf-8', errors='ignore')
                            
                            if keyword in ('workflow', 'comfyui_workflow'):
                                workflow_data = text
                            elif keyword in ('prompt', 'parameters'):
                                prompt_data = text
                        except (ValueError, zlib.error, UnicodeDecodeError):
                            pass
                    
                    elif chunk_type == 'iTXt':
                        data = f.read(length)
                        try:
                            null_idx = data.index(b'\x00')
                            keyword = data[:null_idx].decode('utf-8', errors='ignore').strip().lower()
                            rest = data[null_idx + 1:]
                            
                            if len(rest) >= 2:
                                compression_flag = rest[0]
                                rest = rest[2:]
                                
                                null_idx = rest.index(b'\x00')
                                rest = rest[null_idx + 1:]
                                null_idx = rest.index(b'\x00')
                                text_data = rest[null_idx + 1:]
                                
                                if compression_flag == 1:
                                    text_data = zlib.decompress(text_data)
                                
                                text = text_data.decode('utf-8', errors='ignore')
                                
                                if keyword in ('workflow', 'comfyui_workflow'):
                                    workflow_data = text
                                elif keyword in ('prompt', 'parameters'):
                                    prompt_data = text
                        except (ValueError, zlib.error, UnicodeDecodeError, IndexError):
                            pass
                    
                    elif chunk_type == 'IEND':
                        break
                    else:
                        # IMPORTANT: don't read large chunks (e.g. IDAT) into memory
                        try:
                            f.seek(length, 1)
                        except Exception:
                            # Fallback for non-seekable streams (shouldn't happen for files)
                            f.read(length)
                    
                    f.read(4)  # CRC
            
            # Return workflow if found (preferred - contains UI layout)
            if workflow_data:
                try:
                    workflow = json.loads(workflow_data)
                    return {'success': True, 'workflow': workflow, 'type': 'workflow'}
                except json.JSONDecodeError:
                    pass
            
            # Fall back to prompt data (execution-only, no UI layout)
            if prompt_data:
                try:
                    prompt = json.loads(prompt_data)
                    return {'success': True, 'workflow': prompt, 'type': 'prompt'}
                except json.JSONDecodeError:
                    pass
            
            return {'success': False, 'message': 'No workflow found in this image'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def _extract_webp_workflow(self, file_path: Path) -> dict:
        """Extract workflow from WebP EXIF UserComment field"""
        try:
            # Try using PIL/Pillow for EXIF extraction
            from PIL import Image
            
            img = Image.open(file_path)
            exif_data = img.info.get('exif')
            
            if exif_data:
                text = self._extract_exif_user_comment(img, exif_data)
                if text:
                    try:
                        workflow = json.loads(text)
                        return {'success': True, 'workflow': workflow, 'type': 'workflow'}
                    except json.JSONDecodeError:
                        pass
            
            # Also check for workflow in metadata dict
            if 'workflow' in img.info:
                try:
                    workflow = json.loads(img.info['workflow'])
                    return {'success': True, 'workflow': workflow, 'type': 'workflow'}
                except (json.JSONDecodeError, TypeError):
                    pass
            
            if 'prompt' in img.info:
                try:
                    prompt = json.loads(img.info['prompt'])
                    return {'success': True, 'workflow': prompt, 'type': 'prompt'}
                except (json.JSONDecodeError, TypeError):
                    pass
            
            if 'parameters' in img.info:
                try:
                    prompt = json.loads(img.info['parameters'])
                    return {'success': True, 'workflow': prompt, 'type': 'prompt'}
                except (json.JSONDecodeError, TypeError):
                    pass
            
            return {'success': False, 'message': 'No workflow found in WebP file'}
        except Exception as e:
            return {'success': False, 'message': f'Error reading WebP: {str(e)}'}
    
    def get_file_thumbnail(self, folder_type: str, file_path: str):
        """Get thumbnail for an image file (only images, not videos)"""
        try:
            full_path = self._validate_file_path(folder_type, file_path)
            
            if not full_path.exists():
                return None, None
            
            ext = full_path.suffix.lower()
            
            # Only serve image types - videos should use frontend placeholders
            content_types = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.webp': 'image/webp',
                '.bmp': 'image/bmp',
            }
            
            content_type = content_types.get(ext)
            
            # Return None for non-image files (videos, etc.)
            if not content_type:
                return None, None
            
            with open(full_path, 'rb') as f:
                data = f.read()
            
            return data, content_type
        except Exception:
            return None, None
    
    def _validate_file_path(self, folder_type: str, file_path: str) -> Path:
        """Validate and resolve file path, preventing path traversal attacks.
        Returns the validated path or raises ValueError if invalid."""
        base_path = self.get_comfy_folder_path(folder_type).resolve()
        
        # Normalize and resolve the full path
        full_path = (base_path / file_path).resolve()
        
        # Security check: ensure the resolved path is within the base folder
        try:
            full_path.relative_to(base_path)
        except ValueError:
            raise ValueError(f"Path traversal attempt blocked: {file_path}")
        
        return full_path
    
    def serve_file(self, folder_type: str, file_path: str):
        """Serve a file from output/input folder with proper content-type"""
        try:
            full_path = self._validate_file_path(folder_type, file_path)
            
            if not full_path.exists():
                return None, None, 0
            
            ext = full_path.suffix.lower()
            
            content_types = {
                # Images
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.webp': 'image/webp',
                '.bmp': 'image/bmp',
                # Videos
                '.mp4': 'video/mp4',
                '.webm': 'video/webm',
                '.mov': 'video/quicktime',
                '.avi': 'video/x-msvideo',
                '.mkv': 'video/x-matroska',
                # Audio
                '.mp3': 'audio/mpeg',
                '.wav': 'audio/wav',
                '.ogg': 'audio/ogg',
                '.flac': 'audio/flac',
            }
            
            content_type = content_types.get(ext, 'application/octet-stream')
            file_size = full_path.stat().st_size
            
            return full_path, content_type, file_size
        except Exception:
            return None, None, 0
    
    def delete_file(self, folder_type: str, file_path: str) -> dict:
        """Delete a file from a ComfyUI folder"""
        try:
            full_path = self._validate_file_path(folder_type, file_path)
            
            if not full_path.exists():
                return {'success': False, 'message': 'File not found'}
            
            # Security check - ensure path is within the folder
            try:
                full_path.relative_to(self.get_comfy_folder_path(folder_type))
            except ValueError:
                return {'success': False, 'message': 'Invalid path'}
            
            if full_path.is_dir():
                import shutil
                shutil.rmtree(full_path)
                self.add_backend_log(f"Deleted folder: {file_path}", 'success')
            else:
                full_path.unlink()
                self.add_backend_log(f"Deleted file: {file_path}", 'success')
            
            return {'success': True, 'message': f'Deleted: {file_path}'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
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
                return {'success': False, 'message': 'Folder not found'}
            
            if sys.platform == 'win32':
                os.startfile(str(folder_path))
            elif sys.platform == 'darwin':
                subprocess.run(['open', str(folder_path)])
            else:
                subprocess.run(['xdg-open', str(folder_path)])
            
            return {'success': True, 'message': 'Folder opened'}
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
        comfy_root = Path(__file__).parent.parent.parent  # custom_nodes/ComfyUI_MFConductor -> ComfyUI
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
        
        log_msg = f"[MF Conductor] Launching ComfyUI: {' '.join(cmd)}"
        print(log_msg)
        self.add_backend_log(log_msg, 'info')
        
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
            log_msg = f"[MF Conductor] Error launching ComfyUI: {e}"
            print(log_msg)
            self.add_backend_log(log_msg, 'error')
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
                    # Prevent unbounded growth
                    if len(self.comfy_output_buffer) > self.max_comfy_output:
                        self.comfy_output_buffer = self.comfy_output_buffer[-self.max_comfy_output:]
                        self.comfy_output_index = min(self.comfy_output_index, len(self.comfy_output_buffer))
                    
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
            log_msg = "[MF Conductor] Stopping ComfyUI process..."
            print(log_msg)
            self.add_backend_log(log_msg, 'info')
            
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
                log_msg = "[MF Conductor] Process not responding, force killing..."
                print(log_msg)
                self.add_backend_log(log_msg, 'warning')
                self.comfy_process.kill()
                self.comfy_process.wait()
            
            with self.output_lock:
                self.comfy_output_buffer.append({'text': 'ComfyUI process stopped', 'type': 'info'})
            
            self.comfy_process = None
            return {'success': True, 'message': 'ComfyUI stopped'}
        except Exception as e:
            log_msg = f"[MF Conductor] Error stopping ComfyUI: {e}"
            print(log_msg)
            self.add_backend_log(log_msg, 'error')
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
    
    def create_conductor_shortcut(self, save_path: str = None) -> dict:
        """Create a shortcut to launch MF Conductor standalone server"""
        try:
            if os.name != 'nt':
                return {'success': False, 'message': 'Shortcut creation is only supported on Windows'}
            
            # Default to Desktop if no path specified
            if not save_path:
                save_path = str(Path.home() / 'Desktop' / 'MF Conductor.lnk')
            
            # Ensure .lnk extension
            if not save_path.endswith('.lnk'):
                save_path = save_path + '.lnk'
            
            # Get paths
            conductor_dir = Path(__file__).parent
            batch_file = conductor_dir / 'Launch_MFConductor.bat'
            icon_path = conductor_dir / 'web' / 'mfconductor_logo.ico'
            icon_line = f'$Shortcut.IconLocation = "{icon_path}"' if icon_path.exists() else ''
            
            # Use PowerShell to create the shortcut
            ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{save_path}")
$Shortcut.TargetPath = "{batch_file}"
$Shortcut.WorkingDirectory = "{conductor_dir}"
$Shortcut.Description = "Launch MF Conductor - ComfyUI Control Center"
{icon_line}
$Shortcut.Save()
'''
            result = subprocess.run(
                ['powershell', '-Command', ps_script],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                return {'success': True, 'message': f'Shortcut created at {save_path}', 'path': save_path}
            else:
                return {'success': False, 'message': f'PowerShell error: {result.stderr}'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def create_profile_shortcut(self, profile_name: str, save_path: str = None) -> dict:
        """Create a shortcut that launches ComfyUI with a specific profile"""
        try:
            if os.name != 'nt':
                return {'success': False, 'message': 'Shortcut creation is only supported on Windows'}
            
            user_data = get_user_data()
            profiles = user_data.get_profiles()
            
            if profile_name not in profiles:
                return {'success': False, 'message': f'Profile "{profile_name}" not found'}
            
            profile = profiles[profile_name]
            
            # Default to Desktop if no path specified
            if not save_path:
                safe_name = "".join(c for c in profile_name if c.isalnum() or c in (' ', '-', '_')).strip()
                save_path = str(Path.home() / 'Desktop' / f'ComfyUI - {safe_name}.lnk')
            
            # Ensure .lnk extension
            if not save_path.endswith('.lnk'):
                save_path = save_path + '.lnk'
            
            # Get paths
            conductor_dir = Path(__file__).parent
            comfy_root = conductor_dir.parent.parent
            portable_root = comfy_root.parent
            
            python_path = portable_root / 'python_embeded' / 'python.exe'
            if not python_path.exists():
                python_path = Path(sys.executable)
            
            # Create a Python launcher script that applies the profile and launches ComfyUI
            safe_filename = profile_name.replace(" ", "_").replace("-", "_")
            launcher_script = conductor_dir / 'data' / f'launch_{safe_filename}.py'
            launcher_script.parent.mkdir(parents=True, exist_ok=True)
            
            # Build command line args from profile
            args = self._build_comfy_args_from_profile(profile)
            args_str = repr(args)
            
            # Get enabled/disabled node lists
            enabled_list = repr(profile.get('enabled', []))
            disabled_list = repr(profile.get('disabled', []))
            
            # Create the Python launcher script
            launcher_content = f'''#!/usr/bin/env python
"""Auto-generated launcher for profile: {profile_name}"""
import os
import sys
import subprocess
from pathlib import Path

# Profile configuration
PROFILE_NAME = {repr(profile_name)}
ENABLED_NODES = {enabled_list}
DISABLED_NODES = {disabled_list}
COMFY_ARGS = {args_str}

def apply_node_states(custom_nodes_path):
    """Enable/disable nodes according to profile"""
    if not ENABLED_NODES and not DISABLED_NODES:
        return  # No node management needed
    
    # Get all node folders
    all_folders = []
    for item in custom_nodes_path.iterdir():
        if item.is_dir() and not item.name.startswith('.'):
            name = item.name.replace('.disabled', '')
            all_folders.append(name)
    
    enabled_set = set(ENABLED_NODES) if ENABLED_NODES else set(all_folders)
    
    for folder_name in all_folders:
        folder_path = custom_nodes_path / folder_name
        disabled_path = custom_nodes_path / f"{{folder_name}}.disabled"
        
        if folder_name in enabled_set:
            # Should be enabled
            if disabled_path.exists() and not folder_path.exists():
                disabled_path.rename(folder_path)
                print(f"Enabled: {{folder_name}}")
        else:
            # Should be disabled
            if folder_path.exists() and not disabled_path.exists():
                folder_path.rename(disabled_path)
                print(f"Disabled: {{folder_name}}")

def main():
    # Paths
    script_dir = Path(__file__).parent.parent
    comfy_root = script_dir.parent.parent
    custom_nodes_path = comfy_root / 'custom_nodes'
    
    print(f"Launching ComfyUI with profile: {{PROFILE_NAME}}")
    
    # Apply node states
    if ENABLED_NODES or DISABLED_NODES:
        print("Applying node configuration...")
        apply_node_states(custom_nodes_path)
    
    # Find Python
    portable_root = comfy_root.parent
    python_path = portable_root / 'python_embeded' / 'python.exe'
    if not python_path.exists():
        python_path = sys.executable
    
    # Launch ComfyUI
    main_py = comfy_root / 'main.py'
    cmd = [str(python_path), str(main_py)] + COMFY_ARGS
    
    print(f"Command: {{' '.join(cmd)}}")
    print("-" * 50)
    
    os.chdir(comfy_root)
    subprocess.run(cmd)

if __name__ == '__main__':
    main()
'''
            
            with open(launcher_script, 'w') as f:
                f.write(launcher_content)
            
            # Create batch wrapper
            batch_file = conductor_dir / 'data' / f'launch_{safe_filename}.bat'
            batch_content = f'@echo off\ncd /d "{conductor_dir / "data"}"\n"{python_path}" "{launcher_script}"\npause\n'
            
            with open(batch_file, 'w') as f:
                f.write(batch_content)
            
            # Use PowerShell to create the shortcut with MF Conductor icon
            icon_path = conductor_dir / 'web' / 'mfconductor_logo.ico'
            icon_line = f'$Shortcut.IconLocation = "{icon_path}"' if icon_path.exists() else ''
            
            ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{save_path}")
$Shortcut.TargetPath = "{batch_file}"
$Shortcut.WorkingDirectory = "{comfy_root}"
$Shortcut.Description = "Launch ComfyUI with {profile_name} profile"
{icon_line}
$Shortcut.Save()
'''
            result = subprocess.run(
                ['powershell', '-Command', ps_script],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                return {
                    'success': True, 
                    'message': f'Quick launch shortcut created at {save_path}',
                    'path': save_path,
                    'launcher_path': str(launcher_script)
                }
            else:
                return {'success': False, 'message': f'PowerShell error: {result.stderr}'}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': str(e)}
    
    def _build_comfy_args_from_profile(self, profile: dict) -> list:
        """Build command line arguments from a profile"""
        args = []
        flags = profile.get('flags', {})
        
        # Process all flag values - flags are stored as {"vram": "--highvram", "attention": "--use-sage-attention"}
        for key, value in flags.items():
            if value and isinstance(value, str) and value.startswith('--'):
                # Split in case there are multiple flags in one value
                args.extend(value.split())
        
        # Port
        port = profile.get('port')
        if port:
            args.extend(['--port', str(port)])
        
        # Listen address
        listen = profile.get('listen')
        if listen:
            args.extend(['--listen', listen])
        
        # Custom flags string
        custom_flags = profile.get('custom_flags', '')
        if custom_flags:
            args.extend(custom_flags.split())
        
        # Custom flags list
        custom_flags_list = profile.get('custom_flags_list', [])
        if custom_flags_list:
            for flag in custom_flags_list:
                if flag and isinstance(flag, str):
                    args.extend(flag.split())
        
        return args


class MFConductorHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for the standalone server"""
    
    api: MFConductorAPI = None
    web_dir: Path = None
    
    def __init__(self, *args, **kwargs):
        # Set the directory to serve static files from
        self.directory = str(self.web_dir)
        super().__init__(*args, directory=self.directory, **kwargs)
    
    def log_message(self, format, *args):
        """Custom log format - suppress noisy polling endpoints"""
        # Safely convert args to string (handles HTTPStatus objects, etc.)
        try:
            msg = format % args if args else format
        except Exception:
            msg = str(args[0]) if args else str(format)
        
        # Ensure msg is a string for the 'in' check
        msg_str = str(msg)
        
        # Skip logging for:
        # - Frequently polled endpoints
        # - Thumbnail 404s (expected for videos)
        # - Generic 404 error messages
        skip_patterns = [
            '/api/comfy/output', '/api/comfy/status', '/api/backend-logs',
            '/api/files/thumbnail', '/api/files/serve',
            'code 404', 'File not found'
        ]
        if any(x in msg_str for x in skip_patterns):
            return
        
        log_msg = f"[MF Conductor] {msg_str}"
        print(log_msg)
        
        # Also add to backend log buffer for frontend console
        if self.api:
            self.api.add_backend_log(log_msg, 'info')
    
    def send_json(self, data: dict, status: int = 200):
        """Send a JSON response"""
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode('utf-8'))
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # Client disconnected - ignore
    
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
            fast = query.get('fast', ['false'])[0].lower() in ('1', 'true', 'yes')
            data = self.api.get_nodes(fast=fast)
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
        
        # Backend logs for frontend console
        if path == '/api/backend-logs':
            since_index = int(query.get('since', ['0'])[0])
            new_logs = self.api.get_backend_logs(since_index)
            self.send_json({
                'success': True,
                'logs': new_logs,
                'next_index': len(self.api.backend_logs)
            })
            return
        
        # Packages
        if path == '/api/packages':
            data = self.api.get_packages()
            self.send_json(data)
            return
        
        if path == '/api/packages/check-updates-status':
            job_id = query.get('job_id', [None])[0]
            if not job_id or not hasattr(self.api, '_update_jobs'):
                self.send_json({'success': False, 'message': 'Invalid job ID'})
                return
            
            job = self.api._update_jobs.get(job_id)
            if not job:
                self.send_json({'success': False, 'message': 'Job not found'})
                return
            
            if job['status'] == 'completed':
                # Clean up old job
                result = job['result']
                del self.api._update_jobs[job_id]
                self.send_json(result)
            elif job['status'] == 'error':
                error = job['error']
                del self.api._update_jobs[job_id]
                self.send_json({'success': False, 'message': error})
            else:
                self.send_json({'success': True, 'status': 'running'})
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
        
        if path == '/api/system/desktop-path':
            desktop = str(Path.home() / 'Desktop')
            self.send_json({'success': True, 'path': desktop})
            return
        
        # File Browser API
        if path == '/api/files':
            try:
                folder_type = query.get('folder', ['output'])[0]
                subfolder = query.get('subfolder', [''])[0]
                sort_by = query.get('sort', ['date'])[0]
                sort_dir = query.get('dir', ['desc'])[0]
                file_type = query.get('type', [''])[0]
                search = query.get('search', [''])[0]
                recursive = query.get('recursive', ['false'])[0].lower() == 'true'
                with_workflow = query.get('with_workflow', ['false'])[0].lower() == 'true'
                data = self.api.get_files(folder_type, subfolder, sort_by, sort_dir, file_type, search, recursive, with_workflow)
                self.send_json(data)
            except Exception as e:
                import traceback
                error_msg = f"[MF Conductor] Error in /api/files: {str(e)}\n{traceback.format_exc()}"
                print(error_msg)
                self.api.add_backend_log(error_msg, 'error')
                self.send_json({'success': False, 'message': str(e)}, 500)
            return
        
        if path.startswith('/api/files/thumbnail/'):
            # /api/files/thumbnail/output/path/to/file.png
            parts = path.split('/api/files/thumbnail/')[1].split('/', 1)
            if len(parts) >= 2:
                folder_type = parts[0]
                file_path = unquote(parts[1])
                data, content_type = self.api.get_file_thumbnail(folder_type, file_path)
                if data:
                    self.send_response(200)
                    self.send_header('Content-Type', content_type)
                    self.send_header('Cache-Control', 'max-age=3600')
                    self.end_headers()
                    self.wfile.write(data)
                    return
            self.send_error(404, 'File not found')
            return
        
        if path.startswith('/api/files/workflow/'):
            # /api/files/workflow/output/path/to/file.png
            parts = path.split('/api/files/workflow/')[1].split('/', 1)
            if len(parts) >= 2:
                folder_type = parts[0]
                file_path = unquote(parts[1])
                data = self.api.get_file_workflow(folder_type, file_path)
                self.send_json(data)
                return
            self.send_json({'success': False, 'message': 'Invalid path'}, 400)
            return
        
        if path.startswith('/api/files/serve/'):
            # /api/files/serve/output/path/to/file.mp4 - serve actual file for video/audio playback
            parts = path.split('/api/files/serve/')[1].split('/', 1)
            if len(parts) >= 2:
                folder_type = parts[0]
                file_path = unquote(parts[1])
                full_path, content_type, file_size = self.api.serve_file(folder_type, file_path)
                if full_path:
                    try:
                        self.send_response(200)
                        self.send_header('Content-Type', content_type)
                        self.send_header('Content-Length', str(file_size))
                        self.send_header('Accept-Ranges', 'bytes')
                        self.end_headers()
                        with open(full_path, 'rb') as f:
                            # Stream file in chunks for large files
                            chunk_size = 64 * 1024  # 64KB chunks
                            while True:
                                chunk = f.read(chunk_size)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                        return
                    except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                        return  # Client disconnected
            self.send_error(404, 'File not found')
            return
        
        # Usage Analytics
        if path == '/api/usage/stats':
            tracker = get_usage_tracker(self.api.comfy_root)
            # Build node-to-package mapping from installed nodes
            nodes = self.api.get_nodes().get('nodes', [])
            tracker.build_node_package_map(nodes)
            data = tracker.get_usage_stats()
            self.send_json({'success': True, **data})
            return
        
        if path == '/api/usage/progress':
            tracker = get_usage_tracker(self.api.comfy_root)
            progress = tracker.get_scan_progress()
            self.send_json({'success': True, **progress})
            return
        
        # Serve static files
        if path == '/' or path == '':
            self.path = '/index.html'
        
        try:
            return super().do_GET()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # Client disconnected - ignore
    
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
                log_msg = f"[MF Conductor] JSON decode error: {e}"
                print(log_msg)
                self.api.add_backend_log(log_msg, 'error')
                self.send_json({'success': False, 'message': f'Invalid JSON: {str(e)}'}, 400)
                return
            except Exception as e:
                log_msg = f"[MF Conductor] Body read error: {e}"
                print(log_msg)
                self.api.add_backend_log(log_msg, 'error')
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
            version = body.get('version', None)  # Optional specific version
            if not package_name:
                self.send_json({'success': False, 'message': 'Package name is required'}, 400)
                return
            data = self.api.upgrade_package(package_name, version)
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
        
        # File Browser API
        if path == '/api/files/delete':
            folder_type = body.get('folder', 'output')
            file_path = body.get('path', '')
            if not file_path:
                self.send_json({'success': False, 'message': 'File path is required'}, 400)
                return
            data = self.api.delete_file(folder_type, file_path)
            self.send_json(data)
            return
        
        if path == '/api/files/open-location':
            folder_type = body.get('folder', 'output')
            file_path = body.get('path', '')
            data = self.api.open_file_location(folder_type, file_path)
            self.send_json(data)
            return
        
        if path == '/api/packages/check-updates':
            # Run in background thread to avoid blocking
            import threading
            import time
            
            # Generate job ID
            job_id = str(int(time.time() * 1000))
            
            # Initialize job status
            if not hasattr(self.api, '_update_jobs'):
                self.api._update_jobs = {}
            
            # Clean up stale jobs older than 5 minutes
            current_time = time.time()
            stale_threshold = current_time - 300  # 5 minutes
            stale_jobs = [jid for jid, job in self.api._update_jobs.items() 
                         if job.get('created_at', 0) < stale_threshold]
            for jid in stale_jobs:
                del self.api._update_jobs[jid]
            
            self.api._update_jobs[job_id] = {
                'status': 'running',
                'result': None,
                'error': None,
                'created_at': current_time
            }
            
            def check_updates_background(job_id):
                try:
                    result = self.api.check_package_updates()
                    self.api._update_jobs[job_id]['status'] = 'completed'
                    self.api._update_jobs[job_id]['result'] = result
                except Exception as e:
                    self.api._update_jobs[job_id]['status'] = 'error'
                    self.api._update_jobs[job_id]['error'] = str(e)
            
            thread = threading.Thread(target=check_updates_background, args=(job_id,), daemon=True)
            thread.start()
            
            # Return job ID immediately
            self.send_json({'success': True, 'job_id': job_id, 'status': 'running'})
            return
        
        
        if path == '/api/packages/check-single':
            # Check a single package for updates
            package_name = body.get('package_name', '')
            if not package_name:
                self.send_json({'success': False, 'message': 'Package name is required'}, 400)
                return
            
            data = self.api.check_single_package_update(package_name)
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
        
        # Usage Analytics
        if path == '/api/usage/scan':
            tracker = get_usage_tracker(self.api.comfy_root)
            # Build node-to-package mapping first
            nodes = self.api.get_nodes().get('nodes', [])
            tracker.build_node_package_map(nodes)
            # Start scan in background thread
            folders = body.get('folders', None)
            force = body.get('force', False)
            
            def run_scan():
                tracker.scan_workflows(folders, force)
            
            thread = threading.Thread(target=run_scan, daemon=True)
            thread.start()
            self.send_json({'success': True, 'message': 'Scan started'})
            return
        
        if path == '/api/usage/clear':
            tracker = get_usage_tracker(self.api.comfy_root)
            tracker.clear_data()
            self.send_json({'success': True, 'message': 'Usage data cleared'})
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
        
        # Shortcut creation
        if path == '/api/shortcuts/conductor':
            save_path = body.get('save_path')
            data = self.api.create_conductor_shortcut(save_path)
            self.send_json(data)
            return
        
        if path == '/api/shortcuts/profile':
            profile_name = body.get('profile_name', '')
            save_path = body.get('save_path')
            if not profile_name:
                self.send_json({'success': False, 'message': 'Profile name is required'}, 400)
                return
            data = self.api.create_profile_shortcut(profile_name, save_path)
            self.send_json(data)
            return
        
        if path == '/api/system/save-dialog':
            suggested_name = body.get('suggested_name', 'shortcut.lnk')
            try:
                # Use PowerShell to show a native Save File dialog
                desktop = str(Path.home() / 'Desktop')
                ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.SaveFileDialog
$dialog.InitialDirectory = "{desktop}"
$dialog.Filter = "Windows Shortcut (*.lnk)|*.lnk"
$dialog.FileName = "{suggested_name}"
$dialog.Title = "Save Shortcut"
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {{
    Write-Output $dialog.FileName
}} else {{
    Write-Output "CANCELLED"
}}
'''
                result = subprocess.run(
                    ['powershell', '-Command', ps_script],
                    capture_output=True,
                    text=True
                )
                output = result.stdout.strip()
                if output == 'CANCELLED' or not output:
                    self.send_json({'success': False, 'cancelled': True})
                else:
                    self.send_json({'success': True, 'path': output})
            except Exception as e:
                self.send_json({'success': False, 'message': str(e)})
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


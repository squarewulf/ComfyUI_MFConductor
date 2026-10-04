"""
MF_Conductor - Standalone Server
Can run independently of ComfyUI for offline node management
"""

import os
import sys
import json
import subprocess
import struct
import hashlib
import base64
import socket
import select
import webbrowser
import time
from functools import wraps
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs, unquote
import threading
import mimetypes

mimetypes.add_type('font/woff2', '.woff2')
mimetypes.add_type('font/ttf', '.ttf')
mimetypes.add_type('font/woff', '.woff')

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from node_scanner import NodeScanner, get_node_requirements, refresh_installed_packages, clear_manager_db_cache, CACHE_VERSION
from git_utils import GitUtils, PipUtils
from user_data import get_user_data
from browse_nodes import (
    browse_nodes,
    get_categories,
    get_node_details,
    install_missing_packs,
    refresh_node_database,
    resolve_missing_packs,
)
from usage_tracker import get_usage_tracker
from workflow_analyzer import (
    apply_enabled_folders,
    folders_for_profile,
    folders_for_workflow_launch,
    get_workflow_analyzer,
    is_never_block_package,
    normalize_workflow_paths,
    persist_pending_workflow,
)
from security_utils import (
    ALLOWED_FILE_FOLDERS,
    ALLOWED_PIP_SUBCOMMANDS,
    escape_ps_string,
    find_comfy_python,
    is_local_api_request,
    read_bounded,
    resolve_under,
    valid_git_url,
    valid_pip_package,
    valid_pip_version,
)
from profile_launch import build_profile_args, isolation_launch_flags, parse_launch_flags, persist_blocked_packages, strip_custom_node_isolation, validate_launch_args, workflow_launch_options, write_desktop_shortcut, write_profile_launcher


def _process_action(method):
    @wraps(method)
    def serialized(self, *args, **kwargs):
        with self._process_lock:
            return method(self, *args, **kwargs)
    return serialized


class MFConductorAPI:
    """API handler for MF Conductor operations"""
    
    PIP_CACHE_TTL = 120  # seconds before pip list cache expires
    
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
        self._process_lock = threading.RLock()
        self.comfy_output_buffer = []
        self.comfy_output_index = 0
        self.output_lock = threading.Lock()
        self.active_profile_name = None
        self.last_enabled_override = None
        self.last_blocked_override = None
        self.last_flags_override = None
        self.last_extra_flags = []
        self.backend_log_base = 0
        
        # Backend log buffer for frontend console
        self.backend_logs = []
        self.backend_log_lock = threading.Lock()
        self.backend_log_index = 0  # Track what logs have been sent to client
        self.max_backend_logs = 1000
        
        # Console output buffer limits
        self.max_comfy_output = 5000
        
        # Pip list cache
        self._pip_cache = None
        self._pip_cache_time = 0
        self._pip_cache_lock = threading.Lock()
        
        # WebSocket clients for push notifications
        self._ws_clients = set()
        self._ws_clients_lock = threading.Lock()
    
    def ws_register(self, client_socket):
        """Register a WebSocket client for push notifications"""
        with self._ws_clients_lock:
            self._ws_clients.add(client_socket)
    
    def ws_unregister(self, client_socket):
        """Unregister a WebSocket client"""
        with self._ws_clients_lock:
            self._ws_clients.discard(client_socket)
    
    def ws_broadcast(self, event_type: str, data: dict = None):
        """Push a message to all connected WebSocket clients"""
        message = json.dumps({'type': event_type, 'data': data or {}, 'timestamp': time.time()})
        frame = _ws_encode_frame(message)
        dead = []
        with self._ws_clients_lock:
            for sock in self._ws_clients:
                try:
                    sock.sendall(frame)
                except Exception:
                    dead.append(sock)
            for sock in dead:
                self._ws_clients.discard(sock)

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
            if len(self.backend_logs) > self.max_backend_logs:
                overflow = len(self.backend_logs) - self.max_backend_logs
                del self.backend_logs[:overflow]
                self.backend_log_base += overflow
    
    def get_backend_logs(self, since_index: int = 0) -> list:
        """Get backend logs since the given absolute index"""
        with self.backend_log_lock:
            start = max(0, int(since_index) - self.backend_log_base)
            return list(self.backend_logs[start:])
    
    def get_nodes(self, refresh: bool = False, fast: bool = False) -> dict:
        """Get list of all custom nodes. With fast=True, never blocks."""
        if not refresh and fast:
            cache = self.scanner.get_cached_nodes(allow_stale=True)
            if cache and cache.get('nodes') is not None:
                cache_version = cache.get('version')
                stale = cache_version != CACHE_VERSION
                self._cached_nodes = cache.get('nodes', [])
                self._cache_time = cache.get('scanned_at')
                if stale:
                    self._start_background_scan()
                return {
                    'nodes': self._cached_nodes,
                    'scanned_at': self._cache_time,
                    'total': len(self._cached_nodes),
                    'cache_used': True,
                    'cache_stale': stale
                }
            
            if self._cached_nodes is not None:
                return {
                    'nodes': self._cached_nodes,
                    'scanned_at': self._cache_time,
                    'total': len(self._cached_nodes),
                    'cache_used': True
                }
            
            # No cache at all — return folder names as lightweight placeholders
            # and start a full scan in the background
            self._start_background_scan()
            placeholder_nodes = []
            skip_items = {'__pycache__', '.git', 'example_node.py.example'}
            for item in self.scanner.custom_nodes_path.iterdir():
                if not item.is_dir():
                    continue
                folder_name = item.name
                if folder_name in skip_items or folder_name.startswith('.'):
                    continue
                
                if folder_name.endswith('.disabled'):
                    is_disabled = True
                    base_name = folder_name[:-9]
                else:
                    is_disabled = False
                    base_name = folder_name
                
                placeholder_nodes.append({
                    'folder_name': folder_name,
                    'display_name': base_name,
                    'base_folder_name': base_name,
                    'author': 'Scanning...',
                    'description': '',
                    'git_url': None,
                    'stars': 0,
                    'enabled': not is_disabled,
                    'is_disabled': is_disabled,
                    'is_git_repo': False,
                    'has_requirements': False,
                    'provided_nodes': [],
                    'node_count': 0,
                    'date_added': None,
                    'last_updated': None,
                    'folder_path': str(item),
                })
            return {
                'nodes': placeholder_nodes,
                'scanned_at': None,
                'total': len(placeholder_nodes),
                'scanning': True
            }
        
        if refresh or self._cached_nodes is None:
            nodes = self.scanner.scan(use_cache=not refresh)
            
            # Safeguard: if cache returned suspiciously few nodes, force fresh scan
            # Most installations have at least 5+ nodes (including MFConductor, Manager, etc.)
            if not refresh and len(nodes) < 5:
                # Count actual directories to compare
                actual_dirs = sum(1 for item in self.scanner.custom_nodes_path.iterdir() 
                                  if item.is_dir() and not item.name.startswith('.') 
                                  and item.name not in {'__pycache__', '.git'})
                if actual_dirs > len(nodes) + 5:
                    # Cache is likely corrupted, force fresh scan
                    nodes = self.scanner.scan(use_cache=False)
            
            self._cached_nodes = nodes
            self._cache_time = datetime.now().isoformat()
        
        return {
            'nodes': self._cached_nodes,
            'scanned_at': self._cache_time,
            'total': len(self._cached_nodes)
        }
    
    def _start_background_scan(self):
        """Start a background node scan if one isn't already running"""
        if getattr(self, '_scan_running', False):
            return
        self._scan_running = True
        self.ws_broadcast('scan_started')
        self.add_backend_log("Background node scan started...", 'info')
        
        def _do_scan():
            try:
                nodes = self.scanner.scan(use_cache=False)
                self._cached_nodes = nodes
                self._cache_time = datetime.now().isoformat()
                self.add_backend_log(f"Scan complete: {len(nodes)} nodes found", 'success')
                self.ws_broadcast('scan_complete', {'total': len(nodes)})
            except Exception as e:
                self.add_backend_log(f"Scan failed: {e}", 'error')
            finally:
                self._scan_running = False
        
        threading.Thread(target=_do_scan, daemon=True).start()
    
    def refresh_nodes(self) -> dict:
        """Force refresh the node list"""
        clear_manager_db_cache()
        self._start_background_scan()
        return {
            'nodes': self._cached_nodes or [],
            'scanned_at': self._cache_time,
            'total': len(self._cached_nodes or []),
            'scanning': True
        }
    
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
        if not valid_git_url(url):
            return {'success': False, 'message': 'Invalid git URL'}
        self.ws_broadcast('node_operation', {'action': 'installing', 'url': url})
        success, message = self.git.clone_repo(url, folder_name)
        
        if not success:
            self.ws_broadcast('node_operation', {'action': 'install_failed', 'url': url})
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
        
        self.refresh_nodes()
        self.invalidate_pip_cache()
        self.ws_broadcast('node_installed', {'folder_name': folder_name})
        
        return {'success': True, 'message': message, 'folder_name': folder_name}
    
    def open_folder(self, folder_name: str) -> dict:
        """Open the node folder in file explorer"""
        folder_path, err = self.scanner._safe_node_path(folder_name)
        if folder_path is None:
            return {'success': False, 'message': err}
        
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
            self.ws_broadcast('node_removed', {'folder_name': folder_name})
        return {'success': success, 'message': message}
    
    def deactivate_node(self, folder_name: str) -> dict:
        """Deactivate a custom node"""
        success, message = self.scanner.deactivate_node(folder_name)
        if success:
            self._cached_nodes = None
            self.ws_broadcast('node_deactivated', {'folder_name': folder_name})
        return {'success': success, 'message': message}
    
    def activate_node(self, folder_name: str) -> dict:
        """Activate a disabled custom node"""
        success, message = self.scanner.activate_node(folder_name)
        if success:
            self._cached_nodes = None
            self.ws_broadcast('node_activated', {'folder_name': folder_name})
        return {'success': success, 'message': message}
    
    def get_requirements(self, folder_name: str) -> dict:
        """Get requirements for a specific node"""
        folder_path, err = self.scanner._safe_node_path(folder_name)
        if folder_path is None:
            return {'success': False, 'message': err, 'requirements': []}
        
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
        if not valid_pip_package(package_name):
            return {'success': False, 'message': 'Invalid package name'}
        try:
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'install', package_name.strip()],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            refresh_installed_packages()
            self.invalidate_pip_cache()
            
            if result.returncode == 0:
                self.ws_broadcast('package_installed', {'package': package_name})
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
        """Launch ComfyUI with a profile's folders, flags, and excluded packages."""
        if not get_user_data().get_profile(name):
            return {'success': False, 'message': 'Profile not found'}
        return self.launch_comfy(profile_name=name)
    
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
        
        # Normalize names: strip .disabled suffix so comparisons work
        # regardless of whether the profile was saved while nodes were active or disabled
        all_folders = self.scanner.list_folder_names()
        results = apply_enabled_folders(self.scanner, folders_for_profile(profile, all_folders))
        self._cached_nodes = None
        if results['errors']:
            return {'success': False, 'message': '; '.join(results['errors']), 'results': results}
        persist_blocked_packages(profile.get('excluded_packages') or [])
        return {'success': True, 'results': results}

    def apply_enabled_folders(self, enabled_folders, disable_others: bool = True) -> dict:
        results = apply_enabled_folders(self.scanner, enabled_folders, disable_others=disable_others)
        self._cached_nodes = None
        if results['errors']:
            return {'success': False, 'message': '; '.join(results['errors']), 'results': results}
        return {'success': True, 'results': results}

    def persist_default_profile_blocks(self):
        for profile in get_user_data().get_profiles().values():
            if profile.get('is_default'):
                persist_blocked_packages(profile.get('excluded_packages') or [])
                return
        persist_blocked_packages([])

    def _installed_nodes_for_map(self, allow_scan: bool = False) -> list:
        if self._cached_nodes:
            return self._cached_nodes
        cached = self.scanner.get_cached_nodes(allow_stale=True)
        if cached and cached.get('nodes'):
            self._cached_nodes = cached['nodes']
            return self._cached_nodes
        if not allow_scan:
            return []
        cache = self.scanner.scan(use_cache=True)
        self._cached_nodes = cache or []
        return self._cached_nodes

    def list_workflows(self) -> dict:
        analyzer = get_workflow_analyzer(self.comfy_root, self.scanner)
        return analyzer.list_workflows(self._installed_nodes_for_map(allow_scan=False))

    def analyze_workflow(self, rel_path: str, include_packages: bool = False) -> dict:
        analyzer = get_workflow_analyzer(self.comfy_root, self.scanner)
        return analyzer.analyze(
            rel_path,
            self._installed_nodes_for_map(allow_scan=True),
            include_packages=include_packages,
        )

    def _append_comfy_log(self, text: str, line_type: str = 'info') -> None:
        with self.output_lock:
            self.comfy_output_buffer.append({'text': text, 'type': line_type})

    def _warn_broken_native_packs(self, enabled_folders) -> None:
        names = {str(name).lower() for name in (enabled_folders or [])}
        if 'comfyui-trellis2' not in names:
            return
        try:
            import importlib
            importlib.import_module('cumesh')
            return
        except Exception as exc:
            torch_ver = 'unknown'
            try:
                import torch
                torch_ver = f'{torch.__version__} cu{torch.version.cuda}'
            except Exception:
                pass
            self._append_comfy_log(
                f'Trellis2 is enabled but cumesh failed to import ({exc}). '
                f'Your torch is {torch_ver}. visualbruno has no Windows wheel for this build, '
                'so ComfyUI will list the Trellis2 node types as missing.',
                'error',
            )

    def _isolation_for_workflows(self, rel_path=None, rel_paths=None, extra_nodes=()):
        paths = normalize_workflow_paths(rel_path, rel_paths)
        if not paths:
            return None, {'success': False, 'message': 'Workflow path is required'}
        self._append_comfy_log(f'Analyzing isolation for {len(paths)} workflow{"s" if len(paths) != 1 else ""}...')
        analyzer = get_workflow_analyzer(self.comfy_root, self.scanner)
        batch = analyzer.analyze_many(paths, self._installed_nodes_for_map(allow_scan=False), include_packages=False)
        if not batch.get('success'):
            return None, batch
        required = []
        names = []
        missing = []
        last = None
        for analysis in batch.get('analyses') or []:
            last = analysis
            names.append(analysis.get('name') or analysis.get('path') or '')
            required.extend(analysis.get('required_folders') or [])
            missing.extend(analysis.get('missing_folders') or [])
        missing = sorted({str(name) for name in missing if name}, key=str.lower)
        if missing:
            self._append_comfy_log(
                'Continuing without missing packs: ' + ', '.join(missing),
                'warning',
            )
        enabled = folders_for_workflow_launch({'required_folders': required}, self.scanner.list_folder_names(), extra_nodes)
        return {
            'paths': paths,
            'names': names,
            'enabled': enabled,
            'analysis': last,
            'missing_folders': missing,
        }, None

    def launch_workflow(self, rel_path: str = None, profile_name: str = None, rel_paths=None,
                        launch_flags=None, extra_nodes=()) -> dict:
        try:
            flags = parse_launch_flags(launch_flags) if launch_flags is not None else None
            prepared, error = self._isolation_for_workflows(rel_path, rel_paths, extra_nodes)
            if error:
                return error
            with self.output_lock:
                self.comfy_output_buffer = []
                self.comfy_output_index = 0
        except ValueError as exc:
            return {'success': False, 'message': str(exc)}
        if error:
            return error
        self._append_comfy_log(
            f'Isolation plan ready: {len(prepared["enabled"])} pack{"s" if len(prepared["enabled"]) != 1 else ""}'
        )
        self._warn_broken_native_packs(prepared['enabled'])

        blocked = []
        if profile_name is None:
            for name, profile in get_user_data().get_profiles().items():
                if profile.get('is_default'):
                    profile_name = name
                    break

        if profile_name:
            profile = get_user_data().get_profile(profile_name)
            if profile:
                blocked = list(profile.get('excluded_packages') or [])

        names = prepared['names']
        label = f'workflow "{names[0]}"' if len(names) == 1 else f'{len(names)} workflows'
        result = self.launch_comfy(
            profile_name=profile_name,
            enabled_override=prepared['enabled'],
            blocked_override=blocked,
            launch_label=label,
            reset_output=False,
            restart_if_running=True,
            flags_override=flags,
        )
        if result.get('success'):
            persist_pending_workflow(prepared['paths'][0], prepared['paths'])
        return result

    def resolve_missing_workflow_packs(self, names) -> dict:
        return resolve_missing_packs(names)

    def install_missing_workflow_packs(self, names) -> dict:
        def _log(text):
            self._append_comfy_log(text, 'info')
            self.add_backend_log(text, 'info')

        result = install_missing_packs(self.git, self.pip, self.scanner, names, log=_log)
        self._cached_nodes = None
        get_workflow_analyzer(self.comfy_root, self.scanner).reset_maps()
        self.refresh_nodes()
        return result
    
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
    
    def invalidate_pip_cache(self):
        """Clear the pip list cache so the next call fetches fresh data"""
        with self._pip_cache_lock:
            self._pip_cache = None
            self._pip_cache_time = 0
    
    def _get_packages_fast(self) -> list:
        """Get installed packages using importlib.metadata (no subprocess, instant)"""
        import importlib.metadata
        packages = []
        try:
            for dist in importlib.metadata.distributions():
                name = dist.metadata.get('Name')
                version = dist.metadata.get('Version', '')
                if name:
                    packages.append({'name': name, 'version': version, 'location': ''})
        except Exception:
            pass
        packages.sort(key=lambda p: p['name'].lower())
        return packages
    
    def get_packages(self, refresh: bool = False) -> dict:
        """Get list of installed Python packages (cached with TTL)"""
        with self._pip_cache_lock:
            now = time.time()
            if not refresh and self._pip_cache is not None and (now - self._pip_cache_time) < self.PIP_CACHE_TTL:
                return {'success': True, 'packages': self._pip_cache, 'cached': True}
        
        # Fast path: use importlib.metadata (instant, no subprocess)
        packages = self._get_packages_fast()
        if packages:
            with self._pip_cache_lock:
                self._pip_cache = packages
                self._pip_cache_time = time.time()
            return {'success': True, 'packages': packages}
        
        # Fallback: pip subprocess
        try:
            python_path = self.pip.python_path if self.pip else 'python'
            result = subprocess.run(
                [python_path, '-m', 'pip', 'list', '--format=json', '--disable-pip-version-check'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                packages = json.loads(result.stdout)
                for pkg in packages:
                    pkg['location'] = ''
                with self._pip_cache_lock:
                    self._pip_cache = packages
                    self._pip_cache_time = time.time()
                return {'success': True, 'packages': packages}
            else:
                return {'success': False, 'message': result.stderr or 'Failed to list packages'}
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'Timeout listing packages'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def check_package_updates(self) -> dict:
        """Check which packages have updates available - FAST version using PyPI API"""
        import urllib.request
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        try:
            pkg_result = self.get_packages()
            if not pkg_result.get('success'):
                return {'success': False, 'message': 'Failed to get installed packages list'}
            
            installed_packages = pkg_result.get('packages', [])
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
        if not valid_pip_package(package_name):
            return {'success': False, 'message': 'Invalid package name'}
        try:
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'uninstall', '-y', package_name.strip()],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            refresh_installed_packages()
            self.invalidate_pip_cache()
            
            if result.returncode == 0:
                self.ws_broadcast('package_uninstalled', {'package': package_name})
                return {'success': True, 'message': f'Successfully uninstalled {package_name}'}
            else:
                return {'success': False, 'message': f'Uninstall failed: {result.stderr}'}
        except subprocess.TimeoutExpired:
            return {'success': False, 'message': 'Uninstall timed out'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def upgrade_package(self, package_name: str, version: str = None) -> dict:
        """Upgrade a specific package to a specific version or latest"""
        if not valid_pip_package(package_name) or not valid_pip_version(version or ''):
            return {'success': False, 'message': 'Invalid package name or version'}
        try:
            if version:
                package_spec = f'{package_name.strip()}=={version.strip()}'
            else:
                package_spec = package_name.strip()
            
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'install', '--upgrade', package_spec],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            refresh_installed_packages()
            self.invalidate_pip_cache()
            
            if result.returncode == 0:
                version_msg = f' to {version}' if version else ''
                self.ws_broadcast('package_upgraded', {'package': package_name})
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
        
        if folder_type not in ALLOWED_FILE_FOLDERS or folder_type == 'both':
            folder_type = 'output'
        folder_map = {
            'output': comfy_root / 'output',
            'input': comfy_root / 'input',
            'temp': comfy_root / 'temp',
        }
        
        return folder_map[folder_type]
    
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
            base_path = folder_path
            
            if subfolder and not recursive:
                folder_path = resolve_under(base_path, subfolder)
                if folder_path is None:
                    return {'success': False, 'message': 'Invalid path'}
            
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
                            data = read_bounded(f, length) or b''
                            if b'\x00' in data:
                                keyword, text = data.split(b'\x00', 1)
                                keyword = keyword.decode('latin-1', errors='ignore').strip().lower()
                                if keyword in ('workflow', 'comfyui_workflow'):
                                    workflow_data = text.decode('utf-8', errors='ignore')
                                elif keyword in ('prompt', 'parameters'):
                                    prompt_data = text.decode('utf-8', errors='ignore')
                        
                        elif chunk_type == 'zTXt':
                            data = read_bounded(f, length) or b''
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
                            data = read_bounded(f, length) or b''
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
                            read_bounded(f, length)
                        
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
                        data = read_bounded(f, length) or b''
                        if b'\x00' in data:
                            keyword, text = data.split(b'\x00', 1)
                            keyword = keyword.decode('latin-1', errors='ignore').strip().lower()
                            if keyword in ('workflow', 'comfyui_workflow'):
                                workflow_data = text.decode('utf-8', errors='ignore')
                            elif keyword in ('prompt', 'parameters'):
                                prompt_data = text.decode('utf-8', errors='ignore')
                    
                    elif chunk_type == 'zTXt':
                        data = read_bounded(f, length) or b''
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
                        data = read_bounded(f, length) or b''
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
                            read_bounded(f, length)
                    
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
            
            if full_path == self.get_comfy_folder_path(folder_type).resolve():
                return {'success': False, 'message': 'Cannot delete the folder root'}
            
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
                full_path = self._validate_file_path(folder_type, file_path)
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
        except ValueError:
            return {'success': False, 'message': 'Invalid path'}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def reinstall_package(self, package_name: str) -> dict:
        """Force reinstall a specific package"""
        if not valid_pip_package(package_name):
            return {'success': False, 'message': 'Invalid package name'}
        try:
            result = subprocess.run(
                [self.pip.python_path, '-m', 'pip', 'install', '--force-reinstall', '--no-deps', package_name.strip()],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            refresh_installed_packages()
            self.invalidate_pip_cache()
            
            if result.returncode == 0:
                self.ws_broadcast('package_reinstalled', {'package': package_name})
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
        process = self.comfy_process
        if process is not None:
            poll = process.poll()
            if poll is None:
                return {
                    'success': True,
                    'status': 'running',
                    'managed': True,
                    'port': getattr(self, 'comfy_port', 8188),
                    'active_profile': self.active_profile_name
                }
        
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
    
    @_process_action
    def launch_comfy(self, profile_name: str = None, enabled_override=None,
                     blocked_override=None, launch_label: str = None,
                     extra_flags=None, reset_output: bool = True,
                     restart_if_running: bool = False, flags_override=None) -> dict:
        """Launch ComfyUI with optional profile, folder set, and package blocklist."""
        profile = None
        if profile_name:
            profile = get_user_data().get_profile(profile_name)
            if profile is None:
                return {'success': False, 'message': 'Profile not found'}
        try:
            flags = (list(flags_override) if flags_override is not None
                     else build_profile_args(profile or {}))
            extra_flags = [str(flag) for flag in (extra_flags or []) if flag]
            flags.extend(extra_flags)
            validate_launch_args(flags)
        except ValueError as exc:
            return {'success': False, 'message': str(exc)}
        comfy_root = self.comfy_root
        python_path = find_comfy_python(comfy_root)
        main_script = comfy_root / 'main.py'
        if not main_script.is_file():
            return {'success': False, 'message': f'ComfyUI main.py not found at {main_script}'}

        status = self.get_comfy_status()
        if status.get('status') == 'running':
            if not restart_if_running:
                return {'success': False, 'message': 'ComfyUI is already running'}
            if status.get('managed') is False:
                return {
                    'success': False,
                    'message': 'ComfyUI is already running outside MF Conductor. Stop it first.',
                }
            self._append_comfy_log('Stopping ComfyUI to apply this workflow set...')
            stop_result = self.stop_comfy()
            if not stop_result.get('success') and 'not running' not in (stop_result.get('message') or '').lower():
                return stop_result
        
        if reset_output:
            with self.output_lock:
                self.comfy_output_buffer = []
                self.comfy_output_index = 0
        
        label = launch_label or (f'profile "{profile_name}"' if profile_name else 'ComfyUI')
        apply_result = None
        if enabled_override is not None:
            with self.output_lock:
                names = ', '.join(str(name) for name in enabled_override[:12])
                extra = '' if len(enabled_override) <= 12 else f' (+{len(enabled_override) - 12} more)'
                self.comfy_output_buffer.append({
                    'text': f'Applying {label} - enabling {len(enabled_override)} packs: {names}{extra}',
                    'type': 'info'
                })
            apply_result = self.apply_enabled_folders(enabled_override, disable_others=False)
        elif profile_name:
            with self.output_lock:
                self.comfy_output_buffer.append({
                    'text': f'Applying profile "{profile_name}" - enabling/disabling nodes...',
                    'type': 'info'
                })
            apply_result = self.apply_profile(profile_name)

        if apply_result is not None:
            if apply_result.get('success'):
                results = apply_result.get('results', {})
                enabled_count = len(results.get('enabled', []))
                kept_count = len(results.get('kept', []))
                disabled_count = len(results.get('disabled', []))
                errors = results.get('errors', [])
                
                with self.output_lock:
                    disabled_names = results.get('disabled') or []
                    disabled_note = ''
                    if disabled_names:
                        preview = ', '.join(str(name) for name in disabled_names[:8])
                        more = '' if len(disabled_names) <= 8 else f' (+{len(disabled_names) - 8} more)'
                        disabled_note = f': {preview}{more}'
                    if enabled_override is not None:
                        summary = (
                            f'Isolation applied: loading {len(enabled_override)} packs. '
                            'Other packs stay where they are; ComfyUI will skip them.'
                        )
                    else:
                        summary = (
                            f'Isolation applied: {enabled_count} turned on, '
                            f'{kept_count} already on (includes Manager/Frisk/Crystools), '
                            f'{disabled_count} turned off{disabled_note}'
                        )
                    self.comfy_output_buffer.append({
                        'text': summary,
                        'type': 'success'
                    })
                    for err in errors:
                        self.comfy_output_buffer.append({'text': f'Warning: {err}', 'type': 'warning'})
            else:
                return {'success': False, 'message': apply_result.get('message', 'Could not apply node selection')}
            if enabled_override is not None:
                flags = strip_custom_node_isolation(flags) + isolation_launch_flags(enabled_override)
        
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
            port = 8188
            for index, flag in enumerate(flags):
                if flag == '--port' and index + 1 < len(flags):
                    port = int(flags[index + 1])
                elif flag.startswith('--port='):
                    port = int(flag.split('=', 1)[1])
            # Use CREATE_NEW_PROCESS_GROUP on Windows to allow proper termination
            creation_flags = 0
            if os.name == 'nt':
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
            
            # Set up environment for UTF-8 output
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUTF8'] = '1'
            env.pop('MFCONDUCTOR_BLOCKED_PACKAGES', None)
            
            excluded_packages = blocked_override
            if excluded_packages is None and profile:
                excluded_packages = profile.get('excluded_packages', [])
            if excluded_packages:
                excluded_packages = [p for p in excluded_packages if not is_never_block_package(p)]
            persist_blocked_packages(excluded_packages or [])
            if excluded_packages:
                env['MFCONDUCTOR_BLOCKED_PACKAGES'] = ','.join(excluded_packages)
                with self.output_lock:
                    self.comfy_output_buffer.append({
                        'text': f'Blocking {len(excluded_packages)} packages: {", ".join(excluded_packages)}',
                        'type': 'info'
                    })
            
            self.comfy_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                cwd=str(comfy_root),
                env=env,
                creationflags=creation_flags
            )
            
            # Track which profile was used for this launch
            self.active_profile_name = profile_name
            self.last_enabled_override = None if enabled_override is None else list(enabled_override)
            self.last_blocked_override = list(excluded_packages or [])
            self.last_flags_override = None if flags_override is None else list(flags_override)
            self.last_extra_flags = extra_flags
            self.comfy_port = port
            
            # Start output reader thread
            reader_thread = threading.Thread(target=self._read_comfy_output, args=(self.comfy_process,), daemon=True)
            reader_thread.start()
            self._append_comfy_log('ComfyUI process spawned. Waiting for startup output...')
            threading.Thread(
                target=self._watch_comfy_startup,
                args=(self.comfy_process.pid,),
                daemon=True,
            ).start()
            
            self.comfy_port = port
            return {'success': True, 'message': 'ComfyUI started', 'pid': self.comfy_process.pid, 'port': port, 'flags': flags}
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
    
    def _watch_comfy_startup(self, pid: int) -> None:
        ready_markers = ('To see the GUI', 'Starting server', 'Prompt Server')
        for _ in range(36):
            time.sleep(10)
            process = self.comfy_process
            if process is None or process.pid != pid or process.poll() is not None:
                return
            with self.output_lock:
                recent = [row.get('text', '') for row in self.comfy_output_buffer[-120:]]
            if any(marker in text for text in recent for marker in ready_markers):
                return
            self._append_comfy_log('Still waiting for ComfyUI startup output...')

    def _read_comfy_output(self, process):
        """Background thread to read ComfyUI output"""
        try:
            if process.stdout is None:
                return
            
            # Read binary and decode ourselves
            while True:
                line_bytes = process.stdout.readline()
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
                    if self.comfy_process is not process:
                        break
                    self.comfy_output_buffer.append({'text': line, 'type': line_type})
                    # Prevent unbounded growth
                    if len(self.comfy_output_buffer) > self.max_comfy_output:
                        overflow = len(self.comfy_output_buffer) - self.max_comfy_output
                        self.comfy_output_buffer = self.comfy_output_buffer[overflow:]
                        self.comfy_output_index = max(0, self.comfy_output_index - overflow)
                    
            # Process ended
            with self.output_lock:
                if self.comfy_process is process and process.poll() is not None:
                    exit_code = process.poll()
                    self.comfy_output_buffer.append({
                        'text': f'Process exited with code {exit_code}',
                        'type': 'error' if exit_code != 0 else 'info'
                    })
        except Exception as e:
            with self.output_lock:
                if self.comfy_process is process:
                    self.comfy_output_buffer.append({'text': f'[Output reader error: {e}]', 'type': 'error'})
        finally:
            if process.stdout is not None:
                process.stdout.close()
    
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
    
    @_process_action
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
            return {'success': False, 'message': str(e)}
    
    @_process_action
    def restart_comfy(self) -> dict:
        """Restart ComfyUI using the same profile it was launched with"""
        # Use the profile that was active when ComfyUI was last launched
        profile_name = self.active_profile_name
        
        return self.launch_comfy(
            profile_name,
            enabled_override=self.last_enabled_override,
            blocked_override=self.last_blocked_override,
            extra_flags=self.last_extra_flags,
            flags_override=self.last_flags_override,
            restart_if_running=True,
        )

    def run_python_command(self, command: str) -> dict:
        """Run a Python command in the ComfyUI environment (pip operations only)"""
        # Find Python executable
        comfy_root = Path(__file__).parent.parent.parent
        portable_root = comfy_root.parent
        
        python_path = portable_root / 'python_embeded' / 'python.exe'
        if not python_path.exists():
            python_path = Path(sys.executable)
        
        # Split command into parts and validate the target module
        cmd_parts = command.split()
        if not cmd_parts:
            return {'success': False, 'message': 'Empty command'}
        
        module_name = cmd_parts[0]
        if module_name != 'pip':
            return {'success': False, 'message': 'Only pip list/show/freeze/check are allowed in the terminal'}
        if len(cmd_parts) < 2 or cmd_parts[1] not in ALLOWED_PIP_SUBCOMMANDS:
            return {'success': False, 'message': 'Use the Packages tab to install or uninstall. Terminal pip is limited to list, show, freeze, and check.'}
        
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
    
    @staticmethod
    def _escape_ps_string(value: str) -> str:
        return escape_ps_string(value)

    def create_conductor_shortcut(self, save_path: str = None) -> dict:
        """Create a shortcut to launch MF Conductor standalone server"""
        try:
            conductor_dir = Path(__file__).parent
            if os.name == 'nt':
                target = conductor_dir / 'Launch_MFConductor.bat'
            else:
                target = conductor_dir / 'Launch_MFConductor.sh'
            icon_path = conductor_dir / 'web' / 'mfconductor_logo.ico'
            dest, err = write_desktop_shortcut(
                save_path,
                str(target),
                str(conductor_dir),
                'MF Conductor',
                'Launch MF Conductor - ComfyUI Control Center',
                icon_path,
            )
            if dest is None:
                return {'success': False, 'message': err}
            return {'success': True, 'message': f'Shortcut created at {dest}', 'path': str(dest)}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    def create_profile_shortcut(self, profile_name: str, save_path: str = None) -> dict:
        """Create a shortcut that launches ComfyUI with a specific profile"""
        try:
            user_data = get_user_data()
            profiles = user_data.get_profiles()
            
            if profile_name not in profiles:
                return {'success': False, 'message': f'Profile "{profile_name}" not found'}
            
            profile = profiles[profile_name]
            conductor_dir = Path(__file__).parent
            comfy_root = conductor_dir.parent.parent
            args = self._build_comfy_args_from_profile(profile)
            launcher_script = write_profile_launcher(conductor_dir, profile_name, profile, args)
            target = launcher_script.with_suffix('.bat' if os.name == 'nt' else '.sh')
            icon_path = conductor_dir / 'web' / 'mfconductor_logo.ico'
            dest, err = write_desktop_shortcut(
                save_path,
                str(target),
                str(comfy_root),
                f'ComfyUI - {profile_name}',
                f'Launch ComfyUI with {profile_name} profile',
                icon_path,
            )
            if dest is None:
                return {'success': False, 'message': err}
            return {
                'success': True,
                'message': f'Quick launch shortcut created at {dest}',
                'path': str(dest),
                'launcher_path': str(launcher_script),
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': str(e)}
    
    def _build_comfy_args_from_profile(self, profile: dict) -> list:
        return build_profile_args(profile)



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
            '/ws', 'code 404', 'File not found'
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
            self.end_headers()
            self.wfile.write(json.dumps(data).encode('utf-8'))
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # Client disconnected - ignore
    
    def _is_local_client(self):
        return is_local_api_request(
            self.client_address[0] if self.client_address else '',
            self.headers.get('Host', ''), self.headers,
        )

    def do_OPTIONS(self):
        parsed = urlparse(self.path)
        if (parsed.path.startswith('/api/') or parsed.path == '/ws') and not self._is_local_client():
            self.send_error(403, 'Forbidden')
            return
        self.send_response(204)
        self.end_headers()
    
    def _handle_ws_upgrade(self):
        """Handle WebSocket upgrade on the same HTTP port"""
        raw_socket = self.request
        try:
            key = None
            for header_name in ('Sec-WebSocket-Key', 'sec-websocket-key'):
                val = self.headers.get(header_name)
                if val:
                    key = val
                    break
            if not key:
                self.send_error(400, 'Missing Sec-WebSocket-Key')
                return
            
            GUID = '258EAFA5-E914-47DA-95CA-5AB9ADF63B05'
            accept = base64.b64encode(
                hashlib.sha1((key + GUID).encode()).digest()
            ).decode()
            
            response = (
                'HTTP/1.1 101 Switching Protocols\r\n'
                'Upgrade: websocket\r\n'
                'Connection: Upgrade\r\n'
                f'Sec-WebSocket-Accept: {accept}\r\n'
                ''
                '\r\n'
            )
            # Write directly to raw socket to avoid buffering issues
            raw_socket.sendall(response.encode())
            
            # Set socket to blocking mode with no timeout for WebSocket
            raw_socket.setblocking(True)
            raw_socket.settimeout(None)
            
            self.api.ws_register(raw_socket)
            
            welcome = json.dumps({'type': 'connected', 'data': {'message': 'MF Conductor WebSocket'}})
            raw_socket.sendall(_ws_encode_frame(welcome))
            
            buffer = b''
            while True:
                ready = select.select([raw_socket], [], [], 30)
                if not ready[0]:
                    try:
                        raw_socket.sendall(struct.pack('!BB', 0x89, 0))
                    except Exception:
                        break
                    continue
                
                try:
                    chunk = raw_socket.recv(4096)
                except Exception:
                    break
                if not chunk:
                    break
                
                buffer += chunk
                while buffer:
                    opcode, payload = _ws_decode_frame(buffer)
                    if opcode is None:
                        break
                    
                    frame_len = 2
                    raw_len = buffer[1] & 0x7F
                    if raw_len == 126:
                        frame_len = 4
                    elif raw_len == 127:
                        frame_len = 10
                    if (buffer[1] & 0x80) != 0:
                        frame_len += 4
                    actual_len = raw_len
                    if raw_len == 126:
                        actual_len = struct.unpack('!H', buffer[2:4])[0]
                    elif raw_len == 127:
                        actual_len = struct.unpack('!Q', buffer[2:10])[0]
                    frame_len += actual_len
                    buffer = buffer[frame_len:]
                    
                    if opcode == 0x8:
                        try:
                            raw_socket.sendall(struct.pack('!BB', 0x88, 0))
                        except Exception:
                            pass
                        self.api.ws_unregister(raw_socket)
                        self.close_connection = True
                        return
                    elif opcode == 0x9:
                        try:
                            pong = struct.pack('!BB', 0x8A, len(payload)) + payload
                            raw_socket.sendall(pong)
                        except Exception:
                            pass
                    elif opcode == 0x1:
                        try:
                            msg = json.loads(payload.decode('utf-8'))
                            if msg.get('type') == 'ping':
                                reply = json.dumps({'type': 'pong', 'data': {}})
                                raw_socket.sendall(_ws_encode_frame(reply))
                        except Exception:
                            pass
        except Exception:
            pass
        finally:
            self.api.ws_unregister(self.request)
            self.close_connection = True
    
    def do_GET(self):
        """Handle GET requests"""
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if (path.startswith('/api/') or path == '/ws') and not self._is_local_client():
            self.send_json({'success': False, 'message': 'MF Conductor API is localhost-only'}, 403)
            return
        
        # WebSocket upgrade on same port — no separate WS server needed
        if path == '/ws':
            upgrade_header = self.headers.get('Upgrade', '')
            connection_header = self.headers.get('Connection', '')
            if 'websocket' in upgrade_header.lower() or 'upgrade' in connection_header.lower():
                self._handle_ws_upgrade()
                return
        
        # API routes
        if path == '/api/workflows/launch-options':
            self.send_json(workflow_launch_options(self.api.scanner, get_user_data()))
            return
        if path == '/api/nodes':
            fast = query.get('fast', ['false'])[0].lower() in ('1', 'true', 'yes')
            data = self.api.get_nodes(fast=fast)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/details'):
            folder_name = unquote(path.split('/')[3])
            data = self.api.get_node(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/requirements'):
            folder_name = unquote(path.split('/')[3])
            data = self.api.get_requirements(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/disk-usage'):
            folder_name = unquote(path.split('/')[3])
            data = self.api.get_disk_usage(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/git-log'):
            folder_name = unquote(path.split('/')[3])
            count = int(query.get('count', ['10'])[0])
            data = self.api.get_git_log(folder_name, count)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/check-updates'):
            folder_name = unquote(path.split('/')[3])
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
            folder_name = unquote(path.split('/')[3])
            data = self.api.get_tags(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/note'):
            folder_name = unquote(path.split('/')[3])
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
                'next_index': self.api.backend_log_base + len(self.api.backend_logs)
            })
            return
        
        # Packages
        if path == '/api/packages':
            refresh = query.get('refresh', ['false'])[0].lower() in ('1', 'true', 'yes')
            data = self.api.get_packages(refresh=refresh)
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
        
        if path == '/api/workflows':
            self.send_json(self.api.list_workflows())
            return
        
        if path == '/api/workflows/analyze':
            rel_path = query.get('path', [''])[0]
            self.send_json(self.api.analyze_workflow(rel_path))
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
        if path.startswith('/api/') and not self._is_local_client():
            self.send_json({'success': False, 'message': 'MF Conductor API is localhost-only'}, 403)
            return

        if self.headers.get_content_type() != 'application/json':
            self.send_json({'success': False, 'message': 'Content-Type must be application/json'}, 415)
            return
        
        # Read request body
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length < 0:
                raise ValueError
        except ValueError:
            self.send_json({'success': False, 'message': 'Invalid Content-Length'}, 400)
            return
        body = {}
        if content_length > 0:
            try:
                raw_body = self.rfile.read(content_length).decode('utf-8')
                body = json.loads(raw_body)
                if not isinstance(body, dict):
                    self.send_json({'success': False, 'message': 'JSON object required'}, 400)
                    return
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
            folder_name = unquote(path.split('/')[3])
            data = self.api.update_node(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/open-folder'):
            folder_name = unquote(path.split('/')[3])
            data = self.api.open_folder(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/remove'):
            folder_name = unquote(path.split('/')[3])
            data = self.api.remove_node(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/deactivate'):
            folder_name = unquote(path.split('/')[3])
            data = self.api.deactivate_node(folder_name)
            self.send_json(data)
            return
        
        if path.startswith('/api/nodes/') and path.endswith('/activate'):
            folder_name = unquote(path.split('/')[3])
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
            folder_name = unquote(path.split('/')[3])
            data = self.api.toggle_favorite(folder_name)
            self.send_json(data)
            return
        
        # Tags
        if path.startswith('/api/nodes/') and path.endswith('/tags'):
            folder_name = unquote(path.split('/')[3])
            tags = body.get('tags', [])
            data = self.api.set_tags(folder_name, tags)
            self.send_json(data)
            return
        
        # Notes
        if path.startswith('/api/nodes/') and path.endswith('/note'):
            folder_name = unquote(path.split('/')[3])
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
            folder_name = unquote(path.split('/')[3])
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
        
        if path == '/api/workflows/resolve-missing':
            self.send_json(self.api.resolve_missing_workflow_packs(body.get('names') or []))
            return

        if path == '/api/workflows/install-missing':
            self.send_json(self.api.install_missing_workflow_packs(body.get('names') or []))
            return

        if path == '/api/workflows/launch':
            profile = body.get('profile') or ''
            data = self.api.launch_workflow(body.get('path'), profile or None, body.get('paths'),
                                           body.get('launch_flags'), body.get('extra_nodes') or [])
            if not data.get('success') and data.get('message') == 'Workflow path is required':
                self.send_json(data, 400)
                return
            self.send_json(data)
            return
        
        if path == '/api/workflows/apply':
            prepared, error = self.api._isolation_for_workflows(body.get('path'), body.get('paths'))
            if error:
                status = 400 if error.get('message') == 'Workflow path is required' else 200
                self.send_json(error, status)
                return
            data = self.api.apply_enabled_folders(prepared['enabled'])
            if not data.get('results', {}).get('errors'):
                persist_pending_workflow(prepared['paths'][0], prepared['paths'])
            self.api.persist_default_profile_blocks()
            data['analysis'] = prepared['analysis']
            data['paths'] = prepared['paths']
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
                esc = MFConductorAPI._escape_ps_string
                ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.SaveFileDialog
$dialog.InitialDirectory = "{esc(desktop)}"
$dialog.Filter = "Windows Shortcut (*.lnk)|*.lnk"
$dialog.FileName = "{esc(suggested_name)}"
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


# ==================== WebSocket helpers ====================

def _ws_encode_frame(message: str) -> bytes:
    """Encode a string into a WebSocket text frame"""
    payload = message.encode('utf-8')
    length = len(payload)
    if length <= 125:
        header = struct.pack('!BB', 0x81, length)
    elif length <= 65535:
        header = struct.pack('!BBH', 0x81, 126, length)
    else:
        header = struct.pack('!BBQ', 0x81, 127, length)
    return header + payload


def _ws_decode_frame(data: bytes):
    """Decode a WebSocket frame, returns (opcode, payload_bytes) or (None, None)"""
    if len(data) < 2:
        return None, None
    
    opcode = data[0] & 0x0F
    masked = (data[1] & 0x80) != 0
    length = data[1] & 0x7F
    offset = 2
    
    if length == 126:
        if len(data) < 4:
            return None, None
        length = struct.unpack('!H', data[2:4])[0]
        offset = 4
    elif length == 127:
        if len(data) < 10:
            return None, None
        length = struct.unpack('!Q', data[2:10])[0]
        offset = 10
    
    if masked:
        if len(data) < offset + 4:
            return None, None
        mask = data[offset:offset + 4]
        offset += 4
    
    if len(data) < offset + length:
        return None, None
    
    payload = data[offset:offset + length]
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    
    return opcode, payload




def run_server(host: str = 'localhost', port: int = 8199, custom_nodes_path: str = None, open_browser: bool = True):
    """Run the standalone MF Conductor server"""
    
    # Initialize API
    MFConductorHandler.api = MFConductorAPI(custom_nodes_path)
    MFConductorHandler.web_dir = Path(__file__).parent / 'web'
    
    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
    
    server = ThreadedHTTPServer((host, port), MFConductorHandler)
    
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

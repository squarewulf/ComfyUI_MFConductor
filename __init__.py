"""
MF_Conductor - Custom Node Manager for ComfyUI
Integrates with ComfyUI's web interface to provide node management capabilities
"""

print("[MF Conductor] Loading...")

import os
import sys
import json
from pathlib import Path
from aiohttp import web

# Get the directory of this file
MF_CONDUCTOR_DIR = Path(__file__).parent

# Import local modules using relative imports or direct path
sys.path.insert(0, str(MF_CONDUCTOR_DIR))

# Import each module separately to identify which one fails
NodeScanner = None
GitUtils = None
PipUtils = None
get_user_data = None
browse_nodes = None
get_categories = None
refresh_node_database = None

try:
    from node_scanner import NodeScanner
    print("[MF Conductor] node_scanner loaded")
except Exception as e:
    print(f"[MF Conductor] Error loading node_scanner: {e}")

try:
    from git_utils import GitUtils, PipUtils
    print("[MF Conductor] git_utils loaded")
except Exception as e:
    print(f"[MF Conductor] Error loading git_utils: {e}")

try:
    from user_data import get_user_data
    print("[MF Conductor] user_data loaded")
except Exception as e:
    print(f"[MF Conductor] Error loading user_data: {e}")
    import traceback
    traceback.print_exc()

try:
    from browse_nodes import browse_nodes, get_categories, refresh_node_database
    print("[MF Conductor] browse_nodes loaded")
except Exception as e:
    print(f"[MF Conductor] Error loading browse_nodes: {e}")

# Global instances
_scanner = None
_git = None
_pip = None

def get_scanner():
    global _scanner
    if _scanner is None:
        if NodeScanner is None:
            raise RuntimeError("NodeScanner module not loaded")
        _scanner = NodeScanner()
    return _scanner

def get_git():
    global _git
    if _git is None:
        if GitUtils is None:
            raise RuntimeError("GitUtils module not loaded")
        _git = GitUtils()
    return _git

def get_pip():
    global _pip
    if _pip is None:
        if PipUtils is None:
            raise RuntimeError("PipUtils module not loaded")
        _pip = PipUtils()
    return _pip


# =============================================================================
# ComfyUI API Routes
# =============================================================================

async def api_get_nodes(request):
    """Get list of all custom nodes"""
    try:
        scanner = get_scanner()
        nodes = scanner.scan(use_cache=True)
        
        from datetime import datetime
        return web.json_response({
            'nodes': nodes,
            'scanned_at': datetime.now().isoformat(),
            'total': len(nodes)
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


async def api_refresh_nodes(request):
    """Force refresh the node list"""
    try:
        scanner = get_scanner()
        nodes = scanner.refresh()
        
        from datetime import datetime
        return web.json_response({
            'nodes': nodes,
            'scanned_at': datetime.now().isoformat(),
            'total': len(nodes)
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)


async def api_update_node(request):
    """Update a specific node via git pull"""
    try:
        folder_name = request.match_info.get('folder_name', '')
        if not folder_name:
            return web.json_response({'success': False, 'message': 'Folder name required'}, status=400)
        
        git = get_git()
        success, message = git.pull_updates(folder_name)
        
        return web.json_response({'success': success, 'message': message})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)


async def api_install_node(request):
    """Install a new node from git URL"""
    try:
        data = await request.json()
        url = (data.get('url') or '').strip()
        folder_name_raw = data.get('folder_name')
        folder_name = folder_name_raw.strip() if folder_name_raw else None
        install_deps = data.get('install_deps', True)
        
        if not url:
            return web.json_response({'success': False, 'message': 'URL is required'}, status=400)
        
        git = get_git()
        pip = get_pip()
        scanner = get_scanner()
        
        # Clone repository
        success, message = git.clone_repo(url, folder_name)
        
        if not success:
            return web.json_response({'success': False, 'message': message})
        
        # Determine folder name
        if not folder_name:
            folder_name = url.rstrip('/').split('/')[-1]
            if folder_name.endswith('.git'):
                folder_name = folder_name[:-4]
        
        # Install requirements
        if install_deps:
            req_path = scanner.custom_nodes_path / folder_name / 'requirements.txt'
            if req_path.exists():
                pip_success, pip_msg = pip.install_requirements(
                    str(scanner.custom_nodes_path / folder_name)
                )
                if not pip_success:
                    message += f" (Warning: {pip_msg})"
        
        # Refresh cache
        scanner.refresh()
        
        return web.json_response({'success': True, 'message': message})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)


async def api_open_folder(request):
    """Open node folder in file explorer"""
    try:
        folder_name = request.match_info.get('folder_name', '')
        if not folder_name:
            return web.json_response({'success': False, 'message': 'Folder name required'}, status=400)
        
        scanner = get_scanner()
        folder_path = scanner.custom_nodes_path / folder_name
        
        if not folder_path.exists():
            return web.json_response({'success': False, 'message': 'Folder not found'}, status=404)
        
        import subprocess
        if sys.platform == 'win32':
            os.startfile(str(folder_path))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(folder_path)])
        else:
            subprocess.run(['xdg-open', str(folder_path)])
        
        return web.json_response({'success': True, 'message': 'Folder opened'})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)


async def api_remove_node(request):
    """Remove (delete) a custom node"""
    try:
        folder_name = request.match_info.get('folder_name', '')
        if not folder_name:
            return web.json_response({'success': False, 'message': 'Folder name required'}, status=400)
        
        scanner = get_scanner()
        success, message = scanner.remove_node(folder_name)
        
        return web.json_response({'success': success, 'message': message})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)


async def api_deactivate_node(request):
    """Deactivate a custom node"""
    try:
        folder_name = request.match_info.get('folder_name', '')
        if not folder_name:
            return web.json_response({'success': False, 'message': 'Folder name required'}, status=400)
        
        scanner = get_scanner()
        success, message = scanner.deactivate_node(folder_name)
        
        return web.json_response({'success': success, 'message': message})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)


async def api_activate_node(request):
    """Activate a disabled custom node"""
    try:
        folder_name = request.match_info.get('folder_name', '')
        if not folder_name:
            return web.json_response({'success': False, 'message': 'Folder name required'}, status=400)
        
        scanner = get_scanner()
        success, message = scanner.activate_node(folder_name)
        
        return web.json_response({'success': success, 'message': message})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)


async def serve_web_file(request):
    """Serve static files from the web directory"""
    filename = request.match_info.get('filename', 'index.html')
    if not filename:
        filename = 'index.html'
    
    web_dir = Path(__file__).parent / 'web'
    file_path = web_dir / filename
    
    # Security check - prevent directory traversal
    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str(web_dir.resolve())):
            return web.Response(status=403, text='Forbidden')
    except Exception:
        return web.Response(status=404, text='Not found')
    
    if not file_path.exists():
        return web.Response(status=404, text='Not found')
    
    # Determine content type
    content_types = {
        '.html': 'text/html',
        '.css': 'text/css',
        '.js': 'application/javascript',
        '.json': 'application/json',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.svg': 'image/svg+xml',
        '.webp': 'image/webp',
        '.ico': 'image/x-icon',
    }
    
    suffix = file_path.suffix.lower()
    content_type = content_types.get(suffix, 'application/octet-stream')
    
    with open(file_path, 'rb') as f:
        content = f.read()
    
    return web.Response(body=content, content_type=content_type)


# =============================================================================
# ComfyUI Integration
# =============================================================================

# This tells ComfyUI where to find the JavaScript extensions
WEB_DIRECTORY = "./js"

# Node class mappings (empty - we don't provide nodes, just UI)
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}



# Register routes with ComfyUI using the standard extension pattern
try:
    print("[MF Conductor] Attempting to register routes with ComfyUI...")
    import server
    from aiohttp import web as aiohttp_web
    
    routes = server.PromptServer.instance.routes
    print("[MF Conductor] Got PromptServer routes")
    
    # API Routes
    @routes.get('/mf_conductor/api/nodes')
    async def _mnf_get_nodes(request):
        return await api_get_nodes(request)
    
    @routes.post('/mf_conductor/api/nodes/refresh')
    async def _mnf_refresh_nodes(request):
        return await api_refresh_nodes(request)
    
    @routes.post('/mf_conductor/api/nodes/install')
    async def _mnf_install_node(request):
        return await api_install_node(request)
    
    @routes.post('/mf_conductor/api/nodes/{folder_name}/update')
    async def _mnf_update_node(request):
        return await api_update_node(request)
    
    @routes.post('/mf_conductor/api/nodes/{folder_name}/open-folder')
    async def _mnf_open_folder(request):
        return await api_open_folder(request)
    
    @routes.post('/mf_conductor/api/nodes/{folder_name}/remove')
    async def _mnf_remove_node(request):
        return await api_remove_node(request)
    
    @routes.post('/mf_conductor/api/nodes/{folder_name}/deactivate')
    async def _mnf_deactivate_node(request):
        return await api_deactivate_node(request)
    
    @routes.post('/mf_conductor/api/nodes/{folder_name}/activate')
    async def _mnf_activate_node(request):
        return await api_activate_node(request)
    
    @routes.get('/mf_conductor/api/nodes/{folder_name}/requirements')
    async def _mnf_get_requirements(request):
        try:
            folder_name = request.match_info.get('folder_name', '')
            if not folder_name:
                return web.json_response({'success': False, 'message': 'Folder name required'}, status=400)
            
            scanner = get_scanner()
            folder_path = scanner.custom_nodes_path / folder_name
            
            if not folder_path.exists():
                return web.json_response({'success': False, 'message': 'Folder not found', 'requirements': []})
            
            from node_scanner import get_node_requirements
            requirements = get_node_requirements(folder_path)
            
            return web.json_response({
                'success': True,
                'requirements': requirements,
                'total': len(requirements),
                'installed': sum(1 for r in requirements if r['status'] == 'installed'),
                'missing': sum(1 for r in requirements if r['status'] == 'missing'),
                'warnings': sum(1 for r in requirements if r['status'] == 'warning')
            })
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e), 'requirements': []}, status=500)
    
    @routes.post('/mf_conductor/api/install-package')
    async def _mnf_install_package(request):
        try:
            data = await request.json()
            package_name = (data.get('package_name') or '').strip()
            if not package_name:
                return web.json_response({'success': False, 'message': 'Package name required'}, status=400)
            
            import subprocess
            pip = get_pip()
            
            result = subprocess.run(
                [pip.python_path, '-m', 'pip', 'install', package_name],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            from node_scanner import refresh_installed_packages
            refresh_installed_packages()
            
            if result.returncode == 0:
                return web.json_response({'success': True, 'message': f'Successfully installed {package_name}'})
            else:
                return web.json_response({'success': False, 'message': f'Installation failed: {result.stderr}'})
        except subprocess.TimeoutExpired:
            return web.json_response({'success': False, 'message': 'Installation timed out'})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # ==================== USER DATA ROUTES ====================
    
    @routes.get('/mf_conductor/api/user-data')
    async def _mnf_get_user_data(request):
        try:
            user_data = get_user_data()
            return web.json_response({
                'success': True,
                'favorites': user_data.get_favorites(),
                'tags': dict(user_data._tags),
                'notes': user_data.get_all_notes(),
                'usage': user_data.get_usage_stats()
            })
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.get('/mf_conductor/api/favorites')
    async def _mnf_get_favorites(request):
        try:
            user_data = get_user_data()
            return web.json_response({'success': True, 'favorites': user_data.get_favorites()})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/nodes/{folder_name}/toggle-favorite')
    async def _mnf_toggle_favorite(request):
        try:
            folder_name = request.match_info.get('folder_name', '')
            user_data = get_user_data()
            is_favorite = user_data.toggle_favorite(folder_name)
            return web.json_response({'success': True, 'is_favorite': is_favorite})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.get('/mf_conductor/api/tags')
    async def _mnf_get_all_tags(request):
        try:
            user_data = get_user_data()
            return web.json_response({'success': True, 'all_tags': user_data.get_all_tags()})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.get('/mf_conductor/api/nodes/{folder_name}/tags')
    async def _mnf_get_node_tags(request):
        try:
            folder_name = request.match_info.get('folder_name', '')
            user_data = get_user_data()
            return web.json_response({'success': True, 'tags': user_data.get_tags(folder_name)})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/nodes/{folder_name}/tags')
    async def _mnf_set_node_tags(request):
        try:
            folder_name = request.match_info.get('folder_name', '')
            data = await request.json()
            tags = data.get('tags', [])
            user_data = get_user_data()
            user_data.set_tags(folder_name, tags)
            return web.json_response({'success': True, 'tags': tags})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.get('/mf_conductor/api/nodes/{folder_name}/note')
    async def _mnf_get_note(request):
        try:
            folder_name = request.match_info.get('folder_name', '')
            user_data = get_user_data()
            return web.json_response({'success': True, 'note': user_data.get_note(folder_name)})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/nodes/{folder_name}/note')
    async def _mnf_set_note(request):
        try:
            folder_name = request.match_info.get('folder_name', '')
            data = await request.json()
            note = data.get('note', '')
            user_data = get_user_data()
            user_data.set_note(folder_name, note)
            return web.json_response({'success': True, 'note': note})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # ==================== PROFILES ====================
    
    @routes.get('/mf_conductor/api/profiles')
    async def _mnf_get_profiles(request):
        try:
            user_data = get_user_data()
            return web.json_response({'success': True, 'profiles': user_data.get_profiles()})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/profiles/save')
    async def _mnf_save_profile(request):
        try:
            data = await request.json()
            name = data.get('name', '')
            old_name = data.get('old_name', '')  # For renaming profiles
            enabled = data.get('enabled', [])
            disabled = data.get('disabled', [])
            flags = data.get('flags', {})
            custom_flags = data.get('custom_flags', '')
            custom_flags_list = data.get('custom_flags_list', [])
            excluded_packages = data.get('excluded_packages', [])
            description = data.get('description', '')
            avatar = data.get('avatar', 'default.svg')
            if not name:
                return web.json_response({'success': False, 'message': 'Profile name required'}, status=400)
            user_data = get_user_data()
            
            # If renaming (old_name provided and different from new name), delete the old profile first
            if old_name and old_name != name:
                user_data.delete_profile(old_name)
            
            user_data.save_profile(name, enabled, disabled, flags, custom_flags, custom_flags_list, excluded_packages, description, avatar)
            return web.json_response({'success': True, 'message': f'Profile "{name}" saved'})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/profiles/delete')
    async def _mnf_delete_profile(request):
        try:
            data = await request.json()
            name = data.get('name', '')
            user_data = get_user_data()
            if user_data.delete_profile(name):
                return web.json_response({'success': True, 'message': f'Profile "{name}" deleted'})
            return web.json_response({'success': False, 'message': 'Profile not found'})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/profiles/apply')
    async def _mnf_apply_profile(request):
        try:
            data = await request.json()
            name = data.get('name', '')
            user_data = get_user_data()
            profile = user_data.get_profile(name)
            if not profile:
                return web.json_response({'success': False, 'message': 'Profile not found'})
            
            scanner = get_scanner()
            results = {'enabled': [], 'disabled': [], 'errors': []}
            
            enabled_list = profile.get('enabled', [])
            disabled_list = profile.get('disabled', [])
            
            # Get all node folders
            all_nodes = scanner.scan()
            all_folders = [n['folder_name'] for n in all_nodes]
            
            # If enabled list is empty, treat as "all nodes enabled"
            if not enabled_list and not disabled_list:
                # Empty lists = use all nodes (enable everything)
                for folder in all_folders:
                    success, msg = scanner.activate_node(folder)
                    if success:
                        results['enabled'].append(folder)
            else:
                # Specific selection - enable only selected, disable others
                enabled_set = set(enabled_list) if enabled_list else set(all_folders)
                
                for folder in all_folders:
                    if folder in enabled_set:
                        success, msg = scanner.activate_node(folder)
                        if success:
                            results['enabled'].append(folder)
                        elif 'already' not in msg.lower():
                            results['errors'].append(f"{folder}: {msg}")
                    else:
                        success, msg = scanner.deactivate_node(folder)
                        if success:
                            results['disabled'].append(folder)
                        elif 'already' not in msg.lower():
                            results['errors'].append(f"{folder}: {msg}")
            
            return web.json_response({'success': True, 'results': results})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/profiles/launch')
    async def _mnf_launch_profile(request):
        try:
            import subprocess
            data = await request.json()
            name = data.get('name', '')
            user_data = get_user_data()
            profile = user_data.get_profile(name)
            if not profile:
                return web.json_response({'success': False, 'message': 'Profile not found'})
            
            # Create batch file for this profile
            bat_path = Path(__file__).parent / 'profiles' / f'{name}.bat'
            bat_path.parent.mkdir(exist_ok=True)
            
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
                python_path = Path(__file__).parent.parent.parent.parent / 'python_embeded' / 'python.exe'
                if not python_path.exists():
                    import sys
                    python_path = sys.executable
                bat_content = f'@echo off\ncd /d "{comfy_root}"\n"{python_path}" "{run_script}" {flags_str}\n'
            
            with open(bat_path, 'w') as f:
                f.write(bat_content)
            
            # Launch the batch file
            subprocess.Popen(['cmd', '/c', str(bat_path)], shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE)
            
            return web.json_response({'success': True, 'message': f'Launching profile {name}...'})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/profiles/set-default')
    async def _mnf_set_default_profile(request):
        try:
            data = await request.json()
            name = data.get('name', '')
            user_data = get_user_data()
            
            # Clear default from all profiles, set on this one
            profiles = user_data.get_profiles()
            for pname, profile in profiles.items():
                profile['is_default'] = (pname == name)
            
            # Save all profiles
            user_data._profiles = profiles
            user_data._save_json(user_data.profiles_file, profiles)
            
            return web.json_response({'success': True, 'message': f'{name} set as default'})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # ==================== BACKUP / RESTORE ====================
    
    @routes.get('/mf_conductor/api/backup')
    async def _mnf_export_backup(request):
        try:
            user_data = get_user_data()
            return web.json_response({'success': True, 'backup': user_data.export_backup()})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/backup/import')
    async def _mnf_import_backup(request):
        try:
            data = await request.json()
            backup_data = data.get('data', {})
            merge = data.get('merge', False)
            user_data = get_user_data()
            if user_data.import_backup(backup_data, merge):
                return web.json_response({'success': True, 'message': 'Backup imported successfully'})
            return web.json_response({'success': False, 'message': 'Failed to import backup'})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.get('/mf_conductor/api/export-nodes')
    async def _mnf_export_nodes(request):
        try:
            scanner = get_scanner()
            user_data = get_user_data()
            nodes = scanner.scan(use_cache=True)
            return web.json_response({'success': True, 'data': user_data.export_node_list(nodes)})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # ==================== UPDATE CHECKING ====================
    
    @routes.get('/mf_conductor/api/check-updates')
    async def _mnf_check_all_updates(request):
        try:
            scanner = get_scanner()
            if not scanner.nodes:
                scanner.scan(use_cache=True)
            results = scanner.batch_check_updates()
            updates_available = {k: v for k, v in results.items() if v.get('has_updates')}
            return web.json_response({
                'success': True,
                'updates_available': len(updates_available),
                'total_checked': len(results),
                'nodes': results
            })
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.get('/mf_conductor/api/nodes/{folder_name}/check-updates')
    async def _mnf_check_node_updates(request):
        try:
            folder_name = request.match_info.get('folder_name', '')
            scanner = get_scanner()
            result = scanner.check_for_updates(folder_name)
            return web.json_response({'success': True, 'folder_name': folder_name, **result})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/batch-update')
    async def _mnf_batch_update(request):
        try:
            data = await request.json()
            folder_names = data.get('folder_names')  # None = update all
            scanner = get_scanner()
            results = scanner.batch_update(folder_names)
            successes = sum(1 for v in results.values() if v[0])
            return web.json_response({
                'success': True,
                'updated': successes,
                'total': len(results),
                'results': {k: {'success': v[0], 'message': v[1]} for k, v in results.items()}
            })
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # ==================== DISK USAGE ====================
    
    @routes.get('/mf_conductor/api/disk-usage')
    async def _mnf_get_all_disk_usage(request):
        try:
            scanner = get_scanner()
            if not scanner.nodes:
                scanner.scan(use_cache=True)
            
            results = {}
            total_size = 0
            for node in scanner.nodes:
                usage = scanner.get_disk_usage(node.folder_name)
                results[node.folder_name] = usage
                total_size += usage['size_bytes']
            
            return web.json_response({
                'success': True,
                'total_size_bytes': total_size,
                'total_size_formatted': scanner._format_size(total_size),
                'nodes': results
            })
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.get('/mf_conductor/api/nodes/{folder_name}/disk-usage')
    async def _mnf_get_node_disk_usage(request):
        try:
            folder_name = request.match_info.get('folder_name', '')
            scanner = get_scanner()
            return web.json_response({'success': True, **scanner.get_disk_usage(folder_name)})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # ==================== GIT HISTORY ====================
    
    @routes.get('/mf_conductor/api/nodes/{folder_name}/git-log')
    async def _mnf_get_git_log(request):
        try:
            folder_name = request.match_info.get('folder_name', '')
            count = int(request.query.get('count', '10'))
            scanner = get_scanner()
            commits = scanner.get_git_log(folder_name, count)
            return web.json_response({'success': True, 'commits': commits})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/nodes/{folder_name}/rollback')
    async def _mnf_rollback_node(request):
        try:
            folder_name = request.match_info.get('folder_name', '')
            data = await request.json()
            commit_hash = data.get('commit_hash', '')
            if not commit_hash:
                return web.json_response({'success': False, 'message': 'Commit hash required'}, status=400)
            scanner = get_scanner()
            success, message = scanner.rollback_node(folder_name, commit_hash)
            return web.json_response({'success': success, 'message': message})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # ==================== BROKEN NODES ====================
    
    @routes.get('/mf_conductor/api/broken-nodes')
    async def _mnf_detect_broken_nodes(request):
        try:
            scanner = get_scanner()
            if not scanner.nodes:
                scanner.scan(use_cache=True)
            broken = scanner.detect_broken_nodes()
            return web.json_response({'success': True, 'broken_nodes': broken, 'count': len(broken)})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # ==================== BROWSE NODES ====================
    
    @routes.get('/mf_conductor/api/browse')
    async def _mnf_browse_nodes(request):
        try:
            search = request.query.get('search', '')
            category = request.query.get('category', '')
            sort_by = request.query.get('sort', 'stars')
            limit = int(request.query.get('limit', '100'))
            offset = int(request.query.get('offset', '0'))
            installed_only = request.query.get('installed', 'false') == 'true'
            not_installed_only = request.query.get('not_installed', 'false') == 'true'
            
            result = browse_nodes(
                search=search,
                category=category,
                installed_only=installed_only,
                not_installed_only=not_installed_only,
                sort_by=sort_by,
                limit=limit,
                offset=offset
            )
            return web.json_response({'success': True, **result})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.get('/mf_conductor/api/browse/categories')
    async def _mnf_browse_categories(request):
        try:
            return web.json_response({'success': True, 'categories': get_categories()})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/browse/refresh')
    async def _mnf_refresh_browse_db(request):
        try:
            if refresh_node_database():
                return web.json_response({'success': True, 'message': 'Database refreshed'})
            return web.json_response({'success': False, 'message': 'Failed to refresh database'})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # ==================== PACKAGES ====================
    
    @routes.get('/mf_conductor/api/packages')
    async def _mnf_get_packages(request):
        import asyncio
        import json as json_module
        
        try:
            # Get python path from PipUtils
            try:
                pip = get_pip()
                python_path = pip.python_path if pip else None
            except:
                python_path = None
            
            # Find python executable
            if not python_path:
                import sys
                python_path = sys.executable
            
            # Use asyncio subprocess to avoid blocking
            # Use python -m pip instead of pip directly
            proc = await asyncio.create_subprocess_exec(
                python_path, '-m', 'pip', 'list', '--format=json',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            
            if proc.returncode == 0:
                packages = json_module.loads(stdout.decode())
                return web.json_response({
                    'success': True,
                    'packages': packages
                })
            else:
                return web.json_response({
                    'success': False,
                    'message': stderr.decode() or 'Failed to list packages'
                }, status=500)
        except asyncio.TimeoutError:
            return web.json_response({'success': False, 'message': 'Timeout listing packages'}, status=500)
        except Exception as e:
            import traceback
            print(f"[MF_Conductor] Error listing packages: {e}")
            traceback.print_exc()
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/packages/check-updates')
    async def _mnf_check_package_updates(request):
        import asyncio
        import json as json_module
        
        try:
            try:
                pip = get_pip()
                python_path = pip.python_path if pip else None
            except:
                python_path = None
            
            if not python_path:
                import sys
                python_path = sys.executable
            
            proc = await asyncio.create_subprocess_exec(
                python_path, '-m', 'pip', 'list', '--outdated', '--format=json',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            
            if proc.returncode == 0:
                outdated = json_module.loads(stdout.decode()) if stdout.decode().strip() else []
                updates = []
                for pkg in outdated:
                    updates.append({
                        'name': pkg.get('name', ''),
                        'current_version': pkg.get('version', ''),
                        'latest_version': pkg.get('latest_version', '')
                    })
                return web.json_response({'success': True, 'updates': updates})
            else:
                return web.json_response({
                    'success': False,
                    'message': stderr.decode() or 'Failed to check updates'
                }, status=500)
        except asyncio.TimeoutError:
            return web.json_response({'success': False, 'message': 'Timeout checking updates'}, status=500)
        except Exception as e:
            print(f"[MF_Conductor] Error checking package updates: {e}")
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/packages/install')
    async def _mnf_install_package(request):
        import asyncio
        
        try:
            data = await request.json()
            package_name = data.get('package_name', '')
            
            if not package_name:
                return web.json_response({'success': False, 'message': 'Package name is required'}, status=400)
            
            try:
                pip = get_pip()
                python_path = pip.python_path if pip else None
            except:
                python_path = None
            
            if not python_path:
                import sys
                python_path = sys.executable
            
            proc = await asyncio.create_subprocess_exec(
                python_path, '-m', 'pip', 'install', package_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            
            if proc.returncode == 0:
                refresh_installed_packages()
                return web.json_response({'success': True, 'message': f'Successfully installed {package_name}'})
            else:
                return web.json_response({
                    'success': False,
                    'message': f'Installation failed: {stderr.decode()}'
                }, status=500)
        except asyncio.TimeoutError:
            return web.json_response({'success': False, 'message': 'Installation timed out'}, status=500)
        except Exception as e:
            print(f"[MF_Conductor] Error installing package: {e}")
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/packages/uninstall')
    async def _mnf_uninstall_package(request):
        import asyncio
        
        try:
            data = await request.json()
            package_name = data.get('package_name', '')
            
            if not package_name:
                return web.json_response({'success': False, 'message': 'Package name is required'}, status=400)
            
            try:
                pip = get_pip()
                python_path = pip.python_path if pip else None
            except:
                python_path = None
            
            if not python_path:
                import sys
                python_path = sys.executable
            
            proc = await asyncio.create_subprocess_exec(
                python_path, '-m', 'pip', 'uninstall', '-y', package_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            
            if proc.returncode == 0:
                refresh_installed_packages()
                return web.json_response({'success': True, 'message': f'Successfully uninstalled {package_name}'})
            else:
                return web.json_response({
                    'success': False,
                    'message': f'Uninstall failed: {stderr.decode()}'
                }, status=500)
        except asyncio.TimeoutError:
            return web.json_response({'success': False, 'message': 'Uninstall timed out'}, status=500)
        except Exception as e:
            print(f"[MF_Conductor] Error uninstalling package: {e}")
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/packages/upgrade')
    async def _mnf_upgrade_package(request):
        import asyncio
        
        try:
            data = await request.json()
            package_name = data.get('package_name', '')
            
            if not package_name:
                return web.json_response({'success': False, 'message': 'Package name is required'}, status=400)
            
            try:
                pip = get_pip()
                python_path = pip.python_path if pip else None
            except:
                python_path = None
            
            if not python_path:
                import sys
                python_path = sys.executable
            
            proc = await asyncio.create_subprocess_exec(
                python_path, '-m', 'pip', 'install', '--upgrade', package_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            
            if proc.returncode == 0:
                refresh_installed_packages()
                return web.json_response({'success': True, 'message': f'Successfully upgraded {package_name}'})
            else:
                return web.json_response({
                    'success': False,
                    'message': f'Upgrade failed: {stderr.decode()}'
                }, status=500)
        except asyncio.TimeoutError:
            return web.json_response({'success': False, 'message': 'Upgrade timed out'}, status=500)
        except Exception as e:
            print(f"[MF_Conductor] Error upgrading package: {e}")
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/packages/reinstall')
    async def _mnf_reinstall_package(request):
        import asyncio
        
        try:
            data = await request.json()
            package_name = data.get('package_name', '')
            
            if not package_name:
                return web.json_response({'success': False, 'message': 'Package name is required'}, status=400)
            
            try:
                pip = get_pip()
                python_path = pip.python_path if pip else None
            except:
                python_path = None
            
            if not python_path:
                import sys
                python_path = sys.executable
            
            proc = await asyncio.create_subprocess_exec(
                python_path, '-m', 'pip', 'install', '--force-reinstall', '--no-deps', package_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            
            if proc.returncode == 0:
                refresh_installed_packages()
                return web.json_response({'success': True, 'message': f'Successfully reinstalled {package_name}'})
            else:
                return web.json_response({
                    'success': False,
                    'message': f'Reinstall failed: {stderr.decode()}'
                }, status=500)
        except asyncio.TimeoutError:
            return web.json_response({'success': False, 'message': 'Reinstall timed out'}, status=500)
        except Exception as e:
            print(f"[MF_Conductor] Error reinstalling package: {e}")
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # ==================== SETTINGS ====================
    
    @routes.get('/mf_conductor/api/settings')
    async def _mnf_get_settings(request):
        try:
            user_data = get_user_data()
            return web.json_response({'success': True, 'settings': user_data.get_settings()})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/settings')
    async def _mnf_update_settings(request):
        try:
            data = await request.json()
            settings = data.get('settings', {})
            user_data = get_user_data()
            for key, value in settings.items():
                user_data.set_setting(key, value)
            return web.json_response({'success': True, 'settings': user_data.get_settings()})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # ==================== COMFYUI STATUS (INTEGRATED MODE) ====================
    
    @routes.get('/mf_conductor/api/comfy/status')
    async def _mnf_comfy_status(request):
        """In integrated mode, ComfyUI is always running (since it's serving this page)"""
        return web.json_response({
            'success': True,
            'status': 'running',
            'managed': False,
            'port': 8188
        })
    
    @routes.get('/mf_conductor/api/comfy/output')
    async def _mnf_comfy_output(request):
        """Console output not available in integrated mode"""
        return web.json_response({
            'success': True,
            'output': [],
            'status': 'running'
        })
    
    @routes.post('/mf_conductor/api/comfy/launch')
    async def _mnf_comfy_launch(request):
        """Cannot launch ComfyUI from integrated mode (it's already running)"""
        return web.json_response({
            'success': False,
            'message': 'ComfyUI is already running. Use standalone mode to control ComfyUI launching.'
        })
    
    @routes.post('/mf_conductor/api/comfy/stop')
    async def _mnf_comfy_stop(request):
        """Cannot stop ComfyUI from integrated mode"""
        return web.json_response({
            'success': False,
            'message': 'Cannot stop ComfyUI from within ComfyUI. Use standalone mode for process control.'
        })
    
    @routes.post('/mf_conductor/api/comfy/restart')
    async def _mnf_comfy_restart(request):
        """Cannot restart ComfyUI from integrated mode"""
        return web.json_response({
            'success': False,
            'message': 'Cannot restart ComfyUI from within ComfyUI. Use standalone mode for process control.'
        })
    
    @routes.post('/mf_conductor/api/comfy/run-command')
    async def _mnf_comfy_run_command(request):
        """Run a pip/python command"""
        try:
            import asyncio
            data = await request.json()
            command = data.get('command', '')
            
            if not command:
                return web.json_response({'success': False, 'message': 'Command is required'}, status=400)
            
            # Find Python executable
            comfy_root = Path(__file__).parent.parent.parent
            portable_root = comfy_root.parent
            
            python_path = portable_root / 'python_embeded' / 'python.exe'
            if not python_path.exists():
                python_path = Path(sys.executable)
            
            cmd_parts = command.split()
            
            proc = await asyncio.create_subprocess_exec(
                str(python_path), '-m', *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(comfy_root)
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            
            return web.json_response({
                'success': True,
                'output': stdout.decode('utf-8', errors='replace') if stdout else None,
                'error': stderr.decode('utf-8', errors='replace') if stderr else None,
                'return_code': proc.returncode
            })
        except asyncio.TimeoutError:
            return web.json_response({'success': False, 'message': 'Command timed out after 120 seconds'})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # Serve static files from web directory
    @routes.get('/mf_conductor/{filename:.*}')
    async def _mnf_serve_static(request):
        filename = request.match_info.get('filename', 'index.html')
        if not filename or filename == '':
            filename = 'index.html'
        
        web_dir = Path(__file__).parent / 'web'
        file_path = web_dir / filename
        
        # Security check
        try:
            file_path = file_path.resolve()
            if not str(file_path).startswith(str(web_dir.resolve())):
                return aiohttp_web.Response(status=403, text='Forbidden')
        except:
            return aiohttp_web.Response(status=404, text='Not found')
        
        if not file_path.exists():
            # Try index.html for directory requests
            if (web_dir / filename / 'index.html').exists():
                file_path = web_dir / filename / 'index.html'
            else:
                return aiohttp_web.Response(status=404, text='Not found')
        
        content_types = {
            '.html': 'text/html',
            '.css': 'text/css', 
            '.js': 'application/javascript',
            '.json': 'application/json',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.svg': 'image/svg+xml',
            '.webp': 'image/webp',
            '.ico': 'image/x-icon',
        }
        
        content_type = content_types.get(file_path.suffix.lower(), 'application/octet-stream')
        
        with open(file_path, 'rb') as f:
            content = f.read()
        
        return aiohttp_web.Response(body=content, content_type=content_type)
    
    @routes.get('/mf_conductor')
    async def _mnf_redirect(request):
        raise aiohttp_web.HTTPFound('/mf_conductor/index.html')
    
    print("[MF Conductor] ✓ Routes registered with ComfyUI")
    print("[MF Conductor] ✓ Access at: http://localhost:8188/mf_conductor/")
    
except Exception as e:
    import traceback
    print(f"[MF Conductor] Could not register routes: {e}")
    traceback.print_exc()
    print("[MF Conductor] Use standalone mode instead: run Launch_MFConductor.bat")


__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']


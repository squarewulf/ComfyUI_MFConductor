"""
MF_Conductor - Custom Node Manager for ComfyUI
Integrates with ComfyUI's web interface to provide node management capabilities
"""

print("[MF Conductor] Loading...")

import os
import sys
import json
import asyncio
import threading
from pathlib import Path
from aiohttp import web

# Get the directory of this file
MF_CONDUCTOR_DIR = Path(__file__).parent

# Import each module separately to identify which one fails
NodeScanner = None
GitUtils = None
PipUtils = None
get_user_data = None
browse_nodes = None
get_categories = None
refresh_node_database = None
resolve_missing_packs = None
install_missing_packs = None

try:
    from .node_scanner import NodeScanner, get_node_requirements, refresh_installed_packages, CACHE_VERSION
    print("[MF Conductor] node_scanner loaded")
except Exception as e:
    print(f"[MF Conductor] Error loading node_scanner: {e}")
    get_node_requirements = None
    refresh_installed_packages = None

try:
    # IMPORTANT: use explicit relative import to avoid name-collisions with ComfyUI-Manager's git_utils
    from .git_utils import GitUtils, PipUtils
    print("[MF Conductor] git_utils loaded")
except Exception as e:
    print(f"[MF Conductor] Error loading git_utils: {e}")

try:
    from .user_data import get_user_data
    print("[MF Conductor] user_data loaded")
except Exception as e:
    print(f"[MF Conductor] Error loading user_data: {e}")
    import traceback
    traceback.print_exc()

try:
    from .browse_nodes import (
        browse_nodes,
        get_categories,
        install_missing_packs,
        refresh_node_database,
        resolve_missing_packs,
    )
    print("[MF Conductor] browse_nodes loaded")
except Exception as e:
    print(f"[MF Conductor] Error loading browse_nodes: {e}")
    install_missing_packs = None
    resolve_missing_packs = None

try:
    from .usage_tracker import get_usage_tracker
    print("[MF Conductor] usage_tracker loaded")
except Exception as e:
    print(f"[MF Conductor] Error loading usage_tracker: {e}")
    get_usage_tracker = None

try:
    from .workflow_analyzer import (
        apply_enabled_folders,
        clear_pending_workflow,
        folders_for_profile,
        folders_for_workflow_launch,
        get_workflow_analyzer,
        normalize_workflow_paths,
        persist_pending_workflow,
    )
    print("[MF Conductor] workflow_analyzer loaded")
except Exception as e:
    print(f"[MF Conductor] Error loading workflow_analyzer: {e}")
    apply_enabled_folders = None
    folders_for_profile = None
    folders_for_workflow_launch = None
    get_workflow_analyzer = None
    normalize_workflow_paths = None
    persist_pending_workflow = None
    clear_pending_workflow = None

from .security_utils import (
    escape_ps_string,
    is_local_request,
    resolve_under,
    safe_node_name,
    valid_git_url,
    valid_pip_package,
    valid_pip_version,
)
from .profile_launch import build_profile_args, parse_launch_flags, persist_blocked_packages, workflow_launch_options, write_desktop_shortcut, write_profile_launcher

# Global instances
_scanner = None
_git = None
_pip = None
_init_lock = threading.Lock()

def get_scanner():
    global _scanner
    if _scanner is None:
        with _init_lock:
            if _scanner is None:
                if NodeScanner is None:
                    raise RuntimeError("NodeScanner module not loaded")
                _scanner = NodeScanner()
    return _scanner

def get_git():
    global _git
    if _git is None:
        with _init_lock:
            if _git is None:
                if GitUtils is None:
                    raise RuntimeError("GitUtils module not loaded")
                _git = GitUtils()
    return _git

def get_pip():
    global _pip
    if _pip is None:
        with _init_lock:
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
        fast = request.query.get('fast', 'false').lower() in ('1', 'true', 'yes')
        if fast:
            cache = scanner.get_cached_nodes(allow_stale=True)
            if cache and cache.get('nodes') is not None:
                cache_version = cache.get('version')
                stale = cache_version != CACHE_VERSION
                if stale:
                    threading.Thread(target=scanner.refresh, daemon=True).start()
                return web.json_response({
                    'success': True,
                    'nodes': cache.get('nodes', []),
                    'scanned_at': cache.get('scanned_at'),
                    'total': len(cache.get('nodes', [])),
                    'cache_used': True,
                    'cache_stale': stale
                })
        loop = asyncio.get_event_loop()
        nodes = await loop.run_in_executor(None, lambda: scanner.scan(use_cache=True))
        
        from datetime import datetime
        return web.json_response({
            'success': True,
            'nodes': nodes,
            'scanned_at': datetime.now().isoformat(),
            'total': len(nodes)
        })
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)


async def api_refresh_nodes(request):
    """Force refresh the node list"""
    try:
        scanner = get_scanner()
        loop = asyncio.get_event_loop()
        nodes = await loop.run_in_executor(None, scanner.refresh)
        
        from datetime import datetime
        return web.json_response({
            'success': True,
            'nodes': nodes,
            'scanned_at': datetime.now().isoformat(),
            'total': len(nodes)
        })
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)


async def api_update_node(request):
    """Update a specific node via git pull"""
    try:
        folder_name = request.match_info.get('folder_name', '')
        ok, folder_name = safe_node_name(folder_name)
        if not ok:
            return web.json_response({'success': False, 'message': folder_name}, status=400)
        
        git = get_git()
        loop = asyncio.get_event_loop()
        success, message = await loop.run_in_executor(None, git.pull_updates, folder_name)
        
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
        
        if not valid_git_url(url):
            return web.json_response({'success': False, 'message': 'Invalid git URL'}, status=400)
        if folder_name:
            ok, folder_name = safe_node_name(folder_name)
            if not ok:
                return web.json_response({'success': False, 'message': folder_name}, status=400)
        
        git = get_git()
        pip = get_pip()
        scanner = get_scanner()
        loop = asyncio.get_event_loop()
        
        # Clone repository
        success, message = await loop.run_in_executor(None, git.clone_repo, url, folder_name)
        
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
                pip_success, pip_msg = await loop.run_in_executor(
                    None, pip.install_requirements, str(scanner.custom_nodes_path / folder_name)
                )
                if not pip_success:
                    message += f" (Warning: {pip_msg})"
        
        # Refresh cache
        await loop.run_in_executor(None, scanner.refresh)
        
        return web.json_response({'success': True, 'message': message, 'folder_name': folder_name})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)


async def api_open_folder(request):
    """Open node folder in file explorer"""
    try:
        folder_name = request.match_info.get('folder_name', '')
        scanner = get_scanner()
        folder_path, err = scanner._safe_node_path(folder_name)
        if folder_path is None:
            return web.json_response({'success': False, 'message': err}, status=400)
        
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
        loop = asyncio.get_event_loop()
        success, message = await loop.run_in_executor(None, scanner.remove_node, folder_name)
        
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
        loop = asyncio.get_event_loop()
        success, message = await loop.run_in_executor(None, scanner.deactivate_node, folder_name)
        
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
        loop = asyncio.get_event_loop()
        success, message = await loop.run_in_executor(None, scanner.activate_node, folder_name)
        
        return web.json_response({'success': success, 'message': message})
    except Exception as e:
        return web.json_response({'success': False, 'message': str(e)}, status=500)


async def serve_web_file(request):
    """Serve static files from the web directory"""
    filename = request.match_info.get('filename', 'index.html')
    if not filename:
        filename = 'index.html'
    
    web_dir = (Path(__file__).parent / 'web').resolve()
    file_path = resolve_under(web_dir, *Path(filename).parts) if filename else web_dir / 'index.html'
    if file_path is None:
        return web.Response(status=403, text='Forbidden')
    
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

    @web.middleware
    async def _mf_local_only(request, handler):
        if request.path.startswith('/mf_conductor/api'):
            if not is_local_request(request):
                return web.json_response({
                    'success': False,
                    'message': 'MF Conductor API is localhost-only',
                }, status=403)
            if request.method == 'POST' and request.content_type != 'application/json':
                return web.json_response({
                    'success': False,
                    'message': 'Content-Type must be application/json',
                }, status=415)
        return await handler(request)

    try:
        server.PromptServer.instance.app.middlewares.insert(0, _mf_local_only)
    except Exception:
        try:
            server.PromptServer.instance.app.middlewares.append(_mf_local_only)
        except Exception as e:
            print(f"[MF Conductor] Localhost middleware failed; API routes not registered: {e}")
            raise
    
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
            scanner = get_scanner()
            folder_path, err = scanner._safe_node_path(folder_name)
            if folder_path is None:
                return web.json_response({'success': False, 'message': err, 'requirements': []}, status=400)
            
            # get_node_requirements imported at module level
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
            if apply_enabled_folders is None or folders_for_profile is None:
                return web.json_response({'success': False, 'message': 'Isolation is not available'}, status=500)

            scanner = get_scanner()

            def _apply():
                results = apply_enabled_folders(
                    scanner,
                    folders_for_profile(profile, scanner.list_folder_names()),
                )
                if not results['errors']:
                    persist_blocked_packages(profile.get('excluded_packages') or [])
                return results

            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, _apply)
            if results['errors']:
                return web.json_response({'success': False, 'message': '; '.join(results['errors']), 'results': results})
            return web.json_response({'success': True, 'results': results})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/profiles/launch')
    async def _mnf_launch_profile(request):
        try:
            data = await request.json()
            name = data.get('name', '')
            user_data = get_user_data()
            profile = user_data.get_profile(name)
            if not profile:
                return web.json_response({'success': False, 'message': 'Profile not found'})
            if apply_enabled_folders is None or folders_for_profile is None:
                return web.json_response({'success': False, 'message': 'Isolation is not available'}, status=500)

            scanner = get_scanner()

            def _apply():
                results = apply_enabled_folders(
                    scanner,
                    folders_for_profile(profile, scanner.list_folder_names()),
                )
                if not results['errors']:
                    persist_blocked_packages(profile.get('excluded_packages') or [])
                return results

            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, _apply)
            if results['errors']:
                return web.json_response({'success': False, 'message': '; '.join(results['errors']), 'results': results})
            return web.json_response({
                'success': True,
                'launched': False,
                'message': f'Applied profile "{name}". Restart ComfyUI to load the isolated node set and excluded packages.',
                'results': results,
            })
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

    @routes.post('/mf_conductor/api/profiles/clear-default')
    async def _mnf_clear_default_profile(request):
        try:
            user_data = get_user_data()
            profiles = user_data.get_profiles()
            for profile in profiles.values():
                profile['is_default'] = False
            user_data._profiles = profiles
            user_data._save_json(user_data.profiles_file, profiles)
            return web.json_response({'success': True, 'message': 'Default profile cleared'})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)

    @routes.post('/mf_conductor/api/profiles/load-presets')
    async def _mnf_load_preset_profiles(request):
        try:
            user_data = get_user_data()
            count = user_data.load_preset_profiles()
            return web.json_response({'success': True, 'message': f'Loaded {count} preset profiles', 'count': count})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)

    # ==================== WORKFLOWS ====================

    def _mnf_workflow_analyzer():
        if get_workflow_analyzer is None:
            raise RuntimeError('workflow_analyzer module not loaded')
        scanner = get_scanner()
        comfy_root = Path(__file__).parent.parent.parent
        return get_workflow_analyzer(comfy_root, scanner)

    def _mnf_installed_nodes(allow_scan=False):
        scanner = get_scanner()
        cached = scanner.get_cached_nodes(allow_stale=True)
        if cached and cached.get('nodes'):
            return cached['nodes']
        if not allow_scan:
            return []
        return scanner.scan(use_cache=True) or []

    @routes.get('/mf_conductor/api/workflows/launch-options')
    async def _mnf_workflow_launch_options(request):
        return web.json_response(workflow_launch_options(get_scanner(), get_user_data()))

    @routes.get('/mf_conductor/api/workflows')
    async def _mnf_list_workflows(request):
        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None, lambda: _mnf_workflow_analyzer().list_workflows(_mnf_installed_nodes())
            )
            return web.json_response(data)
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)

    @routes.get('/mf_conductor/api/workflows/analyze')
    async def _mnf_analyze_workflow(request):
        try:
            rel_path = request.query.get('path', '')
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None, lambda: _mnf_workflow_analyzer().analyze(rel_path, _mnf_installed_nodes(True), True)
            )
            return web.json_response(data)
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)

    @routes.post('/mf_conductor/api/workflows/resolve-missing')
    async def _mnf_resolve_missing(request):
        try:
            if resolve_missing_packs is None:
                return web.json_response({'success': False, 'message': 'browse_nodes module not loaded'}, status=500)
            data = await request.json()
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, resolve_missing_packs, data.get('names') or [])
            return web.json_response(result)
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)

    @routes.post('/mf_conductor/api/workflows/install-missing')
    async def _mnf_install_missing(request):
        try:
            if install_missing_packs is None:
                return web.json_response({'success': False, 'message': 'browse_nodes module not loaded'}, status=500)
            data = await request.json()

            def _install():
                result = install_missing_packs(
                    get_git(), get_pip(), get_scanner(), data.get('names') or []
                )
                get_scanner().refresh()
                _mnf_workflow_analyzer().reset_maps()
                return result

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _install)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)

    @routes.post('/mf_conductor/api/workflows/apply')
    async def _mnf_apply_workflow(request):
        try:
            data = await request.json()
            rel_path = data.get('path', '')
            if apply_enabled_folders is None:
                return web.json_response({'success': False, 'message': 'workflow_analyzer module not loaded'}, status=500)

            def _apply():
                paths = normalize_workflow_paths(rel_path, data.get('paths')) if normalize_workflow_paths else ([rel_path] if rel_path else [])
                if not paths:
                    return {'success': False, 'message': 'Workflow path is required'}
                batch = _mnf_workflow_analyzer().analyze_many(paths, _mnf_installed_nodes(True), False)
                if not batch.get('success'):
                    return batch
                required = []
                last = None
                for analysis in batch.get('analyses') or []:
                    last = analysis
                    required.extend(analysis.get('required_folders') or [])
                if persist_pending_workflow:
                    persist_pending_workflow(paths[0], paths)
                enabled = folders_for_workflow_launch({'required_folders': required}, get_scanner().list_folder_names())
                results = apply_enabled_folders(get_scanner(), enabled)
                _mnf_persist_default_blocks()
                return {'success': True, 'results': results, 'analysis': last, 'paths': paths}

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _apply)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)

    def _mnf_persist_default_blocks():
        user_data = get_user_data()
        for profile in user_data.get_profiles().values():
            if profile.get('is_default'):
                persist_blocked_packages(profile.get('excluded_packages') or [])
                return
        persist_blocked_packages([])

    @routes.post('/mf_conductor/api/workflows/launch')
    async def _mnf_launch_workflow(request):
        """Integrated mode cannot spawn ComfyUI; apply isolation for the next restart."""
        try:
            data = await request.json()
            selected_profile = get_user_data().get_profile(data.get('profile', '')) or {}
            flags = parse_launch_flags(data['launch_flags']) if 'launch_flags' in data else build_profile_args(selected_profile)
            rel_path = data.get('path', '')
            if apply_enabled_folders is None:
                return web.json_response({'success': False, 'message': 'workflow_analyzer module not loaded'}, status=500)

            def _apply():
                paths = normalize_workflow_paths(rel_path, data.get('paths')) if normalize_workflow_paths else ([rel_path] if rel_path else [])
                if not paths:
                    return {'success': False, 'message': 'Workflow path is required'}
                batch = _mnf_workflow_analyzer().analyze_many(paths, _mnf_installed_nodes(True), False)
                if not batch.get('success'):
                    return batch
                required = []
                last = None
                for analysis in batch.get('analyses') or []:
                    last = analysis
                    required.extend(analysis.get('required_folders') or [])
                enabled = folders_for_workflow_launch({'required_folders': required}, get_scanner().list_folder_names(), data.get('extra_nodes') or [])
                results = apply_enabled_folders(get_scanner(), enabled)
                if results['errors']:
                    return {'success': False, 'message': '; '.join(results['errors']), 'results': results}
                persist_blocked_packages(selected_profile.get('excluded_packages') or [])
                launcher = write_profile_launcher(MF_CONDUCTOR_DIR, 'Workflow launch', {
                    'enabled': enabled, 'excluded_packages': selected_profile.get('excluded_packages') or [],
                }, flags)
                if persist_pending_workflow:
                    persist_pending_workflow(paths[0], paths)
                return {
                    'success': True,
                    'applied': True,
                    'launched': False,
                    'results': results,
                    'analysis': last,
                    'paths': paths,
                    'launcher_path': str(launcher.with_suffix('.bat' if os.name == 'nt' else '.sh')),
                    'flags': flags,
                    'message': 'Selection applied. Stop ComfyUI, then run the generated Workflow launch file to use these flags.',
                }

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _apply)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)

    @routes.get('/mf_conductor/api/workflows/pending')
    async def _mnf_pending_workflow(request):
        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None, lambda: _mnf_workflow_analyzer().pending_workflow_payload()
            )
            return web.json_response(data)
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)

    @routes.post('/mf_conductor/api/workflows/pending/ack')
    async def _mnf_ack_pending_workflow(request):
        try:
            if clear_pending_workflow:
                clear_pending_workflow()
            return web.json_response({'success': True, 'pending': False})
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
    
    # ==================== USAGE ANALYTICS ====================
    
    @routes.get('/mf_conductor/api/usage/stats')
    async def _mnf_usage_stats(request):
        try:
            if get_usage_tracker is None:
                return web.json_response({'success': False, 'message': 'Usage tracker not available'}, status=501)
            
            comfy_root = MF_CONDUCTOR_DIR.parent.parent
            tracker = get_usage_tracker(comfy_root)
            
            # Build node-to-package mapping from installed nodes
            scanner = get_scanner()
            nodes = scanner.scan(use_cache=True)
            tracker.build_node_package_map(nodes)
            
            data = tracker.get_usage_stats()
            return web.json_response({'success': True, **data})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.get('/mf_conductor/api/usage/progress')
    async def _mnf_usage_progress(request):
        try:
            if get_usage_tracker is None:
                return web.json_response({'success': False, 'message': 'Usage tracker not available'}, status=501)
            
            comfy_root = MF_CONDUCTOR_DIR.parent.parent
            tracker = get_usage_tracker(comfy_root)
            progress = tracker.get_scan_progress()
            return web.json_response({'success': True, **progress})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/usage/scan')
    async def _mnf_usage_scan(request):
        try:
            if get_usage_tracker is None:
                return web.json_response({'success': False, 'message': 'Usage tracker not available'}, status=501)
            
            import threading
            data = await request.json()
            
            comfy_root = MF_CONDUCTOR_DIR.parent.parent
            tracker = get_usage_tracker(comfy_root)
            
            # Build node-to-package mapping first
            scanner = get_scanner()
            nodes = scanner.scan(use_cache=True)
            tracker.build_node_package_map(nodes)
            
            # Start scan in background thread
            folders = data.get('folders', None)
            force = data.get('force', False)
            
            def run_scan():
                tracker.scan_workflows(folders, force)
            
            thread = threading.Thread(target=run_scan, daemon=True)
            thread.start()
            
            return web.json_response({'success': True, 'message': 'Scan started'})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/usage/clear')
    async def _mnf_usage_clear(request):
        try:
            if get_usage_tracker is None:
                return web.json_response({'success': False, 'message': 'Usage tracker not available'}, status=501)
            
            comfy_root = MF_CONDUCTOR_DIR.parent.parent
            tracker = get_usage_tracker(comfy_root)
            tracker.clear_data()
            return web.json_response({'success': True, 'message': 'Usage data cleared'})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # ==================== UPDATE CHECKING ====================
    
    @routes.get('/mf_conductor/api/check-updates')
    async def _mnf_check_all_updates(request):
        try:
            scanner = get_scanner()
            loop = asyncio.get_event_loop()
            def _check():
                if not scanner.nodes:
                    scanner.scan(use_cache=True)
                return scanner.batch_check_updates()
            results = await loop.run_in_executor(None, _check)
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
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, scanner.check_for_updates, folder_name)
            return web.json_response({'success': True, 'folder_name': folder_name, **result})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/batch-update')
    async def _mnf_batch_update(request):
        try:
            data = await request.json()
            folder_names = data.get('folder_names')
            scanner = get_scanner()
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, scanner.batch_update, folder_names)
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
            loop = asyncio.get_event_loop()
            def _calc():
                if not scanner.nodes:
                    scanner.scan(use_cache=True)
                results = {}
                total_size = 0
                for node in scanner.nodes:
                    usage = scanner.get_disk_usage(node.folder_name)
                    results[node.folder_name] = usage
                    total_size += usage['size_bytes']
                return results, total_size
            results, total_size = await loop.run_in_executor(None, _calc)
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
            loop = asyncio.get_event_loop()
            usage = await loop.run_in_executor(None, scanner.get_disk_usage, folder_name)
            return web.json_response({'success': True, **usage})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # ==================== GIT HISTORY ====================
    
    @routes.get('/mf_conductor/api/nodes/{folder_name}/git-log')
    async def _mnf_get_git_log(request):
        try:
            folder_name = request.match_info.get('folder_name', '')
            count = int(request.query.get('count', '10'))
            scanner = get_scanner()
            loop = asyncio.get_event_loop()
            commits = await loop.run_in_executor(None, scanner.get_git_log, folder_name, count)
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
            loop = asyncio.get_event_loop()
            success, message = await loop.run_in_executor(None, scanner.rollback_node, folder_name, commit_hash)
            return web.json_response({'success': success, 'message': message})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # ==================== BROKEN NODES ====================
    
    @routes.get('/mf_conductor/api/broken-nodes')
    async def _mnf_detect_broken_nodes(request):
        try:
            scanner = get_scanner()
            loop = asyncio.get_event_loop()
            def _detect():
                if not scanner.nodes:
                    scanner.scan(use_cache=True)
                return scanner.detect_broken_nodes()
            broken = await loop.run_in_executor(None, _detect)
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
            except Exception:
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
        import aiohttp
        
        try:
            try:
                pip = get_pip()
                python_path = pip.python_path if pip else None
            except Exception:
                python_path = None
            
            if not python_path:
                import sys
                python_path = sys.executable
            
            # Step 1: Get installed packages list (fast)
            proc = await asyncio.create_subprocess_exec(
                python_path, '-m', 'pip', 'list', '--format=json',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            
            if proc.returncode != 0:
                return web.json_response({
                    'success': False,
                    'message': 'Failed to get installed packages list'
                }, status=500)
            
            installed_packages = json_module.loads(stdout.decode()) if stdout.decode().strip() else []
            if not installed_packages:
                return web.json_response({'success': True, 'updates': []})
            
            connector = aiohttp.TCPConnector(limit=10)
            async with aiohttp.ClientSession(connector=connector) as shared_session:
                async def check_with_session(pkg_info):
                    package_name = pkg_info.get('name', '').lower()
                    current_version = pkg_info.get('version', '')
                    if not valid_pip_package(package_name) or not current_version or current_version.startswith('file://'):
                        return None
                    try:
                        url = f'https://pypi.org/pypi/{package_name}/json'
                        async with shared_session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as response:
                            if response.status == 404:
                                return None
                            pdata = await response.json()
                            latest_version = pdata.get('info', {}).get('version', '')
                            if latest_version and latest_version != current_version:
                                try:
                                    from packaging import version
                                    if version.parse(latest_version) > version.parse(current_version):
                                        return {
                                            'name': package_name,
                                            'current_version': current_version,
                                            'latest_version': latest_version,
                                        }
                                except (ImportError, ValueError, TypeError):
                                    if latest_version > current_version:
                                        return {
                                            'name': package_name,
                                            'current_version': current_version,
                                            'latest_version': latest_version,
                                        }
                    except (aiohttp.ClientError, asyncio.TimeoutError, Exception):
                        return None
                    return None

                tasks = [check_with_session(pkg) for pkg in installed_packages]
                results = await asyncio.gather(*tasks, return_exceptions=True)
            
            updates = [r for r in results if r and not isinstance(r, Exception)]
            
            return web.json_response({'success': True, 'updates': updates})
            
        except asyncio.TimeoutError:
            return web.json_response({'success': False, 'message': 'Timeout checking updates'}, status=500)
        except Exception as e:
            print(f"[MF_Conductor] Error checking package updates: {e}")
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/packages/check-single')
    async def _mnf_check_single_package_update(request):
        import asyncio
        import aiohttp
        
        try:
            data = await request.json()
            package_name = data.get('package_name', '')
            
            if not valid_pip_package(package_name):
                return web.json_response({'success': False, 'message': 'Invalid package name'}, status=400)
            
            try:
                pip = get_pip()
                python_path = pip.python_path if pip else None
            except Exception:
                python_path = None
            
            if not python_path:
                import sys
                python_path = sys.executable
            
            # Get current installed version
            proc = await asyncio.create_subprocess_exec(
                python_path, '-m', 'pip', 'show', package_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
            
            current_version = 'unknown'
            if proc.returncode == 0:
                for line in stdout.decode().split('\n'):
                    if line.startswith('Version:'):
                        current_version = line.split(':', 1)[1].strip()
                        break
            
            # Check PyPI for available versions
            try:
                url = f'https://pypi.org/pypi/{package_name}/json'
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                        if response.status == 404:
                            return web.json_response({
                                'success': True,
                                'name': package_name,
                                'current_version': current_version,
                                'latest_version': current_version,
                                'has_update': False,
                                'available_versions': []
                            })
                        
                        pypi_data = await response.json()
                        latest_version = pypi_data.get('info', {}).get('version', current_version)
                        
                        # Get available versions newer than current
                        available_versions = []
                        releases = pypi_data.get('releases', {})
                        
                        try:
                            from packaging import version as pkg_version
                            current_parsed = pkg_version.parse(current_version) if current_version != 'unknown' else None
                            
                            for ver in releases.keys():
                                try:
                                    ver_parsed = pkg_version.parse(ver)
                                    if current_parsed and ver_parsed > current_parsed:
                                        if releases[ver]:  # Has files
                                            available_versions.append(ver)
                                except (ValueError, TypeError, KeyError):
                                    continue
                            
                            available_versions.sort(key=lambda v: pkg_version.parse(v), reverse=True)
                        except (ImportError, ValueError, KeyError):
                            if latest_version != current_version:
                                available_versions = [latest_version]
                        
                        # Limit to 10 most recent
                        available_versions = available_versions[:10]
                        
                        # Check if update available
                        has_update = False
                        if latest_version and latest_version != 'unknown' and latest_version != current_version:
                            try:
                                from packaging import version
                                has_update = version.parse(latest_version) > version.parse(current_version)
                            except (ImportError, ValueError, TypeError):
                                has_update = latest_version > current_version
                        
                        return web.json_response({
                            'success': True,
                            'name': package_name,
                            'current_version': current_version,
                            'latest_version': latest_version,
                            'has_update': has_update,
                            'available_versions': available_versions
                        })
            except Exception as pypi_error:
                return web.json_response({
                    'success': True,
                    'name': package_name,
                    'current_version': current_version,
                    'latest_version': current_version,
                    'has_update': False,
                    'available_versions': []
                })
                
        except asyncio.TimeoutError:
            return web.json_response({'success': False, 'message': 'Check timed out'}, status=500)
        except Exception as e:
            print(f"[MF_Conductor] Error checking single package: {e}")
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/packages/install')
    async def _mnf_install_package(request):
        import asyncio
        
        try:
            data = await request.json()
            package_name = data.get('package_name', '')
            
            if not valid_pip_package(package_name):
                return web.json_response({'success': False, 'message': 'Invalid package name'}, status=400)
            
            try:
                pip = get_pip()
                python_path = pip.python_path if pip else None
            except Exception:
                python_path = None
            
            if not python_path:
                import sys
                python_path = sys.executable
            
            proc = await asyncio.create_subprocess_exec(
                python_path, '-m', 'pip', 'install', package_name.strip(),
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

    @routes.post('/mf_conductor/api/install-package')
    async def _mnf_install_package_alias(request):
        return await _mnf_install_package(request)
    
    @routes.post('/mf_conductor/api/packages/uninstall')
    async def _mnf_uninstall_package(request):
        import asyncio
        
        try:
            data = await request.json()
            package_name = data.get('package_name', '')
            
            if not valid_pip_package(package_name):
                return web.json_response({'success': False, 'message': 'Invalid package name'}, status=400)
            
            try:
                pip = get_pip()
                python_path = pip.python_path if pip else None
            except Exception:
                python_path = None
            
            if not python_path:
                import sys
                python_path = sys.executable
            
            proc = await asyncio.create_subprocess_exec(
                python_path, '-m', 'pip', 'uninstall', '-y', package_name.strip(),
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
            version = data.get('version', None)
            
            if not valid_pip_package(package_name) or not valid_pip_version(version or ''):
                return web.json_response({'success': False, 'message': 'Invalid package name or version'}, status=400)
            
            try:
                pip = get_pip()
                python_path = pip.python_path if pip else None
            except Exception:
                python_path = None
            
            if not python_path:
                import sys
                python_path = sys.executable
            
            # Build package spec with optional version
            package_spec = f'{package_name}=={version}' if version else package_name
            
            proc = await asyncio.create_subprocess_exec(
                python_path, '-m', 'pip', 'install', '--upgrade', package_spec,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            
            if proc.returncode == 0:
                refresh_installed_packages()
                version_msg = f' to {version}' if version else ''
                return web.json_response({'success': True, 'message': f'Successfully upgraded {package_name}{version_msg}'})
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
            
            if not valid_pip_package(package_name):
                return web.json_response({'success': False, 'message': 'Invalid package name'}, status=400)
            
            try:
                pip = get_pip()
                python_path = pip.python_path if pip else None
            except Exception:
                python_path = None
            
            if not python_path:
                import sys
                python_path = sys.executable
            
            proc = await asyncio.create_subprocess_exec(
                python_path, '-m', 'pip', 'install', '--force-reinstall', '--no-deps', package_name.strip(),
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
    
    @routes.get('/mf_conductor/api/system/desktop-path')
    async def _mnf_desktop_path(request):
        """Get the user's Desktop path for shortcut creation"""
        desktop = str(Path.home() / 'Desktop')
        return web.json_response({'success': True, 'path': desktop})
    
    @routes.post('/mf_conductor/api/system/save-dialog')
    async def _mnf_save_dialog(request):
        """Show a native Windows save file dialog"""
        try:
            import subprocess
            data = await request.json()
            suggested_name = data.get('suggested_name', 'shortcut.lnk')
            suggested_name = Path(str(suggested_name)).name
            if not suggested_name.endswith('.lnk'):
                suggested_name = 'shortcut.lnk'
            
            desktop = str(Path.home() / 'Desktop')
            ps_desktop = escape_ps_string(desktop)
            ps_name = escape_ps_string(suggested_name)
            ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.SaveFileDialog
$dialog.InitialDirectory = "{ps_desktop}"
$dialog.Filter = "Windows Shortcut (*.lnk)|*.lnk"
$dialog.FileName = "{ps_name}"
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
                return web.json_response({'success': False, 'cancelled': True})
            else:
                return web.json_response({'success': True, 'path': output})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
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
        """Command execution is not allowed in integrated mode"""
        return web.json_response({
            'success': False,
            'message': 'Command execution is disabled in integrated mode. Use standalone mode instead.'
        }, status=403)
    
    # ==================== SHORTCUT CREATION ====================
    
    @routes.post('/mf_conductor/api/shortcuts/conductor')
    async def _mnf_create_conductor_shortcut(request):
        """Create a shortcut to launch MF Conductor standalone server"""
        try:
            data = await request.json()
            save_path = data.get('save_path')
            conductor_dir = Path(__file__).parent
            target = conductor_dir / ('Launch_MFConductor.bat' if os.name == 'nt' else 'Launch_MFConductor.sh')
            dest, err = write_desktop_shortcut(
                save_path,
                str(target),
                str(conductor_dir),
                'MF Conductor',
                'Launch MF Conductor - ComfyUI Control Center',
                conductor_dir / 'web' / 'mfconductor_logo.ico',
            )
            if dest is None:
                return web.json_response({'success': False, 'message': err}, status=400)
            return web.json_response({'success': True, 'message': f'Shortcut created at {dest}', 'path': str(dest)})
        except Exception as e:
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    @routes.post('/mf_conductor/api/shortcuts/profile')
    async def _mnf_create_profile_shortcut(request):
        """Create a shortcut that launches ComfyUI with a specific profile"""
        try:
            data = await request.json()
            profile_name = data.get('profile_name', '')
            save_path = data.get('save_path')
            if not profile_name:
                return web.json_response({'success': False, 'message': 'Profile name is required'}, status=400)
            
            user_data = get_user_data()
            profiles = user_data.get_profiles()
            if profile_name not in profiles:
                return web.json_response({'success': False, 'message': f'Profile "{profile_name}" not found'})
            
            profile = profiles[profile_name]
            try:
                args = build_profile_args(profile)
            except ValueError as e:
                return web.json_response({'success': False, 'message': str(e)}, status=400)
            
            conductor_dir = Path(__file__).parent
            launcher_script = write_profile_launcher(conductor_dir, profile_name, profile, args)
            target = launcher_script.with_suffix('.bat' if os.name == 'nt' else '.sh')
            dest, err = write_desktop_shortcut(
                save_path,
                str(target),
                str(conductor_dir.parent.parent),
                f'ComfyUI - {profile_name}',
                f'Launch ComfyUI with {profile_name} profile',
                conductor_dir / 'web' / 'mfconductor_logo.ico',
            )
            if dest is None:
                return web.json_response({'success': False, 'message': err}, status=400)
            return web.json_response({
                'success': True,
                'message': f'Shortcut created at {dest}',
                'path': str(dest),
                'launcher_path': str(launcher_script),
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            return web.json_response({'success': False, 'message': str(e)}, status=500)
    
    # Serve static files from web directory
    @routes.get('/mf_conductor/{filename:.*}')
    async def _mnf_serve_static(request):
        filename = request.match_info.get('filename', 'index.html')
        if not filename:
            filename = 'index.html'
        
        web_dir = (Path(__file__).parent / 'web').resolve()
        file_path = resolve_under(web_dir, *Path(filename).parts)
        if file_path is None:
            return aiohttp_web.Response(status=403, text='Forbidden')
        
        if not file_path.exists():
            index_path = resolve_under(web_dir, *Path(filename).parts, 'index.html') if filename else None
            if index_path is not None and index_path.exists():
                file_path = index_path
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
    
    # ==================== FILES API (Integrated Mode Stubs) ====================
    # Files feature is only available in standalone mode
    
    @routes.get('/mf_conductor/api/files')
    async def _mnf_files_list(request):
        """Files browser not available in integrated mode"""
        return web.json_response({
            'success': False,
            'message': 'File browser is only available in standalone mode. Run Launch_MFConductor.bat instead.',
            'files': [],
            'total': 0,
            'total_size': 0
        })
    
    @routes.get('/mf_conductor/api/files/thumbnail/{folder}/{path:.*}')
    async def _mnf_files_thumbnail(request):
        """File thumbnails not available in integrated mode"""
        return web.json_response({'success': False, 'message': 'Not available in integrated mode'})
    
    @routes.get('/mf_conductor/api/files/workflow/{folder}/{path:.*}')
    async def _mnf_files_workflow(request):
        """File workflow extraction not available in integrated mode"""
        return web.json_response({'success': False, 'message': 'Not available in integrated mode'})
    
    @routes.get('/mf_conductor/api/files/serve/{folder}/{path:.*}')
    async def _mnf_files_serve(request):
        """File serving not available in integrated mode"""
        return web.json_response({'success': False, 'message': 'Not available in integrated mode'})
    
    @routes.post('/mf_conductor/api/files/open-location')
    async def _mnf_files_open_location(request):
        """Open file location not available in integrated mode"""
        return web.json_response({'success': False, 'message': 'Not available in integrated mode'})
    
    @routes.post('/mf_conductor/api/files/delete')
    async def _mnf_files_delete(request):
        """File deletion not available in integrated mode"""
        return web.json_response({'success': False, 'message': 'Not available in integrated mode'})
    
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

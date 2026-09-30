"""
MF_Conductor - User Data Management
Handles favorites, tags, notes, profiles, and user preferences
"""

import json
import os
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Iterable


REQUIRED_NODES = {
    'ComfyUI_MFConductor',
    'ComfyUI-Manager',
    'ComfyUI-MediaFrisk',
    'ComfyUI-ModelFrisk',
    'ComfyUI-Crystools',
}


def is_required_node_folder(folder_name: str) -> bool:
    key = str(folder_name or '').removesuffix('.disabled').strip().lower()
    return key in {name.lower() for name in REQUIRED_NODES}


def required_folder_keys() -> set:
    return {name.lower() for name in REQUIRED_NODES}


def merge_required_folders(folders: Iterable[str], all_folders: Optional[Iterable[str]] = None) -> List[str]:
    """Keep user folders and always append required packs that exist on disk."""
    merged = []
    seen = set()
    for name in folders or []:
        base = str(name).removesuffix('.disabled').strip()
        if not base:
            continue
        key = base.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(base)
    known = None
    if all_folders is not None:
        known = {str(name).removesuffix('.disabled').lower(): str(name).removesuffix('.disabled') for name in all_folders}
    for name in REQUIRED_NODES:
        key = name.lower()
        if key in seen:
            continue
        if known is not None and key not in known:
            continue
        seen.add(key)
        merged.append(known[key] if known else name)
    return merged


class UserDataManager:
    """Manages user preferences and node metadata"""
    
    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path(__file__).parent / 'data'
        
        self.data_dir.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        
        # File paths
        self.favorites_file = self.data_dir / 'favorites.json'
        self.tags_file = self.data_dir / 'tags.json'
        self.notes_file = self.data_dir / 'notes.json'
        self.profiles_file = self.data_dir / 'profiles.json'
        self.settings_file = self.data_dir / 'settings.json'
        self.usage_file = self.data_dir / 'usage.json'
        
        # Load data
        self._favorites: List[str] = self._load_json(self.favorites_file, [])
        self._tags: Dict[str, List[str]] = self._load_json(self.tags_file, {})
        self._notes: Dict[str, str] = self._load_json(self.notes_file, {})
        self._profiles: Dict[str, Dict] = self._load_json(self.profiles_file, {})
        self._settings: Dict[str, Any] = self._load_json(self.settings_file, {
            'theme': 'dark',
            'auto_update': False,
            'show_disk_usage': True
        })
        self._usage: Dict[str, str] = self._load_json(self.usage_file, {})  # folder_name -> last_used ISO date
        
        # Initialize default profiles if none exist
        if not self._profiles:
            self._create_default_profiles()
    
    def _load_json(self, path: Path, default: Any) -> Any:
        """Load JSON file or return default"""
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return default
    
    def _save_json(self, path: Path, data: Any):
        """Save data to JSON file (thread-safe with atomic write)"""
        with self._lock:
            try:
                tmp_path = path.with_suffix('.tmp')
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                tmp_path.replace(path)
            except IOError as e:
                print(f"[MF Conductor] Error saving {path}: {e}")
    
    def _create_default_profiles(self):
        """Create default starter profiles"""
        now = datetime.now().isoformat()
        
        default_profiles = {
            "GPU - Standard": {
                "description": "Standard GPU mode with optimal settings for most graphics cards",
                "avatar": "avatars/gpu-standard.svg",
                "enabled": [],  # Will use all nodes
                "disabled": [],
                "flags": {
                    "vram": "",  # Default VRAM management
                    "attention": ""
                },
                "custom_flags": "",
                "custom_flags_list": [],
                "excluded_packages": [],
                "is_default": True,  # Set this as the default
                "created": now,
                "updated": now
            },
            "GPU - Low VRAM": {
                "description": "For GPUs with 4-6GB VRAM. Uses memory-efficient settings",
                "avatar": "avatars/gpu-lowvram.svg",
                "enabled": [],
                "disabled": [],
                "flags": {
                    "vram": "--lowvram",
                    "attention": ""
                },
                "custom_flags": "",
                "custom_flags_list": [],
                "excluded_packages": [],
                "is_default": False,
                "created": now,
                "updated": now
            },
            "GPU - Very Low VRAM": {
                "description": "For GPUs with 2-4GB VRAM. Maximum memory savings",
                "avatar": "avatars/gpu-verylowvram.svg",
                "enabled": [],
                "disabled": [],
                "flags": {
                    "vram": "--novram",
                    "attention": ""
                },
                "custom_flags": "",
                "custom_flags_list": [],
                "excluded_packages": [],
                "is_default": False,
                "created": now,
                "updated": now
            },
            "GPU - High VRAM": {
                "description": "For GPUs with 12GB+ VRAM. Maximum performance",
                "avatar": "avatars/gpu-highvram.svg",
                "enabled": [],
                "disabled": [],
                "flags": {
                    "vram": "--highvram",
                    "attention": ""
                },
                "custom_flags": "",
                "custom_flags_list": [],
                "excluded_packages": [],
                "is_default": False,
                "created": now,
                "updated": now
            },
            "CPU Only": {
                "description": "Run entirely on CPU. Slow but works without a GPU",
                "avatar": "avatars/cpu-only.svg",
                "enabled": [],
                "disabled": [],
                "flags": {
                    "vram": "--cpu",
                    "attention": ""
                },
                "custom_flags": "",
                "custom_flags_list": [],
                "excluded_packages": [],
                "is_default": False,
                "created": now,
                "updated": now
            },
            "DirectML (AMD/Intel)": {
                "description": "For AMD and Intel GPUs using DirectML backend",
                "avatar": "avatars/directml.svg",
                "enabled": [],
                "disabled": [],
                "flags": {
                    "vram": "--directml",
                    "attention": ""
                },
                "custom_flags": "",
                "custom_flags_list": [],
                "excluded_packages": [],
                "is_default": False,
                "created": now,
                "updated": now
            },
            "Preview Mode": {
                "description": "Fast preview generation with lower quality settings",
                "avatar": "avatars/preview.svg",
                "enabled": [],
                "disabled": [],
                "flags": {
                    "vram": "--lowvram",
                    "preview": "--preview-method auto",
                    "attention": ""
                },
                "custom_flags": "",
                "custom_flags_list": [],
                "excluded_packages": [],
                "is_default": False,
                "created": now,
                "updated": now
            }
        }
        
        self._profiles = default_profiles
        self._save_json(self.profiles_file, self._profiles)
        print("[MF Conductor] Created default profiles")
    
    def load_preset_profiles(self) -> int:
        """Load preset profiles (overwrites existing presets with same names)"""
        now = datetime.now().isoformat()
        
        preset_profiles = {
            "GPU - Standard": {
                "description": "Standard GPU mode with optimal settings for most graphics cards",
                "avatar": "avatars/gpu-standard.svg",
                "enabled": [],
                "disabled": [],
                "flags": {
                    "vram": "",
                    "attention": ""
                },
                "custom_flags": "",
                "custom_flags_list": [],
                "excluded_packages": [],
                "is_default": False,
                "created": now,
                "updated": now
            },
            "GPU - Low VRAM": {
                "description": "For GPUs with 4-6GB VRAM. Uses memory-efficient settings",
                "avatar": "avatars/gpu-lowvram.svg",
                "enabled": [],
                "disabled": [],
                "flags": {
                    "vram": "--lowvram",
                    "attention": ""
                },
                "custom_flags": "",
                "custom_flags_list": [],
                "excluded_packages": [],
                "is_default": False,
                "created": now,
                "updated": now
            },
            "GPU - Very Low VRAM": {
                "description": "For GPUs with 2-4GB VRAM. Maximum memory savings",
                "avatar": "avatars/gpu-verylowvram.svg",
                "enabled": [],
                "disabled": [],
                "flags": {
                    "vram": "--novram",
                    "attention": ""
                },
                "custom_flags": "",
                "custom_flags_list": [],
                "excluded_packages": [],
                "is_default": False,
                "created": now,
                "updated": now
            },
            "GPU - High VRAM": {
                "description": "For GPUs with 12GB+ VRAM. Maximum performance",
                "avatar": "avatars/gpu-highvram.svg",
                "enabled": [],
                "disabled": [],
                "flags": {
                    "vram": "--highvram",
                    "attention": ""
                },
                "custom_flags": "",
                "custom_flags_list": [],
                "excluded_packages": [],
                "is_default": False,
                "created": now,
                "updated": now
            },
            "CPU Only": {
                "description": "Run entirely on CPU. Slow but works without a GPU",
                "avatar": "avatars/cpu-only.svg",
                "enabled": [],
                "disabled": [],
                "flags": {
                    "vram": "--cpu",
                    "attention": ""
                },
                "custom_flags": "",
                "custom_flags_list": [],
                "excluded_packages": [],
                "is_default": False,
                "created": now,
                "updated": now
            },
            "DirectML (AMD/Intel)": {
                "description": "For AMD and Intel GPUs using DirectML backend",
                "avatar": "avatars/directml.svg",
                "enabled": [],
                "disabled": [],
                "flags": {
                    "vram": "--directml",
                    "attention": ""
                },
                "custom_flags": "",
                "custom_flags_list": [],
                "excluded_packages": [],
                "is_default": False,
                "created": now,
                "updated": now
            },
            "Preview Mode": {
                "description": "Fast preview generation with lower quality settings",
                "avatar": "avatars/preview.svg",
                "enabled": [],
                "disabled": [],
                "flags": {
                    "vram": "--lowvram",
                    "preview": "--preview-method auto",
                    "attention": ""
                },
                "custom_flags": "",
                "custom_flags_list": [],
                "excluded_packages": [],
                "is_default": False,
                "created": now,
                "updated": now
            }
        }
        
        # Overwrite preset profiles (keeps user's custom profiles intact)
        count = 0
        for name, profile in preset_profiles.items():
            # Preserve is_default status if the profile already exists
            if name in self._profiles:
                profile['is_default'] = self._profiles[name].get('is_default', False)
            self._profiles[name] = profile
            count += 1
        
        self._save_json(self.profiles_file, self._profiles)
        print(f"[MF Conductor] Loaded {count} preset profiles")
        return count
    
    # ==================== FAVORITES ====================
    
    def get_favorites(self) -> List[str]:
        """Get list of favorite node folder names"""
        return self._favorites.copy()
    
    def is_favorite(self, folder_name: str) -> bool:
        """Check if a node is favorited"""
        return folder_name in self._favorites
    
    def add_favorite(self, folder_name: str) -> bool:
        """Add a node to favorites"""
        if folder_name not in self._favorites:
            self._favorites.append(folder_name)
            self._save_json(self.favorites_file, self._favorites)
            return True
        return False
    
    def remove_favorite(self, folder_name: str) -> bool:
        """Remove a node from favorites"""
        if folder_name in self._favorites:
            self._favorites.remove(folder_name)
            self._save_json(self.favorites_file, self._favorites)
            return True
        return False
    
    def toggle_favorite(self, folder_name: str) -> bool:
        """Toggle favorite status, returns new state"""
        if folder_name in self._favorites:
            self._favorites.remove(folder_name)
            self._save_json(self.favorites_file, self._favorites)
            return False
        else:
            self._favorites.append(folder_name)
            self._save_json(self.favorites_file, self._favorites)
            return True
    
    # ==================== TAGS ====================
    
    def get_all_tags(self) -> List[str]:
        """Get list of all unique tags"""
        all_tags = set()
        for tags in self._tags.values():
            all_tags.update(tags)
        return sorted(list(all_tags))
    
    def get_tags(self, folder_name: str) -> List[str]:
        """Get tags for a specific node"""
        return self._tags.get(folder_name, [])
    
    def set_tags(self, folder_name: str, tags: List[str]) -> None:
        """Set tags for a node"""
        if tags:
            self._tags[folder_name] = tags
        elif folder_name in self._tags:
            del self._tags[folder_name]
        self._save_json(self.tags_file, self._tags)
    
    def add_tag(self, folder_name: str, tag: str) -> None:
        """Add a single tag to a node"""
        if folder_name not in self._tags:
            self._tags[folder_name] = []
        if tag not in self._tags[folder_name]:
            self._tags[folder_name].append(tag)
            self._save_json(self.tags_file, self._tags)
    
    def remove_tag(self, folder_name: str, tag: str) -> None:
        """Remove a tag from a node"""
        if folder_name in self._tags and tag in self._tags[folder_name]:
            self._tags[folder_name].remove(tag)
            if not self._tags[folder_name]:
                del self._tags[folder_name]
            self._save_json(self.tags_file, self._tags)
    
    def get_nodes_by_tag(self, tag: str) -> List[str]:
        """Get all node folder names with a specific tag"""
        return [folder for folder, tags in self._tags.items() if tag in tags]
    
    # ==================== NOTES ====================
    
    def get_note(self, folder_name: str) -> str:
        """Get note for a node"""
        return self._notes.get(folder_name, '')
    
    def set_note(self, folder_name: str, note: str) -> None:
        """Set note for a node"""
        if note:
            self._notes[folder_name] = note
        elif folder_name in self._notes:
            del self._notes[folder_name]
        self._save_json(self.notes_file, self._notes)
    
    def get_all_notes(self) -> Dict[str, str]:
        """Get all notes"""
        return self._notes.copy()
    
    # ==================== PROFILES ====================
    
    def get_profiles(self) -> Dict[str, Dict]:
        """Get all profiles"""
        return self._profiles.copy()
    
    def get_profile(self, name: str) -> Optional[Dict]:
        """Get a specific profile"""
        return self._profiles.get(name)
    
    REQUIRED_NODES = REQUIRED_NODES
    
    def save_profile(self, name: str, enabled_nodes: List[str], disabled_nodes: List[str], 
                     flags: Optional[Dict[str, str]] = None, custom_flags: str = '',
                     custom_flags_list: Optional[List] = None,
                     excluded_packages: Optional[List[str]] = None,
                     description: str = '', avatar: str = 'default.svg') -> None:
        """Save a profile (list of enabled/disabled nodes with optional flags)"""
        required_lower = required_folder_keys()
        if enabled_nodes:
            enabled_set = set(enabled_nodes)
            enabled_set.update(self.REQUIRED_NODES)
            enabled_nodes = list(enabled_set)
        else:
            enabled_nodes = []
        disabled_nodes = [n for n in disabled_nodes if n.lower() not in required_lower]
        
        existing = self._profiles.get(name, {})
        self._profiles[name] = {
            'enabled': enabled_nodes,
            'disabled': disabled_nodes,
            'flags': flags or {},
            'custom_flags': custom_flags,
            'custom_flags_list': custom_flags_list or [],
            'excluded_packages': excluded_packages or [],
            'description': description,
            'avatar': avatar,
            'is_default': existing.get('is_default', False),
            'created': existing.get('created', datetime.now().isoformat()),
            'updated': datetime.now().isoformat()
        }
        self._save_json(self.profiles_file, self._profiles)
    
    def delete_profile(self, name: str) -> bool:
        """Delete a profile"""
        if name in self._profiles:
            del self._profiles[name]
            self._save_json(self.profiles_file, self._profiles)
            return True
        return False
    
    # ==================== USAGE TRACKING ====================
    
    def record_usage(self, folder_name: str) -> None:
        """Record that a node was used"""
        self._usage[folder_name] = datetime.now().isoformat()
        self._save_json(self.usage_file, self._usage)
    
    def get_last_used(self, folder_name: str) -> Optional[str]:
        """Get when a node was last used"""
        return self._usage.get(folder_name)
    
    def get_usage_stats(self) -> Dict[str, str]:
        """Get all usage data"""
        return self._usage.copy()
    
    # ==================== SETTINGS ====================
    
    def get_settings(self) -> Dict[str, Any]:
        """Get all settings"""
        return self._settings.copy()
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a specific setting"""
        return self._settings.get(key, default)
    
    def set_setting(self, key: str, value: Any) -> None:
        """Set a setting"""
        self._settings[key] = value
        self._save_json(self.settings_file, self._settings)
    
    # ==================== BACKUP/RESTORE ====================
    
    def export_backup(self) -> Dict[str, Any]:
        """Export all user data as a backup"""
        return {
            'version': '1.0',
            'exported_at': datetime.now().isoformat(),
            'favorites': self._favorites,
            'tags': self._tags,
            'notes': self._notes,
            'profiles': self._profiles,
            'settings': self._settings,
            'usage': self._usage
        }
    
    def import_backup(self, data: Dict[str, Any], merge: bool = False) -> bool:
        """Import user data from backup"""
        try:
            if merge:
                # Merge with existing data
                self._favorites = list(set(self._favorites + data.get('favorites', [])))
                for folder, tags in data.get('tags', {}).items():
                    existing = self._tags.get(folder, [])
                    self._tags[folder] = list(set(existing + tags))
                self._notes.update(data.get('notes', {}))
                self._profiles.update(data.get('profiles', {}))
                self._settings.update(data.get('settings', {}))
                self._usage.update(data.get('usage', {}))
            else:
                # Replace all data
                self._favorites = data.get('favorites', [])
                self._tags = data.get('tags', {})
                self._notes = data.get('notes', {})
                self._profiles = data.get('profiles', {})
                self._settings = data.get('settings', {})
                self._usage = data.get('usage', {})
            
            # Save all
            self._save_json(self.favorites_file, self._favorites)
            self._save_json(self.tags_file, self._tags)
            self._save_json(self.notes_file, self._notes)
            self._save_json(self.profiles_file, self._profiles)
            self._save_json(self.settings_file, self._settings)
            self._save_json(self.usage_file, self._usage)
            
            return True
        except Exception as e:
            print(f"[MF Conductor] Error importing backup: {e}")
            return False
    
    def export_node_list(self, nodes: List[Dict]) -> Dict[str, Any]:
        """Export list of installed nodes (for reinstallation)"""
        node_list = []
        for node in nodes:
            node_list.append({
                'folder_name': node.get('folder_name'),
                'git_url': node.get('git_url'),
                'display_name': node.get('display_name'),
                'author': node.get('author')
            })
        
        return {
            'version': '1.0',
            'exported_at': datetime.now().isoformat(),
            'node_count': len(node_list),
            'nodes': node_list
        }


# Global instance
_user_data: Optional[UserDataManager] = None


def get_user_data() -> UserDataManager:
    """Get global UserDataManager instance"""
    global _user_data
    if _user_data is None:
        _user_data = UserDataManager()
    return _user_data




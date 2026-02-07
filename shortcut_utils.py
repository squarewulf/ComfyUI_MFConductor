"""
MF_Conductor - Cross-Platform Shortcut Utilities
Creates desktop shortcuts on Windows, Linux, and macOS
"""

import os
import sys
import stat
import subprocess
from pathlib import Path
from typing import Optional, Tuple


class ShortcutCreator:
    """Cross-platform shortcut creator"""
    
    def __init__(self):
        self.platform = sys.platform
        self.conductor_dir = Path(__file__).parent
        self.comfy_root = self.conductor_dir.parent.parent
    
    def get_desktop_path(self) -> Path:
        """Get the user's desktop path"""
        if self.platform == 'win32':
            return Path.home() / 'Desktop'
        elif self.platform == 'darwin':
            return Path.home() / 'Desktop'
        else:
            # Linux - check XDG_DESKTOP_DIR first
            xdg_config = Path.home() / '.config' / 'user-dirs.dirs'
            if xdg_config.exists():
                try:
                    with open(xdg_config, 'r') as f:
                        for line in f:
                            if line.startswith('XDG_DESKTOP_DIR'):
                                path = line.split('=')[1].strip().strip('"')
                                path = path.replace('$HOME', str(Path.home()))
                                return Path(path)
                except:
                    pass
            return Path.home() / 'Desktop'
    
    def create_conductor_shortcut(self, save_path: str, avatar: str = 'default') -> Tuple[bool, str]:
        """
        Create a shortcut to launch MF Conductor standalone
        
        Args:
            save_path: Full path where to save the shortcut
            avatar: Avatar name for the icon
            
        Returns:
            Tuple of (success, message)
        """
        try:
            save_path = Path(save_path)
            
            if self.platform == 'win32':
                return self._create_windows_shortcut_conductor(save_path, avatar)
            elif self.platform == 'darwin':
                return self._create_macos_shortcut_conductor(save_path, avatar)
            else:
                return self._create_linux_shortcut_conductor(save_path, avatar)
        except Exception as e:
            return False, str(e)
    
    def create_profile_shortcut(self, profile_name: str, save_path: str, 
                                 profile_data: dict) -> Tuple[bool, str]:
        """
        Create a shortcut to launch ComfyUI with a specific profile
        
        Args:
            profile_name: Name of the profile
            save_path: Full path where to save the shortcut
            profile_data: Profile configuration data
            
        Returns:
            Tuple of (success, message)
        """
        try:
            save_path = Path(save_path)
            
            if self.platform == 'win32':
                return self._create_windows_shortcut_profile(profile_name, save_path, profile_data)
            elif self.platform == 'darwin':
                return self._create_macos_shortcut_profile(profile_name, save_path, profile_data)
            else:
                return self._create_linux_shortcut_profile(profile_name, save_path, profile_data)
        except Exception as e:
            return False, str(e)
    
    # ==================== WINDOWS ====================
    
    def _create_windows_shortcut_conductor(self, save_path: Path, avatar: str) -> Tuple[bool, str]:
        """Create Windows .lnk shortcut for MF Conductor"""
        bat_file = self.conductor_dir / 'Launch_MFConductor.bat'
        icon_path = self.conductor_dir / 'web' / 'mfconductor_logo.ico'
        
        icon_line = f'$Shortcut.IconLocation = "{icon_path}"' if icon_path.exists() else ''
        
        ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{save_path}")
$Shortcut.TargetPath = "{bat_file}"
$Shortcut.WorkingDirectory = "{self.conductor_dir}"
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
            return True, f'Shortcut created at {save_path}'
        else:
            return False, f'PowerShell error: {result.stderr}'
    
    def _create_windows_shortcut_profile(self, profile_name: str, save_path: Path, 
                                          profile_data: dict) -> Tuple[bool, str]:
        """Create Windows .lnk shortcut for a profile"""
        # Create a Python launcher script
        safe_filename = "".join(c for c in profile_name if c.isalnum() or c in (' ', '-', '_')).strip()
        launcher_script = self.conductor_dir / 'data' / f'launch_{safe_filename}.py'
        
        enabled_nodes = profile_data.get('enabled', [])
        disabled_nodes = profile_data.get('disabled', [])
        flags = profile_data.get('flags', {})
        custom_flags_list = profile_data.get('custom_flags_list', [])
        
        # Build command line args
        comfy_args = []
        for flag_value in flags.values():
            if flag_value:
                comfy_args.extend(flag_value.split())
        for flag in custom_flags_list:
            if flag.get('enabled') and flag.get('value'):
                comfy_args.extend(flag['value'].split())
        
        # Find Python path
        portable_root = self.comfy_root.parent
        python_path = portable_root / 'python_embeded' / 'python.exe'
        if not python_path.exists():
            python_path = sys.executable
        
        launcher_content = f'''#!/usr/bin/env python
"""MF Conductor Profile Launcher - {profile_name}"""
import os
import sys
import subprocess
from pathlib import Path

PROFILE_NAME = {repr(profile_name)}
ENABLED_NODES = {repr(enabled_nodes)}
DISABLED_NODES = {repr(disabled_nodes)}
COMFY_ARGS = {repr(comfy_args)}

def apply_node_states(custom_nodes_path):
    """Enable/disable nodes for this profile"""
    for folder_name in ENABLED_NODES:
        disabled_path = custom_nodes_path / f"{{folder_name}}.disabled"
        enabled_path = custom_nodes_path / folder_name
        if disabled_path.exists() and not enabled_path.exists():
            disabled_path.rename(enabled_path)
    
    for folder_name in DISABLED_NODES:
        enabled_path = custom_nodes_path / folder_name
        disabled_path = custom_nodes_path / f"{{folder_name}}.disabled"
        if enabled_path.exists() and not disabled_path.exists():
            enabled_path.rename(disabled_path)

def main():
    script_dir = Path(__file__).parent.parent
    comfy_root = script_dir.parent.parent
    custom_nodes_path = comfy_root / 'custom_nodes'
    
    print(f"Launching ComfyUI with profile: {{PROFILE_NAME}}")
    
    if ENABLED_NODES or DISABLED_NODES:
        print("Applying node configuration...")
        apply_node_states(custom_nodes_path)
    
    portable_root = comfy_root.parent
    python_path = portable_root / 'python_embeded' / 'python.exe'
    if not python_path.exists():
        python_path = sys.executable
    
    main_py = comfy_root / 'main.py'
    cmd = [str(python_path), str(main_py)] + COMFY_ARGS
    
    print(f"Command: {{' '.join(cmd)}}")
    print("-" * 50)
    
    os.chdir(comfy_root)
    subprocess.run(cmd)

if __name__ == '__main__':
    main()
'''
        
        launcher_script.parent.mkdir(parents=True, exist_ok=True)
        with open(launcher_script, 'w') as f:
            f.write(launcher_content)
        
        # Create batch wrapper
        batch_file = self.conductor_dir / 'data' / f'launch_{safe_filename}.bat'
        batch_content = f'@echo off\ncd /d "{self.conductor_dir / "data"}"\n"{python_path}" "{launcher_script}"\npause\n'
        
        with open(batch_file, 'w') as f:
            f.write(batch_content)
        
        # Create shortcut
        icon_path = self.conductor_dir / 'web' / 'mfconductor_logo.ico'
        icon_line = f'$Shortcut.IconLocation = "{icon_path}"' if icon_path.exists() else ''
        
        ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{save_path}")
$Shortcut.TargetPath = "{batch_file}"
$Shortcut.WorkingDirectory = "{self.comfy_root}"
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
            return True, f'Profile shortcut created at {save_path}'
        else:
            return False, f'PowerShell error: {result.stderr}'
    
    # ==================== macOS ====================
    
    def _create_macos_shortcut_conductor(self, save_path: Path, avatar: str) -> Tuple[bool, str]:
        """Create macOS .app bundle or .command script for MF Conductor"""
        # Use a .command script (simpler and works well)
        if not str(save_path).endswith('.command'):
            save_path = save_path.with_suffix('.command')
        
        # Find Python
        python_path = sys.executable
        server_script = self.conductor_dir / 'standalone_server.py'
        
        script_content = f'''#!/bin/bash
cd "{self.conductor_dir}"
"{python_path}" "{server_script}"
'''
        
        with open(save_path, 'w') as f:
            f.write(script_content)
        
        # Make executable
        os.chmod(save_path, os.stat(save_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        
        return True, f'Shortcut created at {save_path}'
    
    def _create_macos_shortcut_profile(self, profile_name: str, save_path: Path, 
                                        profile_data: dict) -> Tuple[bool, str]:
        """Create macOS .command script for a profile"""
        if not str(save_path).endswith('.command'):
            save_path = save_path.with_suffix('.command')
        
        # Create launcher script first
        safe_filename = "".join(c for c in profile_name if c.isalnum() or c in (' ', '-', '_')).strip()
        launcher_script = self.conductor_dir / 'data' / f'launch_{safe_filename}.py'
        
        enabled_nodes = profile_data.get('enabled', [])
        disabled_nodes = profile_data.get('disabled', [])
        flags = profile_data.get('flags', {})
        custom_flags_list = profile_data.get('custom_flags_list', [])
        
        comfy_args = []
        for flag_value in flags.values():
            if flag_value:
                comfy_args.extend(flag_value.split())
        for flag in custom_flags_list:
            if flag.get('enabled') and flag.get('value'):
                comfy_args.extend(flag['value'].split())
        
        launcher_content = f'''#!/usr/bin/env python3
"""MF Conductor Profile Launcher - {profile_name}"""
import os
import sys
import subprocess
from pathlib import Path

PROFILE_NAME = {repr(profile_name)}
ENABLED_NODES = {repr(enabled_nodes)}
DISABLED_NODES = {repr(disabled_nodes)}
COMFY_ARGS = {repr(comfy_args)}

def apply_node_states(custom_nodes_path):
    for folder_name in ENABLED_NODES:
        disabled_path = custom_nodes_path / f"{{folder_name}}.disabled"
        enabled_path = custom_nodes_path / folder_name
        if disabled_path.exists() and not enabled_path.exists():
            disabled_path.rename(enabled_path)
    
    for folder_name in DISABLED_NODES:
        enabled_path = custom_nodes_path / folder_name
        disabled_path = custom_nodes_path / f"{{folder_name}}.disabled"
        if enabled_path.exists() and not disabled_path.exists():
            enabled_path.rename(disabled_path)

def main():
    script_dir = Path(__file__).parent.parent
    comfy_root = script_dir.parent.parent
    custom_nodes_path = comfy_root / 'custom_nodes'
    
    print(f"Launching ComfyUI with profile: {{PROFILE_NAME}}")
    
    if ENABLED_NODES or DISABLED_NODES:
        print("Applying node configuration...")
        apply_node_states(custom_nodes_path)
    
    python_path = sys.executable
    main_py = comfy_root / 'main.py'
    cmd = [python_path, str(main_py)] + COMFY_ARGS
    
    print(f"Command: {{' '.join(cmd)}}")
    print("-" * 50)
    
    os.chdir(comfy_root)
    subprocess.run(cmd)

if __name__ == '__main__':
    main()
'''
        
        launcher_script.parent.mkdir(parents=True, exist_ok=True)
        with open(launcher_script, 'w') as f:
            f.write(launcher_content)
        os.chmod(launcher_script, os.stat(launcher_script).st_mode | stat.S_IXUSR)
        
        # Create .command wrapper
        script_content = f'''#!/bin/bash
cd "{self.conductor_dir / 'data'}"
python3 "{launcher_script}"
'''
        
        with open(save_path, 'w') as f:
            f.write(script_content)
        
        os.chmod(save_path, os.stat(save_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        
        return True, f'Profile shortcut created at {save_path}'
    
    # ==================== LINUX ====================
    
    def _create_linux_shortcut_conductor(self, save_path: Path, avatar: str) -> Tuple[bool, str]:
        """Create Linux .desktop file for MF Conductor"""
        if not str(save_path).endswith('.desktop'):
            save_path = save_path.with_suffix('.desktop')
        
        python_path = sys.executable
        server_script = self.conductor_dir / 'standalone_server.py'
        icon_path = self.conductor_dir / 'web' / 'mfconductor_logo.svg'
        
        desktop_content = f'''[Desktop Entry]
Version=1.0
Type=Application
Name=MF Conductor
Comment=ComfyUI Control Center
Exec="{python_path}" "{server_script}"
Icon={icon_path}
Terminal=true
Categories=Development;
Path={self.conductor_dir}
'''
        
        with open(save_path, 'w') as f:
            f.write(desktop_content)
        
        # Make executable
        os.chmod(save_path, os.stat(save_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        
        return True, f'Shortcut created at {save_path}'
    
    def _create_linux_shortcut_profile(self, profile_name: str, save_path: Path, 
                                        profile_data: dict) -> Tuple[bool, str]:
        """Create Linux .desktop file for a profile"""
        if not str(save_path).endswith('.desktop'):
            save_path = save_path.with_suffix('.desktop')
        
        # Create launcher script first
        safe_filename = "".join(c for c in profile_name if c.isalnum() or c in (' ', '-', '_')).strip()
        launcher_script = self.conductor_dir / 'data' / f'launch_{safe_filename}.py'
        
        enabled_nodes = profile_data.get('enabled', [])
        disabled_nodes = profile_data.get('disabled', [])
        flags = profile_data.get('flags', {})
        custom_flags_list = profile_data.get('custom_flags_list', [])
        
        comfy_args = []
        for flag_value in flags.values():
            if flag_value:
                comfy_args.extend(flag_value.split())
        for flag in custom_flags_list:
            if flag.get('enabled') and flag.get('value'):
                comfy_args.extend(flag['value'].split())
        
        launcher_content = f'''#!/usr/bin/env python3
"""MF Conductor Profile Launcher - {profile_name}"""
import os
import sys
import subprocess
from pathlib import Path

PROFILE_NAME = {repr(profile_name)}
ENABLED_NODES = {repr(enabled_nodes)}
DISABLED_NODES = {repr(disabled_nodes)}
COMFY_ARGS = {repr(comfy_args)}

def apply_node_states(custom_nodes_path):
    for folder_name in ENABLED_NODES:
        disabled_path = custom_nodes_path / f"{{folder_name}}.disabled"
        enabled_path = custom_nodes_path / folder_name
        if disabled_path.exists() and not enabled_path.exists():
            disabled_path.rename(enabled_path)
    
    for folder_name in DISABLED_NODES:
        enabled_path = custom_nodes_path / folder_name
        disabled_path = custom_nodes_path / f"{{folder_name}}.disabled"
        if enabled_path.exists() and not disabled_path.exists():
            enabled_path.rename(disabled_path)

def main():
    script_dir = Path(__file__).parent.parent
    comfy_root = script_dir.parent.parent
    custom_nodes_path = comfy_root / 'custom_nodes'
    
    print(f"Launching ComfyUI with profile: {{PROFILE_NAME}}")
    
    if ENABLED_NODES or DISABLED_NODES:
        print("Applying node configuration...")
        apply_node_states(custom_nodes_path)
    
    python_path = sys.executable
    main_py = comfy_root / 'main.py'
    cmd = [python_path, str(main_py)] + COMFY_ARGS
    
    print(f"Command: {{' '.join(cmd)}}")
    print("-" * 50)
    
    os.chdir(comfy_root)
    subprocess.run(cmd)

if __name__ == '__main__':
    main()
'''
        
        launcher_script.parent.mkdir(parents=True, exist_ok=True)
        with open(launcher_script, 'w') as f:
            f.write(launcher_content)
        os.chmod(launcher_script, os.stat(launcher_script).st_mode | stat.S_IXUSR)
        
        python_path = sys.executable
        icon_path = self.conductor_dir / 'web' / 'mfconductor_logo.svg'
        
        desktop_content = f'''[Desktop Entry]
Version=1.0
Type=Application
Name=ComfyUI - {profile_name}
Comment=Launch ComfyUI with {profile_name} profile
Exec="{python_path}" "{launcher_script}"
Icon={icon_path}
Terminal=true
Categories=Development;
Path={self.comfy_root}
'''
        
        with open(save_path, 'w') as f:
            f.write(desktop_content)
        
        os.chmod(save_path, os.stat(save_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        
        return True, f'Profile shortcut created at {save_path}'


# Global instance
_shortcut_creator: Optional[ShortcutCreator] = None


def get_shortcut_creator() -> ShortcutCreator:
    """Get global ShortcutCreator instance"""
    global _shortcut_creator
    if _shortcut_creator is None:
        _shortcut_creator = ShortcutCreator()
    return _shortcut_creator








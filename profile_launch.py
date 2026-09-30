"""
Write profile shortcut launchers. Uses ComfyUI's folder.disabled suffix
and MFCONDUCTOR_BLOCKED_PACKAGES — no core ComfyUI patch.
"""

import os
import shlex
import sys
from pathlib import Path

try:
    from .security_utils import escape_ps_string, find_comfy_python, resolve_desktop_shortcut
    from .workflow_analyzer import is_never_block_package
    from .user_data import merge_required_folders
except ImportError:
    from security_utils import escape_ps_string, find_comfy_python, resolve_desktop_shortcut
    from workflow_analyzer import is_never_block_package
    from user_data import merge_required_folders

BLOCKED_PACKAGES_FILE = Path(__file__).parent / 'data' / 'blocked_packages.txt'


def parse_launch_flags(value):
    if not isinstance(value, str):
        raise ValueError('Launch flags must be text')
    lexer = shlex.shlex(value, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ''
    if os.name == 'nt':
        lexer.escape = ''  # Backslashes in Windows paths are literal.
    return validate_launch_args(list(lexer))


def validate_launch_args(args):
    if any('\x00' in arg for arg in args) or (args and not args[0].startswith('--')):
        raise ValueError('Launch flags must start with --; quote paths containing spaces')
    memory_modes = {'--gpu-only', '--highvram', '--lowvram', '--novram', '--cpu'}
    if len(memory_modes.intersection(args)) > 1:
        raise ValueError('Choose only one memory mode: GPU only, high VRAM, low VRAM, no VRAM, or CPU')
    for index, arg in enumerate(args):
        if arg == '--port' or arg.startswith('--port='):
            value = arg.partition('=')[2] if '=' in arg else (args[index + 1] if index + 1 < len(args) else '')
            if not value.isdigit() or not 1 <= int(value) <= 65535:
                raise ValueError('Port must be a number between 1 and 65535')
    return args


def build_profile_args(profile):
    args = []
    for value in (profile.get('flags') or {}).values():
        if value:
            args.extend(parse_launch_flags(value))
    for option in ('port', 'listen'):
        if profile.get(option):
            args.extend([f'--{option}', str(profile[option])])
    custom = profile.get('custom_flags_list') or [profile.get('custom_flags', '')]
    for flag in custom:
        if isinstance(flag, dict):
            flag = flag.get('value', '') if flag.get('enabled') is not False else ''
        if flag:
            args.extend(parse_launch_flags(flag))
    return validate_launch_args(args)


def workflow_launch_options(scanner, user_data):
    folders = scanner.list_folder_names()
    profiles = user_data.get_profiles()
    return {
        'success': True,
        'profiles': {name: shlex.join(build_profile_args(profile)) for name, profile in profiles.items()},
        'default_profile': next((name for name, profile in profiles.items() if profile.get('is_default')), ''),
        'keep_enabled': merge_required_folders([], folders),
        'available_nodes': sorted(folders, key=str.lower),
    }


def persist_blocked_packages(packages) -> list:
    """Write excluded pip names for the next ComfyUI start (any launcher)."""
    cleaned = []
    seen = set()
    for raw in packages or []:
        name = str(raw).strip()
        if not name or is_never_block_package(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(name)
    BLOCKED_PACKAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if cleaned:
        BLOCKED_PACKAGES_FILE.write_text(','.join(cleaned), encoding='utf-8')
    elif BLOCKED_PACKAGES_FILE.exists():
        BLOCKED_PACKAGES_FILE.unlink()
    return cleaned


_LAUNCHER_TEMPLATE = r'''#!/usr/bin/env python
"""Auto-generated MF Conductor profile launcher."""
import os
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from node_scanner import NodeScanner
from workflow_analyzer import apply_enabled_folders, folders_for_profile

PROFILE_NAME = {profile_name!r}
ENABLED_NODES = {enabled_nodes!r}
DISABLED_NODES = {disabled_nodes!r}
COMFY_ARGS = {comfy_args!r}
EXCLUDED_PACKAGES = {excluded_packages!r}
PYTHON_PATH = {python_path!r}

def apply_node_states(custom_nodes_path):
    scanner = NodeScanner(str(custom_nodes_path))
    profile = {{'enabled': ENABLED_NODES, 'disabled': DISABLED_NODES}}
    enabled = folders_for_profile(profile, scanner.list_folder_names())
    result = apply_enabled_folders(scanner, enabled)
    if result['errors']:
        raise RuntimeError('; '.join(result['errors']))
    return result

def main():
    script_dir = Path(__file__).parent.parent
    comfy_root = script_dir.parent.parent
    custom_nodes_path = comfy_root / 'custom_nodes'
    print(f"Launching ComfyUI with profile: {{PROFILE_NAME}}")
    print("Applying node configuration...")
    apply_node_states(custom_nodes_path)
    python_path = PYTHON_PATH if Path(PYTHON_PATH).exists() else sys.executable
    main_py = comfy_root / 'main.py'
    env = os.environ.copy()
    env.pop('MFCONDUCTOR_BLOCKED_PACKAGES', None)
    persist = Path(__file__).parent / 'blocked_packages.txt'
    if EXCLUDED_PACKAGES:
        env['MFCONDUCTOR_BLOCKED_PACKAGES'] = ','.join(EXCLUDED_PACKAGES)
        persist.write_text(','.join(EXCLUDED_PACKAGES), encoding='utf-8')
    elif persist.exists():
        persist.unlink()
    cmd = [str(python_path), str(main_py)] + COMFY_ARGS
    print(f"Command: {{' '.join(cmd)}}")
    print("-" * 50)
    os.chdir(comfy_root)
    subprocess.run(cmd, env=env)

if __name__ == '__main__':
    main()
'''


def write_profile_launcher(conductor_dir: Path, profile_name: str, profile: dict, comfy_args: list) -> Path:
    safe_filename = ''.join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in profile_name).strip()
    safe_filename = safe_filename.replace(' ', '_')
    if not safe_filename:
        safe_filename = 'profile'
    data_dir = Path(conductor_dir) / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    launcher_script = data_dir / f'launch_{safe_filename}.py'
    comfy_root = Path(conductor_dir).parent.parent
    python_path = find_comfy_python(comfy_root)
    content = _LAUNCHER_TEMPLATE.format(
        python_path=str(python_path),
        profile_name=profile_name,
        enabled_nodes=profile.get('enabled', []),
        disabled_nodes=profile.get('disabled', []),
        comfy_args=comfy_args,
        excluded_packages=[
            p for p in (profile.get('excluded_packages') or [])
            if not is_never_block_package(p)
        ],
    )
    launcher_script.write_text(content, encoding='utf-8')

    batch_file = data_dir / f'launch_{safe_filename}.bat'
    batch_file.write_text(
        f'@echo off\ncd /d "{data_dir}"\n"{python_path}" "{launcher_script}"\npause\n',
        encoding='utf-8',
    )
    shell_file = data_dir / f'launch_{safe_filename}.sh'
    shell_file.write_text(
        f'#!/bin/sh\ncd "{data_dir}"\n"{python_path}" "{launcher_script}"\n',
        encoding='utf-8',
    )
    try:
        os.chmod(shell_file, 0o755)
    except OSError:
        pass
    return launcher_script


def write_desktop_shortcut(save_path: str, target: str, working_dir: str, name: str, description: str, icon_path: Path = None) -> tuple:
    """Create a Desktop shortcut on Windows (.lnk), Linux (.desktop), or macOS (.command)."""
    target = str(target)
    working_dir = str(working_dir)
    if sys.platform == 'win32':
        default_name = f'{name}.lnk'
    elif sys.platform == 'darwin':
        default_name = f'{name}.command'
    else:
        default_name = f'{name}.desktop'
    dest, err = resolve_desktop_shortcut(save_path, default_name)
    if dest is None:
        return None, err

    if sys.platform == 'win32':
        import subprocess
        script = powershell_shortcut_script(str(dest), target, working_dir, description, icon_path)
        result = subprocess.run(['powershell', '-Command', script], capture_output=True, text=True)
        if result.returncode != 0:
            return None, result.stderr or 'PowerShell shortcut failed'
        return dest, ''

    if sys.platform == 'darwin':
        dest.write_text(f'#!/bin/sh\ncd "{working_dir}"\n"{target}"\n', encoding='utf-8')
    else:
        icon_line = f'Icon={icon_path}\n' if icon_path and Path(icon_path).exists() else ''
        dest.write_text(
            '[Desktop Entry]\n'
            'Type=Application\n'
            f'Name={name}\n'
            f'Comment={description}\n'
            f'Exec="{target}"\n'
            f'Path={working_dir}\n'
            f'{icon_line}'
            'Terminal=true\n',
            encoding='utf-8',
        )
    try:
        os.chmod(dest, 0o755)
    except OSError:
        pass
    return dest, ''


def powershell_shortcut_script(save_path: str, target: str, working_dir: str, description: str, icon_path: Path = None) -> str:
    ps_save = escape_ps_string(save_path)
    ps_target = escape_ps_string(str(target))
    ps_cwd = escape_ps_string(str(working_dir))
    ps_desc = escape_ps_string(description)
    icon_line = ''
    if icon_path and Path(icon_path).exists():
        icon_line = f'$Shortcut.IconLocation = "{escape_ps_string(str(icon_path))}"'
    return f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("{ps_save}")
$Shortcut.TargetPath = "{ps_target}"
$Shortcut.WorkingDirectory = "{ps_cwd}"
$Shortcut.Description = "{ps_desc}"
{icon_line}
$Shortcut.Save()
'''

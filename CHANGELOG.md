# Changelog

All notable changes to MF Conductor will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2026-02-07

### Fixed
- Async handlers no longer block the event loop during node scanning, git, and pip operations
- Cache invalidation now properly clears stale node data
- `detect_broken_nodes` no longer fails from missing module import
- Exception handler NameError in PyPI update checks
- Restart now reuses the active profile instead of falling back to default
- `launch_comfy` and `launch_profile` no longer silently ignore `custom_flags_list`
- Removed duplicate package install endpoint
- Thread-safe singleton initialization and atomic JSON file writes

### Security
- Path traversal validation added to file location opener
- Improved path traversal check in node removal (uses `pathlib.relative_to`)
- User input escaped in PowerShell shortcut/dialog scripts to prevent injection
- `run_python_command` restricted to allowlisted modules only
- SSL certificate verification re-enabled for PyPI requests

### Added
- `api_core.py` shared business logic module
- `shortcut_utils.py` cross-platform shortcut creation
- Modular frontend JS (`web/js/` - api, console, modal, toast, utils, websocket)
- SVG assets for file browser
- Tailwind CSS build tooling
- Architecture and submission documentation

## [1.2.1] - 2026-02-01

### Added
- **Fast Start Node Loading**: Cached node list loads immediately with background refresh.
- **Improved Metadata Extraction**: Better PNG/WebP workflow parsing and EXIF fallback handling.

### Improved
- **Disabled Node Detection**: Accurate handling of `.disabled` folders in the node list.
- **Usage Analytics Mapping**: Node usage now maps correctly to packages.
- **Package Update State**: Update flags reset cleanly between checks.

### Fixed
- Integrated mode: package update checks now handle immediate responses.
- Integrated mode: missing profile endpoints for clear default and load presets.
- Integrated mode: command execution is disabled for safety.

## [1.2.0] - 2025-01-16

### Added
- **Terminal History Persistence**: Terminal output now persists across page refreshes
  - Auto-saves last 500 lines to localStorage
  - Restores previous session on load
- **Profile View Enhancements**: 
  - Search, sort, and grid/list view toggle for profiles
  - Sort by Name, Node Count, or Default First
- **Terminal View Improvements**:
  - Full-height terminal output with sticky command input
  - Terminal-style dark background
  - Improved command prompt styling
- **Console Logging**: Bottom console panel now shows all package operations
  - Check for updates progress and results
  - Install, upgrade, uninstall, and reinstall operations
  - Individual package update checks
- **Auto-Generated Launcher**: Creates `Launch_MF_Conductor.bat` at portable root on first load
  - Automatically regenerates if deleted
  - Uses relative paths for portability across systems
- **Tab Persistence**: Active tab is saved in URL hash and persists across page refreshes
  - Supports browser back/forward navigation between tabs

### Improved
- **UI Design**: Complete redesign with sidebar navigation and glassmorphism
  - Modern dark theme with moss green/copper accent colors
  - Removed offset border accent styling
  - Improved visual hierarchy and spacing
- **Settings**: Theme and accent colors now properly apply throughout UI
- **Context Menu**: Fixed "Set as Default" icon styling
- **Package Update Performance**: 
  - Switched from slow `pip list --outdated` to fast PyPI API calls
  - Parallel checking (20 concurrent requests)
  - Update checks now complete in seconds instead of minutes
- **Expanded Node Details**:
  - Properly sized icons (14px for buttons, 16px for requirements)
  - Fixed layout and styling issues
  - Restored expandable nodes list functionality
- **Launch Performance**: Splash screen now loads in background without blocking launch
- **Server Ready Detection**: Faster polling (500ms vs 2s) for quicker "Go to Comfy" availability
- **Console Performance**: Optimized appending with batched DOM updates and requestAnimationFrame scrolling
- **"Go to Comfy" Button**: Opens immediately without blocking status checks

### Fixed
- Terminal no longer clears on page refresh
- Profile tiles properly styled and scaled
- Settings modal works correctly with new UI
- Node and package list scaling issues resolved
- Bottom console panel now displays all operation logs
- List header z-index fixed to prevent toolbar overlap when scrolling
- Expanded node detail section styling and icon sizes
- Package update check timeout issues resolved
- **Race condition** in backend log buffer (now returns copy instead of slice reference)
- **Memory leak** from unbounded console buffer (capped at 5000 lines)
- **Path traversal vulnerability** in file serving endpoints (added path validation)
- **Stale update jobs** now cleaned up automatically after timeout
- **Event listener leak** in profile context menu (switched to event delegation)
- **Profile launcher path** calculation corrected for generated shortcuts
- **Missing import** for `refresh_installed_packages` in integrated mode
- Replaced all bare `except:` clauses with proper `except Exception` for better debugging

## [1.1.0] - 2025-12-19

### Added
- **Profile Quick Launch Shortcuts**: Create Windows shortcuts that launch ComfyUI with a specific profile
  - Right-click any profile → "Create Quick Launch"
  - Shortcuts apply node enable/disable states before launching
  - Shortcuts include all profile flags (VRAM, attention, custom flags)
  - Native Windows save dialog for choosing shortcut location
  - Shortcuts use MF Conductor icon
- **MF Conductor Shortcut**: Create a shortcut to launch MF Conductor standalone
  - Settings → Shortcuts → "Create Shortcut"
  - Native save dialog for custom placement
- **Profile Export/Import**: Share profiles with others via JSON files
- **System Theme Sync**: Automatically match OS light/dark theme preference
- **Undo for Node Removal**: Undo accidental node deletions (for git-based nodes)
- **Batch Tag Assignment**: Select multiple nodes and add/remove tags at once
- **Update Badge**: Notification badge on Nodes tab showing available updates
- **Improved Error Handling**:
  - User-friendly error messages for common issues
  - Retry buttons for failed operations
  - Automatic retry for transient failures

### Improved
- **Performance**: Debounced search inputs reduce unnecessary filtering
- **Settings**: Added "Sync with system theme" toggle and Shortcuts section
- **Profiles Toolbar**: Quick import button and profile count display
- **Integrated Mode**: Removed unnecessary controls (Go to Comfy button, status indicator)

### Fixed
- Profile shortcuts now correctly apply node enable/disable states
- Profile shortcuts now correctly pass all launch flags
- Fixed nodes_cache.json saving to wrong directory
- Fixed console panel positioning and collapse behavior
- Date in changelog corrected to 2025

## [1.0.0] - 2025-12-18

### Added
- **Profile System**: Create and manage multiple node configurations
  - Enable/disable nodes per profile
  - Configure ComfyUI launch flags per profile
  - Custom flags support
  - One-click profile launching
  - Default profile setting with star toggle
- **Live Console**: Real-time ComfyUI output capture
  - Command input for running pip commands
  - Auto-scroll functionality
  - Console output copying
  - Clear console button
- **Process Control**: Launch, stop, and restart ComfyUI from the interface
  - Header controls with visual status indicator
  - External process detection
- **Tabbed Interface**: Reorganized UI with Profiles, Nodes, Packages, and Console tabs
- **Node Management**: 
  - Live search filtering
  - Multiple sort options (name, date, stars, author)
  - GitHub stars integration
  - Expandable node details
  - Requirements viewer with install functionality
  - Bulk update capability
- **GitHub Integration**: Automatic repository detection and linking
- **Disk Usage Tracking**: See storage consumption per node
- **Git History**: View commit history and rollback capability
- **Backup/Restore**: Export and import settings
- **User Data**: Favorites, tags, and notes for nodes
- **Dual Mode**: Works both standalone and integrated in ComfyUI
- **Themes**: Multiple built-in themes (Dark, Light, Midnight, Forest, Ocean, Sunset, Blackout)
- **Accent Colors**: Customizable accent colors with theme support
- **UI Scaling**: Compact, Normal, and Old Person view modes

### Technical
- Python backend with aiohttp (integrated) and http.server (standalone)
- Clean separation of concerns with modular file structure
- Caching system for faster subsequent loads
- ComfyUI-Manager database integration for node metadata

## [Unreleased]

### Planned
- Community tab for sharing profiles
- Package management per profile
- Auto-update scheduling
- Virtual scrolling for large node lists


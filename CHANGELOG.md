# Changelog

All notable changes to MF Conductor will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] - 2026-10-04

### Changed
- Profile launch, workflow launch, and desktop shortcuts no longer rename unused packs. ComfyUI is started with `--disable-all-custom-nodes` and `--whitelist-custom-nodes`, including launches from inside ComfyUI.
- A needed pack that is still `Name.disabled` and locked by another program is left in place. MF Conductor adds a directory link at `Name` so ComfyUI can load it.
- Version is 2.0.0.

### Fixed
- Keep stale pre-launch status responses from stopping terminal polling, and update the status label when ComfyUI becomes ready.
- Align workflow list rows and standardize search, sort, view, and action controls across collection pages.
- Make package version sorting numeric, add package sort direction, and keep hidden controls hidden.
- Center the terminal splash without tabs and display the same artwork in the Windows launcher.
- Validate workflow launch settings before stopping ComfyUI and honor the selected launch port.
- Reject foreign browser origins and non-loopback Hosts; require JSON management POSTs in standalone and integrated modes.
- Preserve both folders when an active node and its `.disabled` copy collide.
- Keep profile names out of executable launcher source and share profile selection logic with desktop shortcuts.
- Escape quotes in HTML attributes and use JavaScript escaping for inline handler arguments.
- Resolve excluded distributions to their import modules while preserving shared namespace parents and core imports.

### Added
- Workflow launch setup with editable flags, profile presets, installed utility packs, and optional extra nodes.
- Isolated regression checks for request security, profile shortcuts, folder preservation, package blocking, and frontend escaping.

## [1.4.5] - 2026-09-07

### Fixed
- An already-active required pack can remain enabled when a disabled duplicate exists. Both copies are preserved; disabling a collision reports an error instead of deleting files.
- Workflow launch no longer aborts when a graph still names a pack that is not installed. Missing CNR ids are logged and launch continues with the packs that are present.
- Workflow launch no longer lets Windows pipe `flush()` (`Errno 22`) abort custom-node imports. A print during node load was enough to mark Easy-Use, Media Frisk, rgthree, MF Conductor, and others as failed.

### Added
- Workflow launch can install missing packs from the ComfyUI-Manager list (Install & Launch), then isolate and start ComfyUI.
- **Workflows tab**: lists `user/default/workflows`, maps each graph to the custom nodes it needs (`cnr_id` + node types, including subgraphs), and launches ComfyUI with only those folders enabled. Launch flags come from the default profile. Integrated mode applies isolation and asks you to restart.
- Linux `.desktop` and macOS `.command` desktop shortcuts. Profile launchers also write a `.sh` script.
- ComfyUI command-palette / Extensions menu entry, plus an official sidebar tab when `extensionManager.registerSidebarTab` exists.

### Fixed
- Node type extraction now scans the whole package for `NODE_CLASS_MAPPINGS` keys instead of stopping without `__init__.py`, skipping packs with more than 30 files, or treating class names as registered types.
- Apply/launch writes `data/blocked_packages.txt` so the next ComfyUI start honors excluded packages even without `MFCONDUCTOR_BLOCKED_PACKAGES` in the environment.
- Restart keeps the last workflow/profile package blocklist.
- Node scan no longer calls the GitHub API for star counts.
- Node rollback uses `git reset --hard` so the branch is not left detached.
- Broken-node scan no longer flags a missing `__init__.py`.
- Console and backend log buffers no longer skip lines after the cap trims old entries.
- Workflow launch no longer auto-blocks unused nodes' pip names. That list included stdlib modules such as `uuid` and ComfyUI internals such as `nodes`, so `import torch` failed. Isolation is folder rename; only the default profile's excluded packages are blocked, and stdlib / ComfyUI internals are never hidden.
- Node disable now uses ComfyUI's native `folder.disabled` rename. The `.disabled` file approach never stopped ComfyUI from loading nodes and the documented `nodes.py` patch did not exist.
- Package exclusion wraps every `sys.meta_path` finder so blocked names return `None` from `find_spec()` instead of falling through to PathFinder.
- Mutating API routes are localhost-only. Standalone no longer sends `Access-Control-Allow-Origin: *`. Localhost middleware install failure no longer registers API routes.
- Git clone, pip specs, folder names, commit hashes, and usage-scan folders are validated. `git clone` uses `--` before the URL.
- PowerShell shortcut/dialog strings are escaped in integrated mode as well as standalone. Shortcut paths stay on the Desktop.
- Profile shortcuts and apply/launch share one launcher writer that renames folders and sets `MFCONDUCTOR_BLOCKED_PACKAGES`. Inherited blocked-package env is cleared before launch.
- Default GPU profiles no longer require `--use-sage-attention`.
- Profile and node names in onclick handlers are HTML-attribute escaped.
- Analyze failures no longer report success or apply a Manager+Conductor-only folder set.
- Empty profile `enabled` stays "all nodes". Apply uses the same case-insensitive folder isolation as workflow launch.
- Dual active/`Name.disabled` leftovers no longer abort activate/deactivate.
- Integrated profile launch applies isolation instead of writing a `.bat` and spawning a second ComfyUI.
- Integrated package install accepts `/api/packages/install`. Profile Apply works while ComfyUI is already running.

### Changed
- Standalone workflow launch no longer renames unused packs. ComfyUI is started with `--disable-all-custom-nodes` and `--whitelist-custom-nodes`, so an editor can keep those folders open.
- File browser no longer includes `models`.
- Standalone WebSocket connects only in standalone mode.
- Restart clears the console before the new process starts.

Note: 1.3.1 documented a `.disabled` file plus a `nodes.py` patch. That path was reverted. Isolation is folder rename only.

### Removed
- Unused `web/js` frontend split (live UI is `web/app.js`).
- Community tab stub (still planned).
- Unused `api_core.py` and `shortcut_utils.py`.
- Writing `Launch_MF_Conductor.bat` to the portable root on import.
- `sys.path.insert` of the extension directory in integrated mode.

### Security
- Terminal `run-command` is limited to `pip list/show/freeze/check`.
- File listing resolves subfolders inside the requested ComfyUI folder.

## [1.3.1] - 2026-02-22

### Added
- **Fast Node Disable**: New `.disabled` file approach instead of folder renaming
  - Creates/deletes a tiny `.disabled` file inside node folders
  - Much faster than renaming folders (especially for large nodes)
  - Git-friendly: folder names stay the same, remotes still work
  - Atomic operation: can't fail halfway through
  - Requires one-time ComfyUI patch (auto-applied to `nodes.py`)
- **Package Exclusion**: Actually implemented excluded packages feature
  - Packages listed in profile's "Excluded Packages" are now blocked at startup
  - Uses meta path finder to make packages appear "not installed"
  - Libraries like `transformers` and `diffusers` properly detect packages as unavailable
  - Prevents packages like `bitsandbytes` from causing CUDA errors when not needed
  - Only active when launching via profile (environment variable based)

### Fixed
- **Node Scan Hang**: Fixed catastrophic regex backtracking in `_find_node_classes_in_package()`
  - Nodes with 30+ Python files would cause scanner to hang indefinitely
  - Now limits file scanning and uses simpler pattern matching
  - Full scan completes in ~4 seconds instead of hanging forever
- **WebSocket Connection**: Fixed same-port WebSocket upgrade
  - Writes directly to raw socket instead of buffered output
  - More robust header detection for upgrade requests

### Changed
- Profile launcher scripts now use `.disabled` file approach
- Node detection checks for `.disabled` file before folder suffix

### Technical
- Added ComfyUI patch: `nodes.py` now checks for `.disabled` file in custom node folders
- Scan limit: packages with >30 Python files skip deep node class search
- Package blocking uses `sys.meta_path` finder instead of `sys.modules` injection (compatible with `importlib.util.find_spec()`)

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

## Planned
- Community tab for sharing profiles
- Package management per profile
- Auto-update scheduling
- Virtual scrolling for large node lists

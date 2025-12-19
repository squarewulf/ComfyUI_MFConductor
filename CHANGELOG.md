# Changelog

All notable changes to MF Conductor will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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


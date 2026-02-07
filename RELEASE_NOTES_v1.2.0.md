# Release v1.2.0

## Major Improvements

### 🎯 Console Logging
- **Bottom console panel now shows all package operations**
  - Real-time logging for check updates, install, upgrade, uninstall, and reinstall
  - Individual package update checks with progress feedback
  - All operations now properly logged to the bottom console panel

### ⚡ Package Update Performance
- **Dramatically faster update checks**
  - Switched from slow `pip list --outdated` to fast PyPI API calls
  - Parallel checking (20 concurrent requests)
  - Update checks now complete in **seconds instead of minutes**

### 🎨 UI Fixes & Improvements
- **Expanded Node Details**
  - Properly sized icons (14px for buttons, 16px for requirements)
  - Fixed layout and styling issues
  - Restored expandable nodes list functionality
- **List Header**
  - Fixed z-index to prevent toolbar overlap when scrolling
  - Sticky positioning works correctly

## Added
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

## Improved
- **UI Design**: Complete redesign with sidebar navigation and glassmorphism
  - Modern dark theme with moss green/copper accent colors
  - Removed offset border accent styling
  - Improved visual hierarchy and spacing
- **Settings**: Theme and accent colors now properly apply throughout UI
- **Context Menu**: Fixed "Set as Default" icon styling
- **Package Update Performance**: 10-100x faster update checking
- **Expanded Node Details**: Properly styled and sized

## Fixed
- Terminal no longer clears on page refresh
- Profile tiles properly styled and scaled
- Settings modal works correctly with new UI
- Node and package list scaling issues resolved
- Bottom console panel now displays all operation logs
- List header z-index fixed to prevent toolbar overlap when scrolling
- Expanded node detail section styling and icon sizes
- Package update check timeout issues resolved

---

**Full Changelog**: https://github.com/squarewulf/ComfyUI_MFConductor/blob/main/CHANGELOG.md










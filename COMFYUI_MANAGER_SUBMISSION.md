# ComfyUI Manager Submission for MF Conductor

## 1. JSON Entry for `custom-node-list.json`

Add this entry to the `custom-node-list.json` file:

```json
{
  "author": "squarewulf",
  "title": "MF Conductor",
  "reference": "https://github.com/squarewulf/ComfyUI_MFConductor",
  "files": [
    "https://github.com/squarewulf/ComfyUI_MFConductor"
  ],
  "install_type": "git-clone",
  "description": "The Ultimate ComfyUI Control Center - Profile-based launching, surgical node management, and package control."
}
```

## 2. `__init__.py` Verification

Your `__init__.py` file is correctly configured! ✅

**Required elements present:**
- ✅ `NODE_CLASS_MAPPINGS = {}` (line 304) - Empty dict is fine for management tools
- ✅ `NODE_DISPLAY_NAME_MAPPINGS = {}` (should be present, likely empty)
- ✅ `WEB_DIRECTORY = "./js"` (line 301) - Required for web interface integration
- ✅ `__all__` export list includes all required exports (line 1622)

**Note:** Since MF Conductor is a management tool (not a custom node that adds workflow nodes), having an empty `NODE_CLASS_MAPPINGS` is correct. The `WEB_DIRECTORY` is what allows it to integrate with ComfyUI's web interface.

## 3. Pull Request Description

### Title:
```
Add MF Conductor - Custom Node Manager
```

### Body:
```markdown
## MF Conductor

A powerful Custom Node Manager for ComfyUI that provides comprehensive node management, profile-based launching, and real-time console monitoring.

### Features
- **Profile System**: Create and manage multiple ComfyUI configurations with different node enable/disable states
- **Node Management**: Visual interface for browsing, installing, updating, and managing custom nodes
- **Live Console**: Real-time process control and monitoring with embedded output
- **Package Management**: Install, update, and manage Python packages
- **Standalone & Integrated Modes**: Run as independent server or integrate into ComfyUI's web interface
- **Desktop Shortcuts**: Generate Windows shortcuts for quick profile launching

### Repository
https://github.com/squarewulf/ComfyUI_MFConductor

### Installation
Users can install via ComfyUI Manager or manually clone to `custom_nodes/ComfyUI_MFConductor`.

### Technical Details
- **Type**: Web-based management interface
- **Backend**: Python 3.10+ (aiohttp for integrated mode, http.server for standalone)
- **Frontend**: Vanilla JavaScript, HTML, CSS
- **Platform**: Windows (full support), Linux/macOS (core features)
- **Dependencies**: aiohttp>=3.8.0

The tool integrates seamlessly with ComfyUI's existing web interface and is compatible with ComfyUI-Manager's node management system.
```

---

## Quick Reference

**Repository URL:** `https://github.com/squarewulf/ComfyUI_MFConductor`  
**Author:** `squarewulf`  
**Title:** `MF Conductor`  
**Install Type:** `git-clone`


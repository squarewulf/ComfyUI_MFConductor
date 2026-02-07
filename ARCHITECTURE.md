# MF Conductor - Architecture Documentation

## Overview

MF Conductor is a ComfyUI management tool with a dual-mode architecture supporting both standalone and integrated operation.

## Directory Structure

```
ComfyUI_MFConductor/
├── __init__.py              # ComfyUI integration (aiohttp routes)
├── standalone_server.py     # Independent HTTP server (port 8199)
├── api_core.py              # ★ NEW: Shared API business logic
├── shortcut_utils.py        # ★ NEW: Cross-platform shortcut creation
├── node_scanner.py          # Node discovery and parsing
├── git_utils.py             # Git and pip operations
├── user_data.py             # Profile/settings persistence
├── browse_nodes.py          # Community node discovery
├── data/
│   └── profiles.json        # User profile database
├── web/
│   ├── index.html           # Main HTML structure
│   ├── app.js               # Main frontend application
│   ├── style.css            # Custom styles
│   └── js/                  # ★ NEW: Modular JavaScript components
│       ├── index.js         # Module re-exports
│       ├── api.js           # Centralized API service
│       ├── utils.js         # Utility functions
│       ├── toast.js         # Toast notifications
│       ├── console.js       # Console manager
│       ├── modal.js         # Modal dialogs
│       └── websocket.js     # WebSocket for real-time updates
└── js/
    └── mf_conductor.js      # ComfyUI integration script
```

## Core Modules

### `api_core.py` - Shared Business Logic

The `MFConductorCore` class contains all business logic shared between modes:

- **Node Operations**: get, refresh, install, update, remove, activate/deactivate
- **Package Operations**: install, uninstall, upgrade, check updates
- **User Data**: favorites, tags, notes
- **Profile Operations**: save, delete, apply, set default
- **Browse Operations**: search community nodes
- **Settings**: get, save, reset
- **Shortcut Creation**: cross-platform (Windows/macOS/Linux)

```python
from api_core import get_core, APIResponse

core = get_core()
result = core.get_nodes()  # Returns standardized APIResponse
```

### `APIResponse` - Standardized Response Format

All API responses follow a consistent format:

```python
# Success response
{'success': True, 'message': 'Optional message', 'data': {...}}

# Error response  
{'success': False, 'message': 'Error description'}
```

### `shortcut_utils.py` - Cross-Platform Shortcuts

Creates desktop shortcuts on all platforms:

| Platform | Format | Implementation |
|----------|--------|----------------|
| Windows  | `.lnk` | PowerShell COM object |
| macOS    | `.command` | Shell script |
| Linux    | `.desktop` | XDG desktop entry |

## Frontend Architecture

### Modular Components (`web/js/`)

| Module | Purpose | Key Export |
|--------|---------|------------|
| `api.js` | HTTP API client | `api` singleton |
| `utils.js` | Helper functions | `debounce`, `escapeHtml`, etc. |
| `toast.js` | User notifications | `toast` singleton |
| `console.js` | Log display | `console_manager` singleton |
| `modal.js` | Dialog management | `modal` singleton |
| `websocket.js` | Real-time updates | `websocket` singleton |

### Usage Example

```javascript
import { api, toast, modal } from './js/index.js';

// Make API call
const nodes = await api.getNodes();

// Show notification
toast.success('Nodes loaded successfully');

// Show confirmation dialog
const confirmed = await modal.confirm({
    title: 'Delete Node?',
    message: 'This action cannot be undone.',
    type: 'danger'
});
```

## Dual-Mode Operation

### Standalone Mode (Port 8199)

```
┌─────────────────────────────────────┐
│         standalone_server.py         │
│  ┌───────────────────────────────┐  │
│  │      MFConductorAPI           │  │
│  │  (extends with process mgmt)  │  │
│  └───────────────────────────────┘  │
│             ↓                        │
│  ┌───────────────────────────────┐  │
│  │      MFConductorHandler       │  │
│  │  (HTTP request routing)       │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
              ↓
    ┌─────────────────┐
    │   Browser UI    │
    │  localhost:8199 │
    └─────────────────┘
```

**Capabilities:**
- Launch/stop/restart ComfyUI
- View live console output
- Full node management
- Profile-based launching

### Integrated Mode (Port 8188)

```
┌─────────────────────────────────────┐
│           ComfyUI Server            │
│  ┌───────────────────────────────┐  │
│  │       __init__.py             │  │
│  │  (aiohttp route registration) │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
              ↓
    ┌─────────────────┐
    │   Browser UI    │
    │ localhost:8188  │
    │ /mf_conductor/  │
    └─────────────────┘
```

**Capabilities:**
- Node management
- Profile editing
- Quick adjustments while ComfyUI runs

## Data Flow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Frontend   │────▶│  HTTP/WS     │────▶│   Backend    │
│   (app.js)   │     │   Server     │     │  (api_core)  │
└──────────────┘     └──────────────┘     └──────────────┘
                                                 │
                           ┌─────────────────────┼─────────────────────┐
                           ▼                     ▼                     ▼
                    ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
                    │ NodeScanner  │     │  GitUtils    │     │  UserData    │
                    └──────────────┘     └──────────────┘     └──────────────┘
                           │                     │                     │
                           ▼                     ▼                     ▼
                    ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
                    │custom_nodes/ │     │  .git repos  │     │ data/*.json  │
                    └──────────────┘     └──────────────┘     └──────────────┘
```

## WebSocket Protocol (Future)

For real-time updates without polling:

```javascript
// Connect
websocket.connect();

// Subscribe to channels
websocket.subscribeToConsole();
websocket.subscribeToStatus();

// Handle events
websocket.on('console', (data) => {
    console_manager.appendOutput(data.text, data.type);
});

websocket.on('status', (data) => {
    updateComfyStatus(data.status);
});
```

## Migration Guide

### Using the New Modular Components

Instead of the monolithic `app.js`, you can now import specific modules:

```javascript
// Old way (app.js has everything)
app.showToast('success', 'Done!');

// New way (modular imports)
import { toast } from './js/index.js';
toast.success('Done!');
```

### Using the Shared API Core

```python
# Old way (duplicate code in both servers)
def get_nodes():
    scanner = get_scanner()
    nodes = scanner.scan()
    return {'nodes': nodes}

# New way (shared core)
from api_core import get_core
core = get_core()
result = core.get_nodes()  # Standardized response
```

## Best Practices

1. **API Responses**: Always use `APIResponse.success()` or `APIResponse.error()`
2. **Logging**: Use `core.add_log()` for backend logs visible in frontend
3. **Error Handling**: Wrap operations in try/except, return error responses
4. **Caching**: Use `core._cached_nodes` for node data, invalidate on changes
5. **Cross-Platform**: Use `shortcut_utils.py` for any shortcut creation








# MF Conductor - Architecture Documentation

## Overview

MF Conductor is a ComfyUI management tool with a dual-mode architecture supporting both standalone and integrated operation.

## Directory Structure

```
ComfyUI_MFConductor/
├── __init__.py              # ComfyUI integration (aiohttp routes)
├── standalone_server.py     # Independent HTTP server (port 8199)
├── security_utils.py        # Path, URL, pip, and localhost checks
├── profile_launch.py        # Profile shortcut launcher writer
├── prestartup_script.py     # Package blocking before node import
├── node_scanner.py          # Node discovery and parsing
├── git_utils.py             # Git and pip operations
├── user_data.py             # Profile/settings persistence
├── workflow_analyzer.py     # Workflow catalog and required-node mapping
├── browse_nodes.py          # Community node discovery
├── data/
│   └── profiles.json        # User profile database
├── web/
│   ├── index.html           # Main HTML structure
│   ├── app.js               # Live frontend (index.html loads this)
│   └── style.css            # Custom styles
└── js/
    └── mf_conductor.js      # ComfyUI sidebar button
```

## Core Modules

### Isolation

ComfyUI skips folders named `*.disabled`. Activate/deactivate rename folders. Package exclusion wraps `sys.meta_path` finders so blocked names are invisible to `find_spec()`. Apply/launch writes `data/blocked_packages.txt`; prestartup reads that file when `MFCONDUCTOR_BLOCKED_PACKAGES` is unset. Stdlib modules, ComfyUI internals (`nodes`, `comfy`, …), and core pip names are never hidden. Workflow launch isolates by folder only; it does not auto-block unused nodes' requirements.txt names. The API is localhost-only.

## Frontend Architecture

The live UI is `web/index.html` plus `web/app.js`.

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
│   (app.js)   │     │   Server     │     │   handlers   │
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

## Best Practices

1. Validate folder names, git URLs, pip specs, and commit hashes in `security_utils`.
2. Write profile launchers through `profile_launch.py`.
3. Keep mutating routes localhost-only.








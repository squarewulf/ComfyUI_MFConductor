# MF Conductor

<p align="center">
<img src="web/mfconductor_logo.svg" alt="MF Conductor Logo" width="140" height="140">
</p>

<h3 align="center">The Ultimate ComfyUI Control Center</h3>

<div align="center">

</div>

<p align="center">
Take complete control of your ComfyUI environment. Profile-based launching, surgical node management, package control, and real-time console monitoring - unified in one interface.
</p>

<p align="center">
<strong>
<a href="#-features">FEATURES</a> &nbsp;•&nbsp;
<a href="#-installation">INSTALLATION</a> &nbsp;•&nbsp;
<a href="#-usage">USAGE</a> &nbsp;•&nbsp;
<a href="#-profiles">PROFILES</a> &nbsp;•&nbsp;
<a href="#-shortcuts">SHORTCUTS</a>
</strong>
</p>

---

## Overview

| Property | Details |
|----------|---------|
| **Type** | Web-based application (local server + browser UI) |
| **Backend** | Python 3.10+ (uses `http.server` standalone, `aiohttp` integrated) |
| **Frontend** | Vanilla JavaScript, HTML, CSS (no build step required) |
| **Platform** | **Windows**, **Linux**, **macOS** |
| **Dependencies** | Git (for node management), Python packages listed in `requirements.txt` |

MF Conductor runs as a local web server on port `8199` (standalone) or integrates directly into ComfyUI's existing server on port `8188`. Open your browser to interact with the UI - there is no native desktop app.

---

## Screenshots

<p align="center">
<img src="web/screenshots/profiles.png" alt="Profiles Tab" width="800">
<br><em>Profiles Tab - Manage multiple ComfyUI configurations</em>
</p>

<p align="center">
<img src="web/screenshots/nodes.png" alt="Nodes Tab" width="800">
<br><em>Nodes Tab - View, search, and manage custom nodes</em>
</p>

<p align="center">
<img src="web/screenshots/profile-editor.png" alt="Profile Editor" width="800">
<br><em>Profile Editor - Select enabled/excluded nodes per profile</em>
</p>

---

## ⬢ Features

### ❖ Profile System

The core of the application. Manage launch configurations that control every aspect of the environment.

* **Preset Profiles** - Built-in configs for **GPU - Standard**, **GPU - Low VRAM**, **GPU - Very Low VRAM**, **GPU - High VRAM**, **CPU Only**, **DirectML**, and **Preview Mode**.
* **Context Isolation** - Select exactly which custom nodes are active per profile.
* **Launch Flags** - Configure VRAM limits (`--lowvram`), attention modes, and preview methods visually.
* **Package Exclusion** - Prevent specific Python packages from loading (e.g., `bitsandbytes`) to avoid CUDA conflicts.
* **Desktop Shortcuts** - Generate Desktop shortcuts for a profile or for MF Conductor itself (Windows `.lnk`, Linux `.desktop`, macOS `.command`).
* **Workflow Launch** - The Workflows tab reads `ComfyUI/user/default/workflows` and starts ComfyUI with only the custom nodes that graph uses. Unused node folders are disabled. Flags and any extra excluded packages come from your default profile.

### ❖ Node Management

A clean, functional interface for the custom node ecosystem.

* **Visual Node List** - Auto-strips redundant prefixes for readability.
* **Live Search** - Debounced filtering by name, author, or status.
* **GitHub Integration** - Direct links to repositories and star counts.
* **Bulk Operations** - Update or disable multiple nodes simultaneously.
* **Install from URL** - Direct Git repository installation support.
* **Fast Start** - Cached node list loads instantly with background refresh.

### ❖ Live Console

Real-time process control and monitoring.

* **Embedded Output** - View standard output (stdout) and errors (stderr) directly in the UI.
* **Process Control** - Start, Stop, and Restart the ComfyUI server.
* **Status Indicators** - Visual feedback for server state (Initializing, Running, Stopped).

---

## ⭳ Installation

### Method 1: ComfyUI Manager

1. Open **ComfyUI Manager**.
2. Search for `MF Conductor`.
3. Click **Install**.

### Method 2: Git Clone

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/squarewulf/ComfyUI_MFConductor.git

```

### Method 3: Manual

1. Download the latest archive from [Releases](https://github.com/squarewulf/ComfyUI_MFConductor/releases).
2. Extract to `ComfyUI/custom_nodes/ComfyUI_MFConductor`.
3. Restart ComfyUI.

---

## ➤ Usage

MF Conductor supports two operational modes:

### Standalone Mode

*Recommended for full management capabilities.*

Execute `Launch_MFConductor.bat` or run:

```bash
python standalone_server.py

```

> **Access:** `http://localhost:8199`
> **Benefits:** Manage nodes while ComfyUI is running; view live startup logs; "Go To Comfy" button appears when server is ready.

### Integrated Mode

*Recommended for quick adjustments.*

Access directly within a running ComfyUI instance via the sidebar or URL:

```text
http://localhost:8188/mf_conductor/

```

> **Note:** File browser and command execution are available only in standalone mode.

---

## ⚙ Profiles

Profiles define the state of the ComfyUI runtime.

### Included Presets

| Profile | Target Hardware | Description |
| --- | --- | --- |
| **GPU Standard** | Most GPUs | Balanced configuration. |
| **GPU High VRAM** | 16GB+ | Maximizes caching and performance. |
| **GPU Low VRAM** | 6-8GB | Optimizes VRAM usage (`--lowvram`). |
| **CPU Only** | CPU | Runs without GPU acceleration (`--cpu`). |
| **DirectML** | AMD/Intel (Win) | Uses DirectML backend. |

### Configuration Logic

When a profile is launched, MF Conductor performs the following operations:

1. Renames **disabled** node folders to `name.disabled` (the mechanism ComfyUI already honors).
2. Renames **enabled** folders back from `name.disabled` to `name`.
3. Sets `MFCONDUCTOR_BLOCKED_PACKAGES` and writes `data/blocked_packages.txt` so excluded packages look uninstalled to `import` and `importlib.util.find_spec()` on the next start.
4. Injects selected launch flags (e.g., `--preview-method auto`).

> **Note:** ComfyUI skips folders whose name ends in `.disabled`. MF Conductor does not patch ComfyUI. The management API is localhost-only.

Management requests must use a loopback Host and the same browser origin. API POST requests require `Content-Type: application/json`, including actions without a body. Desktop profile shortcuts use the same node selection rules as the management API.

---

## ⌨ Shortcuts

Efficiently navigate the interface using keyboard commands.

| Key | Function |
| --- | --- |
| <kbd>/</kbd> | Focus Search Field |
| <kbd>R</kbd> | Refresh Node List |
| <kbd>N</kbd> | Open Install Modal |
| <kbd>B</kbd> | Browse Node Library |
| <kbd>U</kbd> | Check for Updates |
| <kbd>Esc</kbd> | Close Active Modal |

---

## ℹ Technical Details

<details>
<summary><strong>File Structure</strong></summary>

```text
ComfyUI_MFConductor/
├── standalone_server.py     # Independent HTTP server (Port 8199)
├── security_utils.py        # Path/URL/pip/localhost checks
├── profile_launch.py        # Profile shortcut launchers
├── node_scanner.py          # Node detection logic
├── prestartup_script.py     # Package blocking (runs before ComfyUI loads)
├── git_utils.py             # Git wrapper for updates/installs
├── user_data.py             # Profile JSON management
├── workflow_analyzer.py     # Workflow list + node/pip mapping
├── data/
│   └── profiles.json        # User profile database
└── web/                     # Frontend assets (Vanilla JS/CSS)

```

</details>

<details>
<summary><strong>Troubleshooting</strong></summary>

**"Git not found" error**
Ensure Git is installed and available in the system PATH variables.

**Console shows "Running (external)"**
This status appears when ComfyUI is started externally (not via MF Conductor). To view live logs, launch ComfyUI using the MF Conductor interface.

**Garbled Console Text**
This is typically a Windows CLI encoding issue. It does not affect functionality.

**Disabled nodes still loading**
Disabled folders must be named `YourNode.disabled`. Restart ComfyUI after applying a profile. A leftover `.disabled` *file* inside a folder does not stop ComfyUI from loading it; use Activate/Deactivate in MF Conductor to migrate that leftover to a folder rename.

**Node scan hangs or is very slow**
This was fixed in v1.3.1. If you're experiencing hangs, ensure you have the latest version.

**Excluded packages still loading**
Apply or launch a profile/workflow first so `data/blocked_packages.txt` is written. The next ComfyUI start reads that file (or `MFCONDUCTOR_BLOCKED_PACKAGES` if set). A start that happens before any Apply will not block packages.

Exclusions use installed distribution metadata to resolve import names, such as `scikit-learn` → `sklearn` and `opencv-python` → `cv2`. Shared namespace parents remain available when the distribution lists its owned modules. If metadata has no import information, startup logs that the exclusion was skipped.

**Both active and disabled folders exist**
Activation and deactivation stop when both `NodeName` and `NodeName.disabled` exist. Compare and preserve any unique files before resolving the duplicate; MF Conductor does not delete either copy during a toggle.

</details>

---

## Regression checks

Run from the MF Conductor directory:

```sh
python -B -m unittest discover -s tests -p "test_*.py" -v
node --test tests/test_web_security.cjs
```

The checks use temporary node folders and an inert local API. They do not launch ComfyUI or install packages.

<p align="center">
<img src="web/mflogo.webp" alt="MediaFrisk" width="120">
<br>
<strong>Powered by <a href="https://friskcinema.com">FriskCinema</a></strong>
</p>

### Workflow launch setup

The Workflows page uses the same search, sort direction, Grid and List controls as the other collection pages. Folders adds a collapsible workflow tree. Select workflows to launch their combined dependencies.

Use **Launch setup** to choose initial profile flags, edit the complete flag text, and select additional installed node packs. These edits do not change the saved profile. Installed Manager, ModelFrisk, MediaFrisk, Crystools, and MFConductor stay enabled automatically. Other packs stay enabled only when needed by the selected workflows or explicitly selected as extras.

Standalone MFConductor starts ComfyUI with the edited flags and selected port. Inside ComfyUI, Launch prepares a launcher file and shows its path; stop ComfyUI and run that file to apply startup flags. Restart MFConductor after updating its Python files, then refresh the browser to load the updated interface.

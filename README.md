# MF Conductor

<p align="center">
  <img src="web/mfconductor_logo.svg" alt="MF Conductor Logo" width="120" height="120">
</p>

<h3 align="center">The Ultimate ComfyUI Control Center</h3>

<p align="center">
  Take complete control of your ComfyUI environment with profile-based launching, node management, package control, and real-time console monitoring - all from one unified interface.
</p>

<p align="center">
  <a href="#features">Features</a> -
  <a href="#installation">Installation</a> -
  <a href="#usage">Usage</a> -
  <a href="#profiles">Profiles</a> -
  <a href="#keyboard-shortcuts">Shortcuts</a>
</p>

---

## What is MF Conductor?

MF Conductor transforms how you work with ComfyUI. Instead of manually managing nodes, editing batch files, and juggling configurations, you get a single control center that handles everything:

- **Launch ComfyUI** with the exact configuration you need
- **Switch between workflows** by loading different profiles
- **Manage custom nodes** with visual tools and bulk operations
- **Control Python packages** with environment-aware package management
- **Monitor everything** with real-time console output

---

## Features

### Profile System
The heart of MF Conductor - create and manage launch configurations that control every aspect of your ComfyUI environment.

- **Preset Profiles** - Pre-configured profiles for common setups (GPU Standard, High VRAM, Low VRAM, CPU Only, DirectML, Preview Mode)
- **Custom Profiles** - Create unlimited profiles tailored to your workflows
- **Per-Profile Node Selection** - Choose exactly which nodes are active for each profile
- **Launch Flags** - Configure VRAM, attention, preview, and other options per profile
- **Custom Flags** - Add any ComfyUI command-line argument you need
- **Package Exclusions** - Exclude specific Python packages from installation per profile
- **Profile Avatars** - Assign unique avatars to visually distinguish your profiles
- **Export/Import** - Share profiles or back them up as JSON files
- **Right-Click Context Menu** - Quick access to launch, edit, duplicate, export, or delete profiles
- **Default Profile** - Set a default profile for one-click launching

### Node Management
Powerful tools for managing your custom node ecosystem.

- **Visual Node List** - Clean interface with automatic "ComfyUI-" prefix stripping
- **Live Search** - Real-time filtering with debounced input
- **Multiple Sort Options** - Sort by name, date added, last updated, author, or GitHub stars
- **GitHub Integration** - Automatic repo detection with direct links and star counts
- **Bulk Operations** - Update multiple nodes simultaneously
- **Requirements Viewer** - See dependencies per node and install missing packages
- **Update Badges** - Visual indicators when node updates are available
- **Install from URL** - Add new nodes directly from Git repositories

### Package Management
Full visibility and control over your Python environment.

- **Environment Packages** - View all installed packages in your ComfyUI environment
- **Search & Filter** - Quickly find specific packages
- **Per-Profile Exclusions** - Prevent specific packages from being installed when launching a profile
- **Version Information** - See installed versions at a glance

### Live Console
Real-time monitoring and control of ComfyUI.

- **Live Output** - See ComfyUI console output directly in the interface
- **Process Control** - Launch, stop, and restart ComfyUI with one click
- **Command Input** - Run Python/pip commands in the ComfyUI environment
- **Go To Comfy** - One-click button to open ComfyUI in your browser once the server is ready
- **Status Monitoring** - Real-time status indicator showing when ComfyUI is starting, running, or stopped

### User Experience
Thoughtful design choices for a smooth workflow.

- **Sticky Toolbars** - Search and filter controls stay visible while scrolling
- **Theme Sync** - Automatically matches your OS light/dark preference
- **Keyboard Shortcuts** - Quick access to common actions
- **Toast Notifications** - Non-intrusive feedback for all operations
- **Undo Support** - Recover from accidental node removal

### Dual Mode Operation
Use MF Conductor however it fits your workflow.

- **Standalone Mode** - Full-featured management without running ComfyUI
- **Integrated Mode** - Access directly within ComfyUI's interface

---

## Installation

### Method 1: ComfyUI Manager (Recommended)
Search for "MF Conductor" in ComfyUI Manager and click Install.

### Method 2: Git Clone
```bash
cd ComfyUI/custom_nodes
git clone https://github.com/squarewulf/ComfyUI_MFConductor.git
```

### Method 3: Manual Download
1. Download the latest release from the [Releases](https://github.com/squarewulf/ComfyUI_MFConductor) page
2. Extract to `ComfyUI/custom_nodes/MComfyUI_MFConductor`
3. Restart ComfyUI

---

## Usage

### Standalone Mode (Recommended)

Double-click `Launch_MFConductor.bat` or run:

```bash
python standalone_server.py
```

This starts a local web server at `http://localhost:8199`

**Why Standalone Mode?**
- Manage nodes and profiles while ComfyUI is running
- Live console output when launching ComfyUI
- Full profile management with launch control
- Monitor ComfyUI startup in real-time
- "Go To Comfy" button appears when server is ready

### Integrated Mode

When ComfyUI is running, access MF Conductor at:
```
http://localhost:8188/mf_conductor/
```

A "Node Manager" button will also appear in ComfyUI's sidebar.

---

## Profiles

Profiles are the core feature of MF Conductor - they let you define complete ComfyUI configurations that you can switch between instantly.

### Preset Profiles

MF Conductor comes with pre-configured profiles for common setups:

| Profile | Description |
|---------|-------------|
| **GPU - Standard** | Default configuration, balanced for most GPUs |
| **GPU - High VRAM** | For 16GB+ GPUs, maximizes performance |
| **GPU - Low VRAM** | For 6-8GB GPUs, optimizes memory usage |
| **GPU - Very Low VRAM** | For 4GB GPUs, aggressive memory optimization |
| **CPU Only** | Runs entirely on CPU, no GPU required |
| **DirectML** | For AMD/Intel GPUs on Windows |
| **Preview Mode** | Fast previews enabled for workflow development |

### Creating a Profile

1. Go to the **Profiles** tab
2. Click the **+ Add Profile** tile
3. Name your profile and optionally add a description
4. Choose an avatar from the gallery
5. In the **Nodes** section, select which nodes should be active
6. In the **Packages** section, exclude any problematic packages
7. In the **Flags** section, configure launch options
8. Click **Save**

### Profile Features

**Node Selection**
- Move nodes between Available and Selected
- Search to quickly find nodes
- Required nodes are marked and protected from removal

**Package Exclusions**
- Exclude packages that cause conflicts with certain node combinations
- Required packages are marked and protected

**Launch Flags**
- VRAM: `--lowvram`, `--highvram`, `--novram`, `--cpu`
- Attention: `--use-sage-attention`, `--use-pytorch-cross-attention`
- Preview: `--preview-method auto/taesd`
- Custom flags for any other options

### Profile Actions

**Right-Click Menu:**
- Launch with profile
- Edit profile settings
- Duplicate profile
- Set/remove as default
- Export to JSON file
- Delete profile

### How Node Enable/Disable Works

When you launch a profile, MF Conductor:
1. Renames disabled nodes to `folder_name.disabled`
2. Renames enabled nodes back from `.disabled`
3. ComfyUI ignores any folder with `.disabled` suffix

This is the same mechanism used by ComfyUI-Manager, ensuring compatibility.

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `/` | Focus search bar |
| `R` | Refresh node list |
| `N` | Open install modal |
| `B` | Open browse nodes |
| `U` | Check for updates |
| `Escape` | Close panels/modals |

---

## Tabs Overview

### Profiles Tab
Your command center for launching ComfyUI. Create, manage, and launch different configurations with one click.

### Nodes Tab
View, search, update, and manage all installed custom nodes. Install new nodes from URL or browse available nodes.

### Packages Tab
View all installed Python packages in the ComfyUI environment. Monitor your environment's dependencies.

### Console Tab
Live console output when ComfyUI is launched from MF Conductor. Includes command input for running pip commands and other Python scripts.

### Community Tab
Coming soon - share profiles and discover popular node combinations from the community.

---

## File Structure

```
MF_Conductor/
├── __init__.py              # ComfyUI integration & API routes
├── standalone_server.py     # Standalone HTTP server
├── node_scanner.py          # Node detection and scanning
├── git_utils.py             # Git operations and updates
├── user_data.py             # Profile and settings management
├── browse_nodes.py          # Community node discovery
├── Launch_MFConductor.bat    # Windows launcher
├── requirements.txt         # Python dependencies
├── README.md                # This file
├── LICENSE                  # MIT License
├── .gitignore               # Git ignore rules
├── data/                    # User data (auto-generated)
│   └── profiles.json        # Saved profiles
├── profiles/                # Generated batch files
├── js/
│   └── mf_conductor.js      # ComfyUI sidebar integration
└── web/
    ├── index.html           # Main UI
    ├── style.css            # Styles
    ├── app.js               # Frontend application
    ├── mfconductor_logo.svg # Logo
    └── avatars/             # Profile avatar images
```

---

## Troubleshooting

### "Git not found"
Install Git from https://git-scm.com/ and ensure it's in your PATH.

### Nodes not showing
Click the refresh button to rescan the custom_nodes directory.

### Can't install from URL
- Ensure the URL is a valid Git repository
- Check that Git is installed and accessible
- Some repositories may require authentication

### Console shows "Running (external)"
This means ComfyUI was started outside of MF Conductor. Console output is only captured when launched from MF Conductor.

### Profile nodes not applying
Make sure to close any externally running ComfyUI before launching from MF Conductor.

### Strange characters in console
If you see garbled text in the console, this is typically a Windows encoding issue. The console uses UTF-8 encoding.

---

## Technical Notes

- Uses Git for repository detection and updates
- Parses `pyproject.toml`, `package.json`, and README files for metadata
- Caches scan results for faster subsequent loads
- Standalone server runs on port 8199 to avoid conflicts with ComfyUI (8188)
- Node enable/disable uses folder renaming (compatible with ComfyUI-Manager)
- Profiles stored as JSON in `data/profiles.json`
- Auto-generates batch files for profile launches in `profiles/` directory

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

**Development Setup:**
1. Clone the repository to your `custom_nodes` folder
2. Run `Launch_MFConductor.bat` for development
3. Frontend is vanilla HTML/CSS/JS - no build step required

---

## License

MIT License - see [LICENSE](LICENSE) file for details.

---

<p align="center">
  <strong>Powered by <a href="https://friskcinema.com">FriskCinema</a></strong>
</p>

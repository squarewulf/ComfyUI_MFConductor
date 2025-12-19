# Contributing to MF Conductor

Thank you for your interest in contributing to MF Conductor! This document provides guidelines and information for contributors.

## Getting Started

1. Fork the repository
2. Clone your fork to your local machine
3. Install into your ComfyUI's `custom_nodes` directory
4. Make your changes
5. Test thoroughly
6. Submit a pull request

## Development Setup

### Prerequisites
- Python 3.10+
- Git
- ComfyUI installation (for testing integrated mode)

### Running in Development

**Standalone Mode:**
```bash
cd ComfyUI/custom_nodes/MF_Conductor
python standalone_server.py
```

**Integrated Mode:**
Simply start ComfyUI - MF Conductor will register its routes automatically.

## Code Style

- Follow PEP 8 for Python code
- Use meaningful variable and function names
- Add docstrings to functions and classes
- Keep functions focused and concise

### Frontend (JavaScript/CSS)
- Use camelCase for JavaScript variables and functions
- Use kebab-case for CSS classes
- Keep the UI consistent with existing design patterns
- Test across different browsers

## Project Structure

```
MF_Conductor/
├── __init__.py           # ComfyUI integration & API routes
├── standalone_server.py  # Standalone HTTP server
├── node_scanner.py       # Node discovery and metadata
├── git_utils.py          # Git operations
├── user_data.py          # User preferences storage
├── browse_nodes.py       # Browse available nodes
├── web/                  # Frontend files
│   ├── index.html
│   ├── style.css
│   └── app.js
└── js/                   # ComfyUI sidebar integration
    └── mf_conductor.js
```

## Submitting Changes

### Pull Request Guidelines

1. **Create a descriptive title** - Summarize what your PR does
2. **Describe your changes** - Explain what you changed and why
3. **Reference issues** - Link to any related issues
4. **Test your changes** - Ensure both modes work correctly
5. **Keep PRs focused** - One feature/fix per PR

### Commit Messages

Use clear, descriptive commit messages:
- `feat: Add node filtering by category`
- `fix: Resolve GitHub stars not loading`
- `docs: Update README installation instructions`
- `style: Fix CSS alignment in profile modal`

## Reporting Bugs

When reporting bugs, please include:
- Description of the issue
- Steps to reproduce
- Expected behavior
- Actual behavior
- Screenshots if applicable
- Your environment (OS, Python version, ComfyUI version)

## Feature Requests

Feature requests are welcome! Please:
- Check existing issues first
- Describe the feature clearly
- Explain the use case
- Consider implementation implications

## Questions?

Feel free to open an issue for questions or discussions about the project.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.



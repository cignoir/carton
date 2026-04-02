# Carton

A local-first package manager for Maya. Manage distribution, installation, and updates of your tools through local registries.

[日本語版はこちら](README_ja.md)

## Features

- **Local First** — No AWS or cloud services required. Works with local directories only
- **Multiple Registries** — Add registries per team, project, or personal use
- **One-Click Install** — Drag & drop a `.py` file onto Maya's viewport
- **Local Script Registration** — Register single files or folders from the UI. Reference-based, so edits are reflected immediately
- **Publish** — Share locally registered scripts to a registry with one click
- **Auto Update** — Carton itself updates automatically from GitHub Releases
- **Emoji Icons** — Use emoji as package icons. Image files also supported
- **VCS Agnostic** — Registries work with Git, SVN, network drives, or anything

## Requirements

- Maya 2024 / 2025 / 2026 / 2027
- PySide2 (Maya < 2025) / PySide6 (Maya >= 2025)

## Quick Start

### Installation

1. Download `install_carton.py` from [Releases](https://github.com/cignoir/carton/releases)
2. Open Maya and drag & drop the file onto the viewport
3. Restart Maya
4. Menu bar → "Carton" → "Open Carton"

### Add a Registry

1. Carton → Settings (⚙) → + Add
2. Select the path to a `registry.json`

### Install a Tool

1. Open Carton → Package list from registries is displayed
2. Click Install → Done

### Register & Share a Script

1. Carton → + Add → Select a file or folder
2. Set Display Name, Icon, Run Mode → Register
3. Click Publish → Select target registry → Shared

## Registry Structure

A registry is a directory containing `registry.json`. Manage it with VCS, put it on a network drive — whatever works for you.

```
my-registry/
├── registry.json
├── packages/
│   └── {uuid}/{version}/
│       └── {name}-{version}.zip
└── icons/
    └── {name}.png  (optional)
```

### registry.json

```json
{
  "schema_version": "2.0",
  "packages": {
    "uuid-here": {
      "name": "my_tool",
      "display_name": "My Tool",
      "type": "python_package",
      "icon": "🔧",
      "description": "Tool description",
      "author": "your_name",
      "latest_version": "1.0.0",
      "versions": {
        "1.0.0": {
          "download_url": "packages/uuid-here/1.0.0/my_tool-1.0.0.zip",
          "sha256": "...",
          "size_bytes": 12345,
          "maya_versions": ["2024", "2025", "2026", "2027"],
          "released_at": "2026-04-03T00:00:00Z"
        }
      }
    }
  }
}
```

`download_url` is relative to registry.json's parent directory. Absolute paths and URLs are also accepted.

## package.json

Metadata file placed in each tool repository.

```json
{
  "name": "my_tool",
  "display_name": "My Tool",
  "version": "1.0.0",
  "type": "python_package",
  "description": "Tool description",
  "author": "your_name",
  "maya_versions": ["2024", "2025", "2026", "2027"],
  "entry_point": {
    "type": "python",
    "module": "my_tool",
    "function": "show"
  },
  "icon": "🔧"
}
```

`icon` accepts an emoji (`"📷"`) or an image path (`"resources/icon.png"`).

## Development

### Tests

```bash
cd carton
python -m pytest tests/ -v
```

### Dev Reload in Maya

```python
exec(open(r"path/to/carton/scripts/dev_reload.py", encoding="utf-8").read())
```

## Architecture

```
carton/
├── carton/                      # Package manager core
│   ├── core/
│   │   ├── config.py            # Multi-registry configuration
│   │   ├── registry_client.py   # Load & merge multiple registries
│   │   ├── publisher.py         # Write directly to registry
│   │   ├── downloader.py        # Local copy / URL download
│   │   ├── installer.py         # Install / uninstall
│   │   ├── updater.py           # Version comparison
│   │   ├── self_updater.py      # GitHub Releases auto-update
│   │   ├── script_manager.py    # Local script registration
│   │   ├── env_manager.py       # Maya environment variable management
│   │   └── handlers/            # Per-type package handlers
│   ├── models/
│   └── ui/
│       ├── main_window.py       # Registry grouping
│       ├── settings_dialog.py   # Registry management UI
│       ├── add_dialog.py        # Local registration (file / folder)
│       └── edit_dialog.py       # Metadata editing
├── bootstrap/
├── installer/
├── .github/workflows/
│   └── release.yml              # Attach installer to GitHub Releases
└── tests/
```

## License

MIT

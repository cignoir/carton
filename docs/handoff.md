# Carton — Handoff Document

> **Archived snapshot (v0.4 era).**
> This document is a frozen session handoff from 2026-04-02 ~ 2026-04-03.
> It describes Carton before the v5.0 "Package-first" redesign and uses
> v0.4 terminology (``registry.json`` / ``registries`` / ``registry_id``
> / ``registry_client.py`` / schema 2.0) throughout. For the current
> design see:
> * ``README.md`` / ``README_ja.md`` — user-facing v5.0 behaviour
> * ``CLAUDE.md`` — architecture summary and internal terminology
> * ``schemas/catalogue.schema.json`` — v5.0 catalogue format
> * ``carton/core/catalogue_client.py`` — current merge + projection code
>
> Left in place so the design history remains browsable, and because
> the v4→v5 migrator paths in ``carton/core/migrations/`` still speak
> the v0.4 shape described below.

Session date: 2026-04-02 ~ 2026-04-03

## Background

Carton is a rewrite of "Ashbox", a Maya package manager originally built on AWS (S3, CloudFront, Lambda, API Gateway). Through development and testing, we concluded that cloud infrastructure was overkill for internal tool distribution. Carton is the local-first successor — no AWS dependencies, multiple registry support, and GitHub Releases for self-update.

The Ashbox repository (`F:\workspace\ashbox`) remains as a reference but is no longer actively developed. The cigref tool (`F:\workspace\cigref`) was migrated from `maya_ref_tool` as a test case.

## Current State

### What Works
- **D&D installer**: `dist/install_carton_*.py` → Maya viewport → restart → Carton menu appears
- **Language-specific installers**: `install_carton_ja_v*.py` forces Japanese, `install_carton_en_v*.py` forces English, plain `install_carton_v*.py` auto-detects from Maya locale
- **Multiple registries**: Add via Settings, reads local `registry.json` files
- **Local script registration**: + Add → file or folder → reference-based (edits reflected immediately)
- **Publish**: Local → registry directory (zip + registry.json update)
- **Unpublish**: From Edit dialog when local UUID matches registry; also CLI admin tool
- **Install / Launch / Uninstall**: From registry packages
- **Update detection**: Version comparison, orange Update button
- **Self-update**: GitHub Releases check → stage → bootstrap apply (tested end-to-end, requires public repo)
- **i18n**: Full Japanese/English support, auto-detected from Maya locale
- **Registry grouping**: UI groups packages by registry name, collapsible
- **Edit dialog**: Metadata editing for local scripts
- **Emoji icons**: Package icons can be emoji or image paths
- **package.json auto-detection**: Folders with package.json skip Run Mode selection
- **UUID persistence**: UUID survives Remove → re-Add cycles via package.json
- **Tests**: 38 tests, all passing
- **CI/CD**: GitHub Actions builds language-specific installers + update zip on tag push

### What Doesn't Work / Needs Attention
- **Self-update requires public repo**: GitHub API returns 404 for private repos without auth token. If private distribution is needed, either add token support to config or switch to registry-based update detection.

## Open Design Questions

These were discussed but not yet implemented. They should be addressed in the next session.

### 1. Registry Management UI (Standalone)

A standalone tool (not inside Carton) that lets registry admins:
- Browse all packages in a registry
- Unpublish / delete packages
- Edit metadata
- View download stats (if logging is added later)

CLI admin commands already exist (`python -m carton list`, `python -m carton unpublish`).
Could be extended with a GUI, or launched as a mode of Carton with a flag.

### 2. Version Sync Between Local and Registry

When a user edits version locally and re-Publishes:
- The registry should add a new version entry (not overwrite)
- Same-version re-publish is already blocked
- Users on other machines see the Update button

Currently working correctly. UUID persistence ensures consistent identity across cycles.

## Architecture

```
F:\workspace\carton\
├── carton/                      # Package manager core
│   ├── __init__.py              # Entry point: startup(), show(), open_settings()
│   ├── __main__.py              # CLI entry: python -m carton <command>
│   ├── cli.py                   # Admin CLI (list, unpublish)
│   ├── core/
│   │   ├── config.py            # Multi-registry config (registries list)
│   │   ├── registry_client.py   # Load + merge multiple registries
│   │   ├── publisher.py         # Publish + unpublish to local registry
│   │   ├── downloader.py        # Local copy or HTTP download
│   │   ├── installer.py         # Install / uninstall (UUID-keyed)
│   │   ├── updater.py           # Version comparison
│   │   ├── self_updater.py      # GitHub Releases check (carton-v*.zip asset)
│   │   ├── script_manager.py    # Local script registration (reference-based)
│   │   ├── env_manager.py       # Maya env var management
│   │   ├── hash_verify.py       # SHA256
│   │   └── handlers/            # Strategy pattern for package types
│   ├── models/
│   │   ├── package_info.py      # PackageInfo model
│   │   └── version.py           # Semantic versioning
│   └── ui/
│       ├── main_window.py       # Main window with registry grouping
│       ├── package_card.py      # Package card widget
│       ├── package_detail.py    # Package detail panel
│       ├── add_dialog.py        # Add file/folder dialog
│       ├── edit_dialog.py       # Edit metadata + unpublish dialog
│       ├── settings_dialog.py   # Registry management + uninstall
│       ├── shelf.py             # Maya menu registration
│       ├── compat.py            # PySide2/6 compatibility
│       └── i18n.py              # Internationalization (en/ja)
├── bootstrap/
│   ├── userSetup.py             # Maya scripts/ entry
│   └── carton_bootstrap.py      # Self-update + import carton
├── installer/
│   └── install_carton.template.py  # D&D installer template
├── .github/workflows/
│   └── release.yml              # GitHub Release + installer generation
├── schemas/                     # JSON schemas
├── scripts/
│   ├── build_installer.py       # Build D&D installers (auto/ja/en + update zip)
│   └── dev_reload.py            # Maya dev reload
├── tests/                       # 38 tests
├── package.json
├── README.md                    # English
└── README_ja.md                 # Japanese
```

## Key Files to Understand

| File | Purpose |
|------|---------|
| `carton/__init__.py` | Initialization flow: config → i18n → services → activate packages → menu |
| `core/config.py` | `Config` with `registries` list of `RegistryEntry` objects. Path normalization on all platforms |
| `core/registry_client.py` | Loads all registries, merges packages, resolves relative `download_url` |
| `core/publisher.py` | Creates zip from local file/folder, writes to registry dir. Also `unpublish()` and `find_published_registries()` |
| `core/self_updater.py` | Checks GitHub Releases for `carton-v*.zip` asset, stages for bootstrap apply |
| `core/script_manager.py` | Reference-based local registration. Supports exec/function/folder modes |
| `ui/main_window.py` | Largest UI file. Registry grouping, all button handlers including unpublish |
| `ui/edit_dialog.py` | Metadata editing. Shows Unpublish button when local UUID exists in a registry |
| `ui/i18n.py` | All translatable strings. `t(key, *args)` function |
| `ui/add_dialog.py` | Detects package.json, hides Run Mode when present |
| `carton/cli.py` | Admin CLI: `python -m carton list <registry>`, `python -m carton unpublish --registry <path> --id <uuid>` |
| `scripts/build_installer.py` | Builds language-specific installers + update zip |

## Config Format

```json
{
  "registries": [
    {"name": "company", "path": "//server/share/registry.json"},
    {"name": "personal", "path": "D:/my-tools/registry.json"}
  ],
  "install_dir": "C:/Users/xxx/Documents/maya/carton",
  "auto_check_updates": true,
  "github_repo": "cignoir/carton",
  "language": "auto"
}
```

`language` values: `"auto"` (Maya locale), `"ja"`, `"en"`. Set by installer variant.

## Registry Format

```json
{
  "schema_version": "2.0",
  "packages": {
    "<uuid>": {
      "name": "cigref",
      "display_name": "CigRef",
      "type": "python_package",
      "icon": "📷",
      "description": "...",
      "author": "cignoir",
      "latest_version": "1.0.0",
      "versions": {
        "1.0.0": {
          "download_url": "packages/<uuid>/1.0.0/cigref-1.0.0.zip",
          "sha256": "...",
          "size_bytes": 32000,
          "maya_versions": ["2024", "2025", "2026", "2027"],
          "released_at": "2026-04-03T00:00:00Z"
        }
      }
    }
  }
}
```

`download_url` is relative to registry.json's parent directory.

## Development Workflow

### Dev reload in Maya
```python
exec(open(r"F:\workspace\carton\scripts\dev_reload.py", encoding="utf-8").read())
```

### Build installers
```bash
cd F:/workspace/carton
python scripts/build_installer.py
python scripts/build_installer.py --version 1.2.3
python scripts/build_installer.py --lang ja      # Japanese only
```

Output:
```
dist/
├── carton-v0.1.0.zip              ← Self-update zip (GitHub Release asset)
├── install_carton_v0-1-0.py       ← Installer (auto language)
├── install_carton_ja_v0-1-0.py    ← Installer (Japanese)
└── install_carton_en_v0-1-0.py    ← Installer (English)
```

### Run tests
```bash
cd F:\workspace\carton
python -m pytest tests/ -v
```

### CLI admin commands
```bash
python -m carton list path/to/registry.json
python -m carton unpublish --registry path/to/registry.json --id <uuid>
python -m carton unpublish --registry path/to/registry.json --id <uuid> --force
```

## Install Directory

All components use the same shared directory (not Maya-version-specific):
- Windows: `~/Documents/maya/carton/`
- Linux/Mac: `~/maya/carton/`

This is consistent across: installer, bootstrap, and `Config.load()`.

## Release Workflow

1. Bump version: edit `package.json` (CI syncs to `__init__.py`)
2. Tag: `git tag v0.2.0 && git push --tags`
3. CI builds: 3 installers + 1 update zip
4. GitHub Release created with all 4 assets
5. Existing Carton installs detect the new version via GitHub API
6. User clicks Update → zip staged → next Maya restart applies it

## Related Repositories

| Repository | Path | Purpose |
|-----------|------|---------|
| carton | `F:\workspace\carton` | Package manager (this repo) |
| ashbox | `F:\workspace\ashbox` | Previous version (AWS-based, archived) |
| cigref | `F:\workspace\cigref` | CigRef tool (test package) |
| carton-tool-template | `F:\workspace\ashbox-tool-template` | Tool template (rename repo to carton-tool-template on GitHub) |
| ashbox-registry | `F:\workspace\ashbox-registry` | Old registry (AWS, deprecated) |
| cigmaya | `F:\workspace\cigmaya` | Test local registry |

## Next Steps

1. **Rename ashbox-tool-template on GitHub** — Contents already updated. Rename repo to `carton-tool-template` via GitHub Settings.

## Coding Conventions

- Source code comments and docstrings: **English only**
- UI text: Managed through `i18n.py`, supports en/ja
- Version source of truth: **git tag** (CI/CD syncs to package.json and __init__.py)
- Package ID: **UUID v4**, auto-generated on first Publish if not present
- Path handling: All paths normalized via `os.path.normpath` (no mixed `/` and `\`)

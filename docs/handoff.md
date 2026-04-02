# Carton — Handoff Document

Session date: 2026-04-02 ~ 2026-04-03

## Background

Carton is a rewrite of "Ashbox", a Maya package manager originally built on AWS (S3, CloudFront, Lambda, API Gateway). Through development and testing, we concluded that cloud infrastructure was overkill for internal tool distribution. Carton is the local-first successor — no AWS dependencies, multiple registry support, and GitHub Releases for self-update.

The Ashbox repository (`F:\workspace\ashbox`) remains as a reference but is no longer actively developed. The cigref tool (`F:\workspace\cigref`) was migrated from `maya_ref_tool` as a test case.

## Current State

### What Works
- **D&D installer**: `dist/install_carton.py` → Maya viewport → restart → Carton menu appears
- **Multiple registries**: Add via Settings, reads local `registry.json` files
- **Local script registration**: + Add → file or folder → reference-based (edits reflected immediately)
- **Publish**: Local → registry directory (zip + registry.json update)
- **Install / Launch / Uninstall**: From registry packages
- **Update detection**: Version comparison, orange Update button
- **Self-update**: GitHub Releases check (not yet tested end-to-end)
- **i18n**: Full Japanese/English support, auto-detected from Maya locale
- **Registry grouping**: UI groups packages by registry name, collapsible
- **Edit dialog**: Metadata editing for local scripts
- **Emoji icons**: Package icons can be emoji or image paths
- **package.json auto-detection**: Folders with package.json skip Run Mode selection
- **Tests**: 26 tests, all passing

### What Doesn't Work / Needs Attention
- **Self-update not tested end-to-end**: GitHub Release → staging → bootstrap apply flow needs real testing with a published release
- **Publish creates duplicate UUIDs**: If a user Publishes, then Removes local, then re-Adds and Publishes again, a new UUID is generated. UUID should persist across Publish cycles.

## Open Design Questions

These were discussed but not yet implemented. They should be addressed in the next session.

### 1. Publish / Unpublish Architecture

**Current behavior:**
- Local Add generates a UUID
- Publish copies zip to registry directory + updates registry.json with that UUID
- Source changes from `local_script` to `published` (prevents duplicate display)
- Local registration is effectively hidden after Publish

**Desired behavior:**
- Publish should keep local registration visible (don't hide it)
- UUID must stay consistent between local and registry for version updates
- Unpublish should be possible from two places:
  - Carton UI: if the same UUID exists locally, show an "Unpublish" button
  - Registry management UI: standalone tool for registry administrators

**Key decisions needed:**
- How to handle UUID persistence across Remove → re-Add cycles
- Whether to store a `_publish_id` in installed.json to remember the registry UUID
- Unpublish confirmation flow (what happens to users who installed it?)

### 2. Registry Management UI (Standalone)

A standalone tool (not inside Carton) that lets registry admins:
- Browse all packages in a registry
- Unpublish / delete packages
- Edit metadata
- View download stats (if logging is added later)

Could be a separate script or a mode of Carton launched with a flag.

### 3. Version Sync Between Local and Registry

When a user edits version locally and re-Publishes:
- The registry should add a new version entry (not overwrite)
- Same-version re-publish is already blocked
- Users on other machines see the Update button

Currently working correctly, but the UUID duplication issue (see above) can break this flow.

## Architecture

```
F:\workspace\carton\
├── carton/                      # Package manager core
│   ├── __init__.py              # Entry point: startup(), show(), open_settings()
│   ├── core/
│   │   ├── config.py            # Multi-registry config (registries list)
│   │   ├── registry_client.py   # Load + merge multiple registries
│   │   ├── publisher.py         # Write zip + registry.json to local registry
│   │   ├── downloader.py        # Local copy or HTTP download
│   │   ├── installer.py         # Install / uninstall (UUID-keyed)
│   │   ├── updater.py           # Version comparison
│   │   ├── self_updater.py      # GitHub Releases check
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
│       ├── edit_dialog.py       # Edit metadata dialog
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
│   ├── dev_reload.py            # Maya dev reload
│   └── demo_standalone.py       # Standalone test (needs update for new config)
├── tests/                       # 26 tests
├── package.json
├── README.md                    # English
└── README_ja.md                 # Japanese
```

## Key Files to Understand

| File | Purpose |
|------|---------|
| `carton/__init__.py` | Initialization flow: config → i18n → services → activate packages → menu |
| `core/config.py` | `Config` with `registries` list of `RegistryEntry` objects |
| `core/registry_client.py` | Loads all registries, merges packages, resolves relative `download_url` |
| `core/publisher.py` | Creates zip from local file/folder, writes to registry dir |
| `core/script_manager.py` | Reference-based local registration. Supports exec/function/folder modes |
| `ui/main_window.py` | Largest UI file. Registry grouping, all button handlers |
| `ui/i18n.py` | All translatable strings. `t(key, *args)` function |
| `ui/add_dialog.py` | Detects package.json, hides Run Mode when present |

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

### Build installer
```python
cd F:/workspace/carton
python -c "
import zipfile, os, base64
zip_path = 'dist/carton.zip'
os.makedirs('dist', exist_ok=True)
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk('carton'):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in files:
            if not f.endswith('.pyc'):
                zf.write(os.path.join(root, f))
with open(zip_path, 'rb') as f:
    b64 = base64.b64encode(f.read()).decode('ascii')
with open('installer/install_carton.template.py', 'r', encoding='utf-8') as f:
    template = f.read()
out = template.replace('__VERSION__', '0.1.0').replace('__CARTON_ZIP_B64__', b64)
with open('dist/install_carton.py', 'w', encoding='utf-8') as f:
    f.write(out)
"
```

### Run tests
```bash
cd F:\workspace\carton
python -m pytest tests/ -v
```

## Related Repositories

| Repository | Path | Purpose |
|-----------|------|---------|
| carton | `F:\workspace\carton` | Package manager (this repo) |
| ashbox | `F:\workspace\ashbox` | Previous version (AWS-based, archived) |
| cigref | `F:\workspace\cigref` | CigRef tool (test package) |
| ashbox-tool-template | `F:\workspace\ashbox-tool-template` | Tool template (needs renaming to carton-tool-template) |
| ashbox-registry | `F:\workspace\ashbox-registry` | Old registry (AWS, deprecated) |
| cigmaya | `F:\workspace\cigmaya` | Test local registry |

## Next Steps (Priority Order)

1. **Fix UUID persistence** — Ensure local registration UUID survives Remove → re-Add. Consider storing publish UUID in package.json or a local mapping file.

2. **Unpublish from Carton UI** — Add "Unpublish" button to Edit dialog when the same UUID exists in a registry. Removes zip + registry.json entry.

3. **Registry management standalone UI** — Separate tool for registry admins. Could be `python -m carton.registry_admin` or a menu item.

4. **Rename ashbox-tool-template** — Update to carton-tool-template with Carton's release.yml.

5. **CI/CD testing** — Push carton to GitHub, create first release, verify installer generation and self-update flow.

6. **demo_standalone.py** — Update for new multi-registry config (currently references old Ashbox AWS endpoints).

7. **Additional languages** — i18n framework is ready. Add zh_CN, ko, etc. as needed.

## Coding Conventions

- Source code comments and docstrings: **English only**
- UI text: Managed through `i18n.py`, supports en/ja
- Version source of truth: **git tag** (CI/CD syncs to package.json and __init__.py)
- Package ID: **UUID v4**, auto-generated on first Publish if not present

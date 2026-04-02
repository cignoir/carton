"""Carton standalone demo — end-to-end test without Maya.

Usage:
    cd F:/workspace/carton
    python scripts/demo_standalone.py
"""

import json
import os
import sys
import tempfile

# Set Windows stdout to UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# Enable importing carton
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from carton.core.config import Config
from carton.core.registry_client import RegistryClient
from carton.core.presign_client import PresignClient
from carton.core.downloader import Downloader
from carton.core.env_manager import MayaEnvManager
from carton.core.installer import InstallManager
from carton.core.updater import Updater
from carton.core.self_updater import SelfUpdater
from carton.models.version import Version

# ---- Settings ----
REGISTRY_URL = "https://d1vruaegycgtru.cloudfront.net/registry.json"
PRESIGN_API_URL = "https://elybq2g9g5.execute-api.ap-northeast-1.amazonaws.com/prod/presign"
API_KEY = "vQgrAn2Dkb8kBSnMhusX17b6HAK8FZJtak3TIfp7"


def main():
    # Temporary directory for testing
    with tempfile.TemporaryDirectory(prefix="carton-demo-") as tmpdir:
        print("=" * 50)
        print("Carton Standalone Demo")
        print("Install dir:", tmpdir)
        print("=" * 50)

        # 1. Config
        print("\n[1] Config initialization...")
        config = Config(
            registry_url=REGISTRY_URL,
            presign_api_url=PRESIGN_API_URL,
            api_key=API_KEY,
            install_dir=tmpdir,
        )
        config.save()
        print("    OK: config.json saved")

        # 2. Fetch registry
        print("\n[2] Fetch registry (CloudFront)...")
        registry = RegistryClient(config)
        data = registry.fetch()
        packages = data.get("packages", {})
        print("    schema_version:", data.get("schema_version"))
        print("    packages:", list(packages.keys()))

        # 3. Display package info
        print("\n[3] Package info...")
        for name, pkg in packages.items():
            latest = pkg.get("latest_version", "?")
            print("    {} v{} ({})".format(
                pkg.get("display_name", name), latest, pkg.get("type", "?")
            ))
            print("      ", pkg.get("description", ""))

        # 4. Get pre-signed URL
        print("\n[4] Get pre-signed URL (API Gateway -> Lambda)...")
        presign = PresignClient(config)
        url = presign.get_download_url("carton-hello", "1.0.0")
        print("    URL:", url[:80] + "...")

        # 5. Download + SHA256 verification
        print("\n[5] Download + SHA256 verification...")
        dl = Downloader(config)
        version_info = packages["carton-hello"]["versions"]["1.0.0"]
        zip_path = os.path.join(config.staging_dir, "carton-hello-1.0.0.zip")
        dl.download(
            url, zip_path,
            expected_sha256=version_info.get("sha256"),
            expected_size=version_info.get("size_bytes"),
        )
        print("    OK: downloaded to", zip_path)
        print("    SHA256 verified!")

        # 6. Install
        print("\n[6] Install...")
        env_mgr = MayaEnvManager()
        install_mgr = InstallManager(config, env_mgr)

        meta = {
            "name": "carton-hello",
            "version": "1.0.0",
            "type": "python_package",
            "display_name": "Hello Carton",
            "entry_point": {"type": "python", "module": "carton_hello", "function": "show"},
        }
        install_mgr.install_package(zip_path, meta)
        print("    OK: installed!")
        print("    installed.json:", json.dumps(
            install_mgr.get_installed_packages(), indent=2, ensure_ascii=False
        ))

        # 7. Package import test
        print("\n[7] Import test...")
        pkg_dir = os.path.join(config.packages_dir, "carton-hello")
        if pkg_dir not in sys.path:
            sys.path.insert(0, pkg_dir)
        try:
            import carton_hello
            print("    carton_hello.__version__:", carton_hello.__version__)
        except (ImportError, NameError) as e:
            print("    (PySide not available, skipping UI import: {})".format(e))
            # Just check the version
            init_path = os.path.join(pkg_dir, "carton_hello", "__init__.py")
            if os.path.exists(init_path):
                with open(init_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if "__version__" in line:
                            print("    Found:", line.strip())
                            break

        # 8. Check for updates
        print("\n[8] Check for updates...")
        updater = Updater(registry, install_mgr)
        updates = updater.check_all_updates()
        if updates:
            for u in updates:
                print("    Update available: {} {} → {}".format(u.name, u.current_version, u.latest_version))
        else:
            print("    All packages up to date!")

        # 9. Uninstall
        print("\n[9] Uninstall...")
        install_mgr.uninstall_package("carton-hello")
        print("    OK: uninstalled")
        print("    Remaining:", list(install_mgr.get_installed_packages().keys()))

        print("\n" + "=" * 50)
        print("All steps passed!")
        print("=" * 50)


if __name__ == "__main__":
    main()

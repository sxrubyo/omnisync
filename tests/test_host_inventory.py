import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from host_inventory import (  # noqa: E402
    build_default_manifest,
    ensure_manifest,
    expand_path,
    is_excluded,
    scan_home,
)


class HostInventoryTests(unittest.TestCase):
    def test_build_default_manifest_has_expected_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = build_default_manifest(tmp)
            self.assertEqual(manifest["profile"], "production-clean")
            self.assertTrue(any(path.endswith("melissa") for path in manifest["state_paths"]))
            self.assertTrue(any(path.endswith(".ssh") for path in manifest["secret_paths"]))

    def test_ensure_manifest_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "config" / "system_manifest.json"
            manifest = ensure_manifest(manifest_path, tmp)
            self.assertTrue(manifest_path.exists())
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["profile"], manifest["profile"])

    def test_exclude_matching(self):
        self.assertTrue(is_excluded("home/ubuntu/project/node_modules/pkg/index.js", ["node_modules"]))
        self.assertTrue(is_excluded("home/ubuntu/project/logs/app.log", ["logs"]))
        self.assertFalse(is_excluded("home/ubuntu/project/src/app.py", ["node_modules", ".cache"]))

    def test_scan_home_classifies_product_and_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "melissa").mkdir()
            (home / ".cache").mkdir()
            manifest = {
                "profile": "production-clean",
                "state_paths": [expand_path("~/melissa", tmp)],
                "secret_paths": [],
                "exclude_patterns": [],
            }
            report = scan_home(tmp, manifest)
            discovered = {item["name"]: item["classification"] for item in report["discovered"]}
            self.assertEqual(discovered["melissa"], "state")
            self.assertEqual(discovered[".cache"], "noise")


if __name__ == "__main__":
    unittest.main()

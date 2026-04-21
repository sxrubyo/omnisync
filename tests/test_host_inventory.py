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
    build_profile_manifest,
    build_state_exclude_patterns,
    classify_path,
    discover_full_home_secret_paths,
    ensure_manifest,
    expand_path,
    is_excluded,
    normalize_manifest,
    scan_home,
)


class HostInventoryTests(unittest.TestCase):
    def test_build_default_manifest_has_expected_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = build_default_manifest(tmp)
            self.assertEqual(manifest["profile"], "production-clean")
            self.assertTrue(any(path.endswith("melissa") for path in manifest["state_paths"]))
            self.assertTrue(any(path.endswith(".ssh") for path in manifest["secret_paths"]))

    def test_build_full_home_profile_uses_home_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".ssh").mkdir()
            (home / ".ssh" / "id_rsa").write_text("PRIVATE", encoding="utf-8")
            (home / ".env").write_text("TOKEN=abc123\n", encoding="utf-8")
            manifest = build_profile_manifest("full-home", tmp)
            self.assertEqual(manifest["profile"], "full-home")
            self.assertEqual(manifest["state_paths"], [expand_path(home.as_posix(), tmp)])
            self.assertTrue(any(path.endswith(".ssh") for path in manifest["secret_paths"]))
            self.assertTrue(any(path.endswith(".env") for path in manifest["secret_paths"]))
            self.assertFalse(any(path.endswith("dump.pm2") for path in manifest["secret_paths"]))
            self.assertTrue(any(path.endswith("backups/auto-bundles") for path in manifest["state_exclude_paths"]))
            patterns = build_state_exclude_patterns(manifest, tmp)
            self.assertIn(".ssh", patterns)
            self.assertIn(".env", patterns)

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

    def test_classify_path_preserves_product_and_noise_hints_inside_full_home_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "melissa").mkdir()
            (home / ".codex").mkdir()
            manifest = build_profile_manifest("full-home", tmp)

            self.assertEqual(classify_path(home / "melissa", manifest), "product")
            self.assertEqual(classify_path(home / ".codex", manifest), "noise")
            self.assertEqual(classify_path(home, manifest), "state")

    def test_normalize_manifest_keeps_explicit_empty_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = normalize_manifest(
                {
                    "profile": "full-home",
                    "state_paths": [],
                    "secret_paths": [],
                    "install_targets": [],
                    "pm2_ecosystems": [],
                    "compose_projects": [],
                },
                tmp,
            )
            self.assertEqual(manifest["state_paths"], [])
            self.assertEqual(manifest["secret_paths"], [])

    def test_full_home_secret_discovery_ignores_examples_and_deep_test_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / "melissa").mkdir()
            (home / "melissa" / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
            (home / "nova-os" / ".env.example").parent.mkdir(parents=True)
            (home / "nova-os" / ".env.example").write_text("EXAMPLE=1\n", encoding="utf-8")
            deep_cert = home / "go" / "pkg" / "mod" / "vendor" / "tests" / "example-cert.pem"
            deep_cert.parent.mkdir(parents=True)
            deep_cert.write_text("CERT\n", encoding="utf-8")

            discovered = discover_full_home_secret_paths(tmp)
            self.assertIn(str(home / "melissa" / ".env"), discovered)
            self.assertNotIn(str(home / "nova-os" / ".env.example"), discovered)
            self.assertNotIn(str(deep_cert), discovered)


if __name__ == "__main__":
    unittest.main()

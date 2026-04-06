import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime_inventory_ops import (  # noqa: E402
    load_installed_inventory,
    merge_manifest_runtime_inventory,
    summarize_installed_inventory,
    write_installed_inventory,
)


class RuntimeInventoryOpsTests(unittest.TestCase):
    def test_write_and_load_installed_inventory_round_trip(self):
        payload = {
            "apt_packages": ["git", "python3"],
            "python_packages": ["openai==2.26.0"],
            "npm_global_packages": ["pm2"],
            "pm2_processes": [{"name": "melissa", "status": "online"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp)
            written = write_installed_inventory(target_dir, payload)
            loaded = load_installed_inventory(target_dir)
            self.assertEqual(Path(written), Path(loaded["path"]))
            self.assertEqual(loaded["apt_packages"], ["git", "python3"])

    def test_merge_manifest_runtime_inventory_extends_install_lists(self):
        manifest = {
            "apt_packages": ["git"],
            "python_packages": ["fastapi==0.135.1"],
            "npm_global_packages": ["pm2"],
        }
        runtime = {
            "apt_packages": ["git", "jq"],
            "python_packages": ["fastapi==0.135.1", "openai==2.26.0"],
            "npm_global_packages": ["pm2", "@openai/codex"],
        }
        merged = merge_manifest_runtime_inventory(manifest, runtime)
        self.assertEqual(merged["apt_packages"], ["git", "jq"])
        self.assertEqual(merged["python_packages"], ["fastapi==0.135.1", "openai==2.26.0"])
        self.assertEqual(merged["npm_global_packages"], ["pm2", "@openai/codex"])

    def test_summarize_installed_inventory_outputs_counts(self):
        lines = summarize_installed_inventory(
            {
                "apt_packages": ["git", "python3", "jq"],
                "python_packages": ["openai==2.26.0"],
                "npm_global_packages": ["pm2", "@openai/codex"],
                "pm2_processes": [{"name": "melissa", "status": "online"}],
            }
        )
        joined = "\n".join(lines)
        self.assertIn("APT", joined)
        self.assertIn("PM2", joined)


if __name__ == "__main__":
    unittest.main()

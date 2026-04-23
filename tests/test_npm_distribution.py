from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path("/home/ubuntu/omni-core")


class NpmDistributionTests(unittest.TestCase):
    def test_package_metadata_exists_for_public_publish(self) -> None:
        package_path = REPO_ROOT / "package.json"
        self.assertTrue(package_path.exists(), msg="package.json is required for npm publishing")
        payload = json.loads(package_path.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("name"), "omnisync")
        self.assertEqual(payload.get("bin", {}).get("omni"), "npm/omni.js")
        self.assertEqual(payload.get("publishConfig", {}).get("access"), "public")

    @unittest.skipUnless(shutil.which("npm"), "npm is required")
    def test_npm_pack_dry_run_succeeds(self) -> None:
        result = subprocess.run(
            ["npm", "pack", "--dry-run", "--json"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload)
        first = payload[0]
        files = {item["path"] for item in first.get("files", [])}
        self.assertIn(".codex/skills/omni-sync/SKILL.md", files)
        self.assertIn("package.json", files)
        self.assertIn("npm/omni.js", files)
        self.assertIn("install.sh", files)
        self.assertNotIn("config/repos.json", files)
        self.assertFalse(any(path.startswith(".claude/handoffs/") for path in files))
        self.assertFalse(any("__pycache__" in path for path in files))

    @unittest.skipUnless(shutil.which("node"), "node is required")
    def test_npm_launcher_bootstraps_and_executes_omni(self) -> None:
        home_root = REPO_ROOT / ".tmp" / "npm-home"
        if home_root.exists():
            shutil.rmtree(home_root)
        self.addCleanup(shutil.rmtree, home_root, ignore_errors=True)
        home_root.mkdir(parents=True, exist_ok=True)

        env = {
            **dict(os.environ),
            "HOME": str(home_root),
            "OMNI_INSTALL_HOME": str(home_root / ".omni"),
            "OMNI_INSTALL_SKIP_DEPENDENCY_BOOTSTRAP": "1",
        }
        result = subprocess.run(
            ["node", "npm/omni.js", "help"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        self.assertNotIn("Repaired preexisting omni runtime", result.stdout)
        self.assertIn("OmniSync - Command Reference", result.stdout)

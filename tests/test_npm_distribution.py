from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class NpmDistributionTests(unittest.TestCase):
    def test_package_metadata_exists_for_public_publish(self) -> None:
        package_path = REPO_ROOT / "package.json"
        self.assertTrue(package_path.exists(), msg="package.json is required for npm publishing")
        payload = json.loads(package_path.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("name"), "omnisync")
        self.assertEqual(payload.get("bin", {}).get("omni"), "npm/omni.js")
        self.assertEqual(payload.get("publishConfig", {}).get("access"), "public")
        self.assertIn("install.ps1", payload.get("files", []))
        self.assertEqual(payload.get("scripts", {}).get("postinstall"), "node npm/postinstall.js")

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
        self.assertIn("npm/postinstall.js", files)
        self.assertIn("install.sh", files)
        self.assertIn("install.ps1", files)
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
            "OMNI_HOME": str(REPO_ROOT / "broken-local-repo"),
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
        self.assertTrue((home_root / ".omni" / "src" / "omni_core.py").exists())
        self.assertNotIn(str(REPO_ROOT / "broken-local-repo"), result.stdout + result.stderr)
        self.assertNotIn("Workspace Init", result.stdout + result.stderr)
        self.assertNotIn("Creando backup automático post-init", result.stdout + result.stderr)
        self.assertIn("OmniSync - Command Reference", result.stdout)
        self.assertIn("[omni] Sincronizando OmniSync", result.stderr)
        self.assertIn("[omni] Preparando runtime local de OmniSync", result.stderr)

    def test_npm_launcher_script_supports_windows_bootstrap(self) -> None:
        script = (REPO_ROOT / "npm" / "omni.js").read_text(encoding="utf-8")
        self.assertNotIn("Windows is not enabled yet", script)
        self.assertIn('"OMNI_HOME"', script)
        self.assertIn("findSystemPython", script)
        self.assertIn("install.ps1", (REPO_ROOT / "package.json").read_text(encoding="utf-8"))

    @unittest.skipUnless(shutil.which("node"), "node is required")
    def test_npm_postinstall_repairs_local_bin_wrappers(self) -> None:
        home_root = REPO_ROOT / ".tmp" / "npm-postinstall-home"
        if home_root.exists():
            shutil.rmtree(home_root)
        self.addCleanup(shutil.rmtree, home_root, ignore_errors=True)
        home_root.mkdir(parents=True, exist_ok=True)

        env = {
            **dict(os.environ),
            "HOME": str(home_root),
        }
        result = subprocess.run(
            ["node", "npm/postinstall.js"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        local_bin = home_root / ".local" / "bin"
        ps1_wrapper = (local_bin / "omni.ps1").read_text(encoding="utf-8")
        cmd_wrapper = (local_bin / "omni.cmd").read_text(encoding="utf-8")
        sh_wrapper = (local_bin / "omni").read_text(encoding="utf-8")
        self.assertIn("npm/omni.js", ps1_wrapper)
        self.assertIn("npm/omni.js", cmd_wrapper)
        self.assertIn("npm/omni.js", sh_wrapper)
        self.assertNotIn("Downloads\\Proyectos\\Ubuntu\\omni-core", ps1_wrapper)

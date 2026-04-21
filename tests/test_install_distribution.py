from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path("/home/ubuntu/omni-core")
INSTALL_SCRIPT = REPO_ROOT / "install.sh"


class InstallDistributionTests(unittest.TestCase):
    def test_install_script_supports_local_repo_override_and_creates_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            local_bin = home / ".local" / "bin"
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["PATH"] = f"{local_bin}:{env['PATH']}"
            env["OMNI_INSTALL_LOCAL_REPO"] = str(REPO_ROOT)
            env["OMNI_INSTALL_SKIP_DEPENDENCY_BOOTSTRAP"] = "1"

            result = subprocess.run(
                ["bash", str(INSTALL_SCRIPT)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

            wrapper = local_bin / "omni"
            self.assertTrue(wrapper.exists())
            self.assertTrue(wrapper.stat().st_mode & stat.S_IXUSR)

            help_result = subprocess.run(
                [str(wrapper), "help"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(help_result.returncode, 0, msg=help_result.stderr or help_result.stdout)
            self.assertIn("Omni Core - Command Reference", help_result.stdout)

    def test_install_script_repairs_preexisting_shadowed_omni_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            local_bin = home / ".local" / "bin"
            shadow_bin = home / "shadow-bin"
            shadow_bin.mkdir(parents=True, exist_ok=True)
            stale_wrapper = shadow_bin / "omni"
            stale_wrapper.write_text("#!/usr/bin/env bash\necho stale-wrapper\n", encoding="utf-8")
            stale_wrapper.chmod(0o755)

            env = os.environ.copy()
            env["HOME"] = str(home)
            env["PATH"] = f"{shadow_bin}:{local_bin}:{env['PATH']}"
            env["OMNI_INSTALL_LOCAL_REPO"] = str(REPO_ROOT)
            env["OMNI_INSTALL_SKIP_DEPENDENCY_BOOTSTRAP"] = "1"

            result = subprocess.run(
                ["bash", str(INSTALL_SCRIPT)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

            guide_result = subprocess.run(
                [str(stale_wrapper), "guide"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(guide_result.returncode, 0, msg=guide_result.stderr or guide_result.stdout)
            self.assertIn("SSH Connect", guide_result.stdout)

            auth_result = subprocess.run(
                [str(stale_wrapper), "auth", "github", "--dry-run"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(auth_result.returncode, 0, msg=auth_result.stderr or auth_result.stdout)
            self.assertNotIn("Unknown action", auth_result.stdout + auth_result.stderr)


if __name__ == "__main__":
    unittest.main()

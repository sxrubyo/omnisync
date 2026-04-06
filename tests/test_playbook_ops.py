import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from playbook_ops import (  # noqa: E402
    build_examples_catalog,
    build_powershell_auto_command,
    build_powershell_auto_script,
    build_powershell_dropper_script,
    build_windows_ps1_path,
)


class PlaybookOpsTests(unittest.TestCase):
    def test_examples_catalog_contains_core_playbooks(self):
        entries = build_examples_catalog()
        keys = {entry.key for entry in entries}
        self.assertIn("guided-start", keys)
        self.assertIn("full-home-capture", keys)
        self.assertIn("full-home-migrate", keys)
        self.assertIn("agent-setup", keys)
        self.assertIn("chat", keys)
        self.assertIn("packages", keys)
        self.assertIn("bridge-send", keys)
        self.assertGreaterEqual(len(entries), 9)

    def test_powershell_auto_command_uses_placeholders_when_values_missing(self):
        command = build_powershell_auto_command()
        self.assertIn("pwsh .\\bootstrap.ps1", command)
        self.assertIn("-TargetHost 'EC2_DNS_O_IP'", command)
        self.assertIn("-IdentityFile 'C:\\ruta\\llave.pem'", command)
        self.assertIn("-InstallTimer", command)
        self.assertNotIn("-Destination", command)

    def test_powershell_auto_command_can_embed_real_values(self):
        command = build_powershell_auto_command(
            target_host="ec2-54-160-79-60.compute-1.amazonaws.com",
            remote_user="ubuntu",
            identity_file="C:\\Users\\santi\\Downloads\\llave.pem",
            repo_url="git@github.com:sxrubyo/omni-core.git",
            ref_name="main",
            destination="/home/ubuntu/omni-core",
        )
        self.assertIn("-TargetHost 'ec2-54-160-79-60.compute-1.amazonaws.com'", command)
        self.assertIn("-Destination '/home/ubuntu/omni-core'", command)

    def test_powershell_auto_script_wraps_command(self):
        script = build_powershell_auto_script("pwsh .\\bootstrap.ps1 `\n  -TargetHost 'host'")
        self.assertIn("$ErrorActionPreference = 'Stop'", script)
        self.assertIn("pwsh .\\bootstrap.ps1", script)

    def test_windows_ps1_path_appends_default_filename(self):
        self.assertEqual(
            build_windows_ps1_path(r"C:\Users\santi\Downloads\Projects\Ubuntu"),
            r"C:\Users\santi\Downloads\Projects\Ubuntu\omni-auto.ps1",
        )

    def test_powershell_dropper_script_creates_script_in_windows_dir(self):
        dropper = build_powershell_dropper_script(
            "pwsh .\\bootstrap.ps1 `\n  -TargetHost 'host'",
            windows_dir=r"C:\Users\santi\Downloads\Projects\Ubuntu",
        )
        self.assertIn("$OmniWindowsDir = 'C:\\Users\\santi\\Downloads\\Projects\\Ubuntu'", dropper)
        self.assertIn("omni-auto.ps1", dropper)
        self.assertIn("Set-Content -Path $OmniScript -Encoding UTF8", dropper)


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from playbook_ops import build_examples_catalog, build_powershell_auto_command  # noqa: E402


class PlaybookOpsTests(unittest.TestCase):
    def test_examples_catalog_contains_core_playbooks(self):
        entries = build_examples_catalog()
        keys = {entry.key for entry in entries}
        self.assertIn("guided-start", keys)
        self.assertIn("full-home-capture", keys)
        self.assertIn("full-home-migrate", keys)
        self.assertIn("agent-setup", keys)
        self.assertIn("bridge-send", keys)
        self.assertGreaterEqual(len(entries), 8)

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


if __name__ == "__main__":
    unittest.main()

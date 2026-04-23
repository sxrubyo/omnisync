import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from connect_ops import (  # noqa: E402
    SSHDestination,
    build_rsync_command,
    build_sftp_command,
    parse_remote_probe_output,
    probe_remote_host,
    transfer_payload,
)


class ConnectOpsTests(unittest.TestCase):
    def test_parse_remote_probe_output_detects_fresh_server(self):
        payload = parse_remote_probe_output(
            "system=Linux\npackage_manager=apt-get\nhome_entries=2\ngit_repos=0\npackage_count=80\nfresh_server=true\nrsync_available=true\n"
        )
        self.assertEqual(payload["system"], "Linux")
        self.assertEqual(payload["package_manager"], "apt-get")
        self.assertTrue(payload["fresh_server"])
        self.assertTrue(payload["rsync_available"])

    def test_build_rsync_command_uses_ssh_port_and_identity(self):
        destination = SSHDestination(host="example.com", user="ubuntu", port=2222, key_path="/tmp/id_ed25519")
        command = build_rsync_command(["/tmp/briefcase.json"], destination, remote_path="~/omni-transfer")
        self.assertEqual(command[0], "rsync")
        self.assertIn("ssh -p 2222 -i /tmp/id_ed25519", command)
        self.assertEqual(command[-1], "ubuntu@example.com:~/omni-transfer/")

    def test_build_sftp_command_creates_batch(self):
        destination = SSHDestination(host="example.com", user="ubuntu")
        command, batch = build_sftp_command(["/tmp/briefcase.json"], destination, remote_path="~/omni-transfer")
        self.assertEqual(command[0], "sftp")
        self.assertIn("put /tmp/briefcase.json", batch)

    def test_probe_remote_host_falls_back_to_windows_when_auto_detect_needs_it(self):
        calls = []

        def fake_runner(command, **kwargs):
            calls.append(command)
            if len(calls) == 1:
                return SimpleNamespace(returncode=1, stdout="", stderr="not a posix shell")
            return SimpleNamespace(
                returncode=0,
                stdout="system=Windows\npackage_manager=winget\nhome_entries=2\ngit_repos=0\npackage_count=0\nfresh_server=true\n",
                stderr="",
            )

        payload = probe_remote_host(
            SSHDestination(host="example.com", user="ubuntu", target_system="auto"),
            runner=fake_runner,
            timeout=5,
        )
        self.assertEqual(payload["system_family"], "windows")
        self.assertEqual(payload["system"], "Windows")
        self.assertEqual(len(calls), 2)

    def test_probe_remote_host_password_mode_uses_interactive_prompt_without_sshpass(self):
        captured = {}

        def fake_runner(command, **kwargs):
            captured["command"] = command
            stdout_file = kwargs["stdout"]
            stdout_file.write(
                "system=Linux\npackage_manager=apt-get\nhome_entries=1\ngit_repos=0\npackage_count=10\nfresh_server=true\nrsync_available=false\n"
            )
            return SimpleNamespace(returncode=0, stderr="")

        destination = SSHDestination(
            host="example.com",
            user="ubuntu",
            auth_mode="password",
            password="",
            target_system="linux",
        )

        with patch("connect_ops.shutil.which", side_effect=lambda name: None if name == "sshpass" else "/usr/bin/" + name), \
             patch("connect_ops._can_prompt_interactively", return_value=True):
            payload = probe_remote_host(destination, runner=fake_runner, timeout=5)

        self.assertEqual(payload["system_family"], "posix")
        self.assertFalse(payload["rsync_available"])
        self.assertEqual(captured["command"][0], "ssh")

    def test_transfer_payload_auto_prefers_sftp_for_windows_and_wraps_sshpass(self):
        captured = {}

        def fake_runner(command, **kwargs):
            captured["command"] = command
            captured["env"] = kwargs.get("env") or {}
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        destination = SSHDestination(
            host="example.com",
            user="ubuntu",
            auth_mode="password",
            password="super-secret",
            target_system="windows",
        )

        with patch("connect_ops.shutil.which", side_effect=lambda name: "/usr/bin/" + name):
            result = transfer_payload(
                ["/tmp/briefcase.json"],
                destination,
                remote_path="~/omni-transfer",
                transport="auto",
                runner=fake_runner,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["transport"], "sftp")
        self.assertEqual(captured["command"][:2], ["sshpass", "-e"])
        self.assertEqual(captured["env"]["SSHPASS"], "super-secret")


if __name__ == "__main__":
    unittest.main()

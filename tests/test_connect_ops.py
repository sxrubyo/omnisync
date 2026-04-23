import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import connect_ops  # noqa: E402
from connect_ops import (  # noqa: E402
    SSHDestination,
    build_rsync_command,
    build_sftp_command,
    parse_remote_probe_output,
    probe_remote_host,
    transfer_payload,
)


class FakeStream:
    def __init__(self, payload: str, exit_status: int):
        self._payload = payload
        self.channel = self
        self._exit_status = exit_status

    def read(self):
        return self._payload.encode("utf-8")

    def recv_exit_status(self):
        return self._exit_status


class FakeSFTP:
    def __init__(self):
        self.directories = {"/remote/home"}
        self.uploads = []
        self.chmods = []

    def normalize(self, path: str):
        if path == ".":
            return "/remote/home"
        return path

    def stat(self, path: str):
        if path not in self.directories:
            raise IOError("missing")
        return object()

    def mkdir(self, path: str):
        self.directories.add(path)

    def put(self, local_path: str, remote_path: str):
        self.uploads.append((local_path, remote_path))

    def chmod(self, remote_path: str, mode: int):
        self.chmods.append((remote_path, mode))

    def close(self):
        return None


class FakeSSHClient:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.connected_with = None
        self.policy = None
        self.commands = []
        self.sftp = FakeSFTP()
        self.closed = False

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, **kwargs):
        self.connected_with = kwargs

    def exec_command(self, command: str, timeout: int | None = None):
        self.commands.append((command, timeout))
        status, stdout, stderr = self.responses.pop(0)
        return None, FakeStream(stdout, status), FakeStream(stderr, status)

    def open_sftp(self):
        return self.sftp

    def close(self):
        self.closed = True


class FakeAutoAddPolicy:
    pass


class FakeParamiko:
    SSHClient = FakeSSHClient
    AutoAddPolicy = FakeAutoAddPolicy


class FakeSocketConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class ConnectOpsTests(unittest.TestCase):
    def test_normalize_remote_system_accepts_posix(self):
        self.assertEqual(connect_ops.normalize_remote_system("posix"), "posix")

    def test_parse_remote_probe_output_detects_fresh_server(self):
        payload = parse_remote_probe_output(
            "system=Linux\npackage_manager=apt-get\nhome_entries=2\ngit_repos=0\npackage_count=80\nfresh_server=true\n"
        )
        self.assertEqual(payload["system"], "Linux")
        self.assertEqual(payload["package_manager"], "apt-get")
        self.assertTrue(payload["fresh_server"])

    def test_build_rsync_command_reports_paramiko_transport(self):
        destination = SSHDestination(host="example.com", user="ubuntu", port=2222, password="secret")
        command = build_rsync_command(["/tmp/briefcase.json"], destination, remote_path="~/omni-transfer")
        self.assertEqual(command[0], "paramiko")
        self.assertEqual(command[1], "sftp")
        self.assertEqual(command[2], "ubuntu@example.com")

    def test_build_sftp_command_creates_placeholder_batch(self):
        destination = SSHDestination(host="example.com", user="ubuntu", password="secret")
        command, batch = build_sftp_command(["/tmp/briefcase.json"], destination, remote_path="~/omni-transfer")
        self.assertEqual(command[0], "paramiko")
        self.assertEqual(batch, "")

    def test_probe_remote_host_falls_back_to_windows_when_auto_detect_needs_it(self):
        client = FakeSSHClient(
            responses=[
                (1, "", "not a posix shell"),
                (0, "system=Windows\npackage_manager=winget\nhome_entries=2\ngit_repos=0\npackage_count=0\nfresh_server=true\n", ""),
            ]
        )

        with patch.object(connect_ops, "paramiko", FakeParamiko), patch.object(
            connect_ops.socket, "create_connection", return_value=FakeSocketConnection()
        ):
            payload = probe_remote_host(
                SSHDestination(host="example.com", user="ubuntu", password="secret", target_system="auto"),
                client_factory=lambda: client,
                timeout=5,
            )

        self.assertEqual(payload["system_family"], "windows")
        self.assertEqual(payload["system"], "Windows")
        self.assertEqual(len(client.commands), 2)
        self.assertTrue(client.closed)

    def test_probe_remote_host_uses_password_auth_when_password_present(self):
        client = FakeSSHClient(
            responses=[
                (0, "system=Linux\npackage_manager=apt-get\nhome_entries=1\ngit_repos=0\npackage_count=10\nfresh_server=true\n", ""),
            ]
        )

        with patch.object(connect_ops, "paramiko", FakeParamiko), patch.object(
            connect_ops.socket, "create_connection", return_value=FakeSocketConnection()
        ):
            probe_remote_host(
                SSHDestination(host="example.com", user="ubuntu", password="super-secret", target_system="linux"),
                client_factory=lambda: client,
                timeout=5,
            )

        self.assertEqual(client.connected_with["password"], "super-secret")
        self.assertFalse(client.connected_with["look_for_keys"])
        self.assertFalse(client.connected_with["allow_agent"])

    def test_probe_remote_host_falls_back_to_key_auth_when_password_is_none(self):
        client = FakeSSHClient(
            responses=[
                (0, "system=Linux\npackage_manager=apt-get\nhome_entries=1\ngit_repos=0\npackage_count=10\nfresh_server=true\n", ""),
            ]
        )

        with patch.object(connect_ops, "paramiko", FakeParamiko), patch.object(
            connect_ops.socket, "create_connection", return_value=FakeSocketConnection()
        ):
            probe_remote_host(
                SSHDestination(host="example.com", user="ubuntu", password=None, key_path="/tmp/id_ed25519", target_system="linux"),
                client_factory=lambda: client,
                timeout=5,
            )

        self.assertEqual(client.connected_with["key_filename"], "/tmp/id_ed25519")
        self.assertTrue(client.connected_with["look_for_keys"])
        self.assertTrue(client.connected_with["allow_agent"])

    def test_transfer_payload_uploads_files_via_paramiko_sftp(self):
        client = FakeSSHClient()

        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "briefcase.json"
            file_path.write_text("{}", encoding="utf-8")

            with patch.object(connect_ops, "paramiko", FakeParamiko), patch.object(
                connect_ops.socket, "create_connection", return_value=FakeSocketConnection()
            ):
                result = transfer_payload(
                    [str(file_path)],
                    SSHDestination(host="example.com", user="ubuntu", password="secret"),
                    remote_path="~/omni-transfer",
                    client_factory=lambda: client,
                )

        self.assertTrue(result["success"])
        self.assertEqual(result["transport"], "sftp")
        self.assertEqual(client.sftp.uploads[0][1], "/remote/home/omni-transfer/briefcase.json")
        self.assertTrue(client.closed)


if __name__ == "__main__":
    unittest.main()

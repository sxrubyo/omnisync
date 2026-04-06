import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from omni_core import (  # noqa: E402
    build_remote_sync_command,
    discover_ssh_identity_candidates,
    resolve_latest_bundle_across_dirs,
    resolve_server_identity_file,
)


class SyncRuntimeOpsTests(unittest.TestCase):
    def test_discover_ssh_identity_candidates_filters_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            ssh_dir = Path(tmp)
            (ssh_dir / "known_hosts").write_text("example", encoding="utf-8")
            (ssh_dir / "authorized_keys").write_text("example", encoding="utf-8")
            (ssh_dir / "config").write_text("Host *", encoding="utf-8")
            (ssh_dir / "llave.pub").write_text("ssh-rsa AAAA", encoding="utf-8")
            private_key = ssh_dir / "llave-xus-maestra"
            private_key.write_text("PRIVATE", encoding="utf-8")

            candidates = discover_ssh_identity_candidates(ssh_dir)

            self.assertEqual(candidates, [private_key])

    def test_resolve_server_identity_file_prefers_explicit_env_then_auto(self):
        with tempfile.TemporaryDirectory() as tmp:
            ssh_dir = Path(tmp)
            auto_key = ssh_dir / "n8n_nova"
            auto_key.write_text("PRIVATE", encoding="utf-8")

            explicit = resolve_server_identity_file({"identity_file": "~/custom.pem"}, ssh_dir=ssh_dir)
            self.assertTrue(explicit.endswith("custom.pem"))

            old_env = os.environ.get("OMNI_SSH_IDENTITY_FILE")
            os.environ["OMNI_SSH_IDENTITY_FILE"] = "/tmp/env-key.pem"
            try:
                env_value = resolve_server_identity_file({}, ssh_dir=ssh_dir)
                self.assertEqual(env_value, "/tmp/env-key.pem")
            finally:
                if old_env is None:
                    os.environ.pop("OMNI_SSH_IDENTITY_FILE", None)
                else:
                    os.environ["OMNI_SSH_IDENTITY_FILE"] = old_env

            auto_value = resolve_server_identity_file({}, ssh_dir=ssh_dir, env={})
            self.assertEqual(auto_value, str(auto_key))

    def test_build_remote_sync_command_includes_identity_file_for_rsync(self):
        with tempfile.TemporaryDirectory() as tmp:
            ssh_dir = Path(tmp) / ".ssh"
            ssh_dir.mkdir()
            private_key = ssh_dir / "n8n_nova"
            private_key.write_text("PRIVATE", encoding="utf-8")
            target_dir = Path(tmp) / "snapshot"

            command = build_remote_sync_command(
                {
                    "user": "ubuntu",
                    "host": "172.31.34.176",
                    "port": 22,
                    "protocol": "rsync",
                    "excludes": [".git", "node_modules"],
                },
                "/home/ubuntu/melissa",
                target_dir,
                ssh_dir=ssh_dir,
            )

            self.assertIn("rsync -az --delete", command)
            self.assertIn("StrictHostKeyChecking=accept-new", command)
            self.assertIn(str(private_key), command)
            self.assertIn("ubuntu@172.31.34.176:", command)
            self.assertIn("/home/ubuntu/melissa/", command)

    def test_build_remote_sync_command_can_disable_delete_for_live_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            ssh_dir = Path(tmp) / ".ssh"
            ssh_dir.mkdir()
            private_key = ssh_dir / "n8n_nova"
            private_key.write_text("PRIVATE", encoding="utf-8")
            target_dir = Path(tmp) / "restore"

            command = build_remote_sync_command(
                {
                    "user": "ubuntu",
                    "host": "172.31.34.176",
                    "port": 22,
                    "protocol": "rsync",
                    "excludes": [],
                },
                "/home/ubuntu",
                target_dir,
                ssh_dir=ssh_dir,
                delete=False,
            )

            self.assertIn("rsync -az ", command)
            self.assertNotIn("--delete", command)

    def test_resolve_latest_bundle_across_dirs_falls_back_to_auto_bundles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host_dir = root / "host-bundles"
            auto_dir = root / "auto-bundles"
            host_dir.mkdir()
            auto_dir.mkdir()
            auto_bundle = auto_dir / "state_bundle_20260406_205902.tar.gz"
            auto_bundle.write_text("bundle", encoding="utf-8")

            resolved = resolve_latest_bundle_across_dirs([host_dir, auto_dir], "", "state_bundle")

            self.assertEqual(resolved, auto_bundle)


if __name__ == "__main__":
    unittest.main()

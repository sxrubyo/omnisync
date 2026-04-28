from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REFRESH_SCRIPT = REPO_ROOT / "scripts" / "refresh_home_snapshot.sh"
RESTORE_SCRIPT = REPO_ROOT / "scripts" / "restore_home_private_snapshot.sh"


class HomeSnapshotScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.home_root = Path(self.temp_dir.name) / "home"
        self.home_root.mkdir(parents=True, exist_ok=True)
        self.public_root = REPO_ROOT / "home_snapshot"
        self.private_root = REPO_ROOT / "home_private_snapshot"
        self.public_backup = Path(self.temp_dir.name) / "home_snapshot.backup"
        self.private_backup = Path(self.temp_dir.name) / "home_private_snapshot.backup"

        if self.public_root.exists():
            shutil.move(str(self.public_root), str(self.public_backup))
        if self.private_root.exists():
            shutil.move(str(self.private_root), str(self.private_backup))

        (self.home_root / ".n8n").mkdir()
        (self.home_root / ".n8n" / "database.sqlite").write_text("secret-workflow-state\n" * 512)
        (self.home_root / ".pm2").mkdir()
        (self.home_root / ".pm2" / "logs").mkdir()
        (self.home_root / ".pm2" / "logs" / "nova.log").write_text("nova-log-line\n" * 512)
        (self.home_root / ".git-credentials").write_text("https://token@example.invalid\n")
        (self.home_root / ".ssh").mkdir()
        (self.home_root / ".ssh" / "id_ed25519").write_text("PRIVATE KEY\n")
        (self.home_root / "nova-os").mkdir()
        (self.home_root / "nova-os" / "README.md").write_text("nova-os project\n")
        (self.home_root / "AGENTS.md").write_text("agents\n")

        self.env = os.environ.copy()
        self.env["HOME_PRIVATE_SNAPSHOT_PASSPHRASE"] = "test-passphrase"
        self.env["HOME_PRIVATE_SNAPSHOT_CHUNK_SIZE"] = "1k"

    def tearDown(self) -> None:
        if self.private_root.exists():
            shutil.rmtree(self.private_root)
        if self.public_root.exists():
            shutil.rmtree(self.public_root)
        if self.private_backup.exists():
            shutil.move(str(self.private_backup), str(self.private_root))
        if self.public_backup.exists():
            shutil.move(str(self.public_backup), str(self.public_root))

    def test_private_mode_generates_encrypted_archives_and_keeps_plaintext_clean(self) -> None:
        result = subprocess.run(
            [str(REFRESH_SCRIPT), "--mode", "private", str(self.home_root)],
            cwd=REPO_ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

        public_root = REPO_ROOT / "home_snapshot" / "ubuntu"
        private_root = REPO_ROOT / "home_private_snapshot"

        self.assertTrue((public_root / "AGENTS.md").exists())
        self.assertFalse((public_root / ".n8n").exists())
        self.assertFalse((public_root / ".git-credentials").exists())

        manifest = private_root / "inventory" / "archive_manifest.tsv"
        self.assertTrue(manifest.exists())
        manifest_text = manifest.read_text()
        self.assertIn(".n8n", manifest_text)
        self.assertIn(".pm2", manifest_text)

        encrypted_chunks = sorted((private_root / "archives").glob("dot_n8n.tar.gz.enc.part-*"))
        self.assertTrue(encrypted_chunks)
        self.assertFalse((private_root / "plain" / ".n8n").exists())

    def test_restore_script_overlays_private_state(self) -> None:
        refresh = subprocess.run(
            [str(REFRESH_SCRIPT), "--mode", "private", str(self.home_root)],
            cwd=REPO_ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(refresh.returncode, 0, msg=refresh.stderr or refresh.stdout)

        restore_target = Path(self.temp_dir.name) / "restore-target"
        restore_target.mkdir(parents=True, exist_ok=True)

        restore = subprocess.run(
            [str(RESTORE_SCRIPT), str(restore_target)],
            cwd=REPO_ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(restore.returncode, 0, msg=restore.stderr or restore.stdout)
        self.assertEqual(
            (restore_target / ".n8n" / "database.sqlite").read_text(),
            (self.home_root / ".n8n" / "database.sqlite").read_text(),
        )
        self.assertEqual(
            (restore_target / ".pm2" / "logs" / "nova.log").read_text(),
            (self.home_root / ".pm2" / "logs" / "nova.log").read_text(),
        )


if __name__ == "__main__":
    unittest.main()

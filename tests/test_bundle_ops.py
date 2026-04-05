import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bundle_ops import create_secrets_bundle, create_state_bundle, restore_bundle  # noqa: E402


class BundleOpsTests(unittest.TestCase):
    def test_state_bundle_round_trip_skips_excluded_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / "home" / "ubuntu" / "melissa"
            state_dir.mkdir(parents=True)
            (state_dir / "keep.txt").write_text("hola", encoding="utf-8")
            (state_dir / "app.log").write_text("ruido", encoding="utf-8")

            manifest = {
                "host_root": str(root / "home" / "ubuntu"),
                "profile": "production-clean",
                "version": 1,
                "state_paths": [str(state_dir)],
                "exclude_patterns": ["*.log"],
            }
            bundles_dir = root / "bundles"
            bundle_path = create_state_bundle(bundles_dir, manifest)

            restore_root = root / "restore"
            restored = restore_bundle(bundle_path, target_root=str(restore_root))

            restored_file = restore_root / "home" / "ubuntu" / "melissa" / "keep.txt"
            self.assertIn(str(restored_file.resolve()), [str(Path(p).resolve()) for p in restored])
            self.assertTrue(restored_file.exists())
            self.assertFalse((restore_root / "home" / "ubuntu" / "melissa" / "app.log").exists())

    def test_secrets_bundle_round_trip_with_passphrase(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret_file = root / "home" / "ubuntu" / "melissa" / ".env"
            secret_file.parent.mkdir(parents=True)
            secret_file.write_text("TOKEN=abc123\n", encoding="utf-8")

            manifest = {
                "host_root": str(root / "home" / "ubuntu"),
                "profile": "production-clean",
                "version": 1,
                "secret_paths": [str(secret_file)],
            }
            bundles_dir = root / "bundles"
            bundle_path = create_secrets_bundle(
                bundles_dir,
                manifest,
                passphrase="secret-passphrase",
            )

            restore_root = root / "restore"
            restore_bundle(bundle_path, target_root=str(restore_root), passphrase="secret-passphrase")

            restored_file = restore_root / "tmp" / "home" / "ubuntu" / "melissa" / ".env"
            if not restored_file.exists():
                restored_file = restore_root / "home" / "ubuntu" / "melissa" / ".env"
            self.assertTrue(restored_file.exists())
            self.assertEqual(restored_file.read_text(encoding="utf-8"), "TOKEN=abc123\n")


if __name__ == "__main__":
    unittest.main()

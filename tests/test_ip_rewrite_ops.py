import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ip_rewrite_ops import (  # noqa: E402
    apply_rewrite_plan,
    build_rewrite_plan,
    detect_host_identity,
    is_allowed_rewrite_file,
    preview_rewrite_plan,
)


class IpRewriteOpsTests(unittest.TestCase):
    def test_detect_host_identity_uses_env_overrides(self):
        with mock.patch.dict(
            os.environ,
            {
                "OMNI_PUBLIC_IP": "203.0.113.10",
                "OMNI_PRIVATE_IP": "10.0.0.12",
                "OMNI_HOSTNAME": "nova-host",
                "OMNI_FQDN": "nova-host.local",
            },
            clear=False,
        ):
            with mock.patch("socket.gethostname", return_value="ignored-host"):
                with mock.patch("socket.getfqdn", return_value="ignored-host.local"):
                    with mock.patch("socket.gethostbyname_ex", return_value=("ignored-host", [], ["10.0.0.12"])):
                        identity = detect_host_identity()

        self.assertEqual(identity.public_ip, "203.0.113.10")
        self.assertEqual(identity.private_ip, "10.0.0.12")
        self.assertEqual(identity.hostname, "nova-host")
        self.assertEqual(identity.fqdn, "nova-host.local")
        self.assertIn("10.0.0.12", identity.ip_candidates)

    def test_build_plan_preview_and_apply_only_touch_allowlisted_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            allowed_dir = root / "config"
            allowed_dir.mkdir(parents=True)
            env_file = allowed_dir / ".env"
            env_file.write_text(
                "API_URL=http://54.160.79.60:3005\nHOST=old-host\n",
                encoding="utf-8",
            )
            caddy_file = root / "Caddyfile"
            caddy_file.write_text(
                "reverse_proxy 54.160.79.60:3005\nhandle_host old-host\n",
                encoding="utf-8",
            )
            ignored_dir = root / "node_modules"
            ignored_dir.mkdir()
            ignored_file = ignored_dir / "bundle.js"
            ignored_file.write_text("54.160.79.60 old-host", encoding="utf-8")
            binary_file = root / "image.png"
            binary_file.write_bytes(b"\x89PNG\r\n\x1a\n")

            replacements = {
                "54.160.79.60": "10.0.0.8",
                "old-host": "new-host",
            }
            plan = build_rewrite_plan(root, replacements)
            preview = preview_rewrite_plan(plan, context_lines=0)
            result = apply_rewrite_plan(plan)

            self.assertIn(env_file, result.applied)
            self.assertIn(caddy_file, result.applied)
            self.assertFalse(binary_file.exists() and "10.0.0.8" in binary_file.read_text(encoding="utf-8", errors="ignore"))
            self.assertNotIn(ignored_file, result.applied)
            self.assertIn("FILE", preview)
            self.assertIn("54.160.79.60 -> 10.0.0.8", preview)
            self.assertIn("old-host -> new-host", preview)
            self.assertEqual(env_file.read_text(encoding="utf-8"), "API_URL=http://10.0.0.8:3005\nHOST=new-host\n")
            self.assertEqual(caddy_file.read_text(encoding="utf-8"), "reverse_proxy 10.0.0.8:3005\nhandle_host new-host\n")

    def test_allowlist_is_strict_for_disallowed_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            allowed = root / "compose.yaml"
            allowed.write_text("host: 54.160.79.60\n", encoding="utf-8")
            disallowed = root / "notes.bin"
            disallowed.write_text("host: 54.160.79.60\n", encoding="utf-8")

            plan = build_rewrite_plan(root, {"54.160.79.60": "10.0.0.8"})

            self.assertTrue(is_allowed_rewrite_file(allowed))
            self.assertFalse(is_allowed_rewrite_file(disallowed))
            self.assertEqual([item.path for item in plan.files], [allowed])


if __name__ == "__main__":
    unittest.main()

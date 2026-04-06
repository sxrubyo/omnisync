import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from permissions_ops import (  # noqa: E402
    classify_action_permission,
    classify_command_permission,
    ensure_permissions_state,
    evaluate_permission_decision,
    normalize_permission_mode,
    render_permissions_lines,
)


class PermissionsOpsTests(unittest.TestCase):
    def test_normalize_permission_mode_supports_aliases(self):
        self.assertEqual(normalize_permission_mode("smart"), "smart")
        self.assertEqual(normalize_permission_mode("todo"), "all")
        self.assertEqual(normalize_permission_mode("ask"), "ask")
        self.assertEqual(normalize_permission_mode("desconocido"), "smart")

    def test_classify_command_permission_distinguishes_levels(self):
        self.assertEqual(classify_command_permission("omni detect-ip"), "safe")
        self.assertEqual(classify_command_permission("omni rewrite-ip --apply"), "rewrite")
        self.assertEqual(classify_command_permission("omni migrate --profile full-home --accept-all"), "install")
        self.assertEqual(classify_command_permission("ls -lah /home/ubuntu"), "safe")
        self.assertEqual(classify_command_permission("python3 -m pip install -r requirements.txt"), "install")
        self.assertEqual(classify_command_permission("rm -rf /tmp/demo"), "danger")

    def test_classify_action_permission_uses_workflow_max_level(self):
        action = {
            "type": "workflow",
            "steps": [
                {"command": "omni detect-ip"},
                {"command": "omni rewrite-ip --apply"},
            ],
        }
        self.assertEqual(classify_action_permission(action), "rewrite")

    def test_smart_permissions_autorun_safe_but_confirm_install(self):
        permissions = ensure_permissions_state({})
        safe = evaluate_permission_decision({"type": "command", "command": "omni detect-ip"}, permissions)
        install = evaluate_permission_decision({"type": "command", "command": "omni migrate --profile full-home"}, permissions)
        self.assertTrue(safe["auto_execute"])
        self.assertFalse(safe["needs_confirmation"])
        self.assertFalse(install["auto_execute"])
        self.assertTrue(install["needs_confirmation"])

    def test_all_permissions_allow_everything(self):
        permissions = ensure_permissions_state({"mode": "all"})
        decision = evaluate_permission_decision({"type": "command", "command": "rm -rf /tmp/demo"}, permissions)
        self.assertTrue(decision["auto_execute"])
        self.assertFalse(decision["needs_confirmation"])

    def test_explicit_confirm_flag_still_requires_confirmation_unless_mode_all(self):
        permissions = ensure_permissions_state({"mode": "smart"})
        decision = evaluate_permission_decision(
            {"type": "command", "command": "omni detect-ip", "confirm": True},
            permissions,
        )
        self.assertTrue(decision["needs_confirmation"])

    def test_render_permissions_lines_is_user_facing(self):
        lines = render_permissions_lines(ensure_permissions_state({"mode": "smart"}))
        self.assertTrue(any("Modo activo" in line for line in lines))
        self.assertTrue(any("safe" in line.lower() for line in lines))


if __name__ == "__main__":
    unittest.main()

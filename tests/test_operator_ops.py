import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from operator_ops import build_operator_response, infer_migration_mode  # noqa: E402


class OperatorOpsTests(unittest.TestCase):
    def test_infer_migration_mode_prefers_destination_when_bundles_exist(self):
        mode = infer_migration_mode(
            {
                "has_state_bundle": True,
                "has_secrets_bundle": True,
                "has_capture_summary": True,
                "has_product_state": True,
            }
        )
        self.assertEqual(mode, "destination")

    def test_infer_migration_mode_prefers_source_when_only_product_state_exists(self):
        mode = infer_migration_mode(
            {
                "has_state_bundle": False,
                "has_secrets_bundle": False,
                "has_capture_summary": False,
                "has_product_state": True,
            }
        )
        self.assertEqual(mode, "source")

    def test_build_operator_response_creates_destination_workflow(self):
        result = build_operator_response(
            "hola, puedes iniciar migracion",
            context={
                "migration_mode": "destination",
                "profile": "production-clean",
                "has_state_bundle": True,
                "has_secrets_bundle": True,
                "has_capture_summary": True,
            },
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["action"]["type"], "workflow")
        commands = [step["command"] for step in result["action"]["steps"]]
        self.assertIn("omni migrate --profile full-home --accept-all", commands)

    def test_build_operator_response_creates_source_capture_workflow(self):
        result = build_operator_response(
            "instala todo y prepara migracion",
            context={
                "migration_mode": "source",
                "profile": "full-home",
                "has_state_bundle": False,
                "has_secrets_bundle": False,
                "has_capture_summary": False,
            },
        )
        self.assertIsNotNone(result)
        commands = [step["command"] for step in result["action"]["steps"]]
        self.assertIn("omni capture --profile full-home --accept-all", commands)

    def test_build_operator_response_asks_when_mode_is_ambiguous(self):
        result = build_operator_response(
            "puedes iniciar migracion",
            context={
                "migration_mode": "ambiguous",
                "profile": "full-home",
                "has_state_bundle": False,
                "has_secrets_bundle": False,
                "has_capture_summary": False,
            },
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["action"]["type"], "todo")
        self.assertIn("origen o destino", result["response"].lower())

    def test_build_operator_response_supports_package_inventory_intent(self):
        result = build_operator_response(
            "enumera todos los paquetes que tenemos instalados",
            context={"profile": "full-home"},
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["action"]["type"], "command")
        self.assertEqual(result["action"]["command"], "omni packages")


if __name__ == "__main__":
    unittest.main()

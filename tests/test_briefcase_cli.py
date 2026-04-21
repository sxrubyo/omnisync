from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path("/home/ubuntu/omni-core")
CLI_PATH = REPO_ROOT / "src" / "omni_core.py"


class BriefcaseCliTests(unittest.TestCase):
    def test_briefcase_and_restore_plan_commands_write_json_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            home_root = tmp_root / "home" / "ubuntu"
            manifest_path = tmp_root / "config" / "system_manifest.json"
            briefcase_path = tmp_root / "briefcase.json"
            restore_plan_path = tmp_root / "restore-plan.json"

            (home_root / "omni-core").mkdir(parents=True)
            (home_root / "omni-core" / "README.md").write_text("omni\n", encoding="utf-8")
            (home_root / ".ssh").mkdir()
            (home_root / ".ssh" / "id_ed25519").write_text("PRIVATE\n", encoding="utf-8")

            briefcase = subprocess.run(
                [
                    "python3",
                    str(CLI_PATH),
                    "briefcase",
                    "--manifest",
                    str(manifest_path),
                    "--home-root",
                    str(home_root),
                    "--profile",
                    "full-home",
                    "--output",
                    str(briefcase_path),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(briefcase.returncode, 0, msg=briefcase.stderr or briefcase.stdout)
            self.assertTrue(briefcase_path.exists())

            restore_plan = subprocess.run(
                [
                    "python3",
                    str(CLI_PATH),
                    "restore-plan",
                    "--briefcase",
                    str(briefcase_path),
                    "--output",
                    str(restore_plan_path),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(restore_plan.returncode, 0, msg=restore_plan.stderr or restore_plan.stdout)
            self.assertTrue(restore_plan_path.exists())

            briefcase_payload = json.loads(briefcase_path.read_text(encoding="utf-8"))
            plan_payload = json.loads(restore_plan_path.read_text(encoding="utf-8"))

            self.assertEqual(briefcase_payload["kind"], "omni-briefcase")
            self.assertEqual(briefcase_payload["source"]["profile"], "full-home")
            self.assertEqual(plan_payload["kind"], "omni-restore-plan")
            self.assertTrue(any(step["id"] == "restore-state" for step in plan_payload["steps"]))

    def test_migrate_sync_family_routes_to_briefcase_and_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            home_root = tmp_root / "home" / "ubuntu"
            manifest_path = tmp_root / "config" / "system_manifest.json"
            briefcase_path = tmp_root / "briefcase-family.json"
            restore_plan_path = tmp_root / "restore-plan-family.json"

            (home_root / "omni-core").mkdir(parents=True)
            (home_root / "omni-core" / "README.md").write_text("omni\n", encoding="utf-8")

            create = subprocess.run(
                [
                    "python3",
                    str(CLI_PATH),
                    "migrate",
                    "sync",
                    "create",
                    "--manifest",
                    str(manifest_path),
                    "--home-root",
                    str(home_root),
                    "--output",
                    str(briefcase_path),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(create.returncode, 0, msg=create.stderr or create.stdout)
            self.assertTrue(briefcase_path.exists())

            plan = subprocess.run(
                [
                    "python3",
                    str(CLI_PATH),
                    "migrate",
                    "sync",
                    "plan",
                    "--briefcase",
                    str(briefcase_path),
                    "--output",
                    str(restore_plan_path),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(plan.returncode, 0, msg=plan.stderr or plan.stdout)
            self.assertTrue(restore_plan_path.exists())


if __name__ == "__main__":
    unittest.main()

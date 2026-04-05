import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cleanup_ops import build_purge_plan, execute_purge  # noqa: E402


class CleanupOpsTests(unittest.TestCase):
    def test_purge_plan_preserves_git_repo_root_but_collects_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "melissa"
            (repo / ".git").mkdir(parents=True)
            (repo / "node_modules").mkdir()
            (repo / "src").mkdir()
            (repo / "node_modules" / "pkg.js").write_text("x", encoding="utf-8")

            state_dir = root / ".n8n"
            state_dir.mkdir()
            (state_dir / "data.db").write_text("db", encoding="utf-8")

            plan = build_purge_plan(
                {
                    "state_paths": [str(repo), str(state_dir)],
                    "secret_paths": [],
                },
                omni_home=root / "omni-core",
                bundle_dir=root / "bundles",
                backup_dir=root / "backups",
                state_dir=root / "state",
                log_dir=root / "logs",
            )

            planned_paths = {item["path"]: item["reason"] for item in plan}
            self.assertIn(str(repo / "node_modules"), planned_paths)
            self.assertEqual(planned_paths[str(repo / "node_modules")], "repo_artifact")
            self.assertIn(str(state_dir), planned_paths)
            self.assertEqual(planned_paths[str(state_dir)], "managed_state")
            self.assertNotIn(str(repo), planned_paths)

    def test_execute_purge_removes_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            victim = root / "victim"
            victim.mkdir()
            (victim / "x.txt").write_text("1", encoding="utf-8")
            report = execute_purge(
                [{"path": str(victim), "size_bytes": 1, "reason": "managed_state"}],
                dry_run=False,
            )
            self.assertFalse(victim.exists())
            self.assertEqual(len(report["removed"]), 1)


if __name__ == "__main__":
    unittest.main()

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_skill_ops import ensure_agent_skill_bridges  # noqa: E402


class AgentSkillOpsTests(unittest.TestCase):
    def test_ensure_agent_skill_bridges_writes_skill_docs_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_root = Path(tmp) / "skills"

            with mock.patch("agent_skill_ops.shutil.which", side_effect=lambda cmd: f"/usr/bin/{cmd}" if cmd in {"claude", "codex", "opencode"} else None), \
                 mock.patch("agent_skill_ops._read_version", side_effect=lambda command: f"{command} 1.0.0"):
                statuses = ensure_agent_skill_bridges(skill_root)

            self.assertEqual(len(statuses), 4)
            self.assertTrue((skill_root / "claude-code" / "SKILL.md").exists())
            self.assertTrue((skill_root / "codex-cli" / "SKILL.md").exists())
            self.assertTrue((skill_root / "gemini-cli" / "SKILL.md").exists())
            self.assertTrue((skill_root / "opencode-cli" / "SKILL.md").exists())
            metadata = (skill_root / "agent-skills.json").read_text(encoding="utf-8")
            self.assertIn("claude-code", metadata)
            self.assertIn("codex-cli", metadata)
            self.assertIn("gemini-cli", metadata)
            self.assertIn("opencode-cli", metadata)


if __name__ == "__main__":
    unittest.main()

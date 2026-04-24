import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_skill_ops import ensure_agent_skill_bridges, sync_agent_integrations  # noqa: E402


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

    def test_sync_agent_integrations_writes_detected_agent_assets_into_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            skill_root = temp_root / ".omni" / "skills"
            home_root = temp_root / "home"
            repo_root = ROOT
            (home_root / ".codex").mkdir(parents=True)
            (home_root / ".claude").mkdir(parents=True)
            (home_root / ".gemini").mkdir(parents=True)
            (home_root / ".config" / "opencode").mkdir(parents=True)

            with mock.patch("agent_skill_ops.shutil.which", side_effect=lambda cmd: ""), \
                 mock.patch("agent_skill_ops._read_version", return_value=""):
                result = sync_agent_integrations(skill_root, home_root=home_root, repo_root=repo_root)

            integrations = {item.key: item for item in result["integrations"]}
            self.assertTrue((home_root / ".codex" / "skills" / "omni-sync" / "SKILL.md").exists())
            self.assertTrue((home_root / ".claude" / "skills" / "omni-sync" / "SKILL.md").exists())
            self.assertTrue((home_root / ".gemini" / "commands" / "omni-sync.toml").exists())
            gemini_text = (home_root / ".gemini" / "commands" / "omni-sync.toml").read_text(encoding="utf-8")
            self.assertNotIn("/workspace.omni-sync", gemini_text)
            self.assertIn("Do not inspect `~/.omni/`", gemini_text)
            self.assertTrue((home_root / ".config" / "opencode" / "commands" / "omni-agent.md").exists())
            self.assertTrue(integrations["codex-cli"].detected)
            self.assertTrue(integrations["claude-code"].detected)
            self.assertTrue(integrations["gemini-cli"].detected)
            self.assertTrue(integrations["opencode-cli"].detected)
            metadata = (skill_root / "agent-integrations.json").read_text(encoding="utf-8")
            self.assertIn("codex-cli", metadata)
            self.assertIn("opencode-cli", metadata)


if __name__ == "__main__":
    unittest.main()

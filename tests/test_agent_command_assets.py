import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgentCommandAssetsTests(unittest.TestCase):
    def test_repo_ships_codex_claude_gemini_and_opencode_assets(self) -> None:
        self.assertTrue((ROOT / ".codex" / "skills" / "omni-sync" / "SKILL.md").exists())
        self.assertTrue((ROOT / ".claude" / "skills" / "omni-sync" / "SKILL.md").exists())
        self.assertTrue((ROOT / ".gemini" / "commands" / "workspace.omni-sync.toml").exists())
        self.assertTrue((ROOT / ".gemini" / "commands" / "workspace.omni-agent.toml").exists())
        self.assertTrue((ROOT / ".gemini" / "templates" / "omni-sync.toml").exists())
        self.assertTrue((ROOT / ".gemini" / "templates" / "omni-agent.toml").exists())
        self.assertTrue((ROOT / ".opencode" / "commands" / "omni-sync.md").exists())
        self.assertTrue((ROOT / ".opencode" / "commands" / "omni-agent.md").exists())

    def test_repo_assets_reference_real_omni_flows(self) -> None:
        codex_text = (ROOT / ".codex" / "skills" / "omni-sync" / "SKILL.md").read_text(encoding="utf-8")
        skill_text = (ROOT / ".claude" / "skills" / "omni-sync" / "SKILL.md").read_text(encoding="utf-8")
        gemini_text = (ROOT / ".gemini" / "templates" / "omni-sync.toml").read_text(encoding="utf-8")
        workspace_gemini_text = (ROOT / ".gemini" / "commands" / "workspace.omni-sync.toml").read_text(encoding="utf-8")
        opencode_text = (ROOT / ".opencode" / "commands" / "omni-agent.md").read_text(encoding="utf-8")
        self.assertTrue(codex_text.startswith("---\n"))
        self.assertIn("omni briefcase --full", codex_text)
        self.assertIn("omni guide", skill_text)
        self.assertIn("omni connect", gemini_text)
        self.assertIn("Do not inspect `~/.omni/`", gemini_text)
        self.assertIn("/workspace.omni-sync", workspace_gemini_text)
        self.assertIn("omni agent", opencode_text)


if __name__ == "__main__":
    unittest.main()

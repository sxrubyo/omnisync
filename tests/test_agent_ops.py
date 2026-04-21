import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_ops import env_has_value, get_provider, provider_catalog, save_agent_config, load_agent_config, upsert_env_value  # noqa: E402


class AgentOpsTests(unittest.TestCase):
    def test_provider_catalog_exposes_expected_options(self):
        keys = {provider.key for provider in provider_catalog()}
        self.assertIn("claude-direct", keys)
        self.assertIn("gemini-direct", keys)
        self.assertIn("openrouter", keys)
        self.assertIn("qwen-intl", keys)
        self.assertIn("custom-openai", keys)
        self.assertIsNotNone(get_provider("claude-direct"))

    def test_agent_config_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "omni_agent.json"
            payload = {"provider": "openrouter", "model": "google/gemini-2.5-flash"}
            save_agent_config(config_path, payload)
            loaded = load_agent_config(config_path)
            self.assertEqual(loaded["provider"], "openrouter")
            self.assertEqual(loaded["model"], "google/gemini-2.5-flash")

    def test_upsert_env_value_marks_secret_as_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            upsert_env_value(env_path, "OPENROUTER_API_KEY", "secret-123")
            self.assertTrue(env_has_value(env_path, "OPENROUTER_API_KEY"))
            upsert_env_value(env_path, "OPENROUTER_API_KEY", "secret-456")
            text = env_path.read_text(encoding="utf-8")
            self.assertIn("OPENROUTER_API_KEY=secret-456", text)


if __name__ == "__main__":
    unittest.main()

import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import omni_core  # noqa: E402


class AgentCliSurfaceTests(unittest.TestCase):
    def test_chat_cmd_executes_omni_action_and_persists_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            omni_home = tmp_root / ".omni"
            config_dir = omni_home / "config"
            state_dir = omni_home / "data"
            backup_dir = omni_home / "backups"
            bundle_dir = backup_dir / "host-bundles"
            auto_bundle_dir = backup_dir / "auto-bundles"
            log_dir = omni_home / "logs"
            chat_dir = state_dir / "chat"
            env_file = omni_home / ".env"
            agent_config = config_dir / "omni_agent.json"
            activation_file = config_dir / "omni_agent_activation.txt"
            repos_file = config_dir / "repos.json"
            servers_file = config_dir / "servers.json"
            manifest_file = config_dir / "system_manifest.json"
            tasks_file = omni_home / "tasks.json"

            for path in (config_dir, state_dir, bundle_dir, auto_bundle_dir, log_dir):
                path.mkdir(parents=True, exist_ok=True)

            env_file.write_text("OPENAI_API_KEY=test-secret\n", encoding="utf-8")
            agent_config.write_text(
                json.dumps(
                    {
                        "provider": "openai-direct",
                        "provider_title": "OpenAI Direct",
                        "protocol": "openai-compatible",
                        "env_var": "OPENAI_API_KEY",
                        "base_url": "https://api.openai.com/v1",
                        "model": "gpt-4.1",
                    }
                ),
                encoding="utf-8",
            )

            patches = [
                mock.patch.object(omni_core, "OMNI_HOME", omni_home),
                mock.patch.object(omni_core, "CONFIG_DIR", config_dir),
                mock.patch.object(omni_core, "STATE_DIR", state_dir),
                mock.patch.object(omni_core, "BACKUP_DIR", backup_dir),
                mock.patch.object(omni_core, "BUNDLE_DIR", bundle_dir),
                mock.patch.object(omni_core, "AUTO_BUNDLE_DIR", auto_bundle_dir),
                mock.patch.object(omni_core, "LOG_DIR", log_dir),
                mock.patch.object(omni_core, "AGENT_CONFIG_FILE", agent_config),
                mock.patch.object(omni_core, "AGENT_SKILL_DIR", omni_home / "skills"),
                mock.patch.object(omni_core, "CHAT_SESSION_DIR", chat_dir),
                mock.patch.object(omni_core, "AGENT_ACTIVATION_FILE", activation_file),
                mock.patch.object(omni_core, "ENV_FILE", env_file),
                mock.patch.object(omni_core, "REPOS_FILE", repos_file),
                mock.patch.object(omni_core, "SERVERS_FILE", servers_file),
                mock.patch.object(omni_core, "SYSTEM_MANIFEST_FILE", manifest_file),
                mock.patch.object(omni_core, "TASKS_FILE", tasks_file),
                mock.patch("omni_core.ensure_agent_skill_bridges", return_value=[]),
                mock.patch("omni_core.render_action_summary"),
                mock.patch("omni_core.print_logo"),
                mock.patch("omni_core.section"),
                mock.patch("omni_core.nl"),
            ]

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                stack.enter_context(
                    mock.patch(
                        "omni_core.chat_completion",
                        side_effect=[
                            {"text": 'Voy a correrlo.\nACTION:{"type":"command","command":"omni doctor","confirm":false,"title":"Diagnóstico"}'},
                            {"text": "Diagnóstico listo. Siguiente paso: omni status."},
                        ],
                    )
                )
                run_mock = stack.enter_context(
                    mock.patch.object(
                        omni_core.OmniCore,
                        "run_agent_omni_command",
                        return_value={"success": True, "stdout": "doctor ok", "stderr": "", "command": "omni doctor"},
                    )
                )
                core = omni_core.OmniCore()
                core.chat_cmd("haz el diagnóstico", accept_all=True)

            run_mock.assert_called_once_with("omni doctor")
            sessions = sorted(chat_dir.glob("chat-*.json"))
            self.assertTrue(sessions)
            payload = json.loads(sessions[-1].read_text(encoding="utf-8"))
            self.assertTrue(any(message["role"] == "assistant" for message in payload["messages"]))

    def test_run_agent_omni_command_rejects_non_omni_commands(self) -> None:
        core = omni_core.OmniCore()
        result = core.run_agent_omni_command("rm -rf /tmp/demo")
        self.assertFalse(result["success"])
        self.assertIn("solo puede ejecutar comandos", result["error"])


if __name__ == "__main__":
    unittest.main()

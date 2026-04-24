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
                mock.patch(
                    "omni_core.sync_agent_integrations",
                    return_value={"runtimes": [], "integrations": [], "metadata_path": str(omni_home / "skills" / "agent-integrations.json")},
                ),
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
        self.assertIn("comandos seguros de inspección", result["error"])

    def test_run_agent_omni_command_allows_safe_shell_inspection(self) -> None:
        core = omni_core.OmniCore()
        with mock.patch("omni_core.subprocess.run") as run_mock:
            run_mock.return_value = mock.Mock(returncode=0, stdout="/home/ubuntu\n", stderr="")
            result = core.run_agent_omni_command("pwd")
        self.assertTrue(result["success"])
        self.assertEqual(result["stdout"], "/home/ubuntu\n")
        run_mock.assert_called_once()

    def test_launch_agent_runtime_executes_local_cli(self) -> None:
        core = omni_core.OmniCore()
        runtime = mock.Mock(
            key="codex-cli",
            title="Codex CLI",
            command="codex",
            installed=True,
            path="/usr/bin/codex",
            version="codex 1.2.3",
            install_hint="install codex",
        )
        with mock.patch("omni_core.detect_agent_runtimes", return_value=[runtime]), \
             mock.patch("omni_core.render_command_header"), \
             mock.patch("omni_core.render_action_summary"), \
             mock.patch("omni_core.subprocess.run") as run_mock:
            run_mock.return_value = mock.Mock(returncode=0)
            result = core.launch_agent_runtime("codex", ["--help"])
        self.assertEqual(result, 0)
        run_mock.assert_called_once_with(["/usr/bin/codex", "--help"], cwd=str(Path.cwd()), check=False)

    def test_launch_agent_runtime_reports_missing_runtime(self) -> None:
        core = omni_core.OmniCore()
        runtime = mock.Mock(
            key="gemini-cli",
            title="Gemini CLI",
            command="gemini",
            installed=False,
            path="",
            version="",
            install_hint="install gemini",
        )
        with mock.patch("omni_core.detect_agent_runtimes", return_value=[runtime]), \
             mock.patch("omni_core.render_human_error") as error_mock:
            result = core.launch_agent_runtime("gemini", [])
        self.assertEqual(result, 1)
        error_mock.assert_called_once()

    def test_chat_cmd_can_chain_shell_and_omni_actions(self) -> None:
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
                mock.patch(
                    "omni_core.sync_agent_integrations",
                    return_value={"runtimes": [], "integrations": [], "metadata_path": str(omni_home / "skills" / "agent-integrations.json")},
                ),
                mock.patch("omni_core.render_action_summary"),
                mock.patch("omni_core.render_command_header"),
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
                            {"text": 'Primero miro el directorio actual.\nACTION:{"type":"command","command":"pwd","confirm":false,"title":"Contexto actual"}'},
                            {"text": 'Ahora reviso OmniSync.\nACTION:{"type":"command","command":"omni doctor","confirm":false,"title":"Diagnóstico Omni"}'},
                            {"text": "Ya tengo contexto del host. El siguiente paso es pedirte el destino exacto."},
                        ],
                    )
                )
                run_mock = stack.enter_context(
                    mock.patch.object(
                        omni_core.OmniCore,
                        "run_agent_omni_command",
                        side_effect=[
                            {"success": True, "stdout": "/home/ubuntu\n", "stderr": "", "command": "pwd"},
                            {"success": True, "stdout": "doctor ok", "stderr": "", "command": "omni doctor"},
                        ],
                    )
                )
                core = omni_core.OmniCore()
                core.chat_cmd("revisa el host y sigue el flujo operativo", accept_all=True)

            self.assertEqual(run_mock.call_count, 2)
            self.assertEqual(run_mock.call_args_list[0].args[0], "pwd")
            self.assertEqual(run_mock.call_args_list[1].args[0], "omni doctor")

    def test_chat_cmd_migrate_all_uses_operator_layer_before_model(self) -> None:
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
                mock.patch(
                    "omni_core.sync_agent_integrations",
                    return_value={"runtimes": [], "integrations": [], "metadata_path": str(omni_home / "skills" / "agent-integrations.json")},
                ),
                mock.patch("omni_core.render_action_summary"),
                mock.patch("omni_core.render_command_header"),
                mock.patch("omni_core.print_logo"),
                mock.patch("omni_core.section"),
                mock.patch("omni_core.nl"),
                mock.patch.object(omni_core.OmniCore, "confirm_step", return_value=True),
            ]

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                chat_mock = stack.enter_context(
                    mock.patch(
                        "omni_core.chat_completion",
                        return_value={"text": "Ya generé la maleta. Ahora necesito la IP o el host destino."},
                    )
                )
                run_mock = stack.enter_context(
                    mock.patch.object(
                        omni_core.OmniCore,
                        "run_agent_omni_command",
                        return_value={"success": True, "stdout": "briefcase ok", "stderr": "", "command": "omni briefcase --full"},
                    )
                )
                core = omni_core.OmniCore()
                core.chat_cmd("quiero migrar todo", accept_all=False)

            run_mock.assert_called_once_with("omni briefcase --full")
            self.assertEqual(chat_mock.call_count, 1)

    def test_chat_cmd_interactive_loop_persists_memory_file(self) -> None:
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
                mock.patch(
                    "omni_core.sync_agent_integrations",
                    return_value={"runtimes": [], "integrations": [], "metadata_path": str(omni_home / "skills" / "agent-integrations.json")},
                ),
                mock.patch("omni_core.render_action_summary"),
                mock.patch("omni_core.print_logo"),
                mock.patch("omni_core.section"),
                mock.patch("omni_core.nl"),
                mock.patch.object(omni_core.OmniCore, "is_interactive", return_value=True),
                mock.patch.object(omni_core.OmniCore, "prompt_text", side_effect=["primer paso", "/exit"]),
            ]

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                stack.enter_context(
                    mock.patch(
                        "omni_core.chat_completion",
                        return_value={"text": "Listo. Siguiente paso: omni doctor."},
                    )
                )
                core = omni_core.OmniCore()
                core.chat_cmd("", accept_all=True)

            memory_path = chat_dir / "memory.json"
            self.assertTrue(memory_path.exists())
            payload = json.loads(memory_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["recent_prompts"])

    def test_chat_cmd_logout_clears_session_and_memory_files(self) -> None:
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

            for path in (config_dir, state_dir, bundle_dir, auto_bundle_dir, log_dir, chat_dir):
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
            session_path = chat_dir / "chat-old.json"
            session_path.write_text(
                json.dumps(
                    {
                        "id": "chat-old",
                        "path": str(session_path),
                        "provider_title": "OpenAI Direct",
                        "protocol": "openai-compatible",
                        "model": "gpt-4.1",
                        "base_url": "https://api.openai.com/v1",
                        "messages": [],
                        "permissions": {"mode": "smart"},
                    }
                ),
                encoding="utf-8",
            )
            (chat_dir / "memory.json").write_text('{"recent_prompts":[]}', encoding="utf-8")

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
                mock.patch(
                    "omni_core.sync_agent_integrations",
                    return_value={"runtimes": [], "integrations": [], "metadata_path": str(omni_home / "skills" / "agent-integrations.json")},
                ),
                mock.patch("omni_core.render_action_summary"),
                mock.patch("omni_core.render_command_header"),
                mock.patch("omni_core.print_logo"),
                mock.patch("omni_core.section"),
                mock.patch("omni_core.nl"),
                mock.patch.object(omni_core.OmniCore, "is_interactive", return_value=True),
                mock.patch.object(omni_core.OmniCore, "prompt_text", side_effect=["/logout"]),
            ]

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                core = omni_core.OmniCore()
                core.chat_cmd("", accept_all=True)

            self.assertFalse((chat_dir / "memory.json").exists())
            self.assertFalse(session_path.exists())


if __name__ == "__main__":
    unittest.main()

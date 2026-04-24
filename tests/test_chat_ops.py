import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chat_ops import (  # noqa: E402
    build_chat_memory_prompt,
    clean_assistant_output,
    build_chat_request,
    default_chat_memory,
    ensure_chat_permissions,
    extract_chat_text,
    load_chat_memory,
    load_chat_session,
    new_chat_session,
    parse_action_block,
    record_chat_turn,
    save_chat_memory,
    save_chat_session,
    trim_chat_messages,
)


class ChatOpsTests(unittest.TestCase):
    def test_openai_compatible_request_uses_chat_completions(self):
        request = build_chat_request(
            protocol="openai-compatible",
            base_url="https://api.openai.com/v1",
            model="gpt-5.2",
            api_key="secret-123",
            messages=[{"role": "system", "content": "Eres Omni."}, {"role": "user", "content": "Hola"}],
        )
        self.assertEqual(request["url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(request["headers"]["Authorization"], "Bearer secret-123")
        payload = json.loads(request["body"])
        self.assertEqual(payload["model"], "gpt-5.2")
        self.assertEqual(payload["messages"][1]["content"], "Hola")

    def test_anthropic_request_splits_system_prompt(self):
        request = build_chat_request(
            protocol="anthropic",
            base_url="https://api.anthropic.com",
            model="claude-sonnet-4-20250514",
            api_key="secret-456",
            messages=[{"role": "system", "content": "Sistema Omni"}, {"role": "user", "content": "Hola"}],
        )
        self.assertEqual(request["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(request["headers"]["x-api-key"], "secret-456")
        payload = json.loads(request["body"])
        self.assertEqual(payload["system"], "Sistema Omni")
        self.assertEqual(payload["messages"][0]["role"], "user")

    def test_gemini_request_uses_native_generate_content(self):
        request = build_chat_request(
            protocol="gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            model="gemini-2.5-flash",
            api_key="gem-secret",
            messages=[{"role": "system", "content": "Eres Omni."}, {"role": "user", "content": "Hola"}],
        )
        self.assertIn("/models/gemini-2.5-flash:generateContent?key=gem-secret", request["url"])
        payload = json.loads(request["body"])
        self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "Eres Omni.")
        self.assertEqual(payload["contents"][0]["role"], "user")

    def test_extract_chat_text_supports_protocol_variants(self):
        self.assertEqual(
            extract_chat_text("openai-compatible", {"choices": [{"message": {"content": "hola openai"}}]}),
            "hola openai",
        )
        self.assertEqual(
            extract_chat_text("anthropic", {"content": [{"type": "text", "text": "hola claude"}]}),
            "hola claude",
        )
        self.assertEqual(
            extract_chat_text(
                "gemini",
                {"candidates": [{"content": {"parts": [{"text": "hola gemini"}]}}]},
            ),
            "hola gemini",
        )

    def test_trim_chat_messages_keeps_system_and_recent_turns(self):
        messages = [{"role": "system", "content": "Sistema"}]
        for idx in range(12):
            messages.append({"role": "user", "content": f"u{idx}"})
            messages.append({"role": "assistant", "content": f"a{idx}"})
        trimmed = trim_chat_messages(messages, max_messages=6)
        self.assertEqual(trimmed[0]["role"], "system")
        self.assertEqual(len(trimmed), 7)
        self.assertEqual(trimmed[-1]["content"], "a11")

    def test_action_block_can_be_extracted_and_removed(self):
        raw = 'Te dejo el comando listo.\nACTION:{"type":"command","command":"omni doctor","confirm":true}'
        action = parse_action_block(raw)
        clean = clean_assistant_output(raw)
        self.assertEqual(action["type"], "command")
        self.assertEqual(action["command"], "omni doctor")
        self.assertEqual(clean, "Te dejo el comando listo.")

    def test_chat_session_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp)
            session = new_chat_session(
                session_dir,
                provider_title="OpenAI Direct",
                model="gpt-5.2",
                base_url="https://api.openai.com/v1",
            )
            session["messages"].append({"role": "user", "content": "hola"})
            save_chat_session(Path(session["path"]), session)
            loaded = load_chat_session(Path(session["path"]))
            self.assertEqual(loaded["provider_title"], "OpenAI Direct")
            self.assertEqual(loaded["messages"][0]["content"], "hola")

    def test_new_chat_session_gets_default_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = new_chat_session(
                Path(tmp),
                provider_title="Gemini",
                model="gemini-2.5-flash",
                base_url="https://generativelanguage.googleapis.com/v1beta",
            )
            permissions = ensure_chat_permissions(session)
            self.assertEqual(permissions["mode"], "smart")

    def test_chat_memory_round_trip_and_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_path = Path(tmp) / "memory.json"
            memory = default_chat_memory(
                host_snapshot={"host": "linux-box", "shell": "bash", "package_manager": "apt-get"},
                provider_title="OpenAI Direct",
                model="gpt-5.2",
                language="es",
            )
            memory = record_chat_turn(
                memory,
                user_prompt="haz diagnóstico",
                assistant_text="Voy a correr omni doctor",
                action={"type": "command", "command": "omni doctor", "title": "Diagnóstico"},
                command_result={"success": True, "returncode": 0},
            )
            save_chat_memory(memory_path, memory)
            loaded = load_chat_memory(memory_path)
            prompt = build_chat_memory_prompt(loaded)
            self.assertIn("linux-box", prompt)
            self.assertIn("OpenAI Direct", prompt)
            self.assertIn("omni doctor", prompt)


if __name__ == "__main__":
    unittest.main()

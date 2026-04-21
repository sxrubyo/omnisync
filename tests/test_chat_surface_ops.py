import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from onboarding_ops import build_flow_options, build_start_menu, normalize_flow_choice  # noqa: E402
from platform_ops import PlatformInfo  # noqa: E402
from playbook_ops import build_examples_catalog  # noqa: E402


class ChatSurfaceOpsTests(unittest.TestCase):
    def _linux_info(self) -> PlatformInfo:
        return PlatformInfo(
            system="linux",
            release="6.0",
            version="6.0",
            machine="x86_64",
            shell="bash",
            shell_family="posix",
            package_manager="apt-get",
            interactive=True,
            home="/home/ubuntu",
            terminal="xterm",
        )

    def test_start_flow_supports_chat(self):
        self.assertEqual(normalize_flow_choice("chat"), "chat")
        self.assertEqual(normalize_flow_choice("7"), "chat")
        options = build_flow_options(self._linux_info())
        keys = [item.key for item in options]
        self.assertIn("connect", keys)
        self.assertIn("briefcase", keys)
        self.assertIn("chat", keys)
        menu = build_start_menu(self._linux_info())
        self.assertTrue(any(option["key"] == "connect" for option in menu["options"]))
        self.assertTrue(any(option["key"] == "chat" for option in menu["options"]))

    def test_examples_catalog_mentions_chat(self):
        entries = build_examples_catalog()
        keys = {entry.key for entry in entries}
        self.assertIn("chat", keys)


if __name__ == "__main__":
    unittest.main()

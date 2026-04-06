import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from onboarding_ops import (  # noqa: E402
    build_flow_options,
    build_flow_prompt,
    build_start_menu,
    build_start_questions,
    normalize_flow_choice,
    recommended_start_flow,
    should_accept_all,
)
from platform_ops import PlatformInfo  # noqa: E402


class OnboardingOpsTests(unittest.TestCase):
    def test_normalize_flow_choice_supports_numbers_and_aliases(self):
        self.assertEqual(normalize_flow_choice("1"), "bridge")
        self.assertEqual(normalize_flow_choice("puente"), "bridge")
        self.assertEqual(normalize_flow_choice("migrar"), "migrate")
        self.assertEqual(normalize_flow_choice("restore"), "restore")
        self.assertEqual(normalize_flow_choice("expert"), "advanced")

    def test_recommended_start_flow_windows_prefers_bridge(self):
        info = PlatformInfo(
            system="windows",
            release="11",
            version="11",
            machine="amd64",
            shell="powershell",
            shell_family="powershell",
            package_manager="winget",
            interactive=True,
            home="C:/Users/santi",
            terminal="windows-terminal",
        )
        self.assertEqual(recommended_start_flow(info), "bridge")

    def test_build_flow_options_marks_one_recommended(self):
        info = PlatformInfo(
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
        options = build_flow_options(info)
        recommended = [option.key for option in options if option.recommended]
        self.assertEqual(recommended, ["migrate"])

    def test_build_start_questions_and_menu_include_guided_choice(self):
        info = PlatformInfo(
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
        questions = build_start_questions(info)
        self.assertEqual(questions[0].key, "entry_mode")
        self.assertIn("puente o como migracion", questions[0].prompt.lower())

        menu = build_start_menu(info)
        self.assertEqual(menu["recommended_flow"], "migrate")
        self.assertFalse(menu["non_interactive"])
        self.assertEqual(len(menu["options"]), 6)

    def test_build_flow_prompt_mentions_recommendation(self):
        prompt = build_flow_prompt(
            PlatformInfo(
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
        )
        self.assertIn("Recommended default:", prompt)
        self.assertIn("Use this machine as a bridge", prompt)

    def test_should_accept_all_honors_flags_and_env(self):
        self.assertTrue(should_accept_all(accept_all=True))
        self.assertTrue(should_accept_all(yes=True))
        self.assertTrue(should_accept_all(env={"OMNI_ASSUME_YES": "1"}))
        self.assertFalse(should_accept_all(env={"OMNI_ASSUME_YES": "0"}))


if __name__ == "__main__":
    unittest.main()

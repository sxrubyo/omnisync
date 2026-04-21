import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from omni_core import apply_digit_jump, ALIASES  # noqa: E402


class OmniCliNavigationTests(unittest.TestCase):
    def test_apply_digit_jump_waits_for_multidigit_indexes(self) -> None:
        buffer, selected, should_return = apply_digit_jump("", "1", option_count=16)
        self.assertEqual(buffer, "1")
        self.assertEqual(selected, 0)
        self.assertFalse(should_return)

        buffer, selected, should_return = apply_digit_jump(buffer, "4", option_count=16)
        self.assertEqual(buffer, "")
        self.assertEqual(selected, 13)
        self.assertTrue(should_return)

    def test_apply_digit_jump_immediately_selects_unambiguous_option(self) -> None:
        buffer, selected, should_return = apply_digit_jump("", "9", option_count=16)
        self.assertEqual(buffer, "")
        self.assertEqual(selected, 8)
        self.assertTrue(should_return)

    def test_commands_alias_routes_to_help(self) -> None:
        self.assertEqual(ALIASES["commands"], "help")


if __name__ == "__main__":
    unittest.main()

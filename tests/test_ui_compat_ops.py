import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from omni_core import _apply_menu_digit_input, _resolve_buffered_menu_selection, _should_buffer_menu_digits  # noqa: E402


class UiCompatOpsTests(unittest.TestCase):
    def test_single_digit_menu_keeps_direct_jump(self):
        buffer, selection = _apply_menu_digit_input("", "4", 9)
        self.assertEqual(buffer, "")
        self.assertEqual(selection, 3)

    def test_large_menu_buffers_digits_until_enter(self):
        buffer, selection = _apply_menu_digit_input("", "1", 16)
        self.assertEqual(buffer, "1")
        self.assertIsNone(selection)
        buffer, selection = _apply_menu_digit_input(buffer, "2", 16)
        self.assertEqual(buffer, "12")
        self.assertIsNone(selection)
        self.assertEqual(_resolve_buffered_menu_selection(buffer, 0, 16), 11)

    def test_large_menu_invalid_buffer_falls_back_to_current(self):
        self.assertTrue(_should_buffer_menu_digits(10))
        self.assertEqual(_resolve_buffered_menu_selection("99", 2, 16), 2)


if __name__ == "__main__":
    unittest.main()

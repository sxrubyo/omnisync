import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from platform_ops import (  # noqa: E402
    PlatformInfo,
    detect_package_manager,
    detect_platform_info,
    detect_shell,
    detect_shell_family,
    is_non_interactive,
)


class PlatformOpsTests(unittest.TestCase):
    def test_detect_shell_prefers_powershell_clues_on_windows(self):
        shell = detect_shell({"PSModulePath": r"C:\\Program Files\\PowerShell\\7"}, system="windows")
        self.assertIn(shell, {"powershell", "pwsh", "7"})

    def test_detect_shell_uses_posix_shell_env(self):
        shell = detect_shell({"SHELL": "/bin/bash"}, system="linux")
        self.assertEqual(shell, "bash")

    def test_detect_shell_family(self):
        self.assertEqual(detect_shell_family("pwsh"), "powershell")
        self.assertEqual(detect_shell_family("bash"), "posix")
        self.assertEqual(detect_shell_family("cmd.exe"), "cmd")

    def test_detect_package_manager_linux_prefers_apt_get(self):
        with patch("platform_ops.detect_system", return_value="linux"):
            pm = detect_package_manager("linux", which=lambda name: "/usr/bin/apt-get" if name == "apt-get" else None)
        self.assertEqual(pm, "apt-get")

    def test_detect_package_manager_windows_prefers_winget(self):
        pm = detect_package_manager("windows", which=lambda name: "C:/Windows/AppInstaller/winget.exe" if name == "winget" else None)
        self.assertEqual(pm, "winget")

    def test_detect_platform_info_marks_non_interactive(self):
        info = detect_platform_info(
            {"OMNI_ASSUME_YES": "1", "SHELL": "/bin/zsh", "TERM": "xterm-256color"},
            system_fn=lambda: "Linux",
            which=lambda name: "/usr/bin/apt" if name == "apt" else None,
        )
        self.assertIsInstance(info, PlatformInfo)
        self.assertFalse(info.interactive)
        self.assertEqual(info.package_manager, "apt")
        self.assertEqual(info.shell, "zsh")

    def test_is_non_interactive_respects_ci_and_assume_yes(self):
        self.assertTrue(is_non_interactive({"CI": "true"}))
        self.assertTrue(is_non_interactive({"OMNI_ASSUME_YES": "yes"}))
        self.assertFalse(is_non_interactive({"CI": "false"}))


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cli_ux_ops import (  # noqa: E402
    build_command_ship_lines,
    build_guided_start_surface_lines,
    build_help_surface_lines,
    collect_host_snapshot,
)


class CliUxOpsTests(unittest.TestCase):
    def test_collect_host_snapshot_exposes_core_runtime_keys(self):
        payload = collect_host_snapshot()
        self.assertIn("system", payload)
        self.assertIn("shell", payload)
        self.assertIn("cpu_cores", payload)
        self.assertIn("disk_free_gb", payload)
        self.assertGreaterEqual(payload["cpu_cores"], 0)

    def test_build_help_surface_lines_places_control_surface_beside_brand(self):
        lines = build_help_surface_lines(
            {
                "system": "linux",
                "release": "6.8",
                "shell": "bash",
                "package_manager": "apt-get",
                "cpu_cores": 2,
                "memory_total_mb": 8000,
                "memory_used_mb": 3200,
                "disk_total_gb": 100.0,
                "disk_free_gb": 42.0,
            },
            [
                "Quickstart: omni guide",
                "Keep secrets out of git.",
            ],
        )
        self.assertTrue(any("OMNI CONTROL SURFACE" in line for line in lines))
        self.assertTrue(any("HOST SNAPSHOT" in line for line in lines))
        self.assertTrue(any("QUICKSTART" in line for line in lines))
        self.assertTrue(any("O  M  N  I" in line for line in lines))
        self.assertTrue(any("Host:" in line for line in lines))

    def test_build_guided_start_surface_lines_uses_single_start_surface_box(self):
        lines = build_guided_start_surface_lines(
            {
                "system": "linux",
                "release": "6.8",
                "shell": "bash",
                "package_manager": "apt-get",
                "cpu_cores": 2,
                "memory_total_mb": 8000,
                "memory_used_mb": 3200,
                "disk_total_gb": 100.0,
                "disk_free_gb": 42.0,
                "terminal": "xterm-256color",
            },
            [
                "Quickstart: omni",
                "Use omni guide or omni connect to begin.",
            ],
            version="2.1.0",
            codename="Titan",
            mode="guided",
            scope="production-clean",
        )
        self.assertTrue(any("OMNI START SURFACE" in line for line in lines))
        self.assertTrue(any("OPERATOR MODE" in line for line in lines))
        self.assertTrue(any("QUICKSTART" in line for line in lines))
        self.assertTrue(any("v2.1.0" in line for line in lines))
        self.assertTrue(any("Host:" in line for line in lines))
        self.assertTrue(any("Mode: guided" in line for line in lines))
        self.assertTrue(any("Scope: production-clean" in line for line in lines))

    def test_build_guided_start_surface_lines_uses_compact_gap_for_terminals(self):
        lines = build_guided_start_surface_lines(
            {
                "system": "linux",
                "release": "6.8.0-1051-aws",
                "shell": "bash",
                "package_manager": "apt-get",
                "cpu_cores": 2,
                "memory_total_mb": 7780,
                "memory_used_mb": 3866,
                "disk_total_gb": 96.7,
                "disk_free_gb": 21.3,
                "terminal": "xterm-256color",
            },
            [],
            version="2.1.0",
            codename="Titan",
            mode="guided",
            scope="production-clean",
        )
        guided_line = next(line for line in lines if "╭ OMNI START SURFACE" in line)
        box_start = guided_line.index("╭ OMNI START SURFACE")
        self.assertLessEqual(len(guided_line[box_start:]), 70)

    def test_build_help_surface_lines_stacks_for_narrow_terminals(self):
        lines = build_help_surface_lines(
            {
                "system": "linux",
                "release": "6.8",
                "shell": "bash",
                "package_manager": "apt-get",
                "cpu_cores": 2,
                "memory_total_mb": 8000,
                "memory_used_mb": 3200,
                "disk_total_gb": 100.0,
                "disk_free_gb": 42.0,
                "terminal_columns": 82,
            },
            [
                "Quickstart: omni guide",
                "Keep secrets out of git.",
            ],
        )
        omni_line = next(line for line in lines if "O  M  N  I" in line)
        surface_line = next(line for line in lines if "╭ OMNI CONTROL SURFACE" in line)
        self.assertLess(lines.index(omni_line), lines.index(surface_line))
        self.assertFalse("╭ OMNI CONTROL SURFACE" in omni_line)

    def test_build_command_ship_lines_stays_compact_and_space_themed(self):
        lines = build_command_ship_lines()
        self.assertGreaterEqual(len(lines), 6)
        self.assertTrue(any('"""' in line for line in lines))
        self.assertTrue(any("/_\\" in line for line in lines))
        self.assertLessEqual(max(len(line) for line in lines), 28)


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()

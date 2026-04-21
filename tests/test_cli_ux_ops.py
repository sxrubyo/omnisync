import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cli_ux_ops import build_guided_start_surface_lines, build_help_surface_lines, collect_host_snapshot  # noqa: E402


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
        self.assertTrue(any("O  M  N  I" in line and "OMNI CONTROL SURFACE" in line for line in lines))

    def test_build_guided_start_surface_lines_places_start_and_control_boxes_beside_brand(self):
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
            },
            [
                "Quickstart: omni",
                "Use omni guide or omni connect to begin.",
            ],
            version="2.1.0",
            codename="Titan",
        )
        self.assertTrue(any("Omni Guided Start" in line for line in lines))
        self.assertTrue(any("OMNI CONTROL SURFACE" in line for line in lines))
        self.assertTrue(any("v2.1.0" in line and "OMNI CONTROL SURFACE" in line for line in lines))


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()

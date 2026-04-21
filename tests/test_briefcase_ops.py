import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from briefcase_ops import build_briefcase_manifest, build_restore_plan  # noqa: E402
from platform_ops import PlatformInfo  # noqa: E402


class BriefcaseOpsTests(unittest.TestCase):
    def test_build_briefcase_manifest_includes_transport_and_summary(self):
        manifest = {
            "version": 1,
            "profile": "full-home",
            "host_root": "/home/ubuntu",
            "state_paths": ["/home/ubuntu"],
            "secret_paths": ["/home/ubuntu/.ssh"],
            "install_targets": ["/home/ubuntu/omni-core"],
            "pm2_ecosystems": ["/home/ubuntu/whatsapp-bridge/ecosystem.config.cjs"],
            "compose_projects": ["/home/ubuntu/nova-os"],
            "apt_packages": ["git", "rsync"],
            "npm_global_packages": ["pm2"],
        }
        report = {
            "included": [
                {"kind": "state", "path": "/home/ubuntu"},
                {"kind": "secret", "path": "/home/ubuntu/.ssh"},
            ],
            "discovered": [
                {"classification": "product", "path": "/home/ubuntu/omni-core"},
                {"classification": "noise", "path": "/home/ubuntu/.cache"},
            ],
        }
        platform_info = PlatformInfo(
            system="linux",
            release="6.8.0",
            version="test",
            machine="x86_64",
            shell="bash",
            shell_family="posix",
            package_manager="apt-get",
            interactive=True,
            home="/home/ubuntu",
            terminal="xterm-256color",
        )

        briefcase = build_briefcase_manifest(manifest, platform_info, inventory_report=report)

        self.assertEqual(briefcase["schema_version"], 3)
        self.assertEqual(briefcase["product"]["name"], "omni-migrate-sync")
        self.assertEqual(briefcase["source"]["platform"]["system"], "linux")
        self.assertEqual(briefcase["inventory"]["summary"]["included_state_count"], 1)
        self.assertEqual(briefcase["inventory"]["summary"]["discovered_noise_count"], 1)
        self.assertEqual(briefcase["transport"]["github"]["role"], "metadata-only")

    def test_build_restore_plan_marks_same_package_manager_as_applicable(self):
        briefcase = {
            "source": {
                "profile": "production-clean",
                "platform": {"system": "linux", "package_manager": "apt-get"},
            },
            "inventory": {
                "state_paths": ["/home/ubuntu/omni-core"],
                "secret_paths": ["/home/ubuntu/.ssh"],
                "install_targets": ["/home/ubuntu/omni-core"],
                "compose_projects": ["/home/ubuntu/nova-os"],
                "pm2_ecosystems": ["/home/ubuntu/whatsapp-bridge/ecosystem.config.cjs"],
                "packages": {
                    "system": ["git", "rsync"],
                    "node_global": ["pm2"],
                },
            },
        }
        target = PlatformInfo(
            system="linux",
            release="6.8.0",
            version="test",
            machine="x86_64",
            shell="bash",
            shell_family="posix",
            package_manager="apt-get",
            interactive=True,
            home="/home/ubuntu",
            terminal="xterm-256color",
        )

        plan = build_restore_plan(briefcase, target)
        package_step = next(step for step in plan["steps"] if step["id"] == "install-system-packages")
        secret_step = next(step for step in plan["steps"] if step["id"] == "restore-secrets")

        self.assertFalse(plan["cross_platform"])
        self.assertEqual(package_step["status"], "applicable")
        self.assertEqual(secret_step["status"], "manual")

    def test_build_restore_plan_exposes_cross_platform_package_gap(self):
        briefcase = {
            "source": {
                "profile": "full-home",
                "platform": {"system": "linux", "package_manager": "apt-get"},
            },
            "inventory": {
                "state_paths": ["/home/ubuntu"],
                "secret_paths": ["/home/ubuntu/.ssh"],
                "install_targets": ["/home/ubuntu/omni-core"],
                "compose_projects": ["/home/ubuntu/nova-os"],
                "pm2_ecosystems": [],
                "packages": {
                    "system": ["git", "docker.io"],
                    "node_global": [],
                },
            },
        }
        target = PlatformInfo(
            system="windows",
            release="11",
            version="test",
            machine="AMD64",
            shell="powershell",
            shell_family="powershell",
            package_manager="winget",
            interactive=True,
            home="C:/Users/santi",
            terminal="xterm-256color",
        )

        plan = build_restore_plan(briefcase, target)
        package_step = next(step for step in plan["steps"] if step["id"] == "install-system-packages")
        compose_step = next(step for step in plan["steps"] if step["id"] == "restore-compose-projects")

        self.assertTrue(plan["cross_platform"])
        self.assertEqual(package_step["status"], "manual")
        self.assertEqual(compose_step["status"], "manual")
        self.assertTrue(any("Cross-platform restore detected" in gap for gap in plan["capability_gaps"]))
        self.assertTrue(any("source uses apt-get, target uses winget" in gap for gap in plan["capability_gaps"]))


if __name__ == "__main__":
    unittest.main()

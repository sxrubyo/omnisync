import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from reconcile_ops import (  # noqa: E402
    build_compose_up_command,
    detect_compose_command,
    ensure_supported_node_runtime,
    install_apt_packages,
    install_npm_global_packages,
)


class ReconcileOpsTests(unittest.TestCase):
    def test_detect_compose_command_prefers_plugin(self):
        with mock.patch("reconcile_ops.command_exists", side_effect=lambda name: name == "docker"), \
             mock.patch("reconcile_ops.run_cmd", return_value=(0, "Docker Compose version v2.27.0", "")):
            self.assertEqual(detect_compose_command(), "docker compose")

    def test_detect_compose_command_falls_back_to_docker_compose(self):
        def fake_exists(name: str) -> bool:
            return name in {"docker", "docker-compose"}

        with mock.patch("reconcile_ops.command_exists", side_effect=fake_exists), \
             mock.patch("reconcile_ops.run_cmd", return_value=(1, "", "unknown shorthand flag: 'f' in -f")):
            self.assertEqual(detect_compose_command(), "docker-compose")

    def test_build_compose_up_command_uses_classic_binary_when_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            compose_file = Path(tmp) / "docker-compose.yml"
            compose_file.write_text("services: {}\n", encoding="utf-8")

            with mock.patch("reconcile_ops.detect_compose_command", return_value="docker-compose"):
                command = build_compose_up_command(compose_file)

            self.assertEqual(command, f"docker-compose -f {str(compose_file)} up -d --build")

    def test_install_apt_packages_falls_back_to_docker_compose_package(self):
        state = {"updated": False}

        def fake_run(cmd: str, cwd=None):
            if cmd == "command -v apt-get":
                return (0, "/usr/bin/apt-get", "")
            if cmd == "dpkg -s docker-compose-plugin":
                return (1, "", "not installed")
            if cmd == "dpkg -s docker-compose":
                return (1, "", "not installed")
            if cmd == "apt-cache show docker-compose-plugin":
                return (100, "", "no packages found")
            if cmd == "apt-cache show docker-compose":
                return (0, "Package: docker-compose", "")
            if cmd == "sudo apt-get update":
                state["updated"] = True
                return (0, "ok", "")
            if cmd == "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker-compose":
                return (0, "installed", "")
            raise AssertionError(f"Unexpected command: {cmd}")

        with mock.patch("reconcile_ops.run_cmd", side_effect=fake_run):
            result = install_apt_packages(["docker-compose-plugin"])

        self.assertTrue(state["updated"])
        self.assertEqual(result["changed"], ["docker-compose"])
        self.assertEqual(result["unavailable"], [])
        self.assertEqual(result["resolved"]["docker-compose-plugin"], "docker-compose")

    def test_install_apt_packages_marks_unavailable_packages_without_crashing(self):
        def fake_run(cmd: str, cwd=None):
            if cmd == "command -v apt-get":
                return (0, "/usr/bin/apt-get", "")
            if cmd == "dpkg -s made-up-package":
                return (1, "", "not installed")
            if cmd == "apt-cache show made-up-package":
                return (100, "", "no packages found")
            raise AssertionError(f"Unexpected command: {cmd}")

        with mock.patch("reconcile_ops.run_cmd", side_effect=fake_run):
            result = install_apt_packages(["made-up-package"])

        self.assertEqual(result["changed"], [])
        self.assertEqual(result["unavailable"], ["made-up-package"])

    def test_ensure_supported_node_runtime_upgrades_old_node(self):
        calls = []

        def fake_run(cmd: str, cwd=None):
            calls.append(cmd)
            if cmd == "command -v node":
                return (0, "/usr/bin/node", "")
            if cmd == "node -v":
                return (0, "v12.22.9", "")
            if cmd == "command -v apt-get":
                return (0, "/usr/bin/apt-get", "")
            if cmd == "command -v curl":
                return (0, "/usr/bin/curl", "")
            if cmd == "command -v sudo":
                return (0, "/usr/bin/sudo", "")
            if cmd == "dpkg -s libnode-dev":
                return (1, "", "not installed")
            if cmd == "dpkg -s nodejs-doc":
                return (1, "", "not installed")
            if cmd == "dpkg -s npm":
                return (1, "", "not installed")
            if cmd == "curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -":
                return (0, "ok", "")
            if cmd == "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs":
                return (0, "installed", "")
            raise AssertionError(f"Unexpected command: {cmd}")

        with mock.patch("reconcile_ops.run_cmd", side_effect=fake_run):
            result = ensure_supported_node_runtime()

        self.assertTrue(result["changed"])
        self.assertEqual(result["target_major"], 20)
        self.assertIn("curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -", calls)

    def test_ensure_supported_node_runtime_removes_legacy_conflicts_before_install(self):
        calls = []

        def fake_run(cmd: str, cwd=None):
            calls.append(cmd)
            if cmd == "command -v node":
                return (0, "/usr/bin/node", "")
            if cmd == "node -v":
                return (0, "v12.22.9", "")
            if cmd == "command -v apt-get":
                return (0, "/usr/bin/apt-get", "")
            if cmd == "command -v curl":
                return (0, "/usr/bin/curl", "")
            if cmd == "command -v sudo":
                return (0, "/usr/bin/sudo", "")
            if cmd == "dpkg -s libnode-dev":
                return (0, "installed", "")
            if cmd == "dpkg -s nodejs-doc":
                return (1, "", "not installed")
            if cmd == "dpkg -s npm":
                return (0, "installed", "")
            if cmd == "sudo DEBIAN_FRONTEND=noninteractive apt-get remove -y libnode-dev npm":
                return (0, "removed", "")
            if cmd == "curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -":
                return (0, "ok", "")
            if cmd == "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs":
                return (0, "installed", "")
            raise AssertionError(f"Unexpected command: {cmd}")

        with mock.patch("reconcile_ops.run_cmd", side_effect=fake_run):
            result = ensure_supported_node_runtime()

        self.assertTrue(result["changed"])
        self.assertIn("sudo DEBIAN_FRONTEND=noninteractive apt-get remove -y libnode-dev npm", calls)

    def test_install_npm_global_packages_uses_sudo_when_prefix_is_system(self):
        calls = []

        def fake_run(cmd: str, cwd=None):
            calls.append(cmd)
            if cmd == "command -v npm":
                return (0, "/usr/bin/npm", "")
            if cmd == "command -v node":
                return (0, "/usr/bin/node", "")
            if cmd == "command -v apt-get":
                return (0, "/usr/bin/apt-get", "")
            if cmd == "command -v curl":
                return (0, "/usr/bin/curl", "")
            if cmd == "node -v":
                return (0, "v20.11.1", "")
            if cmd == "npm list -g pm2 --depth=0":
                return (1, "", "missing")
            if cmd == "npm config get prefix":
                return (0, "/usr/local", "")
            if cmd == "command -v sudo":
                return (0, "/usr/bin/sudo", "")
            if cmd == "sudo npm install -g pm2":
                return (0, "installed", "")
            raise AssertionError(f"Unexpected command: {cmd}")

        with mock.patch("reconcile_ops.run_cmd", side_effect=fake_run), \
             mock.patch("reconcile_ops.os.access", return_value=False):
            result = install_npm_global_packages(["pm2"])

        self.assertEqual(result["changed"], ["pm2"])
        self.assertIn("sudo npm install -g pm2", calls)

    def test_install_npm_global_packages_ensures_node_runtime_before_global_install(self):
        calls = []

        def fake_run(cmd: str, cwd=None):
            calls.append(cmd)
            if cmd == "command -v npm":
                return (0, "/usr/bin/npm", "")
            if cmd == "npm list -g pm2 --depth=0":
                return (1, "", "missing")
            if cmd == "npm config get prefix":
                return (0, "/usr/local", "")
            if cmd == "command -v sudo":
                return (0, "/usr/bin/sudo", "")
            if cmd == "sudo npm install -g pm2":
                return (0, "installed", "")
            raise AssertionError(f"Unexpected command: {cmd}")

        with mock.patch("reconcile_ops.run_cmd", side_effect=fake_run), \
             mock.patch("reconcile_ops.ensure_supported_node_runtime") as ensure_mock, \
             mock.patch("reconcile_ops.os.access", return_value=False):
            result = install_npm_global_packages(["pm2"])

        self.assertEqual(result["changed"], ["pm2"])
        ensure_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()

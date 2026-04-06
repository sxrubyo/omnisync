import sys
import unittest
from pathlib import Path
from unittest import mock
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from omni_core import OmniCore  # noqa: E402


class MigrateFlowOpsTests(unittest.TestCase):
    def test_migrate_host_cmd_stops_when_restore_fails(self):
        core = OmniCore()

        with mock.patch.object(core, "restore_host_cmd", return_value={"success": False}), \
             mock.patch.object(core, "run_backup") as backup_mock, \
             mock.patch("omni_core.render_action_summary") as render_mock:
            core.migrate_host_cmd(accept_all=True)

        backup_mock.assert_not_called()
        render_mock.assert_not_called()

    def test_build_host_drift_report_uses_configured_server_when_summary_missing(self):
        core = OmniCore()
        core.servers = [{"name": "main-ubuntu", "host": "172.31.99.10"}]

        fake_identity = mock.Mock(
            public_ip="54.1.2.3",
            private_ip="172.31.34.176",
            hostname="new-host",
            fqdn="new-host.local",
            ip_candidates=["172.31.34.176"],
            source="local",
        )

        with mock.patch("omni_core.build_host_rewrite_context", return_value={
            "summary": None,
            "summary_found": False,
            "source_identity": {},
            "target_identity": {
                "public_ip": fake_identity.public_ip,
                "private_ip": fake_identity.private_ip,
                "hostname": fake_identity.hostname,
                "fqdn": fake_identity.fqdn,
            },
            "replacements": {},
        }), mock.patch("omni_core.detect_host_identity", return_value=fake_identity):
            drift = core.build_host_drift_report(root="/tmp")

        self.assertTrue(drift["context"]["summary_found"])
        self.assertEqual(drift["context"]["replacements"]["172.31.99.10"], "54.1.2.3")

    def test_restore_host_cmd_ignores_implicit_auto_bundles_during_bootstrap(self):
        core = OmniCore()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host_dir = root / "host-bundles"
            auto_dir = root / "auto-bundles"
            host_dir.mkdir()
            auto_dir.mkdir()
            (auto_dir / "state_bundle_20260406_231509.tar.gz").write_text("state", encoding="utf-8")
            (auto_dir / "secrets_bundle_20260406_231509.tar.gz").write_text("secrets", encoding="utf-8")

            core.bundle_dir = host_dir

            with mock.patch.object(core, "auto_backup_dir", return_value=auto_dir), \
                 mock.patch.object(core, "init_workspace"), \
                 mock.patch.object(core, "resolve_manifest", return_value=(root / "manifest.json", {"profile": "full-home"})), \
                 mock.patch.object(core, "read_passphrase", return_value=""), \
                 mock.patch.object(core, "confirm_step", return_value=True), \
                 mock.patch("omni_core.resolve_installed_inventory_across_dirs", return_value=None), \
                 mock.patch("omni_core.reconcile_host", return_value={"steps": []}) as reconcile_mock:
                result = core.restore_host_cmd(
                    accept_all=True,
                    show_summary=False,
                    auto_backup=False,
                    allow_missing_bundles=True,
                )

        self.assertTrue(result["success"])
        self.assertTrue(result["bootstrap_only"])
        self.assertFalse(result["used_bundles"])
        reconcile_mock.assert_called_once()
        _, kwargs = reconcile_mock.call_args
        self.assertEqual(kwargs["bundle_path"], "")
        self.assertEqual(kwargs["secrets_path"], "")

    def test_restore_host_cmd_hydrates_from_remote_source_in_bootstrap_mode(self):
        core = OmniCore()
        core.servers = [{"name": "main-ubuntu", "host": "172.31.99.10", "paths": ["/home/ubuntu"]}]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host_dir = root / "host-bundles"
            auto_dir = root / "auto-bundles"
            host_dir.mkdir()
            auto_dir.mkdir()
            core.bundle_dir = host_dir

            with mock.patch.object(core, "auto_backup_dir", return_value=auto_dir), \
                 mock.patch.object(core, "init_workspace"), \
                 mock.patch.object(core, "resolve_manifest", return_value=(root / "manifest.json", {"profile": "full-home"})), \
                 mock.patch.object(core, "read_passphrase", return_value=""), \
                 mock.patch.object(core, "confirm_step", return_value=True), \
                 mock.patch.object(core, "hydrate_from_remote_servers", return_value={"success": True, "results": [{"success": True}]} ) as hydrate_mock, \
                 mock.patch("omni_core.resolve_installed_inventory_across_dirs", return_value=None), \
                 mock.patch("omni_core.reconcile_host", return_value={"steps": []}) as reconcile_mock:
                result = core.restore_host_cmd(
                    accept_all=True,
                    show_summary=False,
                    auto_backup=False,
                    allow_missing_bundles=True,
                )

        self.assertTrue(result["success"])
        hydrate_mock.assert_called_once()
        reconcile_mock.assert_called_once()
        self.assertEqual(result["hydration_result"]["results"][0]["success"], True)


if __name__ == "__main__":
    unittest.main()

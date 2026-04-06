import sys
import unittest
from pathlib import Path
from unittest import mock


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


if __name__ == "__main__":
    unittest.main()

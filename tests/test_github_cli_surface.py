import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import omni_core  # noqa: E402


class GitHubCliSurfaceTests(unittest.TestCase):
    def test_config_cmd_language_persists_global_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            global_config = tmp_root / ".omni" / "config.json"

            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(omni_core, "GLOBAL_CONFIG_FILE", global_config))
                stack.enter_context(mock.patch("omni_core.print_logo"))
                stack.enter_context(mock.patch("omni_core.section"))
                core = omni_core.OmniCore()
                core.config_cmd("language", value="en")

            payload = json.loads(global_config.read_text(encoding="utf-8"))
            self.assertEqual(payload["language"], "en")

    def test_auth_cmd_github_persists_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            global_config = tmp_root / ".omni" / "config.json"

            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(omni_core, "GLOBAL_CONFIG_FILE", global_config))
                stack.enter_context(mock.patch("omni_core.gh_cli_token", return_value="gho_test"))
                stack.enter_context(mock.patch("omni_core.github_identity", return_value={"login": "sxrubyo"}))
                stack.enter_context(mock.patch("omni_core.print_logo"))
                stack.enter_context(mock.patch("omni_core.section"))
                stack.enter_context(mock.patch("omni_core.render_action_summary"))
                core = omni_core.OmniCore()
                core.auth_cmd("github", repo_slug="sxrubyo/omni-private")

            payload = json.loads(global_config.read_text(encoding="utf-8"))
            self.assertEqual(payload["github"]["repo"], "omni-private")
            self.assertEqual(payload["github"]["owner"], "sxrubyo")
            self.assertEqual(payload["github"]["token"], "gho_test")

    def test_push_cmd_uploads_briefcase_and_restore_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            global_config = tmp_root / ".omni" / "config.json"
            global_config.parent.mkdir(parents=True, exist_ok=True)
            global_config.write_text(
                json.dumps({"github": {"owner": "sxrubyo", "repo": "omni-private", "token": "gho_test"}}),
                encoding="utf-8",
            )

            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(omni_core, "GLOBAL_CONFIG_FILE", global_config))
                stack.enter_context(mock.patch("omni_core.ensure_private_repo", return_value={"name": "omni-private"}))
                put_mock = stack.enter_context(mock.patch("omni_core.put_file", return_value={"content": {"path": "briefcases/test.json"}}))
                stack.enter_context(
                    mock.patch.object(
                        omni_core.OmniCore,
                        "build_briefcase_export",
                        return_value={
                            "manifest_path": "/tmp/system_manifest.json",
                            "briefcase": {"kind": "omni-briefcase", "source": {"profile": "full-home"}},
                            "restore_script": "#!/usr/bin/env bash\necho restore\n",
                        },
                    )
                )
                stack.enter_context(mock.patch("omni_core.print_logo"))
                stack.enter_context(mock.patch("omni_core.section"))
                stack.enter_context(mock.patch("omni_core.render_action_summary"))
                core = omni_core.OmniCore()
                core.push_cmd(profile="full-home")

            self.assertEqual(put_mock.call_count, 2)

    def test_pull_cmd_downloads_latest_briefcase_and_restore_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            global_config = tmp_root / ".omni" / "config.json"
            global_config.parent.mkdir(parents=True, exist_ok=True)
            global_config.write_text(
                json.dumps({"github": {"owner": "sxrubyo", "repo": "omni-private", "token": "gho_test"}}),
                encoding="utf-8",
            )
            output_dir = tmp_root / "imports"

            entries = [
                {"name": "20260421-120000-host.json", "path": "briefcases/20260421-120000-host.json"},
                {"name": "20260421-120000-host.restore.sh", "path": "briefcases/20260421-120000-host.restore.sh"},
            ]

            def fake_download(_target, path, *, token):
                if path.endswith(".restore.sh"):
                    return "#!/usr/bin/env bash\necho restore\n"
                return '{"kind":"omni-briefcase"}\n'

            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(omni_core, "GLOBAL_CONFIG_FILE", global_config))
                stack.enter_context(mock.patch("omni_core.list_directory", return_value=entries))
                stack.enter_context(mock.patch("omni_core.download_text", side_effect=fake_download))
                stack.enter_context(mock.patch("omni_core.print_logo"))
                stack.enter_context(mock.patch("omni_core.section"))
                stack.enter_context(mock.patch("omni_core.render_action_summary"))
                core = omni_core.OmniCore()
                core.pull_cmd(output=str(output_dir), apply_restore=False)

            self.assertTrue((output_dir / "20260421-120000-host.json").exists())
            self.assertTrue((output_dir / "20260421-120000-host.restore.sh").exists())


if __name__ == "__main__":
    unittest.main()

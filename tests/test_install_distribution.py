from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path("/home/ubuntu/omni-core")
INSTALL_SCRIPT = REPO_ROOT / "install.sh"
POWERSHELL_INSTALL_SCRIPT = REPO_ROOT / "install.ps1"
README = REPO_ROOT / "README.md"


class InstallDistributionTests(unittest.TestCase):
    def test_windows_install_script_exists_with_public_entrypoint(self) -> None:
        self.assertTrue(POWERSHELL_INSTALL_SCRIPT.exists())
        contents = POWERSHELL_INSTALL_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("https://github.com/$RepoSlug/archive/refs/heads/main.zip", contents)
        self.assertIn("omni.cmd", contents)
        self.assertIn('& $WrapperCmd init | Out-Null', contents)
        self.assertIn("Get-Command omni", contents)
        self.assertIn("Paramiko habilita conexiones SSH por contraseña", contents)
        self.assertIn("zipfile.ZipFile", contents)
        self.assertNotIn("Expand-Archive -Path $ZipPath -DestinationPath $TempRoot -Force", contents)
        self.assertIn('if any(not part.strip() for part in rel_parts):', contents)
        self.assertIn('if any(part != part.rstrip(" .") for part in rel_parts):', contents)

    def test_readme_mentions_windows_install_command(self) -> None:
        contents = README.read_text(encoding="utf-8")
        self.assertIn("install.ps1 | iex", contents)
        self.assertIn("npm install -g omnisync", contents)

    def test_unix_install_script_explains_paramiko_bootstrap(self) -> None:
        contents = INSTALL_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Paramiko habilita conexiones SSH por contraseña", contents)
        self.assertIn("OMNI_INSTALL_ASSUME_YES", contents)

    def test_repo_does_not_track_snapshot_payloads(self) -> None:
        result = subprocess.run(
            ["git", "ls-files", "home_snapshot", "home_private_snapshot"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        self.assertEqual(result.stdout.strip(), "")

    def test_install_script_supports_local_repo_override_and_creates_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            local_bin = home / ".local" / "bin"
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["PATH"] = f"{local_bin}:{env['PATH']}"
            env["OMNI_INSTALL_LOCAL_REPO"] = str(REPO_ROOT)
            env["OMNI_INSTALL_SKIP_DEPENDENCY_BOOTSTRAP"] = "1"

            result = subprocess.run(
                ["bash", str(INSTALL_SCRIPT)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

            wrapper = local_bin / "omni"
            self.assertTrue(wrapper.exists())
            self.assertTrue(wrapper.stat().st_mode & stat.S_IXUSR)

            help_result = subprocess.run(
                [str(wrapper), "help"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(help_result.returncode, 0, msg=help_result.stderr or help_result.stdout)
            self.assertIn("OmniSync - Command Reference", help_result.stdout)

    def test_install_script_repairs_preexisting_shadowed_omni_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            local_bin = home / ".local" / "bin"
            shadow_bin = home / "shadow-bin"
            shadow_bin.mkdir(parents=True, exist_ok=True)
            stale_wrapper = shadow_bin / "omni"
            stale_wrapper.write_text("#!/usr/bin/env bash\necho stale-wrapper\n", encoding="utf-8")
            stale_wrapper.chmod(0o755)

            env = os.environ.copy()
            env["HOME"] = str(home)
            env["PATH"] = f"{shadow_bin}:{local_bin}:{env['PATH']}"
            env["OMNI_INSTALL_LOCAL_REPO"] = str(REPO_ROOT)
            env["OMNI_INSTALL_SKIP_DEPENDENCY_BOOTSTRAP"] = "1"

            result = subprocess.run(
                ["bash", str(INSTALL_SCRIPT)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

            guide_result = subprocess.run(
                [str(stale_wrapper), "guide"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(guide_result.returncode, 0, msg=guide_result.stderr or guide_result.stdout)
            self.assertIn("SSH Connect", guide_result.stdout)

            auth_result = subprocess.run(
                [str(stale_wrapper), "auth", "github", "--dry-run"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(auth_result.returncode, 0, msg=auth_result.stderr or auth_result.stdout)
            self.assertNotIn("Unknown action", auth_result.stdout + auth_result.stderr)

    def test_install_script_repairs_external_shadow_wrapper_without_embedding_temp_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            install_home = base / "install-home"
            local_bin = install_home / ".local" / "bin"
            external_root = base / "external-wrapper"
            shadow_bin = external_root / "bin"
            shadow_target_dir = external_root / "worktree"
            shadow_bin.mkdir(parents=True, exist_ok=True)
            shadow_target_dir.mkdir(parents=True, exist_ok=True)

            shadow_target = shadow_target_dir / "omni"
            shadow_target.write_text("#!/usr/bin/env bash\necho stale-wrapper\n", encoding="utf-8")
            shadow_target.chmod(0o755)

            stale_wrapper = shadow_bin / "omni"
            stale_wrapper.symlink_to(shadow_target)

            env = os.environ.copy()
            env["HOME"] = str(install_home)
            env["PATH"] = f"{shadow_bin}:{local_bin}:{env['PATH']}"
            env["OMNI_INSTALL_LOCAL_REPO"] = str(REPO_ROOT)
            env["OMNI_INSTALL_SKIP_DEPENDENCY_BOOTSTRAP"] = "1"

            result = subprocess.run(
                ["bash", str(INSTALL_SCRIPT)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

            repaired_script = shadow_target.read_text(encoding="utf-8")
            self.assertNotIn(str(install_home / ".omni" / "runtime"), repaired_script)
            self.assertIn("$HOME/.omni", repaired_script)

            final_home = base / "final-home"
            final_omni_home = final_home / ".omni"
            final_omni_home.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["cp", "-a", str(install_home / ".omni"), str(final_omni_home)],
                check=True,
                cwd=REPO_ROOT,
            )
            subprocess.run(
                ["rm", "-rf", str(install_home)],
                check=True,
                cwd=REPO_ROOT,
            )

            env_after_cleanup = os.environ.copy()
            env_after_cleanup["HOME"] = str(final_home)
            env_after_cleanup["PATH"] = f"{shadow_bin}:{env_after_cleanup['PATH']}"

            help_result = subprocess.run(
                [str(stale_wrapper), "help"],
                cwd=REPO_ROOT,
                env=env_after_cleanup,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(help_result.returncode, 0, msg=help_result.stderr or help_result.stdout)
            self.assertIn("OmniSync - Command Reference", help_result.stdout)

    def test_install_script_rerun_preserves_runtime_without_rsync_delete_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            local_bin = home / ".local" / "bin"
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["PATH"] = f"{local_bin}:{env['PATH']}"
            env["OMNI_INSTALL_LOCAL_REPO"] = str(REPO_ROOT)
            env["OMNI_INSTALL_SKIP_DEPENDENCY_BOOTSTRAP"] = "1"

            first_result = subprocess.run(
                ["bash", str(INSTALL_SCRIPT)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(first_result.returncode, 0, msg=first_result.stderr or first_result.stdout)

            runtime_site = home / ".omni" / "runtime" / "lib" / "python3.10" / "site-packages" / "demo"
            runtime_site.mkdir(parents=True, exist_ok=True)
            (runtime_site / "__init__.py").write_text("demo = True\n", encoding="utf-8")

            second_result = subprocess.run(
                ["bash", str(INSTALL_SCRIPT)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(second_result.returncode, 0, msg=second_result.stderr or second_result.stdout)
            combined_output = (second_result.stdout or "") + (second_result.stderr or "")
            self.assertNotIn("cannot delete non-empty directory", combined_output)

    def test_install_script_supports_source_archive_without_snapshot_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            archive_root = base / "archive-root" / "omnisync-main"
            archive_root.mkdir(parents=True, exist_ok=True)
            tracked_files = subprocess.check_output(
                ["git", "ls-files", "-z"],
                cwd=REPO_ROOT,
            ).split(b"\0")
            for raw_path in tracked_files:
                if not raw_path:
                    continue
                relative_path = Path(raw_path.decode("utf-8"))
                source = REPO_ROOT / relative_path
                if not source.exists():
                    continue
                target = archive_root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            archive_path = base / "omnisync-main.tgz"
            subprocess.run(
                ["tar", "-czf", str(archive_path), "-C", str(base / "archive-root"), "omnisync-main"],
                cwd=REPO_ROOT,
                check=True,
            )

            home = base / "home"
            local_bin = home / ".local" / "bin"
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["PATH"] = f"{local_bin}:{env['PATH']}"
            env["OMNI_INSTALL_SOURCE_ARCHIVE"] = archive_path.as_uri()

            result = subprocess.run(
                ["bash", str(INSTALL_SCRIPT)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            self.assertFalse((home / ".omni" / "home_snapshot").exists())
            self.assertFalse((home / ".omni" / "home_private_snapshot").exists())

            guide_result = subprocess.run(
                [str(local_bin / "omni"), "guide"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(guide_result.returncode, 0, msg=guide_result.stderr or guide_result.stdout)
            self.assertIn("SSH Connect", guide_result.stdout)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from github_ops import (
    GitHubTarget,
    download_text,
    list_directory,
)


def _collect_tree_files(root: Path, *, app_dir: Path) -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []
    if not root.exists():
        return files
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(app_dir).as_posix()
        files.append(
            {
                "relative_path": rel_path,
                "size": path.stat().st_size,
                "executable": path.suffix == ".sh",
            }
        )
    return files


def _collect_explicit_file(path: Path, *, app_dir: Path) -> Optional[Dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return None
    rel_path = path.relative_to(app_dir).as_posix()
    return {
        "relative_path": rel_path,
        "size": path.stat().st_size,
        "executable": path.suffix == ".sh",
    }


def create_home_snapshot_bundle(
    app_dir: Path,
    *,
    home_root: str,
    snapshot_id: str,
    host: str,
    stamp: str,
    mode: str = "private",
    include_passphrase: bool = True,
) -> Dict[str, Any]:
    script = app_dir / "scripts" / "refresh_home_snapshot.sh"
    if not script.exists():
        raise FileNotFoundError(f"Missing snapshot refresh script: {script}")

    subprocess.run(
        ["bash", str(script), "--mode", mode, str(Path(home_root).expanduser())],
        cwd=str(app_dir),
        check=True,
        capture_output=True,
        text=True,
    )

    files = _collect_tree_files(app_dir / "home_snapshot", app_dir=app_dir)
    if mode == "private":
        files.extend(_collect_tree_files(app_dir / "home_private_snapshot", app_dir=app_dir))

    explicit_candidates = [
        app_dir / "scripts" / "restore_home_private_snapshot.sh",
        app_dir / "scripts" / "refresh_home_snapshot.sh",
    ]
    if include_passphrase:
        explicit_candidates.append(app_dir / "backups" / "home_private_snapshot.passphrase")

    for candidate in explicit_candidates:
        entry = _collect_explicit_file(candidate, app_dir=app_dir)
        if entry:
            files.append(entry)

    manifest = {
        "kind": "omni-home-snapshot",
        "version": 1,
        "snapshot_id": snapshot_id,
        "created_at": stamp,
        "host": host,
        "home_root": str(Path(home_root).expanduser()),
        "mode": mode,
        "files": sorted(files, key=lambda item: str(item.get("relative_path") or "")),
    }

    root_prefix = f"home-snapshots/{snapshot_id}"
    return {
        "manifest": manifest,
        "manifest_path": f"{root_prefix}.manifest.json",
        "root_prefix": root_prefix,
    }


def materialize_home_snapshot_bundle(
    bundle: Dict[str, Any],
    *,
    app_dir: Path,
    destination_root: Path,
) -> Dict[str, Any]:
    manifest = bundle["manifest"]
    root = destination_root.expanduser().resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    manifest_local = root / "snapshot.manifest.json"
    manifest_local.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for entry in manifest.get("files", []):
        rel_path = str(entry.get("relative_path") or "").strip()
        if not rel_path:
            continue
        source = app_dir / rel_path
        if not source.exists():
            continue
        destination = root / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if entry.get("executable"):
            destination.chmod(0o755)

    return {
        "manifest": manifest,
        "root": root,
        "manifest_path": manifest_local,
    }


def create_local_home_snapshot_export(
    app_dir: Path,
    *,
    export_root: Path,
    home_root: str,
    snapshot_id: str,
    host: str,
    stamp: str,
    mode: str = "private",
    include_passphrase: bool = True,
) -> Dict[str, Any]:
    bundle = create_home_snapshot_bundle(
        app_dir,
        home_root=home_root,
        snapshot_id=snapshot_id,
        host=host,
        stamp=stamp,
        mode=mode,
        include_passphrase=include_passphrase,
    )
    return materialize_home_snapshot_bundle(bundle, app_dir=app_dir, destination_root=export_root)


def _run_git(args: List[str], *, token: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="omni-git-auth-") as tmp:
        askpass = Path(tmp) / "askpass.sh"
        askpass.write_text(
            "#!/usr/bin/env sh\n"
            "case \"$1\" in\n"
            "  *Username*) printf '%s\\n' 'x-access-token' ;;\n"
            "  *Password*) printf '%s\\n' \"$OMNI_GITHUB_TOKEN\" ;;\n"
            "  *) printf '%s\\n' \"$OMNI_GITHUB_TOKEN\" ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        askpass.chmod(0o700)
        env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": str(askpass),
            "OMNI_GITHUB_TOKEN": token,
        }
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


def upload_home_snapshot_bundle(target: GitHubTarget, *, token: str, bundle: Dict[str, Any], app_dir: Path) -> Dict[str, Any]:
    manifest = bundle["manifest"]
    root_prefix = str(bundle["root_prefix"])
    manifest_path = str(bundle["manifest_path"])
    manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    repo_url = f"https://github.com/{target.slug}.git"
    uploaded: List[str] = []

    with tempfile.TemporaryDirectory(prefix="omni-home-snapshot-upload-") as tmp:
        clone_root = Path(tmp) / "repo"
        clone_result = _run_git(["clone", "--depth", "1", repo_url, str(clone_root)], token=token)
        if clone_result.returncode != 0:
            raise RuntimeError(clone_result.stderr or clone_result.stdout or "Git clone failed")

        _run_git(["config", "user.name", "OmniSync"], token=token, cwd=clone_root)
        _run_git(["config", "user.email", "omni@local.invalid"], token=token, cwd=clone_root)

        manifest_local = clone_root / manifest_path
        manifest_local.parent.mkdir(parents=True, exist_ok=True)
        manifest_local.write_text(manifest_text, encoding="utf-8")

        snapshot_root = clone_root / root_prefix
        for entry in manifest.get("files", []):
            rel_path = str(entry.get("relative_path") or "").strip()
            if not rel_path:
                continue
            source = app_dir / rel_path
            if not source.exists():
                continue
            destination = snapshot_root / rel_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            uploaded.append(f"{root_prefix}/{rel_path}")

        add_result = _run_git(["add", "home-snapshots"], token=token, cwd=clone_root)
        if add_result.returncode != 0:
            raise RuntimeError(add_result.stderr or add_result.stdout or "Git add failed")

        status_result = _run_git(["status", "--porcelain"], token=token, cwd=clone_root)
        if status_result.returncode != 0:
            raise RuntimeError(status_result.stderr or status_result.stdout or "Git status failed")
        if not (status_result.stdout or "").strip():
            return {"manifest_path": manifest_path, "uploaded": uploaded, "snapshot_id": manifest["snapshot_id"]}

        commit_result = _run_git(
            ["commit", "-m", f"Add home snapshot {manifest['snapshot_id']}"],
            token=token,
            cwd=clone_root,
        )
        if commit_result.returncode != 0:
            raise RuntimeError(commit_result.stderr or commit_result.stdout or "Git commit failed")

        push_result = _run_git(["push", "origin", "HEAD:main"], token=token, cwd=clone_root)
        if push_result.returncode != 0:
            raise RuntimeError(push_result.stderr or push_result.stdout or "Git push failed")

    return {"manifest_path": manifest_path, "uploaded": uploaded, "snapshot_id": manifest["snapshot_id"]}


def latest_home_snapshot_manifest_entry(entries: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    manifests = [entry for entry in entries if str(entry.get("name") or "").endswith(".manifest.json")]
    if not manifests:
        return None
    return sorted(manifests, key=lambda item: str(item.get("name") or ""), reverse=True)[0]


def download_home_snapshot_bundle(target: GitHubTarget, *, token: str, output_dir: Path) -> Optional[Dict[str, Any]]:
    entries = list_directory(target, "home-snapshots", token=token)
    latest = latest_home_snapshot_manifest_entry(entries)
    if not latest:
        return None

    manifest_text = download_text(target, str(latest.get("path") or ""), token=token)
    if not manifest_text:
        return None

    manifest = json.loads(manifest_text)
    snapshot_root = output_dir.expanduser().resolve()
    snapshot_root.mkdir(parents=True, exist_ok=True)

    manifest_local = snapshot_root / "snapshot.manifest.json"
    manifest_local.write_text(manifest_text, encoding="utf-8")

    snapshot_id = str(manifest.get("snapshot_id") or "")
    repo_url = f"https://github.com/{target.slug}.git"
    with tempfile.TemporaryDirectory(prefix="omni-home-snapshot-download-") as tmp:
        clone_root = Path(tmp) / "repo"
        clone_result = _run_git(
            ["clone", "--depth", "1", "--filter=blob:none", "--sparse", repo_url, str(clone_root)],
            token=token,
        )
        if clone_result.returncode != 0:
            raise RuntimeError(clone_result.stderr or clone_result.stdout or "Git clone failed")
        sparse_result = _run_git(
            [
                "sparse-checkout",
                "set",
                f"home-snapshots/{snapshot_id}",
                f"home-snapshots/{snapshot_id}.manifest.json",
            ],
            token=token,
            cwd=clone_root,
        )
        if sparse_result.returncode != 0:
            raise RuntimeError(sparse_result.stderr or sparse_result.stdout or "Git sparse-checkout failed")

        source_root = clone_root / "home-snapshots" / snapshot_id
        for entry in manifest.get("files", []):
            rel_path = str(entry.get("relative_path") or "").strip()
            if not rel_path:
                continue
            source = source_root / rel_path
            if not source.exists():
                raise FileNotFoundError(f"Missing snapshot payload in repo clone: {source}")
            local_path = snapshot_root / rel_path
            local_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, local_path)
            if entry.get("executable"):
                local_path.chmod(0o755)

    return {
        "manifest": manifest,
        "root": snapshot_root,
        "manifest_path": manifest_local,
    }


def apply_downloaded_home_snapshot(snapshot_root: Path, *, target_root: Path) -> subprocess.CompletedProcess[str]:
    restore_script = snapshot_root / "scripts" / "restore_home_private_snapshot.sh"
    if not restore_script.exists():
        raise FileNotFoundError(f"Missing downloaded restore script: {restore_script}")
    restore_script.chmod(0o755)
    return subprocess.run(
        ["bash", str(restore_script), str(target_root)],
        cwd=str(snapshot_root),
        capture_output=True,
        text=True,
        check=False,
    )

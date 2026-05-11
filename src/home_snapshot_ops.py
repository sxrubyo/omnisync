#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from github_ops import (
    GitHubTarget,
    download_bytes,
    download_text,
    list_directory,
    put_bytes,
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

    for candidate in (
        app_dir / "scripts" / "restore_home_private_snapshot.sh",
        app_dir / "scripts" / "refresh_home_snapshot.sh",
        app_dir / "backups" / "home_private_snapshot.passphrase",
    ):
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


def upload_home_snapshot_bundle(target: GitHubTarget, *, token: str, bundle: Dict[str, Any], app_dir: Path) -> Dict[str, Any]:
    manifest = bundle["manifest"]
    root_prefix = str(bundle["root_prefix"])
    manifest_path = str(bundle["manifest_path"])
    manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    put_bytes(
        target,
        manifest_path,
        manifest_text.encode("utf-8"),
        token=token,
        message=f"Add home snapshot manifest {manifest['snapshot_id']}",
    )

    uploaded: List[str] = []
    for entry in manifest.get("files", []):
        rel_path = str(entry.get("relative_path") or "").strip()
        if not rel_path:
            continue
        source = app_dir / rel_path
        if not source.exists():
            continue
        remote_path = f"{root_prefix}/{rel_path}"
        put_bytes(
            target,
            remote_path,
            source.read_bytes(),
            token=token,
            message=f"Add home snapshot file {manifest['snapshot_id']}: {rel_path}",
        )
        uploaded.append(remote_path)
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
    remote_root = f"home-snapshots/{snapshot_id}"
    for entry in manifest.get("files", []):
        rel_path = str(entry.get("relative_path") or "").strip()
        if not rel_path:
            continue
        payload = download_bytes(target, f"{remote_root}/{rel_path}", token=token)
        local_path = snapshot_root / rel_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(payload)
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

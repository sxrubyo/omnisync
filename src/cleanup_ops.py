#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List

from host_inventory import path_size_bytes


DEFAULT_ARTIFACT_PATTERNS = [
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "build",
    "dist",
    "logs",
    "tmp",
    "output",
    "*.pyc",
    "*.pyo",
    "*.log",
]


def is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def matches_pattern(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def collect_repo_artifacts(root: Path, patterns: Iterable[str]) -> List[Path]:
    results: List[Path] = []
    if not root.exists():
        return results

    for current_root, dirs, files in __import__("os").walk(root):
        current = Path(current_root)
        kept_dirs: List[str] = []
        for directory in dirs:
            candidate = current / directory
            if matches_pattern(directory, patterns):
                results.append(candidate)
            else:
                kept_dirs.append(directory)
        dirs[:] = kept_dirs

        for file_name in files:
            if matches_pattern(file_name, patterns):
                results.append(current / file_name)

    unique: Dict[str, Path] = {}
    for item in results:
        unique[str(item)] = item
    return sorted(unique.values(), key=lambda item: str(item))


def _add_candidate(candidates: List[Dict[str, Any]], path: Path, reason: str) -> None:
    if not path.exists():
        return
    candidates.append(
        {
            "path": str(path),
            "reason": reason,
            "size_bytes": path_size_bytes(str(path)),
            "type": "file" if path.is_file() else "dir",
        }
    )


def build_purge_plan(
    manifest: Dict[str, Any],
    *,
    omni_home: Path,
    bundle_dir: Path,
    backup_dir: Path,
    state_dir: Path,
    log_dir: Path,
    include_secrets: bool = False,
    artifact_patterns: Iterable[str] | None = None,
) -> List[Dict[str, Any]]:
    patterns = list(artifact_patterns or DEFAULT_ARTIFACT_PATTERNS)
    candidates: List[Dict[str, Any]] = []

    for extra_path, reason in (
        (bundle_dir, "bundles"),
        (state_dir / "servers", "remote_snapshots"),
        (log_dir, "runtime_logs"),
        (backup_dir, "local_backups"),
    ):
        if extra_path.exists() and extra_path != omni_home:
            _add_candidate(candidates, extra_path, reason)

    for raw_path in manifest.get("state_paths", []):
        path = Path(str(raw_path)).expanduser()
        if not path.exists():
            continue
        if path == omni_home:
            for artifact in collect_repo_artifacts(path, patterns):
                _add_candidate(candidates, artifact, "repo_artifact")
            continue

        if path.is_dir() and is_git_repo(path):
            for artifact in collect_repo_artifacts(path, patterns):
                _add_candidate(candidates, artifact, "repo_artifact")
            continue

        _add_candidate(candidates, path, "managed_state")

    if include_secrets:
        for raw_path in manifest.get("secret_paths", []):
            path = Path(str(raw_path)).expanduser()
            if not path.exists():
                continue
            if path.is_dir() and is_git_repo(path):
                continue
            _add_candidate(candidates, path, "managed_secret")

    deduped: Dict[str, Dict[str, Any]] = {}
    for item in candidates:
        deduped[item["path"]] = item
    return sorted(deduped.values(), key=lambda item: item["path"])


def execute_purge(plan: List[Dict[str, Any]], *, dry_run: bool = True) -> Dict[str, Any]:
    removed: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    reclaimed = 0

    for item in plan:
        path = Path(item["path"])
        if not path.exists():
            skipped.append(item)
            continue
        if dry_run:
            skipped.append(item)
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=False)
        else:
            path.unlink(missing_ok=True)
        removed.append(item)
        reclaimed += int(item.get("size_bytes", 0))

    return {
        "removed": removed,
        "skipped": skipped,
        "reclaimed_bytes": reclaimed,
        "dry_run": dry_run,
    }

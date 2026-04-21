#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from host_inventory import expand_path, is_excluded, normalize_manifest


def _path_within(candidate: Path, parents: Sequence[Path]) -> bool:
    for parent in parents:
        try:
            if candidate == parent or candidate.is_relative_to(parent):
                return True
        except ValueError:
            continue
    return False


def _normalize_rel(path: Path, host_root: Path) -> str:
    try:
        return str(path.relative_to(host_root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _iter_tracked_files(manifest: Dict[str, Any], home_root: str = "/home/ubuntu") -> Iterable[Path]:
    normalized = normalize_manifest(manifest, home_root)
    host_root = Path(normalized.get("host_root") or expand_path(home_root, home_root)).resolve()
    exclude_patterns = [str(pattern) for pattern in normalized.get("exclude_patterns", [])]
    for raw_excluded in normalized.get("state_exclude_paths", []):
        excluded_path = Path(expand_path(str(raw_excluded), str(host_root))).resolve()
        exclude_patterns.append(excluded_path.name)
        exclude_patterns.append(str(raw_excluded))
    excluded_roots = [Path(expand_path(item, str(host_root))).resolve() for item in normalized.get("state_exclude_paths", [])]
    tracked_roots: List[Path] = []
    seen_roots: set[str] = set()

    for raw_path in list(normalized.get("state_paths", [])) + list(normalized.get("secret_paths", [])):
        candidate = Path(expand_path(str(raw_path), str(host_root))).resolve()
        if not candidate.exists():
            continue
        key = str(candidate)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        tracked_roots.append(candidate)

    seen_files: set[str] = set()

    for root in tracked_roots:
        if _path_within(root, excluded_roots):
            continue
        if root.is_file():
            rel_file = _normalize_rel(root, host_root)
            if is_excluded(rel_file, exclude_patterns):
                continue
            key = str(root)
            if key not in seen_files:
                seen_files.add(key)
                yield root
            continue

        for current_root, dirs, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current_root)
            filtered_dirs: List[str] = []
            for name in dirs:
                directory = current_path / name
                rel_dir = _normalize_rel(directory, host_root)
                if _path_within(directory, excluded_roots):
                    continue
                if is_excluded(rel_dir, exclude_patterns):
                    continue
                filtered_dirs.append(name)
            dirs[:] = filtered_dirs

            for name in files:
                file_path = current_path / name
                rel_file = _normalize_rel(file_path, host_root)
                if _path_within(file_path, excluded_roots):
                    continue
                if is_excluded(rel_file, exclude_patterns):
                    continue
                key = str(file_path)
                if key in seen_files:
                    continue
                seen_files.add(key)
                yield file_path


def capture_watch_snapshot(manifest: Dict[str, Any], home_root: str = "/home/ubuntu") -> Dict[str, Any]:
    normalized = normalize_manifest(manifest, home_root)
    host_root = Path(normalized.get("host_root") or expand_path(home_root, home_root)).resolve()
    entries: Dict[str, Dict[str, int]] = {}
    total_size = 0

    for file_path in _iter_tracked_files(normalized, str(host_root)):
        try:
            stat = file_path.stat()
        except OSError:
            continue
        rel_path = _normalize_rel(file_path, host_root)
        entry = {
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }
        entries[rel_path] = entry
        total_size += entry["size"]

    digest = hashlib.sha1()
    for rel_path in sorted(entries):
        entry = entries[rel_path]
        digest.update(rel_path.encode("utf-8", errors="ignore"))
        digest.update(b"|")
        digest.update(str(entry["size"]).encode("ascii"))
        digest.update(b"|")
        digest.update(str(entry["mtime_ns"]).encode("ascii"))
        digest.update(b"\n")

    return {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z"),
        "host_root": str(host_root),
        "profile": normalized.get("profile", "unknown"),
        "file_count": len(entries),
        "total_size_bytes": total_size,
        "fingerprint": digest.hexdigest(),
        "entries": entries,
    }


def summarize_snapshot_diff(
    previous: Dict[str, Any] | None,
    current: Dict[str, Any],
    *,
    sample_limit: int = 12,
) -> Dict[str, Any]:
    previous_entries = dict((previous or {}).get("entries") or {})
    current_entries = dict(current.get("entries") or {})

    previous_keys = set(previous_entries)
    current_keys = set(current_entries)
    added = sorted(current_keys - previous_keys)
    removed = sorted(previous_keys - current_keys)
    modified = sorted(
        path
        for path in (previous_keys & current_keys)
        if previous_entries.get(path) != current_entries.get(path)
    )
    changed_paths = added + modified + removed

    return {
        "changed": bool(changed_paths),
        "changed_files": len(changed_paths),
        "added": len(added),
        "modified": len(modified),
        "removed": len(removed),
        "samples": changed_paths[:sample_limit],
        "previous_fingerprint": (previous or {}).get("fingerprint"),
        "current_fingerprint": current.get("fingerprint"),
    }


def load_watch_snapshot(snapshot_path: Path) -> Dict[str, Any] | None:
    if not snapshot_path.exists():
        return None
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def save_watch_snapshot(snapshot_path: Path, snapshot: Dict[str, Any]) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

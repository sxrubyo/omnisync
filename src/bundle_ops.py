#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import hashlib
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from host_inventory import build_state_exclude_patterns, expand_path, is_excluded


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _metadata_blob(kind: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "kind": kind,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "host_root": manifest.get("host_root"),
        "profile": manifest.get("profile"),
        "version": manifest.get("version", 1),
    }


def latest_bundle(bundle_dir: Path, prefix: str) -> Optional[Path]:
    candidates = sorted(bundle_dir.glob(f"{prefix}_*"), key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def default_bundle_path(output_dir: Path, prefix: str, encrypted: bool = False) -> Path:
    suffix = ".tar.gz.enc" if encrypted else ".tar.gz"
    return output_dir / f"{prefix}_{_timestamp()}{suffix}"


def _iter_files(base_path: Path, exclude_patterns: Iterable[str]) -> Iterable[tuple[Path, str]]:
    if base_path.is_file():
        rel = str(base_path).lstrip("/")
        if base_path.is_symlink():
            try:
                if os.path.isabs(os.readlink(base_path)):
                    return
            except OSError:
                return
        if not is_excluded(rel, exclude_patterns):
            yield base_path, rel
        return

    for root, dirs, files in os.walk(base_path):
        root_path = Path(root)
        rel_root = str(root_path).lstrip("/")
        filtered_dirs = []
        for name in dirs:
            rel_dir = f"{rel_root}/{name}".strip("/")
            candidate = root_path / name
            if candidate.is_symlink():
                try:
                    if os.path.isabs(os.readlink(candidate)):
                        continue
                except OSError:
                    continue
            if not is_excluded(rel_dir, exclude_patterns):
                filtered_dirs.append(name)
        dirs[:] = filtered_dirs
        for file_name in files:
            file_path = root_path / file_name
            rel_path = str(file_path).lstrip("/")
            if file_path.is_symlink():
                try:
                    if os.path.isabs(os.readlink(file_path)):
                        continue
                except OSError:
                    continue
            if is_excluded(rel_path, exclude_patterns):
                continue
            yield file_path, rel_path


def _is_within_any(path: Path, roots: Iterable[Path]) -> bool:
    try:
        resolved_path = path.resolve()
    except Exception:
        return False

    for root in roots:
        try:
            resolved_root = root.resolve()
        except Exception:
            continue
        if resolved_path == resolved_root:
            return True
        if resolved_root in resolved_path.parents:
            return True
    return False


def create_bundle(
    *,
    bundle_path: Path,
    manifest: Dict[str, Any],
    paths: List[str],
    exclude_patterns: Iterable[str],
    kind: str,
    excluded_paths: Iterable[str] | None = None,
) -> Path:
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = _metadata_blob(kind, manifest)
    host_root = Path(str(manifest.get("host_root") or Path.home())).resolve()
    host_parts = [part for part in host_root.parts if part not in (host_root.root, "")]
    host_prefix = Path(*host_parts[-2:]) if host_parts else Path()

    with tarfile.open(bundle_path, "w:gz") as archive:
        manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        manifest_info = tarfile.TarInfo(name="_omni/manifest.json")
        manifest_info.size = len(manifest_bytes)
        archive.addfile(manifest_info, io.BytesIO(manifest_bytes))

        metadata_bytes = json.dumps(metadata, indent=2, ensure_ascii=False).encode("utf-8")
        metadata_info = tarfile.TarInfo(name="_omni/metadata.json")
        metadata_info.size = len(metadata_bytes)
        archive.addfile(metadata_info, io.BytesIO(metadata_bytes))

        excluded_roots = [Path(path).expanduser() for path in (excluded_paths or [])]
        for raw_path in paths:
            path_obj = Path(raw_path)
            if not path_obj.exists():
                continue
            for file_path, rel_path in _iter_files(path_obj, exclude_patterns):
                if excluded_roots and _is_within_any(file_path, excluded_roots):
                    continue
                try:
                    relative_to_host = file_path.resolve().relative_to(host_root)
                    arcname = str((host_prefix / relative_to_host).as_posix())
                except ValueError:
                    arcname = rel_path.replace("\\", "/")
                archive.add(str(file_path), arcname=arcname, recursive=False)

    return bundle_path


def create_state_bundle(bundle_dir: Path, manifest: Dict[str, Any], bundle_path: Optional[Path] = None) -> Path:
    path = bundle_path or default_bundle_path(bundle_dir, "state_bundle", encrypted=False)
    excluded_paths = list(manifest.get("secret_paths", [])) + list(manifest.get("state_exclude_paths", []))
    excluded_paths.append(str(path))
    excluded_paths.append(str(path.parent))
    return create_bundle(
        bundle_path=path,
        manifest=manifest,
        paths=list(manifest.get("state_paths", [])),
        exclude_patterns=build_state_exclude_patterns(manifest),
        kind="state",
        excluded_paths=excluded_paths,
    )


def _openssl_encrypt(source_path: Path, target_path: Path, passphrase: str) -> Path:
    result = subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-256-cbc",
            "-pbkdf2",
            "-salt",
            "-in",
            str(source_path),
            "-out",
            str(target_path),
            "-pass",
            f"pass:{passphrase}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "openssl encryption failed")
    return target_path


def _openssl_decrypt(source_path: Path, target_path: Path, passphrase: str) -> Path:
    result = subprocess.run(
        [
            "openssl",
            "enc",
            "-d",
            "-aes-256-cbc",
            "-pbkdf2",
            "-in",
            str(source_path),
            "-out",
            str(target_path),
            "-pass",
            f"pass:{passphrase}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "openssl decryption failed")
    return target_path


def create_secrets_bundle(
    bundle_dir: Path,
    manifest: Dict[str, Any],
    *,
    bundle_path: Optional[Path] = None,
    passphrase: str = "",
) -> Path:
    encrypted = bool(passphrase)
    output_path = bundle_path or default_bundle_path(bundle_dir, "secrets_bundle", encrypted=encrypted)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="omni-secrets-") as tmp_dir:
        temp_plain = Path(tmp_dir) / "secrets.tar.gz"
        create_bundle(
            bundle_path=temp_plain,
            manifest=manifest,
            paths=list(manifest.get("secret_paths", [])),
            exclude_patterns=[],
            kind="secrets",
        )
        if passphrase:
            return _openssl_encrypt(temp_plain, output_path, passphrase)
        shutil.copy2(temp_plain, output_path)
        return output_path


def _safe_extract_member_path(target_root: Path, member_name: str) -> Path:
    relative = Path(member_name)
    destination = (target_root / relative).resolve()
    if target_root.resolve() not in destination.parents and destination != target_root.resolve():
        raise RuntimeError(f"Unsafe archive member path: {member_name}")
    return destination


def restore_bundle(
    bundle_path: Path,
    *,
    target_root: str = "/",
    passphrase: str = "",
) -> List[str]:
    restored: List[str] = []
    source_path = Path(bundle_path)
    if not source_path.exists():
        raise FileNotFoundError(str(source_path))

    temp_plain: Optional[tempfile.TemporaryDirectory[str]] = None
    archive_path = source_path
    if source_path.suffix == ".enc":
        if not passphrase:
            raise RuntimeError("Encrypted bundle requires a passphrase")
        temp_plain = tempfile.TemporaryDirectory(prefix="omni-restore-")
        archive_path = Path(temp_plain.name) / "restored.tar.gz"
        _openssl_decrypt(source_path, archive_path, passphrase)

    root = Path(target_root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                if member.name.startswith("_omni/"):
                    continue
                destination = _safe_extract_member_path(root, member.name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    archive.extract(member, path=root, filter="data")
                except TypeError:
                    archive.extract(member, path=root)
                except tarfile.AbsoluteLinkError:
                    continue
                restored.append(str(destination))
    finally:
        if temp_plain is not None:
            temp_plain.cleanup()

    return restored


def latest_or_explicit(bundle_dir: Path, explicit_path: str, prefix: str) -> Optional[Path]:
    if explicit_path:
        return Path(explicit_path).expanduser()
    return latest_bundle(bundle_dir, prefix)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundle_metadata(bundle_path: Path, *, include_hash: bool = False, inspect_archive: bool = False) -> Dict[str, Any]:
    path = Path(bundle_path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    metadata: Dict[str, Any] = {
        "path": str(path),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path) if include_hash else None,
        "encrypted": path.suffix == ".enc",
        "archive_kind": "state" if path.name.startswith("state_bundle_") else "secrets" if path.name.startswith("secrets_bundle_") else "unknown",
        "manifest_profile": None,
        "created_at": None,
    }

    if not inspect_archive:
        return metadata

    inspect_path = path
    temp_plain: Optional[tempfile.TemporaryDirectory[str]] = None
    try:
        if path.suffix == ".enc":
            metadata["archive_kind"] = "secrets"
            return metadata

        with tarfile.open(inspect_path, "r:gz") as archive:
            try:
                meta_member = archive.extractfile("_omni/metadata.json")
                if meta_member is not None:
                    meta_payload = json.loads(meta_member.read().decode("utf-8"))
                    metadata["archive_kind"] = meta_payload.get("kind", "unknown")
                    metadata["created_at"] = meta_payload.get("created_at")
            except KeyError:
                pass
            try:
                manifest_member = archive.extractfile("_omni/manifest.json")
                if manifest_member is not None:
                    manifest_payload = json.loads(manifest_member.read().decode("utf-8"))
                    metadata["manifest_profile"] = manifest_payload.get("profile")
            except KeyError:
                pass
    finally:
        if temp_plain is not None:
            temp_plain.cleanup()

    return metadata

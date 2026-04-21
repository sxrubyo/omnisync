#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from bundle_ops import bundle_metadata, latest_or_explicit
from ip_rewrite_ops import detect_host_identity


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def summarize_bundle_pair(
    *,
    bundle_dir: Path,
    state_bundle: str = "",
    secrets_bundle: str = "",
    include_hash: bool = False,
    inspect_archive: bool = False,
) -> Dict[str, Any]:
    state_path = latest_or_explicit(bundle_dir, state_bundle, "state_bundle")
    secrets_path = latest_or_explicit(bundle_dir, secrets_bundle, "secrets_bundle")

    summary: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "bundle_dir": str(bundle_dir),
        "state_bundle": bundle_metadata(state_path, include_hash=include_hash, inspect_archive=inspect_archive) if state_path else None,
        "secrets_bundle": bundle_metadata(secrets_path, include_hash=include_hash, inspect_archive=inspect_archive) if secrets_path else None,
        "ok": bool(state_path and state_path.exists() and secrets_path and secrets_path.exists()),
    }
    return summary


def write_capture_summary(
    *,
    bundle_dir: Path,
    manifest_path: Path,
    state_bundle: Path,
    secrets_bundle: Path,
    output_path: Optional[Path] = None,
) -> Path:
    target = output_path or (bundle_dir / f"capture_summary_{_timestamp()}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    identity = detect_host_identity()

    payload = summarize_bundle_pair(
        bundle_dir=bundle_dir,
        state_bundle=str(state_bundle),
        secrets_bundle=str(secrets_bundle),
        include_hash=True,
        inspect_archive=True,
    )
    payload["manifest_path"] = str(manifest_path)
    payload["source_identity"] = {
        "public_ip": identity.public_ip,
        "private_ip": identity.private_ip,
        "hostname": identity.hostname,
        "fqdn": identity.fqdn,
        "ip_candidates": identity.ip_candidates,
        "source": identity.source,
    }

    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def latest_capture_summary(bundle_dir: Path) -> Optional[Path]:
    candidates = sorted(bundle_dir.glob("capture_summary_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def load_capture_summary(bundle_dir: Path, explicit_path: str = "") -> Optional[Dict[str, Any]]:
    target = Path(explicit_path).expanduser() if explicit_path else latest_capture_summary(bundle_dir)
    if target is None or not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def build_host_rewrite_context(
    bundle_dir: Path,
    *,
    explicit_summary: str = "",
    target_public_ip: str = "",
    target_private_ip: str = "",
    target_hostname: str = "",
) -> Dict[str, Any]:
    summary = load_capture_summary(bundle_dir, explicit_summary)
    identity = detect_host_identity()
    source_identity = (summary or {}).get("source_identity") or {}

    source_public = str(source_identity.get("public_ip") or "").strip()
    source_private = str(source_identity.get("private_ip") or "").strip()
    source_hostname = str(source_identity.get("hostname") or "").strip()
    source_fqdn = str(source_identity.get("fqdn") or "").strip()

    new_public = target_public_ip or identity.public_ip or ""
    new_private = target_private_ip or identity.private_ip or ""
    new_hostname = target_hostname or identity.hostname or ""
    new_fqdn = target_hostname or identity.fqdn or ""

    replacements: Dict[str, str] = {}
    if source_public and new_public and source_public != new_public:
        replacements[source_public] = new_public
    if source_private and new_private and source_private != new_private:
        replacements[source_private] = new_private
    if source_hostname and new_hostname and source_hostname != new_hostname:
        replacements[source_hostname] = new_hostname
    if source_fqdn and new_fqdn and source_fqdn != new_fqdn:
        replacements[source_fqdn] = new_fqdn

    return {
        "summary": summary,
        "summary_found": bool(summary),
        "source_identity": {
            "public_ip": source_public or None,
            "private_ip": source_private or None,
            "hostname": source_hostname or None,
            "fqdn": source_fqdn or None,
        },
        "target_identity": {
            "public_ip": new_public or None,
            "private_ip": new_private or None,
            "hostname": new_hostname or None,
            "fqdn": new_fqdn or None,
        },
        "replacements": replacements,
    }

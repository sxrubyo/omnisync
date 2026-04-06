#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _run(args: List[str], *, timeout: int = 90) -> str:
    if not args or not shutil.which(args[0]):
        return ""
    result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _parse_python_packages(raw: str) -> List[str]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    packages: List[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        version = str(item.get("version") or "").strip()
        if not name:
            continue
        packages.append(f"{name}=={version}" if version else name)
    return sorted(dict.fromkeys(packages))


def _parse_npm_globals(raw: str) -> List[str]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    deps = payload.get("dependencies") or {}
    return sorted(str(name) for name in deps.keys() if str(name).strip())


def _parse_pm2_processes(raw: str) -> List[Dict[str, Any]]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    rows: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "name": item.get("name"),
                "status": (item.get("pm2_env") or {}).get("status"),
            }
        )
    return rows


def capture_installed_inventory(*, timeout: int = 90) -> Dict[str, Any]:
    apt_raw = _run(["dpkg-query", "-W", "-f=${binary:Package}\n"], timeout=timeout)
    pip_raw = _run(["python3", "-m", "pip", "list", "--format=json"], timeout=timeout)
    npm_raw = _run(["npm", "list", "-g", "--depth=0", "--json"], timeout=timeout)
    pm2_raw = _run(["pm2", "jlist"], timeout=timeout)

    apt_packages = sorted(line.strip() for line in apt_raw.splitlines() if line.strip())
    python_packages = _parse_python_packages(pip_raw)
    npm_global_packages = _parse_npm_globals(npm_raw)
    pm2_processes = _parse_pm2_processes(pm2_raw)

    return {
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "apt_packages": apt_packages,
        "python_packages": python_packages,
        "npm_global_packages": npm_global_packages,
        "pm2_processes": pm2_processes,
        "counts": {
            "apt_packages": len(apt_packages),
            "python_packages": len(python_packages),
            "npm_global_packages": len(npm_global_packages),
            "pm2_processes": len(pm2_processes),
        },
    }


def write_installed_inventory(output_dir: Path, payload: Dict[str, Any], output_path: Optional[Path] = None) -> Path:
    target = output_path or (output_dir / f"installed_inventory_{_timestamp()}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    enriched = dict(payload)
    enriched["path"] = str(target)
    target.write_text(json.dumps(enriched, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def latest_installed_inventory(output_dir: Path) -> Optional[Path]:
    candidates = sorted(output_dir.glob("installed_inventory_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def load_installed_inventory(output_dir: Path, explicit_path: str = "") -> Optional[Dict[str, Any]]:
    target = Path(explicit_path).expanduser() if explicit_path else latest_installed_inventory(output_dir)
    if target is None or not target.exists():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["path"] = str(target)
    return payload


def _unique(values: List[str]) -> List[str]:
    return list(dict.fromkeys([value for value in values if value]))


def merge_manifest_runtime_inventory(manifest: Dict[str, Any], runtime_inventory: Dict[str, Any] | None = None) -> Dict[str, Any]:
    merged = dict(manifest or {})
    runtime = dict(runtime_inventory or {})
    merged["apt_packages"] = _unique(list(merged.get("apt_packages", [])) + list(runtime.get("apt_packages", [])))
    merged["python_packages"] = _unique(list(merged.get("python_packages", [])) + list(runtime.get("python_packages", [])))
    merged["npm_global_packages"] = _unique(list(merged.get("npm_global_packages", [])) + list(runtime.get("npm_global_packages", [])))
    return merged


def summarize_installed_inventory(runtime_inventory: Dict[str, Any] | None = None) -> List[str]:
    payload = dict(runtime_inventory or {})
    counts = payload.get("counts") or {}
    apt_packages = payload.get("apt_packages") or []
    python_packages = payload.get("python_packages") or []
    npm_global_packages = payload.get("npm_global_packages") or []
    pm2_processes = payload.get("pm2_processes") or []
    return [
        f"APT: {counts.get('apt_packages', len(apt_packages))}",
        f"Python: {counts.get('python_packages', len(python_packages))}",
        f"npm global: {counts.get('npm_global_packages', len(npm_global_packages))}",
        f"PM2: {counts.get('pm2_processes', len(pm2_processes))}",
    ]

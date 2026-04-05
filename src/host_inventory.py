#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


DEFAULT_EXCLUDE_PATTERNS = [
    ".git",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "node_modules",
    ".cache",
    ".pytest_cache",
    ".venv",
    "venv",
    "*.log",
    "logs",
    "tmp",
    "output",
    "build",
    "dist",
    "backups-test",
    "data-test",
    "logs-test",
]

DEFAULT_STATE_PATHS = [
    "~/melissa",
    "~/melissa-instances",
    "~/whatsapp-bridge",
    "~/nova-os",
    "~/omni-core",
    "~/Workflows-n8n",
    "~/xus-https",
    "~/.n8n",
    "~/.nova",
    "~/.pm2/dump.pm2",
]

DEFAULT_SECRET_PATHS = [
    "~/.ssh",
    "~/.n8n/config",
    "~/.nova",
    "~/melissa/.env",
    "~/melissa-instances/clinica-de-las-americas/.env",
    "~/whatsapp-bridge/.env",
    "~/omni-core/.env",
]

DEFAULT_INSTALL_TARGETS = [
    "~/melissa",
    "~/melissa-instances/clinica-de-las-americas",
    "~/whatsapp-bridge",
    "~/nova-os/backend",
    "~/nova-os/frontend",
    "~/nova-os/n8n-nodes-nova",
    "~/omni-core",
]

DEFAULT_PM2_ECOSYSTEMS = [
    "~/omni-core/ecosystem.config.js",
    "~/whatsapp-bridge/ecosystem.config.cjs",
]

DEFAULT_COMPOSE_PROJECTS = [
    "~/omni-core",
    "~/nova-os",
    "~/xus-https",
]

DEFAULT_APT_PACKAGES = [
    "git",
    "rsync",
    "curl",
    "ca-certificates",
    "docker.io",
    "docker-compose-plugin",
    "python3",
    "python3-pip",
    "python3-venv",
    "nodejs",
    "npm",
    "sqlite3",
    "jq",
]

DEFAULT_NPM_GLOBAL_PACKAGES = [
    "pm2",
]

CACHE_HINTS = {
    ".cache",
    ".npm",
    ".npm-global",
    ".codex",
    ".claude",
    "node_modules",
    "tmp",
    "output",
    "melissa-backups",
}

PRODUCT_HINTS = {
    "melissa",
    "melissa-instances",
    "whatsapp-bridge",
    "nova-os",
    "omni-core",
    "Workflows-n8n",
    "xus-https",
    ".n8n",
    ".nova",
    ".pm2",
}


def expand_path(raw_path: str, home_root: str = "/home/ubuntu") -> str:
    if not raw_path:
        return raw_path
    home = Path(home_root).expanduser().resolve()
    text = raw_path.replace("$HOME", str(home)).replace("${HOME}", str(home))
    if text.startswith("~/"):
        text = str(home / text[2:])
    return str(Path(os.path.expandvars(text)).expanduser())


def normalize_manifest(manifest: Dict[str, Any], home_root: str) -> Dict[str, Any]:
    normalized = dict(manifest or {})
    normalized["host_root"] = expand_path(normalized.get("host_root", home_root), home_root)
    for key in (
        "state_paths",
        "secret_paths",
        "install_targets",
        "pm2_ecosystems",
        "compose_projects",
    ):
        normalized[key] = [expand_path(item, home_root) for item in normalized.get(key, [])]
    normalized["exclude_patterns"] = list(normalized.get("exclude_patterns", []))
    normalized["apt_packages"] = list(normalized.get("apt_packages", []))
    normalized["npm_global_packages"] = list(normalized.get("npm_global_packages", []))
    return normalized


def build_default_manifest(home_root: str = "/home/ubuntu") -> Dict[str, Any]:
    manifest = {
        "version": 1,
        "profile": "production-clean",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "host_root": expand_path(home_root, home_root),
        "state_paths": [expand_path(path, home_root) for path in DEFAULT_STATE_PATHS],
        "secret_paths": [expand_path(path, home_root) for path in DEFAULT_SECRET_PATHS],
        "install_targets": [expand_path(path, home_root) for path in DEFAULT_INSTALL_TARGETS],
        "pm2_ecosystems": [expand_path(path, home_root) for path in DEFAULT_PM2_ECOSYSTEMS],
        "compose_projects": [expand_path(path, home_root) for path in DEFAULT_COMPOSE_PROJECTS],
        "exclude_patterns": list(DEFAULT_EXCLUDE_PATTERNS),
        "apt_packages": list(DEFAULT_APT_PACKAGES),
        "npm_global_packages": list(DEFAULT_NPM_GLOBAL_PACKAGES),
    }
    return manifest


def load_manifest(manifest_path: Path, home_root: str = "/home/ubuntu") -> Dict[str, Any]:
    if not manifest_path.exists():
        return build_default_manifest(home_root)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return normalize_manifest(data, home_root)


def save_manifest(manifest_path: Path, manifest: Dict[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_manifest(manifest_path: Path, home_root: str = "/home/ubuntu") -> Dict[str, Any]:
    if manifest_path.exists():
        return load_manifest(manifest_path, home_root)
    manifest = build_default_manifest(home_root)
    save_manifest(manifest_path, manifest)
    return manifest


def path_size_bytes(path: str) -> int:
    path_obj = Path(path)
    if not path_obj.exists():
        return 0
    try:
        result = subprocess.run(
            ["du", "-sb", str(path_obj)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.split()[0])
    except Exception:
        pass
    if path_obj.is_file():
        return path_obj.stat().st_size
    total = 0
    for file_path in path_obj.rglob("*"):
        try:
            if file_path.is_file():
                total += file_path.stat().st_size
        except OSError:
            continue
    return total


def human_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    unit = 0
    while value >= 1024 and unit < len(units) - 1:
        value /= 1024
        unit += 1
    if unit == 0:
        return f"{int(value)}{units[unit]}"
    return f"{value:.1f}{units[unit]}"


def is_excluded(rel_path: str, patterns: Iterable[str]) -> bool:
    rel_posix = rel_path.replace("\\", "/").strip("/")
    parts = [part for part in rel_posix.split("/") if part]
    for pattern in patterns:
        normalized = pattern.strip().replace("\\", "/")
        if not normalized:
            continue
        if fnmatch.fnmatch(rel_posix, normalized):
            return True
        if any(fnmatch.fnmatch(part, normalized) for part in parts):
            return True
    return False


def classify_path(path: Path, manifest: Dict[str, Any]) -> str:
    path_str = str(path)
    if path_str in set(manifest.get("state_paths", [])):
        return "state"
    if path_str in set(manifest.get("secret_paths", [])):
        return "secret"
    if path.name in CACHE_HINTS:
        return "noise"
    if path.name in PRODUCT_HINTS:
        return "product"
    return "uncategorized"


def scan_home(home_root: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    home = Path(expand_path(home_root, home_root))
    normalized = normalize_manifest(manifest, home_root)
    included = []
    for key in ("state_paths", "secret_paths"):
        for item in normalized.get(key, []):
            path_obj = Path(item)
            included.append(
                {
                    "path": str(path_obj),
                    "kind": "secret" if key == "secret_paths" else "state",
                    "exists": path_obj.exists(),
                    "size_bytes": path_size_bytes(str(path_obj)) if path_obj.exists() else 0,
                }
            )

    discovered = []
    if home.exists():
        for entry in sorted(home.iterdir(), key=lambda item: item.name.lower()):
            if entry.name in (".", ".."):
                continue
            rel_name = entry.name
            discovered.append(
                {
                    "path": str(entry),
                    "name": rel_name,
                    "classification": classify_path(entry, normalized),
                    "size_bytes": path_size_bytes(str(entry)),
                }
            )

    return {
        "host_root": str(home),
        "manifest_profile": normalized.get("profile", "unknown"),
        "included": included,
        "discovered": discovered,
    }

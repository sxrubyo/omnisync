#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set


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

DEFAULT_PROFILE = "production-clean"
FULL_HOME_PROFILE = "full-home"

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

COMMON_SECRET_DIRS = {
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
    ".pki",
}

COMMON_SECRET_FILES = {
    ".env",
    ".git-credentials",
    ".npmrc",
    ".netrc",
    ".pypirc",
    ".appium.env",
}

COMMON_SECRET_GLOBS = [
    ".env.*",
    "*.pem",
    "*.key",
    "*.crt",
    "*.p12",
    "*.pfx",
    "*.ovpn",
    "*.kubeconfig",
]

IGNORED_SECRET_FILE_GLOBS = [
    ".env.example",
    ".env.*.example",
    "*.example",
    "*.sample",
    "*.template",
    "*.dist",
]

WELL_KNOWN_SECRET_RELATIVE_PATHS = [
    ".ssh",
    ".aws",
    ".gnupg",
    ".kube",
    ".pki",
    ".docker/config.json",
    ".config/gh",
    ".config/gcloud",
    ".config/opencode",
    ".n8n/config",
    ".git-credentials",
    ".npmrc",
    ".netrc",
    ".pypirc",
]


def looks_like_secret_file(path: Path, rel_file: str = "") -> bool:
    name = path.name
    lower_name = name.lower()
    rel_parts = [part for part in rel_file.replace("\\", "/").split("/") if part]
    depth = len(rel_parts)

    if any(fnmatch.fnmatch(lower_name, pattern) for pattern in IGNORED_SECRET_FILE_GLOBS):
        return False
    if name in COMMON_SECRET_FILES:
        return depth <= 3
    if name.startswith(".env"):
        return True
    if any(fnmatch.fnmatch(name, pattern) for pattern in COMMON_SECRET_GLOBS):
        return depth <= 4
    return False


def discover_full_home_secret_paths(
    home_root: str = "/home/ubuntu",
    exclude_patterns: Iterable[str] | None = None,
) -> List[str]:
    home = Path(expand_path(home_root, home_root)).resolve()
    patterns = list(exclude_patterns or DEFAULT_EXCLUDE_PATTERNS)
    found: Set[str] = set()

    for relative in WELL_KNOWN_SECRET_RELATIVE_PATHS:
        candidate = home / relative
        if candidate.exists():
            found.add(str(candidate))

    if not home.exists():
        return sorted(found)

    for root, dirs, files in os.walk(home):
        root_path = Path(root)
        rel_root = str(root_path.relative_to(home)) if root_path != home else ""

        filtered_dirs = []
        for name in dirs:
            rel_dir = "/".join(part for part in (rel_root, name) if part).strip("/")
            if is_excluded(rel_dir, patterns):
                continue
            candidate = root_path / name
            if name in COMMON_SECRET_DIRS and root_path == home:
                found.add(str(candidate))
                continue
            filtered_dirs.append(name)
        dirs[:] = filtered_dirs

        for name in files:
            rel_file = "/".join(part for part in (rel_root, name) if part).strip("/")
            if is_excluded(rel_file, patterns):
                continue
            candidate = root_path / name
            if looks_like_secret_file(candidate, rel_file):
                found.add(str(candidate))

    return sorted(found)


def profile_presets(home_root: str = "/home/ubuntu") -> Dict[str, Dict[str, Any]]:
    home = expand_path(home_root, home_root)
    production_clean = build_default_manifest(home_root, profile=DEFAULT_PROFILE, include_profile_defaults=False)
    full_home_secret_paths = discover_full_home_secret_paths(home_root, DEFAULT_EXCLUDE_PATTERNS)
    full_home = {
        "version": 1,
        "profile": FULL_HOME_PROFILE,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "host_root": home,
        "state_paths": [home],
        "secret_paths": full_home_secret_paths,
        "state_exclude_paths": [
            expand_path("~/omni-core/backups/host-bundles", home_root),
            expand_path("~/omni-core/backups/auto-bundles", home_root),
        ],
        "install_targets": list(DEFAULT_INSTALL_TARGETS),
        "pm2_ecosystems": list(DEFAULT_PM2_ECOSYSTEMS),
        "compose_projects": list(DEFAULT_COMPOSE_PROJECTS),
        "exclude_patterns": list(DEFAULT_EXCLUDE_PATTERNS),
        "apt_packages": list(DEFAULT_APT_PACKAGES),
        "npm_global_packages": list(DEFAULT_NPM_GLOBAL_PACKAGES),
    }
    return {
        DEFAULT_PROFILE: production_clean,
        FULL_HOME_PROFILE: full_home,
    }


def build_profile_manifest(profile: str = DEFAULT_PROFILE, home_root: str = "/home/ubuntu") -> Dict[str, Any]:
    presets = profile_presets(home_root)
    normalized_profile = str(profile or DEFAULT_PROFILE).strip().lower().replace("_", "-")
    selected = presets.get(normalized_profile, presets[DEFAULT_PROFILE])
    return deepcopy(selected)


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
    profile = str(normalized.get("profile") or DEFAULT_PROFILE).strip() or DEFAULT_PROFILE
    defaults = build_profile_manifest(profile, home_root)
    normalized["profile"] = defaults.get("profile", profile)
    normalized["host_root"] = expand_path(normalized.get("host_root", defaults.get("host_root", home_root)), home_root)
    for key in (
        "state_paths",
        "secret_paths",
        "state_exclude_paths",
        "install_targets",
        "pm2_ecosystems",
        "compose_projects",
    ):
        if key in normalized:
            values = normalized.get(key) or []
        else:
            values = defaults.get(key, [])
        normalized[key] = [expand_path(item, home_root) for item in values]
    normalized["exclude_patterns"] = list(normalized.get("exclude_patterns", []))
    normalized["apt_packages"] = list(normalized.get("apt_packages", []))
    normalized["npm_global_packages"] = list(normalized.get("npm_global_packages", []))
    return normalized


def build_default_manifest(
    home_root: str = "/home/ubuntu",
    profile: str = DEFAULT_PROFILE,
    *,
    include_profile_defaults: bool = True,
) -> Dict[str, Any]:
    if include_profile_defaults:
        return build_profile_manifest(profile, home_root)
    manifest = {
        "version": 1,
        "profile": profile,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "host_root": expand_path(home_root, home_root),
        "state_paths": [expand_path(path, home_root) for path in DEFAULT_STATE_PATHS],
        "secret_paths": [expand_path(path, home_root) for path in DEFAULT_SECRET_PATHS],
        "state_exclude_paths": [],
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


def ensure_manifest(
    manifest_path: Path,
    home_root: str = "/home/ubuntu",
    profile: str = DEFAULT_PROFILE,
    force_profile: bool = False,
) -> Dict[str, Any]:
    if manifest_path.exists() and not force_profile:
        loaded = load_manifest(manifest_path, home_root)
        if profile and loaded.get("profile") != profile:
            manifest = build_default_manifest(home_root, profile=profile)
            save_manifest(manifest_path, manifest)
            return manifest
        return loaded
    manifest = build_default_manifest(home_root, profile=profile)
    save_manifest(manifest_path, manifest)
    return manifest


def build_state_exclude_patterns(manifest: Dict[str, Any], home_root: str = "/home/ubuntu") -> List[str]:
    patterns: List[str] = []
    seen: set[str] = set()
    resolved_home = expand_path(str(manifest.get("host_root") or home_root), home_root)

    def add(pattern: str) -> None:
        normalized = str(pattern).strip().replace("\\", "/")
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        patterns.append(normalized)

    for pattern in manifest.get("exclude_patterns", []):
        add(pattern)

    for pattern in manifest.get("state_exclude_paths", []):
        add(Path(expand_path(str(pattern), resolved_home)).name)
        add(str(pattern))

    for raw_secret in manifest.get("secret_paths", []):
        secret_path = Path(expand_path(str(raw_secret), resolved_home))
        add(secret_path.name)
        if secret_path.name.startswith(".env"):
            add(".env")
            add(".env*")

    return patterns


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
    state_paths = [Path(item) for item in manifest.get("state_paths", [])]
    secret_paths = [Path(item) for item in manifest.get("secret_paths", [])]
    if any(path == candidate or path.is_relative_to(candidate) for candidate in secret_paths):
        return "secret"
    if any(path == candidate for candidate in state_paths):
        return "state"
    if path.name in CACHE_HINTS:
        return "noise"
    if path.name in PRODUCT_HINTS:
        return "product"
    if any(path.is_relative_to(candidate) for candidate in state_paths):
        return "state"
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

#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from platform_ops import PlatformInfo, detect_platform_info


DOTFILES = [
    ".bashrc",
    ".zshrc",
    ".profile",
    ".bash_profile",
    ".gitconfig",
]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run(args: List[str], *, timeout: int = 120) -> str:
    if not args or not shutil.which(args[0]):
        return ""
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _parse_json_list(raw: str) -> List[Dict[str, Any]]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _parse_python_packages(raw: str) -> List[str]:
    packages: List[str] = []
    for item in _parse_json_list(raw):
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
    dependencies = payload.get("dependencies") or {}
    return sorted(str(name) for name in dependencies.keys() if str(name).strip())


def _parse_cargo_packages(raw: str) -> List[str]:
    packages: List[str] = []
    for line in raw.splitlines():
        if not line or ":" not in line:
            continue
        name = line.split(" ", 1)[0].strip()
        if name:
            packages.append(name)
    return sorted(dict.fromkeys(packages))


def _parse_snap_packages(raw: str) -> List[str]:
    packages: List[str] = []
    for index, line in enumerate(raw.splitlines()):
        if index == 0 or not line.strip():
            continue
        name = line.split()[0].strip()
        if name:
            packages.append(name)
    return sorted(dict.fromkeys(packages))


def _parse_flatpak_apps(raw: str) -> List[str]:
    apps = [line.strip() for line in raw.splitlines() if line.strip()]
    return sorted(dict.fromkeys(apps))


def _parse_git_config(raw: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            result[key] = value
    return result


def _parse_systemd_services(raw: str) -> List[str]:
    services: List[str] = []
    for index, line in enumerate(raw.splitlines()):
        if index == 0 or not line.strip():
            continue
        name = line.split()[0].strip()
        if name.endswith(".service"):
            services.append(name)
    return sorted(dict.fromkeys(services))


def _parse_json_lines(raw: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _load_public_keys(home_root: str) -> List[Dict[str, str]]:
    ssh_dir = Path(home_root).expanduser() / ".ssh"
    if not ssh_dir.exists():
        return []
    keys: List[Dict[str, str]] = []
    for path in sorted(ssh_dir.glob("*.pub")):
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if content:
            keys.append({"path": str(path), "content": content})
    return keys


def _load_dotfiles(home_root: str) -> List[Dict[str, str]]:
    root = Path(home_root).expanduser()
    files: List[Dict[str, str]] = []
    for name in DOTFILES:
        path = root / name
        if not path.exists() or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        files.append({"path": str(path), "name": name, "content": content})
    return files


def collect_full_inventory(
    *,
    home_root: str,
    platform_info: PlatformInfo | None = None,
    timeout: int = 12,
) -> Dict[str, Any]:
    info = platform_info or detect_platform_info()
    collectors = {
        "system_packages": lambda: sorted(
            line.strip()
            for line in _run(["dpkg-query", "-W", "-f=${binary:Package}\n"], timeout=timeout).splitlines()
            if line.strip()
        ),
        "python_packages": lambda: _parse_python_packages(_run(["python3", "-m", "pip", "list", "--format=json"], timeout=timeout)),
        "npm_global": lambda: _parse_npm_globals(_run(["npm", "list", "-g", "--depth=0", "--json"], timeout=timeout)),
        "cargo_packages": lambda: _parse_cargo_packages(_run(["cargo", "install", "--list"], timeout=timeout)),
        "brew_formulae": lambda: sorted(
            line.strip() for line in _run(["brew", "list", "--formula"], timeout=timeout).splitlines() if line.strip()
        ),
        "brew_casks": lambda: sorted(
            line.strip() for line in _run(["brew", "list", "--cask"], timeout=timeout).splitlines() if line.strip()
        ),
        "snap_packages": lambda: _parse_snap_packages(_run(["snap", "list"], timeout=timeout)),
        "flatpak_apps": lambda: _parse_flatpak_apps(_run(["flatpak", "list", "--app", "--columns=application"], timeout=timeout)),
        "vscode_extensions": lambda: sorted(
            line.strip() for line in _run(["code", "--list-extensions"], timeout=timeout).splitlines() if line.strip()
        ),
        "git_config": lambda: _parse_git_config(_run(["git", "config", "--global", "--list"], timeout=timeout)),
        "user_crontab": lambda: [line for line in _run(["crontab", "-l"], timeout=timeout).splitlines() if line.strip()],
        "enabled_services": lambda: _parse_systemd_services(
            _run(["systemctl", "list-unit-files", "--type=service", "--state=enabled", "--no-pager"], timeout=timeout)
        ),
        "docker_containers": lambda: _parse_json_lines(_run(["docker", "ps", "-a", "--format", "{{json .}}"], timeout=timeout)),
        "docker_images": lambda: _parse_json_lines(_run(["docker", "images", "--format", "{{json .}}"], timeout=timeout)),
        "ssh_public_keys": lambda: _load_public_keys(home_root),
        "dotfiles": lambda: _load_dotfiles(home_root),
    }
    results: Dict[str, Any] = {key: [] for key in collectors}
    results["git_config"] = {}

    max_workers = min(8, len(collectors))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(loader): name for name, loader in collectors.items()}
        for future, name in future_map.items():
            try:
                results[name] = future.result(timeout=timeout + 2)
            except Exception:
                results[name] = {} if name == "git_config" else []

    system_packages = list(results["system_packages"])
    python_packages = list(results["python_packages"])
    npm_global = list(results["npm_global"])
    cargo_packages = list(results["cargo_packages"])
    brew_formulae = list(results["brew_formulae"])
    brew_casks = list(results["brew_casks"])
    snap_packages = list(results["snap_packages"])
    flatpak_apps = list(results["flatpak_apps"])
    vscode_extensions = list(results["vscode_extensions"])
    git_config = dict(results["git_config"])
    user_crontab = list(results["user_crontab"])
    enabled_services = list(results["enabled_services"])
    docker_containers = list(results["docker_containers"])
    docker_images = list(results["docker_images"])
    ssh_public_keys = list(results["ssh_public_keys"])
    dotfiles = list(results["dotfiles"])

    return {
        "captured_at": _timestamp(),
        "platform": info.to_dict(),
        "package_managers": {
            "primary": info.package_manager,
            "available": sorted(
                candidate
                for candidate in ("apt-get", "brew", "npm", "cargo", "snap", "flatpak", "docker")
                if shutil.which(candidate)
            ),
        },
        "packages": {
            "system": system_packages,
            "python": python_packages,
            "node_global": npm_global,
            "cargo": cargo_packages,
            "brew_formulae": brew_formulae,
            "brew_casks": brew_casks,
            "snap": snap_packages,
            "flatpak": flatpak_apps,
        },
        "vscode_extensions": vscode_extensions,
        "git": {"global_config": git_config},
        "ssh": {"public_keys": ssh_public_keys},
        "dotfiles": dotfiles,
        "cron": {"user": user_crontab},
        "systemd": {"enabled_services": enabled_services},
        "docker": {
            "containers": docker_containers,
            "images": docker_images,
        },
        "counts": {
            "system_packages": len(system_packages),
            "python_packages": len(python_packages),
            "node_global_packages": len(npm_global),
            "cargo_packages": len(cargo_packages),
            "brew_formulae": len(brew_formulae),
            "brew_casks": len(brew_casks),
            "snap_packages": len(snap_packages),
            "flatpak_apps": len(flatpak_apps),
            "vscode_extensions": len(vscode_extensions),
            "ssh_public_keys": len(ssh_public_keys),
            "dotfiles": len(dotfiles),
            "cron_lines": len(user_crontab),
            "enabled_services": len(enabled_services),
            "docker_containers": len(docker_containers),
            "docker_images": len(docker_images),
        },
    }

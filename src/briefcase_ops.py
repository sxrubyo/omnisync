#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import shlex
from pathlib import Path
from typing import Any, Mapping

from platform_ops import PlatformInfo


BRIEFCASE_SCHEMA_VERSION = 3
RESTORE_PLAN_SCHEMA_VERSION = 1
TRANSPORT_PREFERENCE = ("ssh", "sftp", "rsync")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _platform_dict(platform_info: PlatformInfo | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(platform_info, PlatformInfo):
        return platform_info.to_dict()
    return dict(platform_info)


def _inventory_summary(report: Mapping[str, Any] | None = None) -> dict[str, int]:
    payload = report or {}
    included = list(payload.get("included", []))
    discovered = list(payload.get("discovered", []))
    return {
        "included_state_count": len([item for item in included if item.get("kind") == "state"]),
        "included_secret_count": len([item for item in included if item.get("kind") == "secret"]),
        "discovered_product_count": len([item for item in discovered if item.get("classification") == "product"]),
        "discovered_noise_count": len([item for item in discovered if item.get("classification") == "noise"]),
    }


def build_briefcase_manifest(
    manifest: Mapping[str, Any],
    platform_info: PlatformInfo | Mapping[str, Any],
    *,
    inventory_report: Mapping[str, Any] | None = None,
    full_inventory: Mapping[str, Any] | None = None,
    repo_slug: str = "sxrubyo/omnisync",
) -> dict[str, Any]:
    source_platform = _platform_dict(platform_info)
    payload = dict(full_inventory or {})
    package_payload = dict(payload.get("packages") or {})
    return {
        "schema_version": BRIEFCASE_SCHEMA_VERSION,
        "kind": "omni-briefcase",
        "created_at": _utc_now(),
        "product": {
            "name": "omni-migrate-sync",
            "engine": "omnisync",
        },
        "source": {
            "profile": str(manifest.get("profile") or "production-clean"),
            "host_root": str(manifest.get("host_root") or ""),
            "platform": source_platform,
        },
        "inventory": {
            "manifest_version": int(manifest.get("version", 1)),
            "state_paths": list(manifest.get("state_paths", [])),
            "secret_paths": list(manifest.get("secret_paths", [])),
            "install_targets": list(manifest.get("install_targets", [])),
            "pm2_ecosystems": list(manifest.get("pm2_ecosystems", [])),
            "compose_projects": list(manifest.get("compose_projects", [])),
            "packages": {
                "system": list(package_payload.get("system") or manifest.get("apt_packages", [])),
                "python": list(package_payload.get("python") or manifest.get("python_packages", [])),
                "node_global": list(package_payload.get("node_global") or manifest.get("npm_global_packages", [])),
                "cargo": list(package_payload.get("cargo", [])),
                "brew_formulae": list(package_payload.get("brew_formulae", [])),
                "brew_casks": list(package_payload.get("brew_casks", [])),
                "snap": list(package_payload.get("snap", [])),
                "flatpak": list(package_payload.get("flatpak", [])),
            },
            "summary": _inventory_summary(inventory_report),
        },
        "full_inventory": payload,
        "transport": {
            "preferred": list(TRANSPORT_PREFERENCE),
            "github": {
                "role": "private-briefcase-plus-home-snapshot",
                "repo_slug": repo_slug,
                "recommended_private_repo": True,
                "suitable_for": [
                    "briefcase-manifest",
                    "restore-plan",
                    "sanitized-inventory",
                    "full-home-private-snapshot",
                    "encrypted-private-overlay",
                ],
                "not_suitable_for": [
                    "ssh-material",
                    "git-credentials",
                ],
            },
        },
        "restore_defaults": {
            "mode": "guided",
            "restore_state": True,
            "restore_apps": True,
            "confirm_secrets": True,
            "rewrite_host_references": True,
        },
    }


def _step(step_id: str, title: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "id": step_id,
        "title": title,
        "status": status,
        "reason": reason,
    }
    payload.update(extra)
    return payload


def build_restore_plan(
    briefcase_manifest: Mapping[str, Any],
    target_platform: PlatformInfo | Mapping[str, Any],
) -> dict[str, Any]:
    target = _platform_dict(target_platform)
    source = dict(briefcase_manifest.get("source", {}))
    source_platform = dict(source.get("platform", {}))
    inventory = dict(briefcase_manifest.get("inventory", {}))
    packages = dict(inventory.get("packages", {}))

    source_system = str(source_platform.get("system") or "unknown")
    source_pm = str(source_platform.get("package_manager") or "unknown")
    target_system = str(target.get("system") or "unknown")
    target_pm = str(target.get("package_manager") or "unknown")

    steps: list[dict[str, Any]] = []
    capability_gaps: list[str] = []

    state_paths = list(inventory.get("state_paths", []))
    secret_paths = list(inventory.get("secret_paths", []))
    install_targets = list(inventory.get("install_targets", []))
    compose_projects = list(inventory.get("compose_projects", []))
    pm2_ecosystems = list(inventory.get("pm2_ecosystems", []))
    system_packages = list(packages.get("system", []))
    node_globals = list(packages.get("node_global", []))

    steps.append(
        _step(
            "restore-state",
            "Restore state payload",
            "applicable" if state_paths else "skipped",
            "State payload is portable and should be restored first." if state_paths else "No state paths declared in the briefcase.",
            paths=state_paths,
        )
    )
    steps.append(
        _step(
            "restore-secrets",
            "Restore secrets payload",
            "manual" if secret_paths else "skipped",
            "Secrets always require explicit operator confirmation." if secret_paths else "No secret paths declared in the briefcase.",
            paths=secret_paths,
        )
    )

    if system_packages:
        if target_pm == "unknown":
            steps.append(
                _step(
                    "install-system-packages",
                    "Install system packages",
                    "manual",
                    "Target package manager is unknown, so package restoration needs operator mapping.",
                    source_package_manager=source_pm,
                    target_package_manager=target_pm,
                    packages=system_packages,
                )
            )
            capability_gaps.append("Target package manager is unknown; system packages need manual installation.")
        elif source_pm == target_pm:
            steps.append(
                _step(
                    "install-system-packages",
                    f"Install system packages via {target_pm}",
                    "applicable",
                    "Source and target package managers match.",
                    source_package_manager=source_pm,
                    target_package_manager=target_pm,
                    packages=system_packages,
                )
            )
        else:
            steps.append(
                _step(
                    "install-system-packages",
                    f"Map system packages to {target_pm}",
                    "manual",
                    "Source and target package managers differ, so package names cannot be reused blindly.",
                    source_package_manager=source_pm,
                    target_package_manager=target_pm,
                    packages=system_packages,
                )
            )
            capability_gaps.append(
                f"System package mapping required: source uses {source_pm}, target uses {target_pm}."
            )
    else:
        steps.append(
            _step(
                "install-system-packages",
                "Install system packages",
                "skipped",
                "No system packages declared in the briefcase.",
                packages=[],
            )
        )

    steps.append(
        _step(
            "install-node-globals",
            "Install Node.js global packages",
            "applicable" if node_globals else "skipped",
            "Node global packages are portable once Node.js is available." if node_globals else "No npm global packages declared in the briefcase.",
            packages=node_globals,
        )
    )
    steps.append(
        _step(
            "restore-repositories",
            "Restore repositories and install targets",
            "applicable" if install_targets else "skipped",
            "Repositories and install targets should be recreated before service recovery." if install_targets else "No install targets declared in the briefcase.",
            targets=install_targets,
        )
    )

    compose_status = "applicable" if compose_projects and target_system != "windows" else "manual" if compose_projects else "skipped"
    compose_reason = (
        "Compose projects can be restored directly on this target."
        if compose_status == "applicable"
        else "Compose projects need operator review on Windows targets."
        if compose_status == "manual"
        else "No compose projects declared in the briefcase."
    )
    if compose_status == "manual":
        capability_gaps.append("Compose projects need explicit review on Windows targets.")
    steps.append(
        _step(
            "restore-compose-projects",
            "Restore Compose projects",
            compose_status,
            compose_reason,
            projects=compose_projects,
        )
    )

    steps.append(
        _step(
            "restore-pm2",
            "Restore PM2 workloads",
            "applicable" if pm2_ecosystems else "skipped",
            "PM2 workloads can be revived once Node.js and apps are present." if pm2_ecosystems else "No PM2 ecosystems declared in the briefcase.",
            ecosystems=pm2_ecosystems,
        )
    )
    steps.append(
        _step(
            "rewrite-host-references",
            "Rewrite host references",
            "applicable",
            "Host and IP references should be rewritten after state and apps are in place.",
        )
    )

    if source_system != target_system:
        capability_gaps.append(
            f"Cross-platform restore detected: source is {source_system}, target is {target_system}."
        )

    return {
        "schema_version": RESTORE_PLAN_SCHEMA_VERSION,
        "kind": "omni-restore-plan",
        "created_at": _utc_now(),
        "source": {
            "profile": source.get("profile"),
            "platform": source_platform,
        },
        "target": target,
        "cross_platform": source_system != target_system,
        "steps": steps,
        "capability_gaps": capability_gaps,
    }


def manifest_from_briefcase(
    briefcase_manifest: Mapping[str, Any],
    *,
    home_root: str,
) -> dict[str, Any]:
    source = dict(briefcase_manifest.get("source", {}))
    inventory = dict(briefcase_manifest.get("inventory", {}))
    packages = dict(inventory.get("packages", {}))
    return {
        "version": 1,
        "profile": str(source.get("profile") or "production-clean"),
        "host_root": str(home_root),
        "state_paths": list(inventory.get("state_paths", [])),
        "secret_paths": list(inventory.get("secret_paths", [])),
        "install_targets": list(inventory.get("install_targets", [])),
        "pm2_ecosystems": list(inventory.get("pm2_ecosystems", [])),
        "compose_projects": list(inventory.get("compose_projects", [])),
        "apt_packages": list(packages.get("system", [])),
        "python_packages": list(packages.get("python", [])),
        "npm_global_packages": list(packages.get("node_global", [])),
    }


def _shell_lines(command: str, values: list[str], *, indent: str = "  ") -> list[str]:
    if not values:
        return []
    lines = [command + " \\"]
    for index, value in enumerate(values):
        suffix = " \\" if index < len(values) - 1 else ""
        lines.append(f"{indent}{shlex.quote(value)}{suffix}")
    return lines


def build_restore_script(
    briefcase_manifest: Mapping[str, Any],
    *,
    fresh_server: bool = True,
) -> str:
    inventory = dict(briefcase_manifest.get("inventory", {}))
    packages = dict(inventory.get("packages", {}))
    full_inventory = dict(briefcase_manifest.get("full_inventory") or {})
    git_config = dict((full_inventory.get("git") or {}).get("global_config") or {})
    public_keys = list((full_inventory.get("ssh") or {}).get("public_keys") or [])
    dotfiles = list(full_inventory.get("dotfiles") or [])
    crontab_lines = list((full_inventory.get("cron") or {}).get("user") or [])
    vscode_extensions = list(full_inventory.get("vscode_extensions") or [])

    lines: list[str] = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        'echo "==> Omni Migrate Sync restore bootstrap"',
        f'echo "Fresh server mode: {"yes" if fresh_server else "no"}"',
        "",
    ]

    system_packages = list(packages.get("system", []))
    if system_packages:
        lines.extend(
            [
                "if command -v apt-get >/dev/null 2>&1; then",
                '  echo "==> Installing system packages via apt-get"',
                "  sudo apt-get update",
            ]
        )
        lines.extend(_shell_lines("  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y", system_packages, indent="    "))
        lines.extend(["fi", ""])

    python_packages = list(packages.get("python", []))
    if python_packages:
        lines.extend(
            [
                "if command -v python3 >/dev/null 2>&1; then",
                '  echo "==> Installing Python packages"',
            ]
        )
        lines.extend(_shell_lines("  python3 -m pip install", python_packages, indent="    "))
        lines.extend(["fi", ""])

    node_packages = list(packages.get("node_global", []))
    if node_packages:
        lines.extend(
            [
                "if command -v npm >/dev/null 2>&1; then",
                '  echo "==> Installing npm global packages"',
            ]
        )
        lines.extend(_shell_lines("  npm install -g", node_packages, indent="    "))
        lines.extend(["fi", ""])

    cargo_packages = list(packages.get("cargo", []))
    if cargo_packages:
        lines.extend(
            [
                "if command -v cargo >/dev/null 2>&1; then",
                '  echo "==> Installing cargo packages"',
            ]
        )
        for package in cargo_packages:
            lines.append(f"  cargo install {shlex.quote(package)}")
        lines.extend(["fi", ""])

    brew_formulae = list(packages.get("brew_formulae", []))
    if brew_formulae:
        lines.extend(
            [
                "if command -v brew >/dev/null 2>&1; then",
                '  echo "==> Installing Homebrew formulae"',
            ]
        )
        lines.extend(_shell_lines("  brew install", brew_formulae, indent="    "))
        lines.extend(["fi", ""])

    brew_casks = list(packages.get("brew_casks", []))
    if brew_casks:
        lines.extend(
            [
                "if command -v brew >/dev/null 2>&1; then",
                '  echo "==> Installing Homebrew casks"',
            ]
        )
        lines.extend(_shell_lines("  brew install --cask", brew_casks, indent="    "))
        lines.extend(["fi", ""])

    snap_packages = list(packages.get("snap", []))
    if snap_packages:
        lines.extend(
            [
                "if command -v snap >/dev/null 2>&1; then",
                '  echo "==> Installing snap packages"',
            ]
        )
        for package in snap_packages:
            lines.append(f"  sudo snap install {shlex.quote(package)}")
        lines.extend(["fi", ""])

    flatpak_apps = list(packages.get("flatpak", []))
    if flatpak_apps:
        lines.extend(
            [
                "if command -v flatpak >/dev/null 2>&1; then",
                '  echo "==> Installing Flatpak apps"',
            ]
        )
        for app in flatpak_apps:
            lines.append(f"  flatpak install -y flathub {shlex.quote(app)}")
        lines.extend(["fi", ""])

    if vscode_extensions:
        lines.extend(
            [
                "if command -v code >/dev/null 2>&1; then",
                '  echo "==> Installing VS Code extensions"',
            ]
        )
        for extension in vscode_extensions:
            lines.append(f"  code --install-extension {shlex.quote(extension)} || true")
        lines.extend(["fi", ""])

    if git_config:
        lines.extend(['echo "==> Restoring git global config"'])
        for key, value in git_config.items():
            lines.append(f"git config --global {shlex.quote(key)} {shlex.quote(value)}")
        lines.append("")

    if public_keys:
        lines.extend(
            [
                'echo "==> Restoring SSH public keys"',
                "mkdir -p ~/.ssh",
                "chmod 700 ~/.ssh",
            ]
        )
        for item in public_keys:
            path = Path(str(item.get("path") or "~/.ssh/id_imported.pub"))
            target = "~/.ssh/" + path.name
            lines.extend(
                [
                    f"cat <<'OMNI_KEY_{path.name.replace('.', '_')}' > {target}",
                    str(item.get("content") or ""),
                    f"OMNI_KEY_{path.name.replace('.', '_')}",
                    f"chmod 644 {target}",
                ]
            )
        lines.append("")

    if dotfiles:
        lines.append('echo "==> Restoring dotfiles"')
        for item in dotfiles:
            name = str(item.get("name") or Path(str(item.get("path") or "")).name)
            marker = "OMNI_DOTFILE_" + name.replace(".", "_").replace("-", "_")
            target = "~/" + name
            lines.extend(
                [
                    f"cat <<'{marker}' > {target}",
                    str(item.get("content") or ""),
                    marker,
                ]
            )
        lines.append("")

    if crontab_lines:
        marker = "OMNI_CRONTAB"
        lines.extend(
            [
                'echo "==> Restoring user crontab"',
                f"cat <<'{marker}' | crontab -",
            ]
        )
        lines.extend(str(line) for line in crontab_lines)
        lines.extend([marker, ""])

    lines.extend(
        [
            'echo "==> Restore bootstrap finished"',
            'echo "Next: run omni restore or omni migrate sync plan on this machine."',
            "",
        ]
    )
    return "\n".join(lines)

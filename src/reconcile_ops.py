#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from bundle_ops import restore_bundle
from host_inventory import expand_path


def run_cmd(cmd: str, cwd: str | None = None) -> Tuple[int, str, str]:
    process = subprocess.Popen(
        cmd,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = process.communicate()
    return process.returncode, stdout.strip(), stderr.strip()


def is_root() -> bool:
    return os.geteuid() == 0


def sudo_prefix() -> str:
    return "" if is_root() else ("sudo " if command_exists("sudo") else "")


def command_exists(name: str) -> bool:
    code, _, _ = run_cmd(f"command -v {name}")
    return code == 0


def run_visible_cmd(cmd: str, cwd: str | None = None, label: str = "") -> Tuple[int, str, str]:
    return run_cmd(cmd, cwd=cwd)


def detect_compose_command() -> str:
    if command_exists("docker"):
        code, out, err = run_cmd("docker compose version")
        if code == 0:
            return "docker compose"
    if command_exists("docker-compose"):
        return "docker-compose"
    return "docker compose"


def docker_requires_sudo() -> bool:
    docker_socket = Path("/var/run/docker.sock")
    return bool(command_exists("sudo") and docker_socket.exists() and not os.access(docker_socket, os.W_OK))


def build_compose_up_command(compose_file: Path) -> str:
    base = detect_compose_command()
    prefix = sudo_prefix()
    return f"{prefix}{base} -f {str(compose_file)} up -d --build"


def build_compose_down_command(compose_file: Path) -> str:
    base = detect_compose_command()
    prefix = sudo_prefix()
    return f"{prefix}{base} -f {str(compose_file)} down --remove-orphans"


def ensure_docker_service_running() -> Dict[str, Any]:
    if not command_exists("docker"):
        return {"changed": False, "status": "missing"}
    if not command_exists("systemctl"):
        return {"changed": False, "status": "skipped"}
    code, out, err = run_cmd("systemctl is-active docker")
    if code == 0 and out.strip() == "active":
        return {"changed": False, "status": "active"}
    prefix = sudo_prefix()
    code, out, err = run_cmd(f"{prefix}systemctl enable --now docker")
    if code != 0:
        raise RuntimeError(err or out or "Failed to start docker service")
    return {"changed": True, "status": "started"}


def ensure_supported_node_runtime(target_major: int = 20) -> Dict[str, Any]:
    if command_exists("node"):
        code, out, _ = run_cmd("node -v")
        if code == 0 and out.strip().startswith("v"):
            try:
                current_major = int(out.strip().lstrip("v").split(".", 1)[0])
            except ValueError:
                current_major = 0
            if current_major >= target_major:
                return {"changed": False, "current_major": current_major, "target_major": target_major}
        else:
            current_major = 0
    else:
        current_major = 0

    if not command_exists("apt-get") or not command_exists("curl"):
        return {"changed": False, "status": "unsupported", "target_major": target_major}

    prefix = sudo_prefix()
    legacy_conflicts: List[str] = []
    for package in ("libnode-dev", "nodejs-doc", "npm"):
        code, _, _ = run_cmd(f"dpkg -s {package}")
        if code == 0:
            legacy_conflicts.append(package)
    if legacy_conflicts:
        code, out, err = run_cmd(
            f"{prefix}DEBIAN_FRONTEND=noninteractive apt-get remove -y {' '.join(legacy_conflicts)}"
        )
        if code != 0:
            raise RuntimeError(err or out or "Failed to remove legacy node conflicts")

    node_setup_cmd = (
        f"curl -fsSL https://deb.nodesource.com/setup_{target_major}.x | "
        + (f"{prefix}-E bash -" if prefix else "bash -")
    )
    code, out, err = run_cmd(node_setup_cmd)
    if code != 0:
        raise RuntimeError(err or out or "Failed to prepare NodeSource repository")
    code, out, err = run_cmd(f"{prefix}DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs")
    if code != 0:
        raise RuntimeError(err or out or "Failed to install nodejs")
    return {"changed": True, "current_major": current_major, "target_major": target_major}


def install_apt_packages(packages: List[str]) -> Dict[str, Any]:
    requested = [pkg for pkg in packages if pkg]
    if not requested or not command_exists("apt-get"):
        return {"changed": [], "skipped": requested, "unavailable": [], "resolved": {}}
    missing: List[str] = []
    unavailable: List[str] = []
    resolved: Dict[str, str] = {}
    for package in requested:
        code, _, _ = run_cmd(f"dpkg -s {package}")
        if code != 0:
            cache_code, _, _ = run_cmd(f"apt-cache show {package}")
            if cache_code == 0:
                missing.append(package)
                continue
            if package == "docker-compose-plugin":
                fallback = "docker-compose"
                fallback_cache, _, _ = run_cmd(f"apt-cache show {fallback}")
                if fallback_cache == 0:
                    missing.append(fallback)
                    resolved[package] = fallback
                    continue
            unavailable.append(package)
    if not missing:
        return {"changed": [], "skipped": requested, "unavailable": unavailable, "resolved": resolved}
    prefix = sudo_prefix()
    run_cmd(f"{prefix}apt-get update")
    code, out, err = run_cmd(
        f"{prefix}DEBIAN_FRONTEND=noninteractive apt-get install -y " + " ".join(missing)
    )
    if code != 0:
        raise RuntimeError(err or out or "apt install failed")
    return {
        "changed": missing,
        "skipped": [pkg for pkg in requested if pkg not in missing and pkg not in unavailable],
        "unavailable": unavailable,
        "resolved": resolved,
    }


def install_npm_global_packages(packages: List[str]) -> Dict[str, Any]:
    requested = [pkg for pkg in packages if pkg]
    if not requested or not command_exists("npm"):
        return {"changed": [], "skipped": requested}
    ensure_supported_node_runtime()
    missing: List[str] = []
    for package in requested:
        code, _, _ = run_cmd(f"npm list -g {package} --depth=0")
        if code != 0:
            missing.append(package)
    if not missing:
        return {"changed": [], "skipped": requested}
    prefix_code, prefix_out, _ = run_cmd("npm config get prefix")
    install_prefix = prefix_out.strip() if prefix_code == 0 else ""
    use_sudo = bool(
        (install_prefix.startswith("/usr") and command_exists("sudo")) 
        or (install_prefix and not os.access(install_prefix, os.W_OK) and command_exists("sudo"))
        or (is_root() and command_exists("sudo") and not os.access(install_prefix, os.W_OK))
    )
    command = (sudo_prefix() if use_sudo else "") + "npm install -g " + " ".join(missing)
    code, out, err = run_cmd(command)
    if code != 0:
        raise RuntimeError(err or out or "npm global install failed")
    return {"changed": missing, "skipped": [pkg for pkg in requested if pkg not in missing]}


def clone_or_update_repos(repo_entries: List[Any]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for entry in repo_entries:
        if isinstance(entry, str):
            path = Path(expand_path(entry))
            results.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "status": "present" if path.exists() else "missing",
                }
            )
            continue

        if not isinstance(entry, dict):
            continue

        path = Path(expand_path(str(entry.get("path") or "")))
        name = str(entry.get("name") or path.name)
        url = str(entry.get("url") or "").strip()
        ref = str(entry.get("ref") or "main").strip()
        if not url or not path:
            results.append({"name": name, "path": str(path), "status": "skipped"})
            continue

        path.parent.mkdir(parents=True, exist_ok=True)
        if (path / ".git").exists():
            code, out, err = run_cmd(
                f"git -C {shlex.quote(str(path))} fetch --all --prune && "
                f"git -C {shlex.quote(str(path))} checkout {shlex.quote(ref)} && "
                f"git -C {shlex.quote(str(path))} pull --ff-only origin {shlex.quote(ref)}"
            )
            if code != 0:
                raise RuntimeError(err or out or f"git update failed for {name}")
            status = "updated"
        else:
            code, out, err = run_cmd(
                f"git clone --branch {shlex.quote(ref)} {shlex.quote(url)} {shlex.quote(str(path))}"
            )
            if code != 0:
                raise RuntimeError(err or out or f"git clone failed for {name}")
            status = "cloned"
        results.append({"name": name, "path": str(path), "status": status})
    return results


def install_project_dependencies(targets: List[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for raw_target in targets:
        path = Path(expand_path(raw_target))
        if not path.exists():
            results.append({"path": str(path), "status": "missing"})
            continue
        actions: List[str] = []
        requirements = path / "requirements.txt"
        package_json = path / "package.json"
        if requirements.exists():
            code, out, err = run_cmd(f"python3 -m pip install -r {shlex.quote(str(requirements))}", cwd=str(path))
            if code != 0:
                raise RuntimeError(err or out or f"pip install failed for {path}")
            actions.append("pip")
        if package_json.exists():
            code, out, err = run_cmd("npm install", cwd=str(path))
            if code != 0:
                raise RuntimeError(err or out or f"npm install failed for {path}")
            actions.append("npm")
        results.append({"path": str(path), "status": "ok", "actions": actions})
    return results


def start_compose_projects(projects: List[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    ensure_docker_service_running()
    for raw_project in projects:
        project = Path(expand_path(raw_project))
        if not project.exists():
            results.append({"path": str(project), "status": "missing"})
            continue
        compose_file = None
        for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
            candidate = project / name
            if candidate.exists():
                compose_file = candidate
                break
        if not compose_file:
            results.append({"path": str(project), "status": "skipped"})
            continue
        up_command = build_compose_up_command(compose_file)
        code, out, err = run_visible_cmd(up_command, cwd=str(project), label=f"compose up :: {project.name}")
        if code != 0:
            combined = f"{out}\n{err}".strip()
            if "ContainerConfig" in combined:
                down_command = build_compose_down_command(compose_file)
                down_code, down_out, down_err = run_visible_cmd(
                    down_command,
                    cwd=str(project),
                    label=f"compose down :: {project.name}",
                )
                if down_code != 0:
                    raise RuntimeError(down_err or down_out or f"docker compose recovery failed for {project}")
                code, out, err = run_visible_cmd(up_command, cwd=str(project), label=f"compose up :: {project.name}")
            if code != 0:
                raise RuntimeError(err or out or f"docker compose failed for {project}")
        results.append({"path": str(project), "status": "started", "compose_file": str(compose_file)})
    return results


def restore_pm2(pm2_dump: str, ecosystems: List[str]) -> Dict[str, Any]:
    if not command_exists("pm2"):
        return {"status": "missing_pm2"}
    dump_path = Path(expand_path(pm2_dump)) if pm2_dump else None
    if dump_path and dump_path.exists():
        code, out, err = run_cmd("pm2 resurrect")
        if code == 0:
            run_cmd("pm2 save")
            return {"status": "resurrected", "source": str(dump_path)}
    started: List[str] = []
    for raw in ecosystems:
        ecosystem = Path(expand_path(raw))
        if not ecosystem.exists():
            continue
        code, out, err = run_cmd(f"pm2 start {shlex.quote(str(ecosystem))} --update-env", cwd=str(ecosystem.parent))
        if code != 0:
            raise RuntimeError(err or out or f"pm2 start failed for {ecosystem}")
        started.append(str(ecosystem))
    if started:
        run_cmd("pm2 save")
        return {"status": "started", "ecosystems": started}
    return {"status": "no_pm2_state"}


def install_systemd_timer(
    *,
    omni_home: Path,
    service_name: str = "omni-update",
    on_calendar: str = "daily",
) -> Dict[str, Any]:
    systemd_dir = Path("/etc/systemd/system")
    service_template = omni_home / "config" / "systemd" / f"{service_name}.service"
    timer_template = omni_home / "config" / "systemd" / f"{service_name}.timer"
    if not service_template.exists():
        service_template = omni_home / "config" / "systemd" / "omni-update.service"
    if not timer_template.exists():
        timer_template = omni_home / "config" / "systemd" / "omni-update.timer"
    if not service_template.exists() or not timer_template.exists():
        raise FileNotFoundError("Missing systemd template files")

    service_text = service_template.read_text(encoding="utf-8").replace("__OMNI_HOME__", str(omni_home))
    timer_text = (
        timer_template.read_text(encoding="utf-8")
        .replace("__OMNI_HOME__", str(omni_home))
        .replace("OnCalendar=daily", f"OnCalendar={on_calendar}")
        .replace("Unit=omni-update.service", f"Unit={service_name}.service")
    )

    service_path = systemd_dir / f"{service_name}.service"
    timer_path = systemd_dir / f"{service_name}.timer"
    writer = ["tee"]
    daemon_reload = ["systemctl", "daemon-reload"]
    enable_timer = ["systemctl", "enable", "--now", f"{service_name}.timer"]
    if os.geteuid() != 0:
        writer.insert(0, "sudo")
        daemon_reload.insert(0, "sudo")
        enable_timer.insert(0, "sudo")

    for text, target in ((service_text, service_path), (timer_text, timer_path)):
        result = subprocess.run(writer + [str(target)], input=text, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Failed to write {target}")

    reload_result = subprocess.run(daemon_reload, capture_output=True, text=True, check=False)
    if reload_result.returncode != 0:
        raise RuntimeError(reload_result.stderr.strip() or reload_result.stdout.strip() or "systemctl daemon-reload failed")

    enable_result = subprocess.run(enable_timer, capture_output=True, text=True, check=False)
    if enable_result.returncode != 0:
        raise RuntimeError(enable_result.stderr.strip() or enable_result.stdout.strip() or "systemctl enable timer failed")
    return {"service": str(service_path), "timer": str(timer_path)}


def install_systemd_service(
    *,
    omni_home: Path,
    template_name: str,
    service_name: str,
) -> Dict[str, Any]:
    systemd_dir = Path("/etc/systemd/system")
    service_template = omni_home / "config" / "systemd" / template_name
    if not service_template.exists():
        raise FileNotFoundError(f"Missing systemd template file: {template_name}")

    service_text = service_template.read_text(encoding="utf-8").replace("__OMNI_HOME__", str(omni_home))
    service_path = systemd_dir / f"{service_name}.service"
    writer = ["tee"]
    daemon_reload = ["systemctl", "daemon-reload"]
    enable_service = ["systemctl", "enable", "--now", f"{service_name}.service"]
    if os.geteuid() != 0:
        writer.insert(0, "sudo")
        daemon_reload.insert(0, "sudo")
        enable_service.insert(0, "sudo")

    result = subprocess.run(writer + [str(service_path)], input=service_text, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Failed to write {service_path}")

    reload_result = subprocess.run(daemon_reload, capture_output=True, text=True, check=False)
    if reload_result.returncode != 0:
        raise RuntimeError(reload_result.stderr.strip() or reload_result.stdout.strip() or "systemctl daemon-reload failed")

    enable_result = subprocess.run(enable_service, capture_output=True, text=True, check=False)
    if enable_result.returncode != 0:
        raise RuntimeError(enable_result.stderr.strip() or enable_result.stdout.strip() or "systemctl enable service failed")

    return {"service": str(service_path)}


def reconcile_host(
    manifest: Dict[str, Any],
    *,
    bundle_path: str = "",
    secrets_path: str = "",
    passphrase: str = "",
    target_root: str = "/",
    repos: List[Any] | None = None,
    before_services: Callable[[Dict[str, Any]], Dict[str, Any] | None] | None = None,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {"steps": []}

    if bundle_path:
        restored = restore_bundle(Path(bundle_path), target_root=target_root)
        report["steps"].append({"name": "restore_state", "restored": len(restored)})

    if secrets_path:
        restored = restore_bundle(Path(secrets_path), target_root=target_root, passphrase=passphrase)
        report["steps"].append({"name": "restore_secrets", "restored": len(restored)})

    apt_res = install_apt_packages(list(manifest.get("apt_packages", [])))
    report["steps"].append({"name": "apt", **apt_res})

    npm_res = install_npm_global_packages(list(manifest.get("npm_global_packages", [])))
    report["steps"].append({"name": "npm_global", **npm_res})

    repo_res = clone_or_update_repos(repos or [])
    report["steps"].append({"name": "repos", "results": repo_res})

    install_res = install_project_dependencies(list(manifest.get("install_targets", [])))
    report["steps"].append({"name": "install_targets", "results": install_res})

    if before_services:
        hook_res = before_services(report) or {}
        report["steps"].append({"name": "before_services", **hook_res})

    compose_res = start_compose_projects(list(manifest.get("compose_projects", [])))
    report["steps"].append({"name": "compose", "results": compose_res})

    pm2_dump = ""
    for candidate in manifest.get("state_paths", []):
        if candidate.endswith("dump.pm2"):
            pm2_dump = candidate
            break
    pm2_res = restore_pm2(pm2_dump, list(manifest.get("pm2_ecosystems", [])))
    report["steps"].append({"name": "pm2", **pm2_res})

    return report

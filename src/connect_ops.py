#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence


@dataclass(frozen=True)
class SSHDestination:
    host: str
    user: str
    port: int = 22
    key_path: str = ""
    auth_mode: str = "agent"
    password: str = ""
    target_system: str = "auto"

    def target(self) -> str:
        return f"{self.user}@{self.host}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


REMOTE_SYSTEM_ALIASES = {
    "": "auto",
    "auto": "auto",
    "linux": "posix",
    "unix": "posix",
    "ubuntu": "posix",
    "debian": "posix",
    "rhel": "posix",
    "fedora": "posix",
    "macos": "posix",
    "darwin": "posix",
    "wsl": "posix",
    "windows": "windows",
    "powershell": "windows",
    "win": "windows",
}


def normalize_remote_system(value: str | None) -> str:
    return REMOTE_SYSTEM_ALIASES.get(str(value or "").strip().lower(), "auto")


def normalize_auth_mode(destination: SSHDestination) -> str:
    if destination.key_path:
        return "key"
    mode = str(destination.auth_mode or "").strip().lower()
    return mode if mode in {"agent", "key", "password"} else "agent"


def _ssh_base_command(destination: SSHDestination) -> List[str]:
    args = ["ssh", "-p", str(destination.port)]
    auth_mode = normalize_auth_mode(destination)
    if auth_mode == "key" and destination.key_path:
        args.extend(["-i", destination.key_path])
    if auth_mode == "password":
        args.extend(
            [
                "-o",
                "BatchMode=no",
                "-o",
                "PreferredAuthentications=password",
                "-o",
                "PubkeyAuthentication=no",
            ]
        )
    else:
        args.extend(["-o", "BatchMode=yes"])
    args.extend(
        [
            "-o",
            "StrictHostKeyChecking=accept-new",
            destination.target(),
        ]
    )
    return args


def _can_prompt_interactively() -> bool:
    try:
        return bool(sys.stdin.isatty()) and bool(sys.stderr.isatty())
    except Exception:
        return False


def parse_remote_probe_output(raw: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "system": "unknown",
        "package_manager": "unknown",
        "home_entries": 0,
        "git_repos": 0,
        "package_count": 0,
        "fresh_server": False,
        "rsync_available": False,
        "home": "",
    }
    for line in str(raw or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key in {"home_entries", "git_repos", "package_count"}:
            try:
                payload[key] = int(value)
            except ValueError:
                payload[key] = 0
        elif key in {"fresh_server", "rsync_available"}:
            payload[key] = value.lower() in {"1", "true", "yes"}
        else:
            payload[key] = value
    return payload


def build_posix_probe_script() -> str:
    return r"""
set -eu
printf 'system=%s\n' "$(uname -s 2>/dev/null || echo unknown)"
pkg=unknown
for candidate in apt-get apt dnf yum pacman apk zypper brew; do
  if command -v "$candidate" >/dev/null 2>&1; then
    pkg="$candidate"
    break
  fi
done
printf 'package_manager=%s\n' "$pkg"
printf 'home=%s\n' "${HOME:-}"
rsync_available=false
if command -v rsync >/dev/null 2>&1; then
  rsync_available=true
fi
home_entries="$(find "${HOME:-.}" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')"
git_repos="$(find "${HOME:-.}" -maxdepth 3 -name .git -type d 2>/dev/null | wc -l | tr -d ' ')"
package_count=0
if command -v dpkg-query >/dev/null 2>&1; then
  package_count="$(dpkg-query -W -f='${Package}\n' 2>/dev/null | wc -l | tr -d ' ')"
elif command -v rpm >/dev/null 2>&1; then
  package_count="$(rpm -qa 2>/dev/null | wc -l | tr -d ' ')"
elif command -v brew >/dev/null 2>&1; then
  package_count="$(brew list 2>/dev/null | wc -l | tr -d ' ')"
fi
fresh=false
if [ "${home_entries:-0}" -le 6 ] && [ "${git_repos:-0}" -eq 0 ] && [ "${package_count:-0}" -le 500 ]; then
  fresh=true
fi
printf 'home_entries=%s\n' "${home_entries:-0}"
printf 'git_repos=%s\n' "${git_repos:-0}"
printf 'package_count=%s\n' "${package_count:-0}"
printf 'fresh_server=%s\n' "$fresh"
printf 'rsync_available=%s\n' "$rsync_available"
"""


def build_windows_probe_script() -> str:
    return (
        'powershell -NoProfile -NonInteractive -Command '
        '"$ErrorActionPreference=\'SilentlyContinue\'; '
        "$homePath=$HOME; "
        "$pkg='unknown'; "
        "foreach($candidate in @('winget','choco','scoop')){ if(Get-Command $candidate -ErrorAction SilentlyContinue){ $pkg=$candidate; break } } "
        "$homeEntries=0; if($homePath -and (Test-Path $homePath)){ $homeEntries=(Get-ChildItem -LiteralPath $homePath -Force -ErrorAction SilentlyContinue | Measure-Object).Count }; "
        "$gitRepos=0; if($homePath -and (Test-Path $homePath)){ $gitRepos=(Get-ChildItem -LiteralPath $homePath -Directory -Filter ''.git'' -Recurse -ErrorAction SilentlyContinue | Measure-Object).Count }; "
        "$packageCount=0; "
        "$fresh='false'; if(($homeEntries -le 6) -and ($gitRepos -eq 0)){ $fresh='true' }; "
        "Write-Output ('system=Windows'); "
        "Write-Output ('package_manager=' + $pkg); "
        "Write-Output ('home=' + $homePath); "
        "Write-Output ('home_entries=' + $homeEntries); "
        "Write-Output ('git_repos=' + $gitRepos); "
        "Write-Output ('package_count=' + $packageCount); "
        "Write-Output ('fresh_server=' + $fresh); "
        "Write-Output ('rsync_available=false')"
        '"'
    )


def _wrap_command_with_auth(
    command: List[str],
    destination: SSHDestination,
    *,
    allow_interactive_password: bool = False,
) -> tuple[List[str], Dict[str, str] | None, bool]:
    auth_mode = normalize_auth_mode(destination)
    if auth_mode != "password":
        return command, None, False

    if destination.password and shutil.which("sshpass"):
        env = os.environ.copy()
        env["SSHPASS"] = destination.password
        return ["sshpass", "-e", *command], env, False

    if allow_interactive_password and _can_prompt_interactively():
        return command, None, True

    if destination.password:
        raise RuntimeError(
            "La autenticación por contraseña requiere `sshpass` para automatizarse. "
            "En una terminal interactiva Omni puede usar el prompt nativo de `ssh`; "
            "fuera de eso usa SSH agent, una clave privada o instala `sshpass`."
        )
    raise RuntimeError("Falta la contraseña SSH para continuar en modo password.")


def _run_password_interactive_command(
    command: List[str],
    *,
    timeout: int,
    runner: Any,
    env: Dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    stdout_fd, stdout_name = tempfile.mkstemp(prefix="omni-ssh-probe-", suffix=".log")
    os.close(stdout_fd)
    stdout_path = Path(stdout_name)
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout_file:
            result = runner(
                command,
                stdout=stdout_file,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=timeout,
                env=env,
            )
        stdout = stdout_path.read_text(encoding="utf-8")
        stderr = str(getattr(result, "stderr", "") or "")
        return subprocess.CompletedProcess(command, getattr(result, "returncode", 1), stdout, stderr)
    finally:
        stdout_path.unlink(missing_ok=True)


def probe_remote_host(
    destination: SSHDestination,
    *,
    timeout: int = 30,
    runner: Any = subprocess.run,
) -> Dict[str, Any]:
    system_hint = normalize_remote_system(destination.target_system)
    attempts = [system_hint] if system_hint != "auto" else ["posix", "windows"]
    errors: list[str] = []

    for attempt in attempts:
        script = build_windows_probe_script() if attempt == "windows" else build_posix_probe_script()
        command, env, interactive_password = _wrap_command_with_auth(
            _ssh_base_command(destination) + [script],
            destination,
            allow_interactive_password=True,
        )
        try:
            if interactive_password:
                result = _run_password_interactive_command(command, timeout=timeout, runner=runner, env=env)
            else:
                result = runner(command, capture_output=True, text=True, check=False, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            errors.append(f"{attempt}: timed out after {timeout} seconds")
            continue
        if result.returncode == 0:
            payload = parse_remote_probe_output(result.stdout)
            payload["system_family"] = attempt
            return payload
        stderr = result.stderr.strip() or result.stdout.strip() or "SSH probe failed"
        errors.append(f"{attempt}: {stderr}")

    raise RuntimeError(" | ".join(errors) if errors else "SSH probe failed")


def build_rsync_command(
    source_paths: Sequence[str],
    destination: SSHDestination,
    *,
    remote_path: str,
) -> List[str]:
    ssh_transport = f"ssh -p {destination.port}"
    auth_mode = normalize_auth_mode(destination)
    if auth_mode == "key" and destination.key_path:
        ssh_transport += f" -i {destination.key_path}"
    if auth_mode == "password":
        ssh_transport += " -o PreferredAuthentications=password -o PubkeyAuthentication=no"
    command = ["rsync", "-az", "--info=progress2", "-e", ssh_transport]
    command.extend(list(source_paths))
    command.append(f"{destination.target()}:{remote_path.rstrip('/')}/")
    return command


def build_sftp_command(
    source_paths: Sequence[str],
    destination: SSHDestination,
    *,
    remote_path: str,
) -> tuple[List[str], str]:
    lines = [f"mkdir {remote_path}", f"cd {remote_path}"]
    for source in source_paths:
        resolved = Path(source)
        if resolved.is_dir():
            lines.append(f"put -r {resolved}")
        else:
            lines.append(f"put {resolved}")
    batch = "\n".join(lines) + "\n"
    command = ["sftp", "-P", str(destination.port)]
    auth_mode = normalize_auth_mode(destination)
    if auth_mode == "key" and destination.key_path:
        command.extend(["-i", destination.key_path])
    if auth_mode == "password":
        command.extend(["-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no"])
    command.extend(["-b", "-", destination.target()])
    return command, batch


def transfer_payload(
    source_paths: Sequence[str],
    destination: SSHDestination,
    *,
    remote_path: str,
    transport: str = "rsync",
    timeout: int = 1200,
    runner: Any = subprocess.run,
) -> Dict[str, Any]:
    if not source_paths:
        raise ValueError("At least one source path is required")

    resolved_transport = transport.lower().strip()
    if resolved_transport in {"", "auto", "scp"}:
        resolved_transport = "sftp" if normalize_remote_system(destination.target_system) == "windows" else "rsync"
    if resolved_transport == "rsync" and not shutil.which("rsync"):
        resolved_transport = "sftp"

    if resolved_transport == "rsync":
        command = build_rsync_command(source_paths, destination, remote_path=remote_path)
        command, env, interactive_password = _wrap_command_with_auth(
            command,
            destination,
            allow_interactive_password=True,
        )
        if interactive_password:
            result = runner(command, text=True, check=False, timeout=timeout, env=env)
        else:
            result = runner(command, capture_output=True, text=True, check=False, timeout=timeout, env=env)
    elif resolved_transport == "sftp":
        command, batch = build_sftp_command(source_paths, destination, remote_path=remote_path)
        command, env, interactive_password = _wrap_command_with_auth(
            command,
            destination,
            allow_interactive_password=True,
        )
        if interactive_password:
            batch_fd, batch_name = tempfile.mkstemp(prefix="omni-sftp-", suffix=".batch")
            os.close(batch_fd)
            batch_path = Path(batch_name)
            try:
                batch_path.write_text(batch, encoding="utf-8")
                command_with_batch = [str(batch_path) if token == "-" else token for token in command]
                result = runner(command_with_batch, text=True, check=False, timeout=timeout, env=env)
                command = command_with_batch
            finally:
                batch_path.unlink(missing_ok=True)
        else:
            result = runner(command, input=batch, capture_output=True, text=True, check=False, timeout=timeout, env=env)
    else:
        raise ValueError(f"Unsupported transport: {transport}")

    return {
        "success": result.returncode == 0,
        "transport": resolved_transport,
        "command": command,
        "stdout": str(getattr(result, "stdout", "") or "").strip(),
        "stderr": str(getattr(result, "stderr", "") or "").strip(),
    }

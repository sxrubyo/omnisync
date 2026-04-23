#!/usr/bin/env python3
from __future__ import annotations

import posixpath
import shlex
import socket
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

try:  # pragma: no cover - exercised through runtime and integration tests
    import paramiko
except ModuleNotFoundError:  # pragma: no cover - handled at runtime
    paramiko = None


@dataclass(frozen=True)
class SSHDestination:
    host: str
    user: str
    port: int = 22
    key_path: str = ""
    auth_mode: str = "password"
    password: str | None = None
    target_system: str = "auto"

    def target(self) -> str:
        return f"{self.user}@{self.host}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


REMOTE_SYSTEM_ALIASES = {
    "": "auto",
    "auto": "auto",
    "posix": "posix",
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
    if destination.password is not None:
        return "password"
    if destination.key_path:
        return "key"
    mode = str(destination.auth_mode or "").strip().lower()
    return mode if mode in {"password", "key"} else "password"


def _require_paramiko():
    if paramiko is None:
        raise RuntimeError(
            "Paramiko no está instalado. Ejecuta `python3 -m pip install paramiko` "
            "o reinstala OmniSync para habilitar `omni connect`."
        )
    return paramiko


def parse_remote_probe_output(raw: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "system": "unknown",
        "package_manager": "unknown",
        "home_entries": 0,
        "git_repos": 0,
        "package_count": 0,
        "fresh_server": False,
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
        elif key == "fresh_server":
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
"""


def build_windows_probe_script() -> str:
    script = (
        "$ErrorActionPreference='SilentlyContinue'; "
        "$homePath=$HOME; "
        "$pkg='unknown'; "
        "foreach($candidate in @('winget','choco','scoop')){ if(Get-Command $candidate -ErrorAction SilentlyContinue){ $pkg=$candidate; break } } "
        "$homeEntries=0; if($homePath -and (Test-Path $homePath)){ $homeEntries=(Get-ChildItem -LiteralPath $homePath -Force -ErrorAction SilentlyContinue | Measure-Object).Count }; "
        "$gitRepos=0; if($homePath -and (Test-Path $homePath)){ $gitRepos=(Get-ChildItem -LiteralPath $homePath -Directory -Filter '.git' -Recurse -ErrorAction SilentlyContinue | Measure-Object).Count }; "
        "$packageCount=0; "
        "$fresh='false'; if(($homeEntries -le 6) -and ($gitRepos -eq 0)){ $fresh='true' }; "
        "Write-Output ('system=Windows'); "
        "Write-Output ('package_manager=' + $pkg); "
        "Write-Output ('home=' + $homePath); "
        "Write-Output ('home_entries=' + $homeEntries); "
        "Write-Output ('git_repos=' + $gitRepos); "
        "Write-Output ('package_count=' + $packageCount); "
        "Write-Output ('fresh_server=' + $fresh)"
    )
    return f"powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command {shlex.quote(script)}"


def _connect_client(
    destination: SSHDestination,
    *,
    timeout: int,
    client_factory: Any = None,
):
    lib = _require_paramiko()
    client = client_factory() if client_factory else lib.SSHClient()
    client.set_missing_host_key_policy(lib.AutoAddPolicy())

    connect_kwargs: Dict[str, Any] = {
        "hostname": destination.host,
        "port": int(destination.port or 22),
        "username": destination.user,
        "timeout": timeout,
        "banner_timeout": timeout,
        "auth_timeout": timeout,
    }

    if destination.password is not None:
        connect_kwargs["password"] = destination.password
        connect_kwargs["look_for_keys"] = False
        connect_kwargs["allow_agent"] = False
    else:
        connect_kwargs["look_for_keys"] = True
        connect_kwargs["allow_agent"] = True
        if destination.key_path:
            connect_kwargs["key_filename"] = destination.key_path

    preflight_timeout = max(2, min(int(timeout or 10), 6))
    try:
        with socket.create_connection(
            (destination.host, int(destination.port or 22)),
            timeout=preflight_timeout,
        ):
            pass
    except TimeoutError as exc:
        raise RuntimeError(
            f"No pude abrir TCP hacia {destination.host}:{destination.port} en {preflight_timeout}s. "
            "El host no responde desde esta red."
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"No pude abrir TCP hacia {destination.host}:{destination.port}: {exc}"
        ) from exc

    client.connect(**connect_kwargs)
    return client


def _read_stream(stream: Any) -> str:
    payload = stream.read()
    if isinstance(payload, bytes):
        return payload.decode("utf-8", errors="replace")
    return str(payload or "")


def _run_remote_command(client: Any, command: str, *, timeout: int) -> tuple[int, str, str]:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    exit_status = stdout.channel.recv_exit_status()
    return exit_status, _read_stream(stdout), _read_stream(stderr)


def probe_remote_host(
    destination: SSHDestination,
    *,
    timeout: int = 30,
    client_factory: Any = None,
) -> Dict[str, Any]:
    system_hint = normalize_remote_system(destination.target_system)
    attempts = [system_hint] if system_hint != "auto" else ["posix", "windows"]
    errors: list[str] = []
    client = _connect_client(destination, timeout=timeout, client_factory=client_factory)
    try:
        for attempt in attempts:
            command = (
                f"sh -lc {shlex.quote(build_posix_probe_script())}"
                if attempt == "posix"
                else build_windows_probe_script()
            )
            status, stdout, stderr = _run_remote_command(client, command, timeout=timeout)
            if status == 0:
                payload = parse_remote_probe_output(stdout)
                payload["system_family"] = attempt
                return payload
            errors.append(f"{attempt}: {(stderr or stdout or 'SSH probe failed').strip()}")
    finally:
        client.close()

    raise RuntimeError(" | ".join(errors) if errors else "SSH probe failed")


def _resolve_remote_path(sftp: Any, remote_path: str) -> str:
    requested = str(remote_path or "").strip()
    home = str(sftp.normalize("."))
    if not requested or requested == "~":
        return home
    if requested.startswith("~/"):
        return posixpath.join(home, requested[2:])
    return requested


def _mkdir_p(sftp: Any, remote_dir: str) -> None:
    parts: list[str] = []
    current = remote_dir
    while current and current not in {"/", "."}:
        parts.append(current)
        current = posixpath.dirname(current)
        if current == parts[-1]:
            break
    for path in reversed(parts):
        try:
            sftp.stat(path)
        except IOError:
            sftp.mkdir(path)


def _put_file(sftp: Any, source: Path, remote_dir: str) -> None:
    _mkdir_p(sftp, remote_dir)
    remote_file = posixpath.join(remote_dir, source.name)
    sftp.put(str(source), remote_file)
    try:
        sftp.chmod(remote_file, stat.S_IMODE(source.stat().st_mode))
    except IOError:
        pass


def _put_path(sftp: Any, source: Path, remote_root: str) -> None:
    if source.is_dir():
        remote_dir = posixpath.join(remote_root, source.name)
        _mkdir_p(sftp, remote_dir)
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            _put_path(sftp, child, remote_dir)
        return
    _put_file(sftp, source, remote_root)


def build_rsync_command(
    source_paths: Sequence[str],
    destination: SSHDestination,
    *,
    remote_path: str,
) -> List[str]:
    return [
        "paramiko",
        "sftp",
        destination.target(),
        remote_path,
        *list(source_paths),
    ]


def build_sftp_command(
    source_paths: Sequence[str],
    destination: SSHDestination,
    *,
    remote_path: str,
) -> tuple[List[str], str]:
    return build_rsync_command(source_paths, destination, remote_path=remote_path), ""


def transfer_payload(
    source_paths: Sequence[str],
    destination: SSHDestination,
    *,
    remote_path: str,
    transport: str = "sftp",
    timeout: int = 1200,
    client_factory: Any = None,
) -> Dict[str, Any]:
    if not source_paths:
        raise ValueError("At least one source path is required")

    client = _connect_client(destination, timeout=timeout, client_factory=client_factory)
    uploaded: List[str] = []
    try:
        sftp = client.open_sftp()
        resolved_remote_root = _resolve_remote_path(sftp, remote_path)
        _mkdir_p(sftp, resolved_remote_root)
        for raw_source in source_paths:
            source = Path(raw_source).expanduser().resolve()
            if not source.exists():
                raise FileNotFoundError(f"Source path not found: {source}")
            _put_path(sftp, source, resolved_remote_root)
            uploaded.append(source.name)
        sftp.close()
    finally:
        client.close()

    return {
        "success": True,
        "transport": "sftp",
        "command": ["paramiko", "sftp", destination.target(), remote_path],
        "stdout": "\n".join(uploaded),
        "stderr": "",
        "remote_path": remote_path,
    }

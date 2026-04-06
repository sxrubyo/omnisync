#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Mapping


WINDOWS_PACKAGE_MANAGERS = ("winget", "choco", "scoop")
MAC_PACKAGE_MANAGERS = ("brew",)
LINUX_PACKAGE_MANAGERS = ("apt-get", "apt", "dnf", "yum", "pacman", "apk", "zypper")


@dataclass(frozen=True)
class PlatformInfo:
    system: str
    release: str
    version: str
    machine: str
    shell: str
    shell_family: str
    package_manager: str
    interactive: bool
    home: str
    terminal: str

    def to_dict(self) -> dict[str, str | bool]:
        return asdict(self)


def _basename(path_value: str | None) -> str:
    if not path_value:
        return ""
    return Path(path_value).name


def detect_system(system_fn: Callable[[], str] | None = None) -> str:
    probe = system_fn or platform.system
    return (probe() or "unknown").strip().lower()


def detect_shell(env: Mapping[str, str] | None = None, system: str | None = None) -> str:
    data = env or os.environ
    system_name = (system or detect_system()).lower()

    candidates = [
        data.get("OMNI_SHELL"),
        data.get("SHELL"),
        data.get("COMSPEC"),
        data.get("PSModulePath") and "powershell",
        data.get("POWERSHELL_DISTRIBUTION_CHANNEL") and "pwsh",
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            name = _basename(candidate)
            if name:
                return name.lower()

    if system_name == "windows":
        return "powershell"
    if system_name == "darwin":
        return "zsh"
    return "bash"


def detect_shell_family(shell_name: str) -> str:
    shell = (shell_name or "").lower()
    if shell in {"powershell", "pwsh", "powershell.exe", "pwsh.exe"}:
        return "powershell"
    if shell in {"bash", "zsh", "sh", "dash", "fish"}:
        return "posix"
    if shell in {"cmd", "cmd.exe"}:
        return "cmd"
    return "unknown"


def detect_package_manager(
    system: str | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> str:
    system_name = (system or detect_system()).lower()

    if system_name == "windows":
        candidates = WINDOWS_PACKAGE_MANAGERS
    elif system_name == "darwin":
        candidates = MAC_PACKAGE_MANAGERS
    else:
        candidates = LINUX_PACKAGE_MANAGERS

    for candidate in candidates:
        if which(candidate):
            return candidate
    return "unknown"


def is_non_interactive(env: Mapping[str, str] | None = None) -> bool:
    data = env or os.environ
    truthy = {"1", "true", "yes", "on"}
    if (data.get("OMNI_ASSUME_YES") or "").strip().lower() in truthy:
        return True
    if (data.get("CI") or "").strip().lower() in truthy:
        return True
    return False


def detect_platform_info(
    env: Mapping[str, str] | None = None,
    *,
    system_fn: Callable[[], str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> PlatformInfo:
    data = env or os.environ
    system_name = detect_system(system_fn)
    shell = detect_shell(data, system_name)
    shell_family = detect_shell_family(shell)
    package_manager = detect_package_manager(system_name, which=which)
    return PlatformInfo(
        system=system_name,
        release=platform.release(),
        version=platform.version(),
        machine=platform.machine(),
        shell=shell,
        shell_family=shell_family,
        package_manager=package_manager,
        interactive=not is_non_interactive(data),
        home=str(Path.home()),
        terminal=(data.get("TERM") or "unknown").lower(),
    )

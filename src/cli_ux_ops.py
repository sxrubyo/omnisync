#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Any, Dict

from platform_ops import detect_platform_info

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except Exception:  # pragma: no cover - fallback only
    Console = None
    Panel = None
    Table = None
    Text = None


OMNI_ASCII = r"""
   ____  __  __ _   _ ___
  / __ \/  |/  /| \ | |_ _|
 / / / / /|_/ / |  \| || |
/ /_/ / /  / /  | |\  || |
\____/_/  /_/   |_| \_|___|
"""

HELP_STARBURST = [
    "              ·",
    "        ╲     │     ╱",
    "          ╲   │   ╱",
    "·  ────────── ✦ ──────────  ·",
    "          ╱   │   ╲",
    "        ╱     │     ╲",
    "              ·",
    "",
]


def _memory_snapshot() -> tuple[int, int]:
    system = platform.system().lower()
    if system == "linux":
        try:
            meminfo: Dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if ":" not in line:
                    continue
                key, raw = line.split(":", 1)
                value = int(raw.strip().split()[0])
                meminfo[key] = value
            total_mb = int(meminfo.get("MemTotal", 0) / 1024)
            available_mb = int(meminfo.get("MemAvailable", 0) / 1024)
            used_mb = max(total_mb - available_mb, 0)
            return total_mb, used_mb
        except Exception:
            return 0, 0

    if system == "darwin":
        try:
            import subprocess

            total_raw = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            vm_stat = subprocess.check_output(["vm_stat"], text=True)
            total_mb = int(int(total_raw) / (1024 * 1024))
            page_size = 4096
            free_pages = 0
            for line in vm_stat.splitlines():
                if "page size of" in line:
                    page_size = int(line.split("page size of", 1)[1].split()[0])
                if line.startswith(("Pages free", "Pages inactive", "Pages speculative")):
                    free_pages += int(line.split(":", 1)[1].strip().rstrip("."))
            free_mb = int((free_pages * page_size) / (1024 * 1024))
            used_mb = max(total_mb - free_mb, 0)
            return total_mb, used_mb
        except Exception:
            return 0, 0

    if system == "windows":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            total_mb = int(status.ullTotalPhys / (1024 * 1024))
            free_mb = int(status.ullAvailPhys / (1024 * 1024))
            used_mb = max(total_mb - free_mb, 0)
            return total_mb, used_mb
        except Exception:
            return 0, 0

    return 0, 0


def collect_host_snapshot() -> Dict[str, Any]:
    info = detect_platform_info()
    disk = shutil.disk_usage(str(Path.home()))
    total_mem_mb, used_mem_mb = _memory_snapshot()
    return {
        "system": info.system,
        "release": info.release,
        "shell": info.shell,
        "package_manager": info.package_manager,
        "cpu_cores": os.cpu_count() or 0,
        "memory_total_mb": total_mem_mb,
        "memory_used_mb": used_mem_mb,
        "disk_total_gb": round(disk.total / (1024**3), 1),
        "disk_free_gb": round(disk.free / (1024**3), 1),
        "home": info.home,
        "terminal": info.terminal,
    }


def _format_memory(snapshot: Dict[str, Any]) -> str:
    total = int(snapshot.get("memory_total_mb", 0) or 0)
    used = int(snapshot.get("memory_used_mb", 0) or 0)
    if not total:
        return "unknown"
    return f"{used}/{total} MB"


def render_command_header(
    title: str,
    subtitle: str = "",
    *,
    dry_run: bool = False,
    snapshot: Dict[str, Any] | None = None,
    console: Console | None = None,
) -> None:
    if Console is None or Panel is None or Table is None:
        mode = "DRY RUN" if dry_run else "LIVE"
        print(OMNI_ASCII)
        print(f"{title} · {mode}")
        if subtitle:
            print(subtitle)
        return

    active_console = console or Console()
    host = snapshot or collect_host_snapshot()

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column(style="white")
    table.add_row("Host", f"{host['system']} {host['release']}")
    table.add_row("Shell", str(host["shell"]))
    table.add_row("Pkg", str(host["package_manager"]))
    table.add_row("CPU", f"{host['cpu_cores']} cores")
    table.add_row("RAM", _format_memory(host))
    table.add_row("Disk", f"{host['disk_free_gb']} GB free / {host['disk_total_gb']} GB")

    body = Table.grid(expand=True)
    body.add_column(ratio=2)
    body.add_column(ratio=3)
    heading = Text(title, style="bold white")
    if dry_run:
        heading.append("  DRY RUN", style="bold yellow")
    subtitle_text = Text(subtitle or "Portable migration control plane", style="bright_black")
    body.add_row(Text(OMNI_ASCII, style="bold bright_blue"), table)
    panel = Panel.fit(
        body,
        title=heading,
        subtitle=subtitle_text,
        border_style="bright_blue",
        padding=(1, 2),
    )
    active_console.print(panel)


def _fit_cell(text: str, width: int) -> str:
    value = str(text or "")
    if len(value) <= width:
        return value.ljust(width)
    if width <= 1:
        return value[:width]
    return value[: width - 1] + "…"


def _build_surface_box_lines(title: str, rows: list[str], width: int = 76) -> list[str]:
    inner = max(24, width - 2)
    label = f" {title} "
    top = "╭" + label + "─" * max(0, inner - len(label)) + "╮"
    body = [f"│{_fit_cell(row, inner)}│" for row in rows]
    bottom = "╰" + "─" * inner + "╯"
    return [top] + body + [bottom]


def build_help_surface_lines(
    snapshot: Dict[str, Any],
    tips: list[str],
    *,
    version: str = "",
    codename: str = "",
    tagline: str = "Automation at scale.",
    edition: str = "OmniSync · by Black Boss",
) -> list[str]:
    host = str(snapshot.get("system", "unknown"))
    release = str(snapshot.get("release", "unknown"))
    shell = str(snapshot.get("shell", "unknown"))
    package_manager = str(snapshot.get("package_manager", "unknown"))
    cpu_cores = int(snapshot.get("cpu_cores", 0) or 0)
    memory = _format_memory(snapshot)
    disk = f"{snapshot.get('disk_free_gb', '0')} GB free / {snapshot.get('disk_total_gb', '0')} GB"
    version_line = f"         ·  v{version} {codename}  ·".rstrip() if version or codename else "         ·  Omni  ·"

    left_lines = HELP_STARBURST + [
        "         O  M  N  I",
        version_line,
        "",
        f"  {tagline}",
        f"  ✦ {edition}",
        "  ──────────────────────────────────────────────────────────────",
    ]

    box_rows = [
        f"Host: {host} {release}",
        f"Shell: {shell}",
        f"Pkg: {package_manager}",
        f"CPU: {cpu_cores} cores",
        f"RAM: {memory}",
        f"Disk: {disk}",
        "",
    ] + list(tips)
    right_lines = _build_surface_box_lines("OMNI CONTROL SURFACE", box_rows, width=78)

    left_width = max(len(line) for line in left_lines)
    right_offset = len(HELP_STARBURST)
    total_lines = max(len(left_lines), right_offset + len(right_lines))
    rendered: list[str] = []
    for idx in range(total_lines):
        left = left_lines[idx] if idx < len(left_lines) else ""
        right_idx = idx - right_offset
        right = right_lines[right_idx] if 0 <= right_idx < len(right_lines) else ""
        if right:
            rendered.append(left.ljust(left_width + 4) + right)
        else:
            rendered.append(left)
    return rendered


def render_help_surface(
    snapshot: Dict[str, Any],
    tips: list[str],
    *,
    version: str = "",
    codename: str = "",
    tagline: str = "Automation at scale.",
    edition: str = "OmniSync · by Black Boss",
) -> None:
    for line in build_help_surface_lines(
        snapshot,
        tips,
        version=version,
        codename=codename,
        tagline=tagline,
        edition=edition,
    ):
        print(f"  {line}".rstrip())


def build_guided_start_surface_lines(
    snapshot: Dict[str, Any],
    tips: list[str],
    *,
    version: str = "",
    codename: str = "",
    tagline: str = "Move a machine without rebuilding it by hand.",
    edition: str = "OmniSync · by Black Boss",
) -> list[str]:
    host = str(snapshot.get("system", "unknown"))
    release = str(snapshot.get("release", "unknown"))
    shell = str(snapshot.get("shell", "unknown"))
    package_manager = str(snapshot.get("package_manager", "unknown"))
    cpu_cores = int(snapshot.get("cpu_cores", 0) or 0)
    memory = _format_memory(snapshot)
    disk = f"{snapshot.get('disk_free_gb', '0')} GB free / {snapshot.get('disk_total_gb', '0')} GB"
    version_line = f"         ·  v{version} {codename}  ·".rstrip() if version or codename else "         ·  Omni  ·"

    left_lines = HELP_STARBURST + [
        "         O  M  N  I",
        version_line,
        "",
        f"  {tagline}",
        f"  ✦ {edition}",
        "  ──────────────────────────────────────────────────────────────",
    ]

    guided_rows = [
        f"Host: {host} {release}  ·  Shell: {shell}",
        f"Pkg: {package_manager}  ·  CPU: {cpu_cores} cores",
        f"RAM: {memory}  ·  Disk: {disk}",
        "",
        "Detect the host, choose the migration path",
        "and keep the operator in control.",
    ]
    right_lines = (
        _build_surface_box_lines("Omni Guided Start", guided_rows, width=78)
        + [""]
        + _build_surface_box_lines("OMNI CONTROL SURFACE", tips, width=78)
    )

    left_width = max(len(line) for line in left_lines)
    total_lines = max(len(left_lines), len(right_lines))
    rendered: list[str] = []
    for idx in range(total_lines):
        left = left_lines[idx] if idx < len(left_lines) else ""
        right = right_lines[idx] if idx < len(right_lines) else ""
        if right:
            rendered.append(left.ljust(left_width + 4) + right)
        else:
            rendered.append(left)
    return rendered


def render_guided_start_surface(
    snapshot: Dict[str, Any],
    tips: list[str],
    *,
    version: str = "",
    codename: str = "",
    tagline: str = "Move a machine without rebuilding it by hand.",
    edition: str = "OmniSync · by Black Boss",
) -> None:
    for line in build_guided_start_surface_lines(
        snapshot,
        tips,
        version=version,
        codename=codename,
        tagline=tagline,
        edition=edition,
    ):
        print(f"  {line}".rstrip())


def render_human_error(
    message: str,
    *,
    suggestion: str = "",
    console: Console | None = None,
) -> None:
    if Console is None or Panel is None:
        print(f"ERROR: {message}")
        if suggestion:
            print(f"Sugerencia: {suggestion}")
        return

    active_console = console or Console()
    detail = f"{message}\n\n[bold cyan]Sugerencia:[/bold cyan] {suggestion}" if suggestion else message
    active_console.print(Panel(detail, title="Omni Error", border_style="red", padding=(1, 2)))

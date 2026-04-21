#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import shutil
import sys
import textwrap
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

OMNI_COMMAND_SHIP = [
    "           .       *",
    "        .-\"\"\"-._.-\"\"\"-.",
    "     .-'___./___\\.___`-.",
    "     \\_  _/  /_\\  \\_  _/",
    "       `-.\\__/ \\__/.-'",
    "          /_   _\\",
    "        .'/_| |_\\'.",
    "      *      .      ",
]

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

ANSI_GOLD = "\033[38;5;220m"
ANSI_FAINT = "\033[38;5;244m"
ANSI_RESET = "\033[0m"


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
        print("\n".join(build_command_ship_lines()))
        print(f"{title} · {mode}")
        if subtitle:
            print(subtitle)
        return

    active_console = console or Console()
    host = snapshot or collect_host_snapshot()

    snapshot = Table.grid(padding=(0, 1))
    snapshot.add_column(style="bold color(220)", justify="right", no_wrap=True)
    snapshot.add_column(style="white", no_wrap=True)
    snapshot.add_row("Host", f"{host['system']} {host['release']}")
    snapshot.add_row("Shell", str(host["shell"]))
    snapshot.add_row("Pkg", str(host["package_manager"]))
    snapshot.add_row("CPU", f"{host['cpu_cores']} cores")
    snapshot.add_row("RAM", _format_memory(host))
    snapshot.add_row("Disk", f"{host['disk_free_gb']} GB free / {host['disk_total_gb']} GB")

    body = Table.grid(padding=(0, 2))
    body.add_column(no_wrap=True)
    body.add_column(no_wrap=True)
    heading = Text(title, style="bold color(230)")
    if dry_run:
        heading.append("  DRY RUN", style="bold yellow")
    subtitle_text = Text(subtitle or "Portable migration control plane", style="color(246)")
    body.add_row(_build_command_ship_text(), snapshot)
    panel = Panel.fit(
        body,
        title=heading,
        subtitle=subtitle_text,
        border_style="color(220)",
        padding=(0, 1),
    )
    active_console.print(panel)


def build_command_ship_lines() -> list[str]:
    return list(OMNI_COMMAND_SHIP)


def _build_command_ship_text():
    if Text is None:
        return "\n".join(build_command_ship_lines())

    palette = [
        "color(244)",
        "color(220)",
        "bold color(222)",
        "bold color(230)",
        "color(222)",
        "color(220)",
        "color(214)",
        "color(244)",
    ]
    art = Text()
    for index, line in enumerate(build_command_ship_lines()):
        art.append(line, style=palette[min(index, len(palette) - 1)])
        if index < len(OMNI_COMMAND_SHIP) - 1:
            art.append("\n")
    return art


def _fit_cell(text: str, width: int) -> str:
    value = str(text or "")
    if len(value) <= width:
        return value.ljust(width)
    if width <= 1:
        return value[:width]
    return value[: width - 1] + "…"


def _expand_surface_rows(rows: list[str], inner: int) -> list[str]:
    expanded: list[str] = []
    for row in rows:
        value = str(row or "")
        if not value:
            expanded.append("")
            continue
        wrapped = textwrap.wrap(
            value,
            width=inner,
            break_long_words=False,
            break_on_hyphens=False,
        )
        expanded.extend(wrapped or [value[:inner]])
    return expanded


def _build_surface_box_lines(title: str, rows: list[str], width: int = 76) -> list[str]:
    inner = max(24, width - 2)
    label = f" {title} "
    top = "╭" + label + "─" * max(0, inner - len(label)) + "╮"
    body = [f"│{_fit_cell(row, inner)}│" for row in _expand_surface_rows(rows, inner)]
    bottom = "╰" + "─" * inner + "╯"
    return [top] + body + [bottom]


def _build_sectioned_surface_box_lines(
    title: str,
    sections: list[tuple[str, list[str]]],
    *,
    width: int = 76,
) -> list[str]:
    rows: list[str] = []
    for index, (heading, values) in enumerate(sections):
        if index:
            rows.append("")
        rows.append(heading)
        rows.extend(values)
    return _build_surface_box_lines(title, rows, width=width)


def _surface_box_width(snapshot: Dict[str, Any], *, default: int = 74) -> int:
    terminal_name = str(snapshot.get("terminal", "")).lower()
    compact_terminals = ("xterm", "screen", "tmux", "linux", "vt")
    if any(token in terminal_name for token in compact_terminals):
        return 66
    return default


def _merge_surface_columns(left_lines: list[str], right_lines: list[str], *, gap: int = 2) -> list[str]:
    left_width = max(len(line.rstrip()) for line in left_lines)
    total_lines = max(len(left_lines), len(right_lines))
    rendered: list[str] = []
    for idx in range(total_lines):
        left = left_lines[idx].rstrip() if idx < len(left_lines) else ""
        right = right_lines[idx] if idx < len(right_lines) else ""
        if right:
            rendered.append(left.ljust(left_width + gap) + right)
        else:
            rendered.append(left)
    return rendered


def _style_surface_line(line: str) -> str:
    if not getattr(sys.stdout, "isatty", lambda: False)():
        return line

    accent_tokens = (
        "·  ────────── ✦ ──────────  ·",
        "O  M  N  I",
        "✦ OmniSync · by Black Boss",
        "╭ ",
        "╰",
        "HOST SNAPSHOT",
        "QUICKSTART",
        "OPERATOR MODE",
        "OMNI CONTROL SURFACE",
        "OMNI START SURFACE",
    )
    muted_tokens = ("Host:", "Shell:", "Pkg:", "CPU:", "RAM:", "Disk:", "Mode:", "Scope:")

    if any(token in line for token in accent_tokens):
        return f"{ANSI_GOLD}{line}{ANSI_RESET}"
    if any(token in line for token in muted_tokens):
        return f"{ANSI_FAINT}{line}{ANSI_RESET}"
    return line


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
    ]

    right_lines = _build_sectioned_surface_box_lines(
        "OMNI CONTROL SURFACE",
        [
            (
                "HOST SNAPSHOT",
                [
                    f"Host: {host} {release}",
                    f"Shell: {shell}",
                    f"Pkg: {package_manager}",
                    f"CPU: {cpu_cores} cores",
                    f"RAM: {memory}",
                    f"Disk: {disk}",
                ],
            ),
            (
                "QUICKSTART",
                list(tips),
            ),
        ],
        width=_surface_box_width(snapshot, default=74),
    )
    return _merge_surface_columns(left_lines, right_lines, gap=2)


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
        print(f"  {_style_surface_line(line)}".rstrip())


def build_guided_start_surface_lines(
    snapshot: Dict[str, Any],
    tips: list[str],
    *,
    version: str = "",
    codename: str = "",
    mode: str = "guided",
    scope: str = "production-clean",
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
    ]

    right_lines = _build_sectioned_surface_box_lines(
        "OMNI START SURFACE",
        [
            (
                "HOST SNAPSHOT",
                [
                    f"Host: {host} {release}  ·  Shell: {shell}",
                    f"Pkg: {package_manager}  ·  CPU: {cpu_cores} cores",
                    f"RAM: {memory}  ·  Disk: {disk}",
                ],
            ),
            (
                "OPERATOR MODE",
                [
                    f"Mode: {mode}",
                    f"Scope: {scope}",
                ],
            ),
            (
                "QUICKSTART",
                list(tips),
            ),
        ],
        width=_surface_box_width(snapshot, default=70),
    )
    return _merge_surface_columns(left_lines, right_lines, gap=1)


def render_guided_start_surface(
    snapshot: Dict[str, Any],
    tips: list[str],
    *,
    version: str = "",
    codename: str = "",
    mode: str = "guided",
    scope: str = "production-clean",
    tagline: str = "Move a machine without rebuilding it by hand.",
    edition: str = "OmniSync · by Black Boss",
) -> None:
    for line in build_guided_start_surface_lines(
        snapshot,
        tips,
        version=version,
        codename=codename,
        mode=mode,
        scope=scope,
        tagline=tagline,
        edition=edition,
    ):
        print(f"  {_style_surface_line(line)}".rstrip())


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

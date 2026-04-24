#!/usr/bin/env python3
"""
OmniSync v2.1
Portable migration control plane.
Built by Black Boss.
"""

import sys
import os
import json
import time
import getpass
import threading
import random
import argparse
import subprocess
import shlex
import shutil
import platform
import socket
import textwrap
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
from pathlib import Path

from bundle_ops import (
    create_secrets_bundle,
    create_state_bundle,
    latest_or_explicit,
    restore_bundle,
)
from briefcase_ops import build_briefcase_manifest, build_restore_plan, build_restore_script
from agent_ops import env_has_value, get_provider, load_agent_config, provider_catalog, save_agent_config, upsert_env_value
from agent_skill_ops import sync_agent_integrations
from bridge_ops import (
    build_host_rewrite_context,
    load_capture_summary,
    summarize_bundle_pair,
    write_capture_summary,
)
from chat_ops import (
    build_chat_memory_prompt,
    chat_completion,
    clean_assistant_output,
    ensure_activation_prompt,
    default_chat_memory,
    load_chat_memory,
    load_chat_session,
    load_env_value,
    new_chat_session,
    parse_action_block,
    record_chat_turn,
    save_chat_memory,
    save_chat_session,
)
from cli_ux_ops import (
    collect_host_snapshot,
    render_command_header,
    render_guided_start_surface,
    render_help_surface,
    render_human_error,
)
from cleanup_ops import build_purge_plan, execute_purge
from connect_ops import (
    SSHDestination,
    build_reverse_tunnel_command,
    normalize_remote_system,
    probe_remote_host,
    transfer_payload,
    wait_for_tcp_port,
)
from full_inventory_ops import collect_full_inventory
from github_ops import (
    GitHubTarget,
    download_text,
    ensure_private_repo,
    gh_cli_token,
    github_identity,
    latest_briefcase_entry,
    list_directory,
    load_global_config,
    parse_repo_slug,
    put_file,
    save_global_config,
)
from guide_ops import build_guide_entries
from host_inventory import (
    DEFAULT_PROFILE,
    FULL_HOME_PROFILE,
    build_default_manifest,
    ensure_manifest,
    expand_path,
    human_size,
    load_manifest,
    save_manifest,
    scan_home,
)
from ip_rewrite_ops import apply_rewrite_plan, build_rewrite_plan, detect_host_identity, preview_rewrite_plan
from onboarding_ops import build_flow_options, normalize_flow_choice, should_accept_all
from platform_ops import detect_platform_info
from reconcile_ops import install_systemd_service, install_systemd_timer, reconcile_host
from watch_ops import capture_watch_snapshot, load_watch_snapshot, save_watch_snapshot, summarize_snapshot_diff
from runtime_inventory_ops import load_installed_inventory


APP_DIR = Path(__file__).resolve().parents[1]
ENV_OMNI_HOME = os.environ.get("OMNI_HOME", "").strip()
USE_ENV_PATHS = False
if ENV_OMNI_HOME:
    candidate_home = Path(ENV_OMNI_HOME).expanduser()
    parent_dir = candidate_home if candidate_home.exists() else candidate_home.parent
    if os.access(parent_dir, os.W_OK):
        OMNI_HOME = candidate_home.resolve()
        USE_ENV_PATHS = True
    else:
        OMNI_HOME = APP_DIR
else:
    OMNI_HOME = APP_DIR


def _path_override(env_name: str, default: Path) -> Path:
    if USE_ENV_PATHS:
        raw = os.environ.get(env_name, "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
    return default.resolve()


CONFIG_DIR = _path_override("OMNI_CONFIG_DIR", OMNI_HOME / "config")
STATE_DIR = _path_override("OMNI_STATE_DIR", OMNI_HOME / "data")
BACKUP_DIR = _path_override("OMNI_BACKUP_DIR", OMNI_HOME / "backups")
BUNDLE_DIR = _path_override("OMNI_BUNDLE_DIR", BACKUP_DIR / "host-bundles")
AUTO_BUNDLE_DIR = _path_override("OMNI_AUTO_BUNDLE_DIR", BACKUP_DIR / "auto-bundles")
LOG_DIR = _path_override("OMNI_LOG_DIR", OMNI_HOME / "logs")
WATCH_STATE_FILE = _path_override("OMNI_WATCH_STATE_FILE", STATE_DIR / "watch_snapshot.json")
ENV_FILE = _path_override("OMNI_ENV_FILE", OMNI_HOME / ".env")
AGENT_CONFIG_FILE = _path_override("OMNI_AGENT_CONFIG_FILE", CONFIG_DIR / "omni_agent.json")
AGENT_SKILL_DIR = _path_override("OMNI_AGENT_SKILL_DIR", Path.home() / ".omni" / "skills")
CHAT_SESSION_DIR = _path_override("OMNI_CHAT_SESSION_DIR", STATE_DIR / "chat")
AGENT_ACTIVATION_FILE = _path_override("OMNI_AGENT_ACTIVATION_FILE", CONFIG_DIR / "omni_agent_activation.txt")
GLOBAL_CONFIG_FILE = _path_override("OMNI_GLOBAL_CONFIG_FILE", Path.home() / ".omni" / "config.json")
TASKS_FILE = _path_override("OMNI_TASKS_FILE", OMNI_HOME / "tasks.json")
REPOS_FILE = _path_override("OMNI_REPOS_FILE", CONFIG_DIR / "repos.json")
SERVERS_FILE = _path_override("OMNI_SERVERS_FILE", CONFIG_DIR / "servers.json")
SYSTEM_MANIFEST_FILE = _path_override("OMNI_MANIFEST_FILE", CONFIG_DIR / "system_manifest.json")
EXPORT_DIR = _path_override("OMNI_EXPORT_DIR", OMNI_HOME / "exports")
CONTINUE_STATE_FILE = _path_override("OMNI_CONTINUE_STATE_FILE", STATE_DIR / "continue.json")
AUTO_BACKUP_ON_CHANGE = os.environ.get("OMNI_AUTO_BACKUP_ON_CHANGE", "1").strip().lower() in {"1", "true", "yes", "on"}
AUTO_BACKUP_KEEP = max(1, int(os.environ.get("OMNI_AUTO_BACKUP_KEEP", "5")))
WATCH_BACKUP_COOLDOWN = max(30, int(os.environ.get("OMNI_WATCH_BACKUP_COOLDOWN", "600")))
OMNI_DRY_RUN = os.environ.get("OMNI_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}
SUPPORTED_LANGUAGES = {"es": "Español", "en": "English"}


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            os.environ.setdefault(key, value)
    except Exception:
        pass


load_env_file(ENV_FILE)


def normalize_language(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("en"):
        return "en"
    return "es"


def split_host_and_port(raw_host: str, default_port: int = 22) -> tuple[str, int]:
    value = str(raw_host or "").strip()
    if not value:
        return "", int(default_port or 22)
    if value.startswith("[") and "]:" in value:
        host_part, port_part = value.rsplit("]:", 1)
        host_part = host_part[1:]
        if port_part.isdigit():
            return host_part, int(port_part)
    if value.count(":") == 1:
        host_part, port_part = value.rsplit(":", 1)
        if port_part.isdigit():
            return host_part, int(port_part)
    return value, int(default_port or 22)


def suggest_relay_host() -> str:
    env_host = str(os.environ.get("OMNI_RELAY_HOST", "") or "").strip()
    if env_host:
        return env_host
    fqdn = str(socket.getfqdn() or "").strip()
    if fqdn and fqdn not in {"localhost", "localhost.localdomain"}:
        return fqdn
    hostname = str(socket.gethostname() or "").strip()
    if hostname:
        return hostname
    return "relay-host"

# ══════════════════════════════════════════════════════════════════════════════
# PLATFORM COMPATIBILITY
# ══════════════════════════════════════════════════════════════════════════════

PLATFORM = platform.system().lower()
IS_WINDOWS = PLATFORM == "windows"
IS_MAC = PLATFORM == "darwin"
IS_LINUX = PLATFORM == "linux"

if IS_WINDOWS:
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

def get_terminal_size():
    try:
        return shutil.get_terminal_size()
    except Exception:
        return 80, 24

TERM_WIDTH, TERM_HEIGHT = get_terminal_size()

# ══════════════════════════════════════════════════════════════════════════════
# COLOR SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

def _detect_color_support():
    if os.environ.get("NO_COLOR"):
        return 0
    if os.environ.get("FORCE_COLOR"):
        return 256
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return 0
    term = os.environ.get("TERM", "").lower()
    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        return 16777216
    if "256" in term or colorterm:
        return 256
    if term in ("xterm", "screen", "vt100", "ansi"):
        return 16
    if IS_WINDOWS:
        return 256
    return 16

COLOR_DEPTH = _detect_color_support()
USE_COLOR = COLOR_DEPTH > 0
OMNI_DEBUG = os.environ.get("OMNI_DEBUG", "").lower() in ("1", "true", "yes")
OMNI_VERBOSE = os.environ.get("OMNI_VERBOSE", "").lower() in ("1", "true", "yes")

def _e(code):
    return "\033[" + code + "m" if USE_COLOR else ""

def _rgb(r, g, b):
    if COLOR_DEPTH >= 16777216:
        return f"\033[38;2;{r};{g};{b}m"
    return _e(f"38;5;{16 + 36*(r//51) + 6*(g//51) + (b//51)}")

class C:
    W = "\033[38;5;15m"
    PRIMARY = _rgb(114, 149, 255)
    G1 = "\033[38;5;255m"
    G2 = "\033[38;5;250m"
    G3 = "\033[38;5;244m"
    ASH = "\033[38;5;240m"
    R = "\033[0m"
    BOLD = _e("1")
    DIM = _e("2")
    ITALIC = _e("3")
    UNDER = _e("4")
    GRN = _e("38;5;108")
    YLW = _e("38;5;179")
    RED = _e("38;5;167")
    ORG = _e("38;5;173")
    MGN = _e("38;5;139")
    CYN = _e("38;5;109")
    PNK = _e("38;5;174")
    GLD = _e("38;5;179")
    GLD_BRIGHT = _e("38;5;180")
    GLD_MATTE = _e("38;5;137")
    B6 = _e("38;5;67")

def q(color, text, bold=False, dim=False, italic=False, underline=False):
    styles = ""
    if bold: styles += C.BOLD
    if dim: styles += C.DIM
    if italic: styles += C.ITALIC
    if underline: styles += C.UNDER
    return styles + color + str(text) + C.R

def _render_reset():
    sys.stdout.write("\033[0m")
    if USE_COLOR:
        sys.stdout.write(_e("38;5;15"))

def debug(msg):
    if OMNI_DEBUG:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:12]
        print("  " + q(C.G3, f"[{ts}]") + " " + q(C.G2, str(msg)))

def verbose(msg):
    if OMNI_VERBOSE or OMNI_DEBUG:
        print("  " + q(C.G3, "[verbose]") + " " + q(C.G2, str(msg)))

# ══════════════════════════════════════════════════════════════════════════════
# BRANDING
# ══════════════════════════════════════════════════════════════════════════════

OMNI_VERSION = "2.1.5"
OMNI_BUILD = "2026.03.portable"
OMNI_CODENAME = "Titan"

_TAGLINES = [
    "Portable migration, without drama.",
    "Your system, portable.",
    "Automation at scale.",
    "Move a machine without rebuilding it by hand.",
    "System state, packed cleanly.",
    "Every process, accounted for.",
    "Restore the host you actually had.",
    "Keep the operator in control.",
]

ALIASES = {
    "s": "status", "f": "fix", "w": "watch", "c": "check", "h": "help",
    "?": "help", "r": "restart", "l": "logs", "t": "transfer", "b": "backup",
    "m": "monitor", "cfg": "config", "v": "version", "st": "stats",
    "proc": "processes", "repo": "repos", "up": "update", "cl": "clean",
    "i": "init",
    "tr": "transfer",
    "bc": "briefcase",
    "rp": "restore-plan",
    "g": "guide",
    "ch": "chat",
    "commands": "help",
    "resume": "continue",
    "cont": "continue",
}

# ══════════════════════════════════════════════════════════════════════════════
# UI PRIMITIVES
# ══════════════════════════════════════════════════════════════════════════════

def ghost_write(text, color=None, delay=0.02, bold=False, newline=True, prefix="  "):
    c = color or C.G1
    if prefix:
        sys.stdout.write(prefix)
    if bold:
        sys.stdout.write(C.BOLD)
    sys.stdout.write(c)
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        if char in ".!?":
            time.sleep(delay * 8)
        elif char in ",;:":
            time.sleep(delay * 4)
        elif char == " ":
            time.sleep(delay * 1.5)
        else:
            time.sleep(delay + random.uniform(-0.005, 0.01))
    sys.stdout.write(C.R)
    if newline:
        print()

def ok(msg, prefix="  "):
    _render_reset()
    print(f"{prefix}" + q(C.GRN, "✓") + "  " + q(C.W, msg))

def fail(msg, prefix="  "):
    _render_reset()
    print(f"{prefix}" + q(C.RED, "✗") + "  " + q(C.W, msg))

def warn(msg, prefix="  "):
    _render_reset()
    print(f"{prefix}" + q(C.YLW, "!") + "  " + q(C.W, msg))

def info(msg, prefix="  "):
    _render_reset()
    print(f"{prefix}" + q(C.CYN, "ℹ") + "  " + q(C.W, msg))

def hint(msg, prefix="  "):
    _render_reset()
    print(f"{prefix}" + q(C.G3, msg))

def dim(msg, prefix="       "):
    _render_reset()
    print(f"{prefix}" + q(C.G3, msg))

def hr(char="─", width=62, color=None):
    _render_reset()
    print("  " + q(color or C.G3, char * width))

def nl(count=1):
    for _ in range(count):
        print()

def kv(key, value, color=None, key_width=22, prefix="  "):
    _render_reset()
    print(f"{prefix}" + q(C.G3, key.rjust(key_width)) + "  " + q(color or C.W, value))

def kvb(key, value, color=None, prefix="  "):
    _render_reset()
    print(f"{prefix}" + q(C.G3, key) + "  " + q(color or C.GRN, value))

def bullet(text, color=None, bullet_char="·", prefix="  ", bold=False):
    _render_reset()
    print(f"{prefix}" + q(color or C.G3, bullet_char) + "  " + q(C.W, text, bold=bold))

def section(title, subtitle="", width=62):
    _render_reset()
    print()
    print("  " + q(C.G3, "─" * width))
    print("  " + q(C.W, title, bold=True))
    if subtitle:
        print("  " + q(C.G3, subtitle))
    print("  " + q(C.G3, "─" * width))
    print()


def box(title: str, lines: List[str], width: int = 72, accent: Optional[str] = None):
    _render_reset()
    color = accent or C.GLD_BRIGHT
    inner_width = max(24, width - 4)
    top = "╭" + "─" * (width - 2) + "╮"
    bottom = "╰" + "─" * (width - 2) + "╯"
    heading = f" {title} ".strip()

    print("  " + q(C.G3, top))
    print("  " + q(C.G3, "│") + q(color, heading, bold=True).ljust(inner_width + len(color) + len(C.R)) + q(C.G3, "│"))
    print("  " + q(C.G3, "├" + "─" * (width - 2) + "┤"))
    wrapped_lines: List[str] = []
    for line in lines:
        wrapped_lines.extend(textwrap.wrap(line, width=inner_width) or [""])
    for line in wrapped_lines:
        visible = line.ljust(inner_width)
        print("  " + q(C.G3, "│") + q(C.W, visible) + q(C.G3, "│"))
    print("  " + q(C.G3, bottom))


def _is_tty() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _should_buffer_menu_digits(option_count: int) -> bool:
    return int(option_count or 0) >= 10


def _apply_menu_digit_input(buffer: str, key: str, option_count: int) -> tuple[str, int | None]:
    if not str(key).isdigit():
        return buffer, None
    if not _should_buffer_menu_digits(option_count):
        selection = int(key) - 1
        if 0 <= selection < option_count:
            return "", selection
        return "", None
    return buffer + key, None


def _resolve_buffered_menu_selection(buffer: str, current: int, option_count: int) -> int:
    raw = str(buffer or "").strip()
    if not raw.isdigit():
        return current
    selection = int(raw) - 1
    if 0 <= selection < option_count:
        return selection
    return current


def select_menu(
    options: List[str],
    *,
    title: str = "",
    descriptions: Optional[List[str]] = None,
    icons: Optional[List[str]] = None,
    default: int = 0,
    show_index: bool = False,
    page_size: int = 10,
    footer: str = "",
) -> int:
    if not options:
        return 0

    descriptions = descriptions or []
    icons = icons or []
    default = max(0, min(default, len(options) - 1))

    def fallback() -> int:
        if title:
            print(f"\n  {q(C.G2, title)}")
        print(f"  {q(C.G3, 'Puedes moverte con ↑/↓ si el terminal lo soporta, o escribir el número.')}")
        for idx, option in enumerate(options):
            num = q(C.PRIMARY, f"{idx + 1}.", bold=True)
            icon = f"{icons[idx]}  " if idx < len(icons) and icons[idx] else ""
            current = q(C.B6, "•", bold=True) + "  " if idx == default else "   "
            color = C.W if idx == default else C.G2
            print(f"{current}{num}  {icon}{q(color, option, bold=idx == default)}")
            if idx < len(descriptions) and descriptions[idx]:
                print("       " + q(C.G3, descriptions[idx]))
        try:
            sys.stdout.write(f"\n  {q(C.PRIMARY, '→')}  ")
            sys.stdout.flush()
            answer = input("").strip()
        except EOFError:
            print()
            return default
        except KeyboardInterrupt:
            print()
            raise
        if answer.isdigit():
            numeric = int(answer) - 1
            if 0 <= numeric < len(options):
                return numeric
        return default

    if not _is_tty():
        return fallback()

    current = default
    scroll_offset = 0
    digit_buffer = ""
    rendered_line_count = 0

    def footer_text() -> str:
        base = footer or "↑/↓ seleccionar · j/k mover · Enter confirmar · número salto directo"
        return f"{base} · salto: {digit_buffer}" if digit_buffer else base

    def draw(first: bool = False) -> None:
        nonlocal rendered_line_count, scroll_offset
        if current < scroll_offset:
            scroll_offset = current
        elif current >= scroll_offset + page_size:
            scroll_offset = current - page_size + 1

        visible = range(scroll_offset, min(len(options), scroll_offset + page_size))
        out: List[str] = []
        if not first and rendered_line_count:
            out.append(f"\033[{rendered_line_count}F")
            for _ in range(rendered_line_count):
                out.append("\033[2K")
                out.append("\033[1E")
            out.append(f"\033[{rendered_line_count}F")

        line_count = 0
        if title:
            out.append("\n  " + q(C.G2, title) + "\n")
            out.append("  " + q(C.G3, "Usa ↑/↓ y Enter. También puedes saltar con un número.") + "\n\n")
            line_count += 4

        for idx in visible:
            prefix = q(C.PRIMARY, f"{idx + 1}.", bold=True) + "  " if show_index else ""
            icon = f"{icons[idx]}  " if idx < len(icons) and icons[idx] else ""
            if idx == current:
                out.append("  " + q(C.B6, "▸", bold=True) + "  " + prefix + icon + q(C.W, options[idx], bold=True) + "\n")
            else:
                out.append("     " + prefix + icon + q(C.G2, options[idx]) + "\n")
            line_count += 1

            if idx < len(descriptions) and descriptions[idx]:
                out.append("       " + q(C.G2 if idx == current else C.G3, descriptions[idx]) + "\n")
                line_count += 1

        if scroll_offset > 0:
            out.append("       " + q(C.G3, "↑ hay más arriba") + "\n")
            line_count += 1
        if scroll_offset + page_size < len(options):
            out.append("       " + q(C.G3, "↓ hay más abajo") + "\n")
            line_count += 1

        out.append("\n")
        out.append("  " + q(C.G3, footer_text()) + "\n")
        line_count += 2
        rendered_line_count = line_count
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    if IS_WINDOWS:
        import msvcrt

        draw(first=True)
        while True:
            ch = msvcrt.getch()
            if ch in (b"\r", b"\n"):
                if digit_buffer:
                    return max(0, min(int(digit_buffer) - 1, len(options) - 1))
                return current
            if ch == b"\x03":
                raise KeyboardInterrupt
            if ch in (b"\x00", b"\xe0"):
                ch2 = msvcrt.getch()
                if ch2 == b"H" and current > 0:
                    digit_buffer = ""
                    current -= 1
                    draw()
                elif ch2 == b"P" and current < len(options) - 1:
                    digit_buffer = ""
                    current += 1
                    draw()
                continue
            try:
                key = ch.decode(errors="ignore")
            except Exception:
                continue
            if key in ("k", "K") and current > 0:
                digit_buffer = ""
                current -= 1
                draw()
            elif key in ("j", "J") and current < len(options) - 1:
                digit_buffer = ""
                current += 1
                draw()
            elif key.isdigit():
                digit_buffer, selected, should_return = apply_digit_jump(digit_buffer, key, len(options))
                if selected is not None:
                    current = selected
                    draw()
                if should_return:
                    return current
            elif key in ("\b", "\x7f"):
                if digit_buffer:
                    digit_buffer = digit_buffer[:-1]
                    draw()
    else:
        import os as _os
        import select as _sel
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        def read_key() -> str:
            tty.setraw(fd)
            try:
                b = _os.read(fd, 1)
                if b in (b"\r", b"\n"):
                    termios.tcflush(fd, termios.TCIFLUSH)
                    return "\r"
                if b == b"\x03":
                    return "\x03"
                if b == b"\x1b":
                    ready, _, _ = _sel.select([fd], [], [], 0.05)
                    if not ready:
                        return "\x1b"
                    b2 = _os.read(fd, 1)
                    if b2 == b"[":
                        ready2, _, _ = _sel.select([fd], [], [], 0.05)
                        if not ready2:
                            return "["
                        b3 = _os.read(fd, 1)
                        if b3 == b"A":
                            return "UP"
                        if b3 == b"B":
                            return "DOWN"
                        return b3.decode(errors="ignore")
                    return b2.decode(errors="ignore")
                return b.decode(errors="ignore")
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

        draw(first=True)
        while True:
            key = read_key()
            if key == "\r":
                if digit_buffer:
                    return max(0, min(int(digit_buffer) - 1, len(options) - 1))
                return current
            if key == "\x03":
                raise KeyboardInterrupt
            if key in ("UP", "k", "K") and current > 0:
                digit_buffer = ""
                current -= 1
                draw()
            elif key in ("DOWN", "j", "J") and current < len(options) - 1:
                digit_buffer = ""
                current += 1
                draw()
            elif key.isdigit():
                digit_buffer, selected, should_return = apply_digit_jump(digit_buffer, key, len(options))
                if selected is not None:
                    current = selected
                    draw()
                if should_return:
                    return current
            elif key in ("\b", "\x7f"):
                if digit_buffer:
                    digit_buffer = digit_buffer[:-1]
                    draw()

    return current


def apply_digit_jump(buffer: str, key: str, option_count: int) -> tuple[str, Optional[int], bool]:
    if not key.isdigit():
        return buffer, None, False

    candidates = [str(index) for index in range(1, option_count + 1)]
    merged = f"{buffer}{key}".lstrip("0")
    if not merged:
        return "", None, False

    if merged in candidates:
        selected = int(merged) - 1
        ambiguous = any(candidate.startswith(merged) and candidate != merged for candidate in candidates)
        return (merged if ambiguous else "", selected, not ambiguous)

    if key in candidates:
        selected = int(key) - 1
        ambiguous = any(candidate.startswith(key) and candidate != key for candidate in candidates)
        return (key if ambiguous else "", selected, not ambiguous)

    return buffer, None, False


def render_action_summary(title: str, lines: List[str], *, accent: Optional[str] = None, width: int = 88):
    clean_lines = [line for line in lines if line is not None]
    box(title, clean_lines, width=min(width, max(72, TERM_WIDTH - 4)), accent=accent or C.PRIMARY)


def render_help_overview():
    tips = [
        "Quickstart: omni  |  omni guide  |  omni connect --host <ip> --user <user>",
        "Maleta portable: omni briefcase --full --output ~/briefcase.json",
        "Migration path: SSH Connect -> Maleta -> Restore -> Migrate Sync",
        "Keep secrets out of git: API keys and SSH material stay in the encrypted bundle",
    ]
    box("OMNI CONTROL SURFACE", tips, width=84, accent=C.PRIMARY)


def path_to_snapshot_name(raw_path: str) -> str:
    clean = raw_path.strip().replace("\\", "/").strip("/")
    if not clean:
        return "root"
    return clean.replace("/", "__").replace(":", "")


def discover_ssh_identity_candidates(ssh_dir: Path | str | None = None) -> List[Path]:
    base = Path(ssh_dir or (Path.home() / ".ssh")).expanduser()
    if not base.exists():
        return []
    candidates: List[Path] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_file():
            continue
        if entry.name in {"known_hosts", "authorized_keys", "config"}:
            continue
        if entry.suffix == ".pub":
            continue
        candidates.append(entry)
    return candidates


def resolve_server_identity_file(
    server: Dict[str, Any],
    *,
    ssh_dir: Path | str | None = None,
    env: Dict[str, str] | None = None,
) -> str:
    explicit = str(server.get("identity_file") or "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        if candidate.exists():
            return str(candidate)

    data = env if env is not None else os.environ
    env_identity = str(data.get("OMNI_SSH_IDENTITY_FILE") or "").strip()
    if env_identity:
        candidate = Path(env_identity).expanduser()
        if candidate.exists():
            return str(candidate)

    candidates = discover_ssh_identity_candidates(ssh_dir)
    return str(candidates[0]) if candidates else ""


def is_rsync_vanished_warning(code: int, stdout: str, stderr: str) -> bool:
    combined = f"{stdout}\n{stderr}".lower()
    return int(code) == 24 and "vanish" in combined


def resolve_latest_bundle_across_dirs(bundle_dirs: List[Path], explicit_path: str, prefix: str) -> Path | None:
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        return candidate if candidate.exists() else None
    candidates: List[Path] = []
    for bundle_dir in bundle_dirs:
        if not Path(bundle_dir).exists():
            continue
        candidates.extend(sorted(Path(bundle_dir).glob(f"{prefix}_*"), key=lambda path: path.stat().st_mtime, reverse=True))
    return candidates[0] if candidates else None


def build_remote_sync_command(
    server: Dict[str, Any],
    source_path: str,
    target_dir: Path,
    *,
    ssh_dir: Path | str | None = None,
    delete: bool = True,
    extra_excludes: List[str] | None = None,
    source_kind: str = "dir",
) -> str:
    protocol = str(server.get("protocol") or "rsync").strip().lower()
    user = str(server.get("user") or "ubuntu").strip()
    host = str(server.get("host") or "").strip()
    port = int(server.get("port") or 22)
    excludes = list(server.get("excludes") or []) + list(extra_excludes or [])
    identity = resolve_server_identity_file(server, ssh_dir=ssh_dir)

    ssh_parts = [f"ssh -p {port}", "-o StrictHostKeyChecking=accept-new"]
    if identity:
        ssh_parts.append(f"-i {identity}")
    remote_source = source_path.rstrip("/") + ("/" if source_kind != "file" else "")

    if protocol == "scp":
        return f"scp -P {port} {'-i ' + identity if identity else ''} -r {user}@{host}:{remote_source} {target_dir}"

    flags = ["rsync -az"]
    if delete:
        flags.append("--delete")
    flags.append(f'-e "{" ".join(ssh_parts)}"')
    for pattern in excludes:
        flags.append(f"--exclude {pattern}")
    flags.append(f"{user}@{host}:{remote_source}")
    flags.append(f"{target_dir}/")
    return " ".join(flags)


def discover_local_runtime_paths(
    home_root: str = "",
    manifest: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    active_manifest = dict(manifest or {})
    root = Path(home_root or active_manifest.get("host_root") or Path.home()).expanduser()
    install_targets = [path for path in active_manifest.get("install_targets", []) if Path(expand_path(path, str(root))).exists()]
    compose_projects = [path for path in active_manifest.get("compose_projects", []) if Path(expand_path(path, str(root))).exists()]
    pm2_ecosystems = [path for path in active_manifest.get("pm2_ecosystems", []) if Path(expand_path(path, str(root))).exists()]
    detected_projects = install_targets + compose_projects
    runtime_markers = [path for path in active_manifest.get("state_paths", []) if Path(expand_path(path, str(root))).exists()]
    return {
        "ready": bool(install_targets or compose_projects or pm2_ecosystems or runtime_markers),
        "install_targets": install_targets,
        "compose_projects": compose_projects,
        "pm2_ecosystems": pm2_ecosystems,
        "detected_projects": detected_projects,
        "runtime_markers": runtime_markers,
    }


def resolve_installed_inventory_across_dirs(bundle_dirs: List[Path], explicit_path: str = "") -> Dict[str, Any] | None:
    if explicit_path:
        explicit = Path(explicit_path).expanduser()
        if explicit.exists():
            return json.loads(explicit.read_text(encoding="utf-8"))
        return None
    for bundle_dir in bundle_dirs:
        payload = load_installed_inventory(Path(bundle_dir))
        if payload:
            return payload
    return None

# ══════════════════════════════════════════════════════════════════════════════
# LOGO
# ══════════════════════════════════════════════════════════════════════════════

def print_omni_starburst(animated=False):
    _render_reset()
    print()
    BRIGHT = _e("38;5;180")
    GOLD = _e("38;5;179")
    MUTED = _e("38;5;136")
    MARK = _e("38;5;252")
    VER = _e("38;5;240")

    def emit(s, color="", bold=False, delay=0.028):
        b = C.BOLD if bold and USE_COLOR else ""
        c = color if USE_COLOR else ""
        sys.stdout.write("  " + b + c + s + C.R + "\n")
        sys.stdout.flush()
        if animated:
            time.sleep(delay)

    emit("              ·", MUTED)
    emit("        ╲     │     ╱", GOLD)
    emit("          ╲   │   ╱", GOLD)

    if USE_COLOR:
        core = MUTED + "·" + GOLD + "  ────────── " + BRIGHT + C.BOLD + "✦" + C.R + GOLD + " ──────────  " + MUTED + "·" + C.R
    else:
        core = "·  ────────── ✦ ──────────  ·"
    sys.stdout.write("  " + core + "\n")
    sys.stdout.flush()
    if animated:
        time.sleep(0.028)

    emit("          ╱   │   ╲", GOLD)
    emit("        ╱     │     ╲", GOLD)
    emit("              ·", MUTED)
    print()
    emit("         O  M  N  I", MARK, bold=True, delay=0.04)
    emit(f"         ·  v{OMNI_VERSION} {OMNI_CODENAME}  ·", VER, delay=0)
    print()
    sys.stdout.flush()

def print_logo(tagline=True, compact=False, animated=False, minimal=False):
    _render_reset()
    print()
    if minimal:
        print("  " + q(C.GLD_BRIGHT, "✦", bold=True))
        sys.stdout.write(C.R)
        return
    if compact:
        banner = f"✦ omni · v{OMNI_VERSION} · Portable migration CLI"
        print("  " + q(C.GLD_BRIGHT, banner, bold=True))
        print()
        sys.stdout.write(C.R)
        return
    print_omni_starburst(animated=animated)
    if tagline:
        tl = random.choice(_TAGLINES)
        if animated:
            ghost_write(tl, color=C.G2, delay=0.01)
        else:
            print("  " + q(C.G2, tl))
        print("  " + q(C.GLD_BRIGHT, "✦") + " " + q(C.G3, "OmniSync · by Black Boss"))
        hr()
    print()
    sys.stdout.write(C.R)

# ══════════════════════════════════════════════════════════════════════════════
# SPINNER & PROGRESS
# ══════════════════════════════════════════════════════════════════════════════

class Spinner:
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message, style="dots", color=None):
        self.message = message
        self.color = color or C.PRIMARY
        self.running = False
        self.thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.finish()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        idx = 0
        while self.running:
            sys.stdout.write("\r  " + self.color + self.frames[idx % len(self.frames)] + C.R + "  " + self.message)
            sys.stdout.flush()
            time.sleep(0.08)
            idx += 1

    def update(self, message):
        self.message = message

    def finish(self, final_message=None, success=True):
        self.running = False
        if self.thread:
            self.thread.join()
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
        if final_message:
            if success:
                ok(final_message)
            else:
                fail(final_message)

class ProgressBar:
    def __init__(self, total, label="", width=30, color=None):
        self.total = max(total, 1)
        self.label = label
        self.width = width
        self.color = color or C.B6
        self.current = 0
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        self._draw()
        return self

    def __exit__(self, *args):
        print()

    def update(self, current, label=None):
        self.current = min(current, self.total)
        if label:
            self.label = label
        self._draw()

    def _draw(self):
        pct = self.current / self.total
        filled = int(self.width * pct)
        empty = self.width - filled
        bar = q(self.color, "█" * filled) + q(C.G3, "·" * empty)
        pct_str = f"{int(pct * 100):3d}%"
        elapsed = time.time() - self.start_time if self.start_time else 0
        if pct > 0 and elapsed > 0.5:
            eta = (elapsed / pct) * (1 - pct)
            eta_str = f" ETA {eta:.0f}s" if eta > 1 else ""
        else:
            eta_str = ""
        line = f"\r  {bar}  {q(C.W, pct_str)}{q(C.G3, eta_str)}  {q(C.G2, self.label[:30])}"
        sys.stdout.write(line)
        sys.stdout.flush()

# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM FIXER
# ══════════════════════════════════════════════════════════════════════════════

class SystemFixer:
    def __init__(self):
        self.platform_info = detect_platform_info()

    def run_cmd(self, cmd: str, shell=True, timeout: int = 15) -> Tuple[int, str, str]:
        try:
            proc = subprocess.Popen(cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = proc.communicate(timeout=timeout)
            return proc.returncode, stdout.strip(), stderr.strip()
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            return -1, stdout.strip(), (stderr.strip() or f"Command timed out after {timeout}s")
        except Exception as e:
            logger.error(f"Error running command '{cmd}': {e}")
            return -1, "", str(e)

    def check_disk_space(self, threshold_percent=90) -> Dict:
        if self.platform_info.system == "windows":
            usage = shutil.disk_usage(Path.home().anchor or str(Path.home()))
            usage_percent = int((usage.used / usage.total) * 100) if usage.total else 0
            return {
                "status": "ok",
                "usage_percent": usage_percent,
                "free": human_size(usage.free),
                "message": f"Disk usage: {usage_percent}% (Windows fallback)",
            }
        code, out, err = self.run_cmd("df -h /")
        if code != 0:
            return {"status": "error", "message": f"Failed to check disk: {err}"}
        lines = out.splitlines()
        if len(lines) < 2:
            return {"status": "error", "message": "Unexpected df output"}
        try:
            parts = lines[1].split()
            use_percent = int(parts[4].replace('%', ''))
            result = {"status": "ok", "usage_percent": use_percent, "free": parts[3], "message": f"Disk usage: {use_percent}%"}
            if use_percent > threshold_percent:
                result["status"] = "warning"
                result["message"] += " - CRITICAL USAGE"
                self.run_cmd("sudo apt-get clean")
                self.run_cmd("journalctl --vacuum-time=3d")
                code, out, _ = self.run_cmd("df -h /")
                parts = out.splitlines()[1].split()
                new_use = int(parts[4].replace('%', ''))
                result["new_usage_percent"] = new_use
                result["actions_taken"] = ["apt-get clean", "journalctl vacuum"]
            return result
        except Exception as e:
            return {"status": "error", "message": f"Failed to parse df output: {e}"}

    def check_memory(self) -> Dict:
        if self.platform_info.system == "windows":
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
                total = int(status.ullTotalPhys / (1024 * 1024))
                available = int(status.ullAvailPhys / (1024 * 1024))
                used = max(total - available, 0)
                percent = (used / total) * 100 if total else 0
                return {
                    "status": "ok",
                    "total_mb": total,
                    "used_mb": used,
                    "available_mb": available,
                    "percent": percent,
                    "message": f"Memory: {used}/{total}MB ({percent:.1f}%) (Windows fallback)",
                }
            except Exception as e:
                return {"status": "error", "message": f"Windows memory probe failed: {e}"}
        code, out, _ = self.run_cmd("free -m")
        if code != 0:
            return {"status": "error"}
        try:
            lines = out.splitlines()
            mem_line = lines[1].split()
            total = int(mem_line[1])
            used = int(mem_line[2])
            available = int(mem_line[6])
            percent = (used / total) * 100
            return {"status": "ok", "total_mb": total, "used_mb": used, "available_mb": available, "percent": percent, "message": f"Memory: {used}/{total}MB ({percent:.1f}%)"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def check_and_fix_pm2(self) -> Dict:
        if self.platform_info.system == "windows":
            return {"status": "skipped", "message": "PM2 check skipped on Windows local shell. Use a remote Linux host for process supervision."}
        code, out, err = self.run_cmd("pm2 jlist")
        if code != 0:
            return {"status": "error", "message": "PM2 not found or error"}
        try:
            processes = json.loads(out)
            restarted = []
            for p in processes:
                name = p.get('name')
                status = p.get('pm2_env', {}).get('status')
                if status in ['stopped', 'errored']:
                    self.run_cmd(f"pm2 restart {name}")
                    restarted.append(name)
            return {"status": "ok", "total_processes": len(processes), "restarted": restarted, "message": f"PM2 check complete. Restarted: {restarted}" if restarted else "All PM2 processes healthy."}
        except Exception as e:
            return {"status": "error", "message": f"Failed to parse PM2 output: {e}"}

    def update_system(self) -> Dict:
        self.run_cmd("sudo apt-get update")
        code, out, _ = self.run_cmd("apt list --upgradable")
        lines = out.splitlines()
        upgradable_count = max(0, len(lines) - 1)
        actions = []
        if upgradable_count > 0:
            self.run_cmd("sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y")
            actions.append("upgrade")
            self.run_cmd("sudo apt-get autoremove -y")
            actions.append("autoremove")
        return {"status": "ok", "updates_found": upgradable_count, "actions": actions, "message": f"System updated. {upgradable_count} packages upgraded." if actions else "System up to date."}

    def check_git_repos(self, paths: List[str]) -> Dict:
        results = {}
        for path in paths:
            if not os.path.exists(path):
                continue
            code, out, _ = self.run_cmd(f"cd {path} && git status --porcelain")
            has_changes = len(out.strip()) > 0
            code, branch, _ = self.run_cmd(f"cd {path} && git rev-parse --abbrev-ref HEAD")
            pull_status = "skipped"
            if not has_changes:
                code, pull_out, _ = self.run_cmd(f"cd {path} && git pull")
                pull_status = "pulled" if "Already up to date" not in pull_out else "up_to_date"
            results[os.path.basename(path)] = {"branch": branch, "has_changes": has_changes, "pull_status": pull_status}
        return {"status": "ok", "repos": results}

# ══════════════════════════════════════════════════════════════════════════════
# TRANSFER ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TransferEngine:
    """File and data transfer between systems."""

    def __init__(self):
        self.protocol = "scp"  # scp, rsync, sftp
        self.compress = True
        self.verify = True

    def transfer_file(self, src: str, dest: str, options: Dict = None) -> Dict:
        """Transfer a file to remote or local destination."""
        opts = options or {}
        protocol = opts.get("protocol", self.protocol)
        compress = opts.get("compress", self.compress)

        result = {"success": False, "src": src, "dest": dest, "protocol": protocol, "bytes_transferred": 0}

        try:
            if not os.path.exists(src):
                return {"success": False, "error": f"Source file not found: {src}"}

            file_size = os.path.getsize(src)

            if protocol == "scp":
                cmd = f"scp {'-C' if compress else ''} '{src}' '{dest}'"
            elif protocol == "rsync":
                cmd = f"rsync -av {'--compress' if compress else ''} '{src}' '{dest}'"
            else:
                return {"success": False, "error": f"Unknown protocol: {protocol}"}

            with Spinner(f"Transferring {os.path.basename(src)}...", color=C.PRIMARY) as sp:
                code, out, err = self._run_cmd(cmd)
                if code == 0:
                    result["success"] = True
                    result["bytes_transferred"] = file_size
                    sp.finish("Transfer complete", success=True)
                else:
                    sp.finish("Transfer failed", success=False)
                    result["error"] = err or out

        except Exception as e:
            result["error"] = str(e)

        return result

    def transfer_directory(self, src: str, dest: str, options: Dict = None) -> Dict:
        """Transfer a directory recursively."""
        opts = options or {}
        protocol = opts.get("protocol", "rsync")

        result = {"success": False, "src": src, "dest": dest, "protocol": protocol}

        try:
            if not os.path.exists(src):
                return {"success": False, "error": f"Source directory not found: {src}"}

            cmd = f"rsync -av {'--compress' if opts.get('compress', True) else ''} '{src}/' '{dest}/'"

            with Spinner(f"Syncing directory...", color=C.PRIMARY) as sp:
                code, out, err = self._run_cmd(cmd)
                if code == 0:
                    result["success"] = True
                    sp.finish("Directory synced", success=True)
                else:
                    sp.finish("Sync failed", success=False)
                    result["error"] = err or out

        except Exception as e:
            result["error"] = str(e)

        return result

    def _run_cmd(self, cmd: str) -> Tuple[int, str, str]:
        try:
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = proc.communicate()
            return proc.returncode, stdout.strip(), stderr.strip()
        except Exception as e:
            return -1, "", str(e)

    def verify_transfer(self, src: str, dest: str) -> bool:
        """Verify transfer integrity via checksum."""
        try:
            code1, md5_src, _ = self._run_cmd(f"md5sum '{src}' | awk '{{print $1}}'")
            code2, md5_dest, _ = self._run_cmd(f"md5sum '{dest}' | awk '{{print $1}}'")
            return code1 == 0 and code2 == 0 and md5_src == md5_dest
        except Exception:
            return False

# ══════════════════════════════════════════════════════════════════════════════
# OMNI CORE
# ══════════════════════════════════════════════════════════════════════════════

class OmniCore:
    def __init__(self):
        self.fixer = SystemFixer()
        self.transfer = TransferEngine()
        self.root_dir = str(OMNI_HOME)
        self.tasks_file = str(TASKS_FILE)
        self.host_snapshot = collect_host_snapshot()
        self.dry_run = OMNI_DRY_RUN
        self.ensure_runtime_dirs()
        self.manifest_path = SYSTEM_MANIFEST_FILE
        self.bundle_dir = BUNDLE_DIR
        self.repo_entries = self.load_repo_entries()
        self.repos = self.repo_paths_from_entries(self.repo_entries)
        self.servers = self.load_servers()
        self.load_tasks()

    def ensure_runtime_dirs(self):
        for path in (OMNI_HOME, CONFIG_DIR, STATE_DIR, BACKUP_DIR, BUNDLE_DIR, AUTO_BUNDLE_DIR, LOG_DIR, EXPORT_DIR):
            path.mkdir(parents=True, exist_ok=True)

    def is_dry_run(self) -> bool:
        return bool(self.dry_run)

    def global_config(self) -> Dict[str, Any]:
        return load_global_config(GLOBAL_CONFIG_FILE)

    def current_language(self) -> str:
        env_language = os.environ.get("OMNI_LANG", "").strip()
        if env_language:
            return normalize_language(env_language)
        return normalize_language(self.global_config().get("language", "es"))

    def t(self, es: str, en: str) -> str:
        return en if self.current_language() == "en" else es

    def persist_language(self, language: str) -> str:
        normalized = normalize_language(language)
        payload = self.global_config()
        payload["language"] = normalized
        if not self.is_dry_run():
            save_global_config(GLOBAL_CONFIG_FILE, payload)
        return normalized

    def load_continue_state(self) -> Dict[str, Any]:
        if not CONTINUE_STATE_FILE.exists():
            return {}
        try:
            payload = json.loads(CONTINUE_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def pending_continue_state(self, flow: str = "") -> Dict[str, Any]:
        payload = self.load_continue_state()
        if not payload:
            return {}
        if flow and payload.get("flow") != flow:
            return {}
        if payload.get("status") in {"completed", "cancelled"}:
            return {}
        return payload

    def save_continue_state(
        self,
        *,
        flow: str,
        status: str,
        params: Dict[str, Any] | None = None,
        context: Dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        payload: Dict[str, Any] = {
            "flow": flow,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if params:
            payload["params"] = params
        if context:
            payload["context"] = context
        if error:
            payload["error"] = error
        if self.is_dry_run():
            return
        CONTINUE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONTINUE_STATE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def clear_continue_state(self, flow: str = "") -> None:
        if not CONTINUE_STATE_FILE.exists():
            return
        if flow:
            payload = self.load_continue_state()
            if payload.get("flow") != flow:
                return
        if not self.is_dry_run():
            CONTINUE_STATE_FILE.unlink(missing_ok=True)

    def continue_cmd(self) -> None:
        print_logo(compact=True)
        state = self.pending_continue_state()
        if not state:
            render_human_error(
                self.t("No hay una operación pendiente para reanudar.", "There is no pending operation to resume."),
                suggestion=self.t(
                    "Empieza con `omni guide` o `omni connect` y Omni guardará el punto de avance.",
                    "Start with `omni guide` or `omni connect` and Omni will save your progress point.",
                ),
            )
            return

        flow = str(state.get("flow", "")).strip().lower()
        params = state.get("params") if isinstance(state.get("params"), dict) else {}
        info(
            self.t(
                f"Reanudando `{flow}` desde `{state.get('status', 'pending')}`.",
                f"Resuming `{flow}` from `{state.get('status', 'pending')}`.",
            )
        )

        if flow == "connect":
            self.connect_cmd(
                host=str(params.get("host", "")),
                user=str(params.get("user", "")),
                port=int(params.get("port", 22) or 22),
                key_path=str(params.get("key_path", "")),
                remote_path=str(params.get("remote_path", "")),
                transport=str(params.get("transport", "auto")),
                target_system=str(params.get("target_system", "")),
                auth_mode=str(params.get("auth_mode", "")),
                password_env=str(params.get("password_env", "OMNI_SSH_PASSWORD")),
                briefcase_path=str(params.get("briefcase_path", "")),
                manifest_path=str(params.get("manifest_path", "")),
                home_root=str(params.get("home_root", "")),
                profile=str(params.get("profile", "")),
            )
            return

        render_human_error(
            self.t(
                f"Todavía no puedo reanudar automáticamente el flujo `{flow}`.",
                f"I cannot resume the `{flow}` flow automatically yet.",
            ),
            suggestion=self.t(
                "Vuelve a abrir el flujo desde `omni guide` o ejecuta el comando principal otra vez.",
                "Open the flow again from `omni guide` or run the primary command again.",
            ),
        )

    def default_briefcase_paths(self) -> tuple[Path, Path]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        host = socket.gethostname().split(".", 1)[0] or "host"
        base = EXPORT_DIR / f"{stamp}-{host}-briefcase.json"
        return base, base.with_suffix(".restore.sh")

    def load_repo_entries(self) -> List[Any]:
        defaults = [
            str((Path.home() / "melissa").resolve()),
            str((Path.home() / "nova-os").resolve()),
            str((Path.home() / ".nova").resolve()),
            str(OMNI_HOME),
        ]

        if REPOS_FILE.exists():
            try:
                repo_data = json.loads(REPOS_FILE.read_text(encoding="utf-8"))
                repos = repo_data.get("repos", repo_data) if isinstance(repo_data, dict) else repo_data
                if isinstance(repos, list):
                    return repos
            except Exception as e:
                debug(f"Failed to load repos.json: {e}")

        return defaults

    def repo_paths_from_entries(self, entries: List[Any]) -> List[str]:
        paths: List[str] = []
        for entry in entries:
            if isinstance(entry, dict):
                raw_path = entry.get("path")
                if raw_path:
                    paths.append(str(Path(os.path.expandvars(str(raw_path))).expanduser()))
            elif isinstance(entry, str):
                paths.append(str(Path(os.path.expandvars(entry)).expanduser()))
        return paths

    def load_servers(self) -> List[Dict[str, Any]]:
        if not SERVERS_FILE.exists():
            return []
        try:
            server_data = json.loads(SERVERS_FILE.read_text(encoding="utf-8"))
            servers = server_data.get("servers", server_data) if isinstance(server_data, dict) else server_data
            return servers if isinstance(servers, list) else []
        except Exception as e:
            debug(f"Failed to load servers.json: {e}")
            return []

    def load_tasks(self):
        self.tasks = []
        if os.path.exists(self.tasks_file):
            try:
                with open(self.tasks_file, 'r') as f:
                    self.tasks = json.load(f)
            except Exception as e:
                debug(f"Failed to load tasks.json: {e}")

    def normalize_profile(self, profile: str = "") -> str:
        raw = (profile or os.environ.get("OMNI_PROFILE", "") or "").strip().lower().replace("_", "-")
        if raw in {"full-home", "full", "home", "todo", "all-home", "all"}:
            return FULL_HOME_PROFILE
        return DEFAULT_PROFILE

    def choose_profile(self, requested: str = "", *, accept_all: bool = False, current_profile: str = "") -> str:
        requested_raw = (requested or "").strip()
        resolved = self.normalize_profile(requested_raw)
        if requested_raw or accept_all or not self.is_interactive():
            return resolved

        manifest_profile = current_profile or DEFAULT_PROFILE
        if self.manifest_path.exists() and not current_profile:
            try:
                manifest_profile = load_manifest(self.manifest_path, str(Path.home())).get("profile", DEFAULT_PROFILE)
            except Exception:
                manifest_profile = DEFAULT_PROFILE
        default_profile = self.normalize_profile(manifest_profile)
        options = ["production-clean", "full-home"]
        descriptions = [
            "Restaura arquitectura curada, más liviana y portable.",
            "Captura y reconstruye TODO /home/ubuntu, con secretos separados.",
        ]
        icons = ["🧩", "🏠"]
        try:
            selected = select_menu(
                options,
                title="Elige el alcance de la migración",
                descriptions=descriptions,
                icons=icons,
                default=options.index(default_profile) if default_profile in options else 0,
                show_index=True,
                footer="↑/↓ elegir alcance · Enter confirmar",
            )
        except KeyboardInterrupt:
            raise
        return self.normalize_profile(options[selected])

    def resolve_manifest(
        self,
        manifest_path: str = "",
        home_root: str = "",
        create: bool = True,
        profile: str = "",
        force_profile: bool = False,
    ) -> tuple[Path, Dict[str, Any]]:
        selected = Path(manifest_path).expanduser() if manifest_path else self.manifest_path
        resolved_home = expand_path(home_root or str(Path.home()))
        selected_profile = self.normalize_profile(profile)
        manifest = (
            ensure_manifest(selected, resolved_home, profile=selected_profile, force_profile=force_profile)
            if create
            else load_manifest(selected, resolved_home)
        )
        return selected, manifest

    def resolve_output_path(self, output: str, prefix: str, encrypted: bool = False) -> Path:
        from bundle_ops import default_bundle_path

        if not output:
            return default_bundle_path(self.bundle_dir, prefix, encrypted=encrypted)
        candidate = Path(output).expanduser()
        if candidate.exists() and candidate.is_dir():
            return default_bundle_path(candidate, prefix, encrypted=encrypted)
        if output.endswith("/") or output.endswith("\\"):
            candidate.mkdir(parents=True, exist_ok=True)
            return default_bundle_path(candidate, prefix, encrypted=encrypted)
        if not candidate.suffix:
            candidate.mkdir(parents=True, exist_ok=True)
            return default_bundle_path(candidate, prefix, encrypted=encrypted)
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    def read_passphrase(self, env_name: str) -> str:
        return os.environ.get(env_name or "OMNI_SECRET_PASSPHRASE", "")

    def write_json_output(self, payload: Dict[str, Any], output_path: str = "") -> None:
        if not output_path:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        destination = Path(output_path).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        ok(f"JSON report saved to {destination}")

    def capture_output_dir(self, output: str = "") -> Path:
        if not output:
            self.bundle_dir.mkdir(parents=True, exist_ok=True)
            return self.bundle_dir
        candidate = Path(output).expanduser()
        if candidate.suffix:
            candidate = candidate.parent
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate

    def auto_backup_dir(self) -> Path:
        AUTO_BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
        return AUTO_BUNDLE_DIR

    def bundle_search_dirs(self, *, include_auto: bool = True) -> List[Path]:
        directories = [Path(self.bundle_dir), BACKUP_DIR]
        if include_auto:
            directories.append(self.auto_backup_dir())
        unique: List[Path] = []
        seen: set[str] = set()
        for item in directories:
            key = str(item)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _run_transfer_cmd_visible(self, cmd: str, label: str = "") -> Tuple[int, str, str]:
        return self.transfer._run_cmd(cmd)

    def list_remote_directory_entries(self, server: Dict[str, Any], root: str) -> List[Dict[str, Any]]:
        return [{"path": root, "kind": "dir"}]

    def prune_bundle_dir(self, bundle_dir: Path, keep: int = AUTO_BACKUP_KEEP) -> None:
        for pattern in ("state_bundle_*", "secrets_bundle_*", "capture_summary_*.json"):
            candidates = sorted(bundle_dir.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
            for stale in candidates[keep:]:
                try:
                    stale.unlink()
                except OSError:
                    continue

    def create_recovery_pack(
        self,
        *,
        manifest_path: str = "",
        home_root: str = "",
        output: str = "",
        passphrase_env: str = "OMNI_SECRET_PASSPHRASE",
        profile: str = "",
        bundle_dir: Path | None = None,
        prune: bool = False,
    ) -> Dict[str, Any]:
        selected_path, manifest = self.resolve_manifest(manifest_path, home_root, create=True, profile=profile)
        target_dir = bundle_dir or self.capture_output_dir(output)
        target_dir.mkdir(parents=True, exist_ok=True)
        passphrase = self.read_passphrase(passphrase_env)
        state_bundle = create_state_bundle(target_dir, manifest)
        secrets_bundle = create_secrets_bundle(target_dir, manifest, passphrase=passphrase)
        summary_path = write_capture_summary(
            bundle_dir=target_dir,
            manifest_path=selected_path,
            state_bundle=state_bundle,
            secrets_bundle=secrets_bundle,
        )
        if prune:
            self.prune_bundle_dir(target_dir, keep=AUTO_BACKUP_KEEP)
        return {
            "manifest_path": str(selected_path),
            "manifest": manifest,
            "bundle_dir": str(target_dir),
            "state_bundle": str(state_bundle),
            "secrets_bundle": str(secrets_bundle),
            "summary_path": str(summary_path),
            "encrypted": bool(passphrase),
        }

    def is_interactive(self) -> bool:
        return bool(getattr(sys.stdin, "isatty", lambda: False)()) and bool(getattr(sys.stdout, "isatty", lambda: False)())

    def prompt_text(self, prompt: str, default: str = "") -> str:
        if not self.is_interactive():
            return default
        suffix = f" [{default}]" if default else ""
        try:
            sys.stdout.write(f"\n  {q(C.PRIMARY, '?')}  {q(C.W, prompt)}{q(C.G3, suffix)}  ")
            sys.stdout.flush()
            answer = input("").strip()
        except EOFError:
            print()
            return default
        except KeyboardInterrupt:
            print()
            raise
        return answer or default

    def confirm_step(self, prompt: str, accept_all: bool = False, default: bool = True) -> bool:
        if accept_all or not self.is_interactive():
            return default
        default_hint = "S/n" if default else "s/N"
        try:
            sys.stdout.write(f"\n  {q(C.PRIMARY, '?')}  {q(C.W, prompt)} {q(C.G3, f'[{default_hint}]')}  ")
            sys.stdout.flush()
            answer = input("").strip().lower()
        except EOFError:
            print()
            return default
        except KeyboardInterrupt:
            print()
            raise
        if not answer:
            return default
        return answer in {"y", "yes", "s", "si", "sí"}

    def send_telegram(self, message):
        telegram_token = os.getenv("OMNI_TELEGRAM_TOKEN", "")
        chat_id = os.getenv("SANTIAGO_CHAT_ID", "")
        if not telegram_token or not chat_id:
            return
        try:
            cmd = ["curl", "-s", "-X", "POST", f"https://api.telegram.org/bot{telegram_token}/sendMessage",
                   "-d", f"chat_id={chat_id}", "-d", f"text={message}", "-d", "parse_mode=Markdown"]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            debug(f"Failed to send Telegram: {e}")

    def run_health_check(self):
        logger = logging.getLogger("omni.core")
        logger.info("Running system health check...")
        report = {
            "timestamp": datetime.now().isoformat(),
            "disk": self.fixer.check_disk_space(),
            "memory": self.fixer.check_memory(),
            "pm2": self.fixer.check_and_fix_pm2(),
            "git": self.fixer.check_git_repos(self.repos)
        }
        self.print_report(report)
        alerts = []
        if report['disk'].get('status') == 'warning':
            alerts.append(f"🚨 DISK CRITICAL: {report['disk'].get('message')}")
        pm2_restarted = report['pm2'].get('restarted', [])
        if pm2_restarted:
            alerts.append(f"⚠️ PM2 RESTARTED: {', '.join(pm2_restarted)}")
        if alerts:
            self.send_telegram("\n".join(alerts))
        return report

    def run_tasks(self):
        if not self.tasks:
            return
        logger = logging.getLogger("omni.core")
        logger.info(f"Running {len(self.tasks)} tasks...")
        for task in self.tasks:
            name = task.get("name", "Unnamed")
            cmd = task.get("command")
            if cmd:
                logger.info(f"Executing task: {name}")
                try:
                    subprocess.run(cmd, shell=True, check=False)
                except Exception as e:
                    logger.error(f"Task '{name}' failed: {e}")

    def sync_servers(self) -> Dict[str, Any]:
        logger = logging.getLogger("omni.core")
        results: List[Dict[str, Any]] = []

        if not self.servers:
            return {"success": False, "message": f"No servers configured in {SERVERS_FILE}", "results": results}

        snapshot_root = STATE_DIR / "servers"
        snapshot_root.mkdir(parents=True, exist_ok=True)
        manifest_profile = ""
        manifest_host_root = ""
        if Path(self.manifest_path).exists():
            try:
                manifest_payload = json.loads(Path(self.manifest_path).read_text(encoding="utf-8"))
                manifest_profile = str(manifest_payload.get("profile", ""))
                manifest_host_root = str(manifest_payload.get("host_root", "")).strip()
            except Exception:
                manifest_profile = ""
                manifest_host_root = ""

        for server in self.servers:
            name = server.get("name") or server.get("host", "server")
            user = server.get("user", "ubuntu")
            host = server.get("host")
            port = int(server.get("port", 22))
            protocol = server.get("protocol", "rsync")
            paths = server.get("paths", [])
            excludes = server.get("excludes", [])

            if not host or not paths:
                results.append({"server": name, "success": False, "error": "Missing host or paths"})
                continue

            server_root = snapshot_root / name
            server_root.mkdir(parents=True, exist_ok=True)

            for remote_path in paths:
                remote_source = manifest_host_root if manifest_profile == FULL_HOME_PROFILE and manifest_host_root else remote_path
                target_dir = server_root / path_to_snapshot_name(remote_source)
                target_dir.mkdir(parents=True, exist_ok=True)
                bundle_excludes = [
                    "backups/auto-bundles",
                    f"{Path(self.root_dir).name}/backups/auto-bundles",
                    str(Path(self.root_dir) / "backups" / "auto-bundles"),
                ]
                cmd = build_remote_sync_command(
                    server,
                    remote_source,
                    target_dir,
                    extra_excludes=bundle_excludes,
                )

                logger.info("Syncing %s:%s", name, remote_source)
                code, out, err = self.transfer._run_cmd(cmd)
                vanished = is_rsync_vanished_warning(code, out, err)
                results.append({
                    "server": name,
                    "path": remote_source,
                    "protocol": protocol,
                    "success": code == 0 or vanished,
                    "status": "warning_vanished" if vanished else ("ok" if code == 0 else "error"),
                    "target": str(target_dir),
                    "error": "" if vanished else (err if code != 0 else ""),
                    "output": out if code == 0 else "",
                })

        ok_count = sum(1 for item in results if item.get("success"))
        return {
            "success": ok_count == len(results) and len(results) > 0,
            "message": f"Synced {ok_count}/{len(results)} remote paths",
            "results": results,
        }

    def run_full_fix(self):
        logger = logging.getLogger("omni.core")
        logger.info("Running FULL SYSTEM FIX...")
        update_res = self.fixer.update_system()
        pm2_res = self.fixer.check_and_fix_pm2()
        disk_res = self.fixer.check_disk_space()
        git_res = self.fixer.check_git_repos(self.repos)
        self.run_tasks()
        report = {"timestamp": datetime.now().isoformat(), "updates": update_res, "pm2": pm2_res, "disk": disk_res, "git": git_res}
        self.print_report(report)
        logger.info("System fix complete.")
        summary = f"🛠️ *Omni Fix Complete*\n"
        if update_res.get('actions'):
            summary += f"• Updates: {', '.join(update_res['actions'])}\n"
        if pm2_res.get('restarted'):
            summary += f"• PM2 Restarted: {', '.join(pm2_res['restarted'])}\n"
        if disk_res.get('actions_taken'):
            summary += f"• Disk Cleaned: {', '.join(disk_res['actions_taken'])}\n"
        if "Updates" in summary or "Restarted" in summary or "Cleaned" in summary:
            self.send_telegram(summary)

    def print_report(self, report):
        print("\n" + "="*60)
        print(f" OMNI CORE REPORT - {report['timestamp']}")
        print("="*60)
        d = report.get('disk', {})
        print(f"DISK: {d.get('message', 'Unknown')} ({d.get('status', 'unknown')})")
        m = report.get('memory', {})
        print(f"MEMORY: {m.get('message', 'Unknown')}")
        p = report.get('pm2', {})
        print(f"PROCESSES: {p.get('message', 'Unknown')}")
        g = report.get('git', {}).get('repos', {})
        if g:
            print("REPOSITORIES:")
            for name, status in g.items():
                print(f"  - {name}: {status.get('branch')} (Changes: {status.get('has_changes')}, Pull: {status.get('pull_status')})")
        u = report.get('updates', {})
        if u:
            print(f"UPDATES: {u.get('message', 'None')}")
        print("="*60 + "\n")

    def watch_mode(
        self,
        interval: int = 300,
        *,
        manifest_path: str = "",
        home_root: str = "",
        profile: str = "",
    ):
        logger = logging.getLogger("omni.core")
        print_logo(compact=True)
        section("Watch Mode")

        selected_path, manifest = self.resolve_manifest(manifest_path, home_root, create=True, profile=profile)
        watch_state_path = WATCH_STATE_FILE
        previous = load_watch_snapshot(watch_state_path)
        current = capture_watch_snapshot(manifest, manifest.get("host_root", home_root or str(Path.home())))
        save_watch_snapshot(watch_state_path, current)
        last_backup_at = 0.0

        kv("Manifest", str(selected_path), color=C.GRN)
        kv("Profile", manifest.get("profile", DEFAULT_PROFILE), color=C.GRN)
        kv("Host Root", manifest.get("host_root", str(Path.home())), color=C.GRN)
        kv("Watch State", str(watch_state_path), color=C.GRN)
        kv("Baseline", f"{current.get('file_count', 0)} files · {human_size(int(current.get('total_size_bytes', 0)))}", color=C.GRN)
        kv("Interval", f"{interval}s", color=C.GRN)
        kv("Backup Cooldown", f"{WATCH_BACKUP_COOLDOWN}s", color=C.GRN)
        nl()

        if previous and previous.get("fingerprint") != current.get("fingerprint"):
            diff = summarize_snapshot_diff(previous, current)
            warn(f"Detected {diff['changed_files']} pending changes since last watch snapshot")
            for sample in diff.get("samples", [])[:6]:
                bullet(sample, C.YLW)
            nl()

        info("Watching managed paths for file changes. Ctrl+C to stop.")
        logger.info("Starting OmniSync watch mode", extra={"interval": interval, "profile": manifest.get("profile")})

        try:
            while True:
                time.sleep(max(5, interval))
                next_snapshot = capture_watch_snapshot(manifest, manifest.get("host_root", home_root or str(Path.home())))
                diff = summarize_snapshot_diff(current, next_snapshot)
                if not diff.get("changed"):
                    current = next_snapshot
                    continue

                warn(
                    f"Detected {diff['changed_files']} file changes "
                    f"(+{diff['added']} / ~{diff['modified']} / -{diff['removed']})"
                )
                for sample in diff.get("samples", [])[:8]:
                    bullet(sample, C.YLW)

                now = time.time()
                if now - last_backup_at >= WATCH_BACKUP_COOLDOWN:
                    self.run_backup(profile=manifest.get("profile", DEFAULT_PROFILE))
                    last_backup_at = now
                else:
                    remaining = int(WATCH_BACKUP_COOLDOWN - (now - last_backup_at))
                    hint(f"Backup cooldown active. Next automatic backup in ~{remaining}s.")
                save_watch_snapshot(watch_state_path, next_snapshot)
                current = next_snapshot
                nl()
        except KeyboardInterrupt:
            info("Watch mode stopped.")
            logger.info("Watch mode stopped.")

    def show_status(self):
        """Show comprehensive system status."""
        print_logo(compact=True)
        section("System Status")

        disk = self.fixer.check_disk_space()
        mem = self.fixer.check_memory()
        pm2 = self.fixer.check_and_fix_pm2()

        kv("Disk Usage", disk.get('message', 'Unknown'), color=C.GRN if disk.get('status') in {'ok', 'skipped'} else C.RED)
        kv("Memory", mem.get('message', 'Unknown'), color=C.GRN if mem.get('status') in {'ok', 'skipped'} else C.YLW)
        kv("PM2 Processes", pm2.get('message', f"{pm2.get('total_processes', 0)} running"), color=C.GRN if pm2.get('status') in {'ok', 'skipped'} and not pm2.get('restarted') else C.YLW)

        nl()
        bullet("Repositories synced", C.GRN)
        bullet("Tasks loaded: " + str(len(self.tasks)), C.GRN)
        bullet("Watch mode: active", C.PRIMARY, bold=True)
        nl()

    def show_logs(self, lines=50, follow=False):
        """Show Omni logs."""
        log_path = str(LOG_DIR / "omni.log")
        if not os.path.exists(log_path):
            fail("Log file not found")
            return
        print_logo(compact=True)
        section("Omni Logs")
        cmd = f"tail -{lines} '{log_path}'"
        if follow:
            cmd = f"tail -f '{log_path}'"
        subprocess.run(cmd, shell=True)

    def restart_services(self):
        """Restart PM2 services managed by Omni."""
        print_logo(compact=True)
        section("Restarting Services")
        with Spinner("Restarting PM2 processes...", color=C.PRIMARY) as sp:
            code, out, err = self.fixer.run_cmd("pm2 restart all")
            if code == 0:
                sp.finish("All services restarted", success=True)
            else:
                sp.finish("Failed to restart services", success=False)

    def run_backup(self, target=None, manifest_path: str = "", home_root: str = "", passphrase_env: str = "OMNI_SECRET_PASSPHRASE", profile: str = ""):
        """Create a real recovery pack in auto-bundles."""
        print_logo(compact=True)
        section("System Backup")

        with Spinner("Creating backup...", color=C.PRIMARY) as sp:
            try:
                target_dir = self.capture_output_dir(str(target)) if target else self.auto_backup_dir()
                pack = self.create_recovery_pack(
                    manifest_path=manifest_path,
                    home_root=home_root,
                    output=str(target_dir),
                    passphrase_env=passphrase_env,
                    profile=profile,
                    bundle_dir=target_dir,
                    prune=(not target),
                )
                sp.finish(f"Backup saved to {pack['bundle_dir']}", success=True)
                ok(f"State bundle: {pack['state_bundle']}")
                ok(f"Secrets bundle: {pack['secrets_bundle']}")
                ok(f"Summary: {pack['summary_path']}")
                if not pack["encrypted"]:
                    warn("Secrets bundle exported without encryption. Set OMNI_SECRET_PASSPHRASE to encrypt automatic backups.")
            except Exception as e:
                sp.finish(f"Backup failed: {e}", success=False)

    def run_transfer(self, src: str, dest: str, options: Dict = None):
        """Transfer files using TransferEngine."""
        print_logo(compact=True)
        section("File Transfer")

        if not src or not dest:
            fail("Source and destination required")
            hint("Usage: omni transfer <src> <dest> [--protocol scp|rsync]")
            return

        result = self.transfer.transfer_file(src, dest, options)

        if result.get("success"):
            ok(f"Transferred {result['bytes_transferred']} bytes")
        else:
            fail(result.get("error", "Unknown error"))

    def show_config(self):
        """Show Omni configuration."""
        print_logo(compact=True)
        section(self.t("Configuración", "Configuration"))

        global_config = self.global_config()
        kv(self.t("Versión", "Version"), OMNI_VERSION)
        kv("Build", OMNI_BUILD)
        kv(self.t("Codename", "Codename"), OMNI_CODENAME)
        kv(self.t("Idioma", "Language"), f"{self.current_language()} ({SUPPORTED_LANGUAGES[self.current_language()]})", color=C.GRN)
        kv(self.t("Archivo de tareas", "Tasks File"), self.tasks_file)
        kv(self.t("Archivo de repos", "Repos File"), str(REPOS_FILE))
        kv("Manifest", str(self.manifest_path))
        kv(self.t("Directorio de bundles", "Bundle Dir"), str(self.bundle_dir))
        kv(self.t("Directorio de exportación", "Export Dir"), str(EXPORT_DIR))
        kv(self.t("Config de agente", "Agent Config"), str(AGENT_CONFIG_FILE))
        kv("Logs", str(LOG_DIR / "omni.log"))
        kv(self.t("Repos", "Repos"), str(len(self.repos)))
        kv("Telegram", self.t("configurado", "configured") if os.getenv("OMNI_TELEGRAM_TOKEN") else self.t("no configurado", "not configured"))
        github_cfg = global_config.get("github") or {}
        kv("GitHub", self.t("autenticado", "authenticated") if github_cfg.get("token") else self.t("no configurado", "not configured"), color=C.GRN if github_cfg.get("token") else C.YLW)
        if github_cfg.get("repo"):
            kv(self.t("Repo de GitHub", "GitHub Repo"), f"{github_cfg.get('owner', '')}/{github_cfg.get('repo', '')}".strip("/"), color=C.GRN)
        agent_config = load_agent_config(AGENT_CONFIG_FILE)
        if agent_config:
            kv(self.t("Proveedor de agente", "Agent Provider"), str(agent_config.get("provider", "unknown")), color=C.GRN)
        nl()

        if self.tasks:
            bullet(self.t("Tareas:", "Tasks:"), C.G3)
            for task in self.tasks:
                dim("  • " + task.get("name", "Unnamed"))

    def config_cmd(self, subaction: str = "", *, value: str = "") -> None:
        normalized = str(subaction or "").strip().lower()
        if normalized in {"language", "lang", "idioma"}:
            requested = value.strip()
            if not requested and self.is_interactive():
                options = [("es", "Español", "UI y mensajes operativos en español."), ("en", "English", "UI and operator copy in English.")]
                selected = select_menu(
                    [title for _, title, _ in options],
                    title="Elige el idioma principal de Omni",
                    descriptions=[description for _, _, description in options],
                    icons=["🇪🇸", "🇺🇸"],
                    default=0 if self.current_language() == "es" else 1,
                    show_index=True,
                    footer="↑/↓ elegir idioma · Enter confirmar",
                )
                requested = options[selected][0]
            if requested:
                language = self.persist_language(requested)
                if self.is_dry_run():
                    warn(self.t(f"Dry run activo: no se guardó el idioma {language}.", f"Dry run active: language {language} was not saved."))
                else:
                    ok(self.t(f"Idioma activo: {language} ({SUPPORTED_LANGUAGES[language]})", f"Active language: {language} ({SUPPORTED_LANGUAGES[language]})"))
            self.show_config()
            return
        self.show_config()

    def show_agent_status(self):
        print_logo(compact=True)
        section("Omni Agent")
        config = load_agent_config(AGENT_CONFIG_FILE)
        sync_report = sync_agent_integrations(AGENT_SKILL_DIR, home_root=Path.home(), repo_root=OMNI_HOME)
        runtimes = sync_report["runtimes"]
        integrations = sync_report["integrations"]
        if not config:
            warn("Omni Agent todavía no está configurado.")
            hint("Usa `omni agent` para elegir proveedor y guardar la configuración.")
            nl()
            section("Agent Runtimes")
            for runtime in runtimes:
                status = "ready" if runtime.installed else "skill-only"
                color = C.GRN if runtime.installed else C.YLW
                kv(runtime.title, status, color=color, key_width=18)
            nl()
            section("Injected Integrations")
            for integration in integrations:
                state = "linked" if integration.written else ("detected" if integration.detected else "missing")
                color = C.GRN if integration.written else (C.YLW if integration.detected else C.G3)
                kv(integration.title, state, color=color, key_width=18)
            return

        provider = get_provider(str(config.get("provider", "")))
        title = provider.title if provider else str(config.get("provider_title", config.get("provider", "unknown")))
        env_var = str(config.get("env_var", ""))
        kv("Provider", title, color=C.GRN)
        kv("Protocol", str(config.get("protocol", "unknown")), color=C.GRN)
        kv("Model", str(config.get("model", "unknown")), color=C.GRN)
        kv("Base URL", str(config.get("base_url", "unknown")), color=C.GRN)
        kv("Env Var", env_var or "none", color=C.GRN)
        kv("Secret", "loaded" if env_var and env_has_value(ENV_FILE, env_var) else "missing", color=C.GRN if env_var and env_has_value(ENV_FILE, env_var) else C.YLW)
        if config.get("docs_url"):
            kv("Docs", str(config.get("docs_url")), color=C.GRN)
        if config.get("notes"):
            dim(str(config.get("notes")))
        nl()
        section("Agent Runtimes")
        for runtime in runtimes:
            status = "ready" if runtime.installed else "skill-only"
            color = C.GRN if runtime.installed else C.YLW
            label = runtime.version or runtime.command
            kv(runtime.title, f"{status} :: {label}", color=color, key_width=18)
        nl()
        section("Injected Integrations")
        for integration in integrations:
            state = "linked" if integration.written else ("detected" if integration.detected else "missing")
            color = C.GRN if integration.written else (C.YLW if integration.detected else C.G3)
            kv(integration.title, state, color=color, key_width=18)
        nl()

    def agent_cmd(self, subaction: str = "", *, accept_all: bool = False):
        normalized = str(subaction or "").strip().lower()
        if normalized in {"status", "show"}:
            self.show_agent_status()
            return
        if normalized in {"chat", "talk"}:
            self.chat_cmd()
            return

        print_logo(compact=True)
        section("Omni Agent")
        sync_report = sync_agent_integrations(AGENT_SKILL_DIR, home_root=Path.home(), repo_root=OMNI_HOME)
        runtimes = sync_report["runtimes"]
        integrations = sync_report["integrations"]
        render_action_summary(
            "Agent Runtimes",
            [
                f"{runtime.title}: {'ready' if runtime.installed else 'skill-only'}"
                + (f" · {runtime.version}" if runtime.version else "")
                for runtime in runtimes
            ],
            accent=C.GRN,
        )
        linked_total = sum(len(item.written) for item in integrations)
        if linked_total:
            info(f"Sincronicé {linked_total} assets de agentes detectados en tu home.")
        current = load_agent_config(AGENT_CONFIG_FILE)
        if current:
            info("Configuración actual detectada.")
            provider = get_provider(str(current.get("provider", "")))
            kv("Provider", provider.title if provider else str(current.get("provider", "unknown")), color=C.GRN)
            kv("Model", str(current.get("model", "unknown")), color=C.GRN)
            kv("Base URL", str(current.get("base_url", "unknown")), color=C.GRN)
            nl()

        providers = provider_catalog()
        default_idx = 0
        if current:
            default_idx = next((idx for idx, item in enumerate(providers) if item.key == current.get("provider")), 0)

        if accept_all or not self.is_interactive():
            selected = default_idx
        else:
            selected = select_menu(
                [item.title for item in providers],
                title="¿Qué proveedor quieres usar para Omni Agent?",
                descriptions=[item.description for item in providers],
                icons=[item.icon for item in providers],
                default=default_idx,
                show_index=True,
                footer="↑/↓ elegir proveedor · Enter confirmar · número salto directo",
            )

        provider = providers[selected]
        base_url = provider.base_url
        env_var = provider.env_var

        if provider.requires_custom_base_url and self.is_interactive():
            raw_base = input(f"Base URL [{provider.base_url}]: ").strip()
            if raw_base:
                base_url = raw_base
        if provider.requires_custom_env_var and self.is_interactive():
            raw_env = input(f"Variable para API key [{provider.env_var}]: ").strip().upper()
            if raw_env:
                env_var = raw_env

        model_choices = list(provider.sample_models) + ["Custom"]
        model_default_idx = 0
        if current and current.get("provider") == provider.key and current.get("model") in model_choices:
            model_default_idx = model_choices.index(str(current.get("model")))
        if accept_all or not self.is_interactive():
            model = current.get("model") if current.get("provider") == provider.key and current.get("model") else provider.default_model
        else:
            model_idx = select_menu(
                model_choices,
                title=f"Modelo por defecto para {provider.title}",
                descriptions=[
                    "Modelo recomendado para empezar." if choice == provider.default_model else (
                        "Escribe tu modelo exacto a mano." if choice == "Custom" else "Opción disponible."
                    )
                    for choice in model_choices
                ],
                icons=["•"] * len(model_choices),
                default=model_default_idx,
                show_index=True,
                footer="↑/↓ elegir modelo · Enter confirmar · número salto directo",
            )
            if model_choices[model_idx] == "Custom":
                custom_model = input(f"Modelo personalizado [{provider.default_model}]: ").strip()
                model = custom_model or provider.default_model
            else:
                model = model_choices[model_idx]

        wrote_secret = False
        if self.is_interactive():
            raw_key = getpass.getpass(f"API key para {provider.title} (Enter para omitir): ").strip()
            if raw_key:
                upsert_env_value(ENV_FILE, env_var, raw_key)
                os.environ[env_var] = raw_key
                wrote_secret = True

        payload = {
            "provider": provider.key,
            "provider_title": provider.title,
            "protocol": provider.protocol,
            "env_var": env_var,
            "base_url": base_url,
            "model": model,
            "docs_url": provider.docs_url,
            "notes": provider.notes,
            "configured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        save_agent_config(AGENT_CONFIG_FILE, payload)

        ok(f"Omni Agent configurado con {provider.title}")
        render_action_summary(
            "Omni Agent",
            [
                f"Provider: {provider.title}",
                f"Protocol: {provider.protocol}",
                f"Model: {model}",
                f"Base URL: {base_url}",
                f"Secret: {'guardado en .env' if wrote_secret else ('ya presente' if env_has_value(ENV_FILE, env_var) else 'pendiente')}",
                f"Docs: {provider.docs_url}",
            ],
            accent=C.PRIMARY,
        )
        hint("Usa `omni chat` para hablar con el agente y permitirle ejecutar comandos `omni` en tu nombre.")

    def run_agent_omni_command(self, command: str) -> Dict[str, Any]:
        normalized = " ".join(str(command or "").strip().split())
        if not normalized.startswith("omni "):
            return {"success": False, "error": "Omni Agent solo puede ejecutar comandos que empiecen por `omni `."}

        argv = shlex.split(normalized)
        if self.is_dry_run():
            return {"success": True, "stdout": "", "stderr": "", "returncode": 0, "command": normalized, "dry_run": True}

        result = subprocess.run(
            [sys.executable, str(APP_DIR / "src" / "omni_core.py"), *argv[1:]],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(APP_DIR),
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": normalized,
            "dry_run": False,
        }

    def chat_cmd(self, prompt: str = "", *, accept_all: bool = False) -> None:
        print_logo(compact=True)
        section("Omni Chat")
        config = load_agent_config(AGENT_CONFIG_FILE)
        if not config:
            render_human_error(
                "Omni Agent todavía no está configurado.",
                suggestion="Ejecuta `omni agent` primero para elegir proveedor, modelo y API key.",
            )
            return

        sync_agent_integrations(AGENT_SKILL_DIR, home_root=Path.home(), repo_root=OMNI_HOME)
        activation_text = ensure_activation_prompt(AGENT_ACTIVATION_FILE)
        api_key = load_env_value(ENV_FILE, str(config.get("env_var", "")))
        if not api_key and str(config.get("provider")) != "ollama-local":
            render_human_error(
                f"Falta la credencial para {config.get('provider_title', config.get('provider', 'Omni Agent'))}.",
                suggestion=f"Guarda {config.get('env_var', 'la API key')} con `omni agent` y vuelve a intentar.",
            )
            return

        CHAT_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        latest_session = max(CHAT_SESSION_DIR.glob("chat-*.json"), default=None, key=lambda path: path.stat().st_mtime if path.exists() else 0)
        if latest_session:
            session = load_chat_session(latest_session)
        else:
            session = new_chat_session(
                CHAT_SESSION_DIR,
                provider_title=str(config.get("provider_title", config.get("provider", "Omni Agent"))),
                model=str(config.get("model", "")),
                base_url=str(config.get("base_url", "")),
                provider_key=str(config.get("provider", "")),
                protocol=str(config.get("protocol", "")),
                activation_file=str(AGENT_ACTIVATION_FILE),
            )
        session_path = Path(session["path"])
        memory_path = CHAT_SESSION_DIR / "memory.json"
        memory = load_chat_memory(
            memory_path,
            fallback=default_chat_memory(
                host_snapshot=self.host_snapshot,
                provider_title=str(config.get("provider_title", config.get("provider", "Omni Agent"))),
                model=str(config.get("model", "")),
                language=str(self.load_global_config().get("language") or "es"),
            ),
        )
        if not any(msg.get("role") == "system" for msg in session.get("messages", [])):
            session.setdefault("messages", []).insert(0, {"role": "system", "content": activation_text})

        interactive_loop = not prompt.strip() and self.is_interactive()
        if interactive_loop:
            hint("Sesión interactiva abierta. Usa /exit para salir, /memory para ver memoria y /clear para limpiar el contexto.")

        pending_prompt = prompt.strip()
        while True:
            user_prompt = pending_prompt
            pending_prompt = ""
            if not user_prompt and self.is_interactive():
                user_prompt = self.prompt_text("Pregunta para Omni Agent", "resume el estado del host y dime el siguiente paso")
            if not user_prompt:
                if interactive_loop:
                    continue
                render_human_error(
                    "Falta el prompt para la sesión de chat.",
                    suggestion="Usa `omni chat \"tu pregunta\"` o abre un TTY interactivo.",
                )
                return

            normalized_prompt = user_prompt.strip()
            if interactive_loop and normalized_prompt.lower() in {"/exit", "exit", "quit", "/quit"}:
                hint("Sesión de Omni Chat cerrada.")
                return
            if interactive_loop and normalized_prompt.lower() in {"/memory", "memory"}:
                render_action_summary(
                    "Memoria activa",
                    build_chat_memory_prompt(memory).splitlines()[:12],
                    accent=C.PRIMARY,
                )
                continue
            if interactive_loop and normalized_prompt.lower() in {"/clear", "clear"}:
                session["messages"] = [{"role": "system", "content": activation_text}]
                memory = default_chat_memory(
                    host_snapshot=self.host_snapshot,
                    provider_title=str(config.get("provider_title", config.get("provider", "Omni Agent"))),
                    model=str(config.get("model", "")),
                    language=str(self.load_global_config().get("language") or "es"),
                )
                save_chat_session(session_path, session)
                save_chat_memory(memory_path, memory)
                ok("Memoria y contexto limpiados.")
                continue

            session.setdefault("messages", []).append({"role": "user", "content": normalized_prompt})
            runtime_messages = list(session["messages"])
            if runtime_messages and runtime_messages[0].get("role") == "system":
                runtime_messages = [runtime_messages[0], {"role": "system", "content": build_chat_memory_prompt(memory)}, *runtime_messages[1:]]
            else:
                runtime_messages.insert(0, {"role": "system", "content": build_chat_memory_prompt(memory)})

            try:
                with Spinner("Consultando Omni Agent...", color=C.PRIMARY) as spinner:
                    completion = chat_completion(
                        protocol=str(config.get("protocol", "")),
                        base_url=str(config.get("base_url", "")),
                        model=str(config.get("model", "")),
                        api_key=api_key,
                        messages=runtime_messages,
                    )
                    spinner.finish("Respuesta recibida", success=True)
            except Exception as err:
                render_human_error(
                    f"El proveedor del agente devolvió un error: {err}",
                    suggestion="Revisa base URL, API key y modelo configurado en `omni agent`.",
                )
                return

            raw_text = str(completion.get("text", "")).strip()
            action = parse_action_block(raw_text)
            clean_text = clean_assistant_output(raw_text)
            if clean_text:
                print(clean_text)
                nl()
            session["messages"].append({"role": "assistant", "content": raw_text})
            memory = record_chat_turn(memory, user_prompt=normalized_prompt, assistant_text=clean_text or raw_text, action=action)
            save_chat_session(session_path, session)
            save_chat_memory(memory_path, memory)

            if not action:
                if interactive_loop:
                    continue
                return

            if action.get("type") != "command":
                render_action_summary(
                    str(action.get("title", "Siguiente paso")),
                    [str(item) for item in action.get("items", [])] or [clean_text or "Sin detalle adicional"],
                    accent=C.PRIMARY,
                )
                if interactive_loop:
                    continue
                return

            command = str(action.get("command", "")).strip()
            if not command:
                if interactive_loop:
                    continue
                return
            render_action_summary(
                str(action.get("title", "Comando sugerido")),
                [command, "Solo se ejecutan comandos que empiecen por `omni `."],
                accent=C.YLW,
            )
            confirm = bool(action.get("confirm", True))
            should_run = accept_all or not confirm or self.confirm_step("¿Ejecuto este comando ahora?", default=False)
            if not should_run:
                warn("Comando sugerido, pero no ejecutado.")
                if interactive_loop:
                    continue
                return

            result = self.run_agent_omni_command(command)
            memory = record_chat_turn(
                memory,
                user_prompt=f"execute:{command}",
                assistant_text=str(result.get("stdout", "") or result.get("stderr", "") or ""),
                action=action,
                command_result=result,
            )
            save_chat_memory(memory_path, memory)
            if not result.get("success"):
                render_human_error(
                    str(result.get("stderr") or result.get("error") or "La ejecución del comando falló."),
                    suggestion="Verifica el comando sugerido o reintenta con un paso más específico.",
                )
                return

            output_lines = (str(result.get("stdout", "")) or "Comando ejecutado sin salida visible.").strip().splitlines()
            render_action_summary(
                "Comando ejecutado",
                [f"Command: {command}", *output_lines[:8]],
                accent=C.GRN,
            )
            session["messages"].append(
                {
                    "role": "user",
                    "content": "Resultado del comando:\n" + (str(result.get("stdout", "")) or str(result.get("stderr", "")) or "Sin salida"),
                }
            )
            try:
                follow_up_messages = list(session["messages"])
                if follow_up_messages and follow_up_messages[0].get("role") == "system":
                    follow_up_messages = [follow_up_messages[0], {"role": "system", "content": build_chat_memory_prompt(memory)}, *follow_up_messages[1:]]
                else:
                    follow_up_messages.insert(0, {"role": "system", "content": build_chat_memory_prompt(memory)})
                follow_up = chat_completion(
                    protocol=str(config.get("protocol", "")),
                    base_url=str(config.get("base_url", "")),
                    model=str(config.get("model", "")),
                    api_key=api_key,
                    messages=follow_up_messages
                    + [{"role": "user", "content": "Explica el resultado anterior en pocas líneas y sugiere el siguiente paso operativo."}],
                )
                follow_up_text = clean_assistant_output(str(follow_up.get("text", "")).strip())
                if follow_up_text:
                    nl()
                    render_action_summary("Siguiente paso", follow_up_text.splitlines()[:8], accent=C.PRIMARY)
                    session["messages"].append({"role": "assistant", "content": str(follow_up.get("text", "")).strip()})
                    memory = record_chat_turn(memory, user_prompt="follow-up", assistant_text=follow_up_text)
                    save_chat_memory(memory_path, memory)
            except Exception:
                pass
            save_chat_session(session_path, session)
            if not interactive_loop:
                return

    def load_global_config(self) -> Dict[str, Any]:
        return load_global_config(GLOBAL_CONFIG_FILE)

    def save_global_config(self, payload: Dict[str, Any]) -> None:
        save_global_config(GLOBAL_CONFIG_FILE, payload)

    def build_briefcase_export(
        self,
        *,
        manifest_path: str = "",
        home_root: str = "",
        profile: str = "",
        full: bool = True,
    ) -> Dict[str, Any]:
        selected_path, manifest = self.resolve_manifest(manifest_path, home_root, create=True, profile=profile or FULL_HOME_PROFILE)
        effective_home_root = home_root or manifest.get("host_root") or str(Path.home())
        report = scan_home(effective_home_root, manifest)
        full_inventory = collect_full_inventory(home_root=effective_home_root) if full else None
        briefcase = build_briefcase_manifest(
            manifest,
            detect_platform_info(),
            inventory_report=report,
            full_inventory=full_inventory,
        )
        return {
            "manifest_path": str(selected_path),
            "briefcase": briefcase,
            "restore_script": build_restore_script(briefcase, fresh_server=True),
        }

    def _briefcase_step(self, title: str, detail: str) -> None:
        bullet(title, C.GRN, bold=True)
        dim(detail)

    def _offer_github_briefcase_sync(self, briefcase_path: Path, *, profile: str = "") -> None:
        config = self.global_config()
        github_cfg = config.get("github") or {}
        token = str(github_cfg.get("token") or "").strip() or gh_cli_token()
        if not token:
            hint(self.t("GitHub no está autenticado todavía. Haz `gh auth login` o `omni auth github` cuando quieras sincronizar la maleta a un repo privado.", "GitHub is not authenticated yet. Run `gh auth login` or `omni auth github` when you want to sync the briefcase to a private repo."))
            return
        if not self.is_interactive():
            hint(self.t("GitHub listo. Ejecuta `omni push --briefcase <archivo>` para subir esta maleta a un repo privado.", "GitHub is ready. Run `omni push --briefcase <file>` to upload this briefcase to a private repo."))
            return
        if not self.confirm_step(self.t("¿Quieres crear o reutilizar un repo privado de GitHub y subir esta maleta ahora?", "Do you want to create or reuse a private GitHub repo and upload this briefcase now?"), default=False):
            return
        try:
            identity = github_identity(token)
        except Exception as err:
            warn(self.t(f"No pude validar la sesión de GitHub: {err}", f"I could not validate the GitHub session: {err}"))
            return
        default_slug = str(github_cfg.get("repo") or f"{identity.get('login', 'omnisync')}/omnisync-briefcases")
        repo_slug = self.prompt_text(self.t("Repo privado de GitHub", "Private GitHub repo"), default_slug)
        config["github"] = {
            "owner": parse_repo_slug(repo_slug, default_owner=str(identity.get("login", ""))).owner,
            "repo": parse_repo_slug(repo_slug, default_owner=str(identity.get("login", ""))).repo,
            "token": token,
            "auth_source": github_cfg.get("auth_source") or ("gh-cli" if not github_cfg.get("token") else github_cfg.get("auth_source", "saved")),
            "authenticated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "user": str(identity.get("login", "")),
        }
        if not self.is_dry_run():
            save_global_config(GLOBAL_CONFIG_FILE, config)
        self.push_cmd(briefcase_path=str(briefcase_path), repo_slug=repo_slug, profile=profile)

    def auth_cmd(self, subaction: str = "", *, repo_slug: str = "") -> None:
        normalized = str(subaction or "").strip().lower()
        if normalized not in {"github", "gh"}:
            render_human_error(
                "Auth provider no soportado.",
                suggestion="Usa `omni auth github` para guardar GitHub OAuth/PAT en ~/.omni/config.json.",
            )
            return

        print_logo(compact=True)
        section("GitHub Auth")
        existing = self.load_global_config().get("github") or {}

        token = os.environ.get("GITHUB_TOKEN", "").strip() or gh_cli_token()
        source = "env" if os.environ.get("GITHUB_TOKEN", "").strip() else "gh-cli"
        if not token and self.is_interactive():
            token = getpass.getpass("GitHub PAT (repo/private repo scope): ").strip()
            source = "pat"
        if not token:
            render_human_error(
                "No encontré un token de GitHub usable.",
                suggestion="Haz `gh auth login` o exporta `GITHUB_TOKEN`, luego corre `omni auth github`.",
            )
            return

        identity = github_identity(token)
        owner = str(identity.get("login") or existing.get("owner") or "").strip()
        resolved_repo = repo_slug or str(existing.get("repo") or "omni-migrate-sync-private")
        target = parse_repo_slug(resolved_repo, default_owner=owner)

        config = self.load_global_config()
        config["github"] = {
            "owner": target.owner,
            "repo": target.repo,
            "token": token,
            "auth_source": source,
            "authenticated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "user": owner,
        }
        if self.is_dry_run():
            warn("Dry run activo: no se persistió ~/.omni/config.json.")
        else:
            self.save_global_config(config)
            ok(f"GitHub auth guardado para {target.slug}")
        render_action_summary(
            "GitHub",
            [
                f"User: {owner}",
                f"Repo: {target.slug}",
                f"Source: {source}",
                f"Config: {GLOBAL_CONFIG_FILE}",
            ],
            accent=C.GRN,
        )

    def push_cmd(self, *, manifest_path: str = "", home_root: str = "", profile: str = "", briefcase_path: str = "", repo_slug: str = "") -> None:
        print_logo(compact=True)
        section("GitHub Push")
        config = self.load_global_config().get("github") or {}
        token = str(config.get("token") or "").strip()
        if not token:
            render_human_error(
                "GitHub auth no está configurado.",
                suggestion="Ejecuta `omni auth github` antes de `omni push`.",
            )
            return

        owner = str(config.get("owner") or "").strip()
        repo_value = repo_slug or str(config.get("repo") or "omni-migrate-sync-private")
        target = parse_repo_slug(repo_value, default_owner=owner)
        ensure_private_repo(target, token=token)

        if briefcase_path:
            briefcase_text = Path(briefcase_path).expanduser().read_text(encoding="utf-8")
            briefcase = json.loads(briefcase_text)
            restore_script = build_restore_script(briefcase, fresh_server=True)
        else:
            export = self.build_briefcase_export(manifest_path=manifest_path, home_root=home_root, profile=profile, full=True)
            briefcase = export["briefcase"]
            briefcase_text = json.dumps(briefcase, indent=2, ensure_ascii=False) + "\n"
            restore_script = str(export["restore_script"])

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        host = socket.gethostname().split(".", 1)[0] or "host"
        briefcase_remote_path = f"briefcases/{stamp}-{host}.json"
        restore_remote_path = f"briefcases/{stamp}-{host}.restore.sh"

        if not self.is_dry_run():
            put_file(target, briefcase_remote_path, briefcase_text, token=token, message=f"Add briefcase {stamp} from {host}")
            put_file(target, restore_remote_path, restore_script, token=token, message=f"Add restore script {stamp} from {host}")
        else:
            warn("Dry run activo: no se subieron archivos a GitHub.")
        render_action_summary(
            "GitHub Push",
            [
                f"Repo: {target.slug}",
                f"Briefcase: {briefcase_remote_path}",
                f"Restore: {restore_remote_path}",
            ],
            accent=C.GRN,
        )

    def pull_cmd(self, *, output: str = "", apply_restore: bool = False, repo_slug: str = "") -> None:
        print_logo(compact=True)
        section("GitHub Pull")
        config = self.load_global_config().get("github") or {}
        token = str(config.get("token") or "").strip()
        if not token:
            render_human_error(
                "GitHub auth no está configurado.",
                suggestion="Ejecuta `omni auth github` antes de `omni pull`.",
            )
            return

        owner = str(config.get("owner") or "").strip()
        repo_value = repo_slug or str(config.get("repo") or "omni-migrate-sync-private")
        target = parse_repo_slug(repo_value, default_owner=owner)
        entries = list_directory(target, "briefcases", token=token)
        latest = latest_briefcase_entry(entries)
        if not latest:
            render_human_error(
                "No encontré briefcases en el repo privado.",
                suggestion="Empuja uno primero con `omni push`.",
            )
            return

        download_dir = Path(output).expanduser() if output else (OMNI_HOME / "imports")
        download_dir.mkdir(parents=True, exist_ok=True)
        briefcase_path = download_dir / str(latest.get("name"))
        briefcase_text = "" if self.is_dry_run() else download_text(target, str(latest.get("path")), token=token)
        if not self.is_dry_run():
            briefcase_path.write_text(briefcase_text, encoding="utf-8")

        restore_name = briefcase_path.name.replace(".json", ".restore.sh")
        restore_entry = next((entry for entry in entries if str(entry.get("name")) == restore_name), None)
        restore_path = download_dir / restore_name
        if restore_entry:
            if not self.is_dry_run():
                restore_text = download_text(target, str(restore_entry.get("path")), token=token)
                restore_path.write_text(restore_text, encoding="utf-8")
                restore_path.chmod(0o755)

        render_action_summary(
            "GitHub Pull",
            [
                f"Repo: {target.slug}",
                f"Briefcase: {briefcase_path}",
                f"Restore script: {restore_path if restore_entry else 'missing'}",
            ],
            accent=C.GRN,
        )

        if self.is_dry_run():
            warn("Dry run activo: no se descargaron archivos ni se ejecutó restore.")
            return

        if apply_restore and restore_entry and not self.is_dry_run():
            result = subprocess.run(["bash", str(restore_path)], capture_output=True, text=True, check=False)
            if result.returncode != 0:
                render_human_error(
                    result.stderr or result.stdout or "El restore script descargado falló.",
                    suggestion="Revisa el host destino o ejecuta `omni restore-plan --briefcase <archivo>`.",
                )
                return
            render_action_summary(
                "Restore aplicado",
                (result.stdout or "Restore script ejecutado.").strip().splitlines()[:8],
                accent=C.GRN,
            )

    def show_help(self):
        """Show help menu."""
        print()
        render_help_surface(
            self.host_snapshot,
            [
                "Quickstart: omni  |  omni guide  |  omni connect --host <ip> --user <user>",
                "Maleta portable: omni briefcase --full --output ~/briefcase.json",
                "Migration path: SSH Connect -> Maleta -> Restore -> Migrate Sync",
                "Keep secrets out of git: API keys and SSH material stay in the encrypted bundle",
            ],
            version=OMNI_VERSION,
            codename=OMNI_CODENAME,
            tagline=random.choice(_TAGLINES),
        )
        print()
        section("Common Flows")
        bullet("Mover un host completo  -> omni start -> Migrate Sync", C.GRN)
        dim("Omni genera maleta, restore script, bundles y deja el destino listo.")
        bullet("Conectar dos máquinas por SSH  -> omni start -> SSH Connect", C.GRN)
        dim("Ideal para enviar el payload directo al destino con Paramiko + SFTP.")
        bullet("Crear maleta portable  -> omni briefcase --full", C.GRN)
        dim("Genera inventory real, contrato portable y restore shell script.")
        bullet("Configurar Omni Agent  -> omni agent", C.GRN)
        dim("Selector visual para Claude, GPT, Gemini, Mistral, Ollama o endpoint compatible.")
        bullet("Hablar con Omni Agent  -> omni chat \"resume el host\"", C.GRN)
        dim("Puede ejecutar comandos `omni`, explicar salida y proponer el siguiente paso.")
        bullet("Abrir el launchpad operativo  -> omni guide", C.GRN)
        dim("Menú con flechas, ETA y acceso a SSH Connect / Maleta / Restore / Agent.")
        bullet("Retomar el último paso  -> omni continue", C.GRN)
        dim("Reutiliza el último intento guardado de SSH Connect sin pedirte todo de nuevo.")
        nl()

        section("OmniSync - Command Reference")

        print("  " + q(C.W, "CORE COMMANDS", bold=True))
        nl()
        bullet("omni check     - Run health check and report", C.GRN)
        bullet("omni fix       - Run full system fix", C.GRN)
        bullet("omni watch     - Watch managed files and auto-backup on change", C.GRN)
        bullet("omni status    - Show system status", C.GRN)
        bullet("omni logs      - View Omni logs", C.GRN)
        bullet("omni doctor    - Run the guided health and recovery audit", C.GRN)
        bullet("omni capture   - Build a full recovery pack from the active profile", C.GRN)
        bullet("omni restore   - Restore from latest bundle + secrets", C.GRN)
        bullet("omni migrate   - Rebuild this host end to end", C.GRN)
        bullet("omni guide     - Open the interactive Omni launchpad", C.GRN)
        bullet("omni continue  - Resume the last saved guided operation", C.GRN)
        bullet("omni commands  - Show this command center explicitly", C.GRN)
        bullet("omni connect   - Probe a remote host and send the migration payload", C.GRN)
        bullet("omni briefcase - Build the portable migration contract", C.GRN)
        dim("    Guarda la maleta y el restore script en ~/.omni/exports aunque no pases --output.")
        bullet("omni restore-plan - Derive the target-side restore sequence", C.GRN)
        bullet("omni migrate sync - Use the new migration family around the briefcase contract", C.GRN)
        bullet("omni chat      - Talk to Omni Agent and let it run safe `omni` actions", C.GRN)
        bullet("omni auth github - Save GitHub auth for private briefcase sync", C.GRN)
        bullet("omni push      - Push the latest briefcase to the private GitHub repo", C.GRN)
        bullet("omni pull      - Pull the latest briefcase from GitHub on a new host", C.GRN)
        nl()

        print("  " + q(C.W, "ADVANCED COMMANDS", bold=True))
        nl()
        bullet("omni restart   - Restart PM2 services", C.PRIMARY)
        bullet("omni backup    - Create system backup", C.PRIMARY)
        bullet("omni transfer  - Transfer files to remote", C.PRIMARY)
        bullet("omni config    - Show configuration or set `omni config language <es|en>`", C.PRIMARY)
        bullet("omni version   - Show version info", C.PRIMARY)
        bullet("omni monitor   - Continuous monitoring mode", C.PRIMARY)
        bullet("omni clean     - Clean temp files and caches", C.PRIMARY)
        bullet("omni repos     - Show repository status", C.PRIMARY)
        bullet("omni processes - Show PM2 processes", C.PRIMARY)
        bullet("omni install   - Show portable install guide", C.PRIMARY)
        bullet("omni init      - Create missing local config/runtime files", C.PRIMARY)
        dim("    Use `omni init --profile full-home` for a full /home/ubuntu capture")
        bullet("omni sync      - Pull snapshots from configured servers", C.PRIMARY)
        bullet("omni inventory - Classify host state vs. secrets vs. noise", C.PRIMARY)
        bullet("omni briefcase - Export portable migration metadata", C.PRIMARY)
        bullet("omni restore-plan - Preview restore blocks for this target host", C.PRIMARY)
        bullet("omni migrate sync - New public surface for create/plan/capture/restore", C.PRIMARY)
        bullet("omni bundle-create - Export state bundle from the active profile", C.PRIMARY)
        bullet("omni bundle-restore - Restore latest or explicit state bundle", C.PRIMARY)
        bullet("omni secrets-export - Export encrypted secrets pack", C.PRIMARY)
        bullet("omni secrets-import - Import encrypted secrets pack", C.PRIMARY)
        bullet("omni reconcile - Rebuild host from manifest + bundles", C.PRIMARY)
        bullet("omni detect-ip - Detect current host identity", C.PRIMARY)
        bullet("omni rewrite-ip - Rewrite old host references safely", C.PRIMARY)
        bullet("omni agent     - Configure Omni Agent provider and model", C.PRIMARY)
        bullet("omni chat      - Run the conversational agent surface", C.PRIMARY)
        bullet("omni auth      - Configure GitHub auth for push/pull", C.PRIMARY)
        bullet("omni push      - Upload briefcase + restore script to GitHub", C.PRIMARY)
        bullet("omni pull      - Download latest GitHub briefcase locally", C.PRIMARY)
        bullet("omni bridge    - Create/send/receive migration packs", C.PRIMARY)
        bullet("omni timer-install - Install daily timer + change watcher service", C.PRIMARY)
        bullet("omni purge - Delete transferred state and repo artifacts to free disk", C.PRIMARY)
        nl()

        print("  " + q(C.W, "ALIASES", bold=True))
        nl()
        dim("  s=status  f=fix  w=watch  c=check  r=restart  l=logs")
        dim("  t=transfer  b=backup  m=monitor  cfg=config  commands=help")
        nl()

        print("  " + q(C.W, "OPTIONS", bold=True))
        nl()
        bullet("--verbose, -v   Enable verbose output", C.G3)
        bullet("--debug         Enable debug mode", C.G3)
        bullet("--interval      Watch mode interval (seconds)", C.G3)
        bullet("--lines         Number of log lines", C.G3)
        bullet("--follow, -f    Follow logs (tail -f)", C.G3)
        bullet("--protocol      Transfer protocol (scp|rsync)", C.G3)
        bullet("--compress      Enable compression for transfer", C.G3)
        bullet("--manifest      System manifest path", C.G3)
        bullet("--profile       Manifest profile (production-clean|full-home)", C.G3)
        bullet("--output        Output file or directory", C.G3)
        bullet("--restore-script  Output path for generated restore shell script", C.G3)
        bullet("--language      Preferred UI language for `omni config` (es|en)", C.G3)
        bullet("--bundle        Explicit state bundle path", C.G3)
        bullet("--secrets       Explicit secrets bundle path", C.G3)
        bullet("--target-root   Restore target root", C.G3)
        bullet("--passphrase-env  Env var containing secrets passphrase", C.G3)
        bullet("--dry-run       Preview changes without mutating host or remote target", C.G3)
        bullet("--full          Capture the full maleta inventory and restore script", C.G3)
        bullet("--yes           Confirm destructive purge", C.G3)
        bullet("--include-secrets  Include secret paths in purge", C.G3)
        nl()

        hr()
        bullet("Migration: inventory -> bundle -> secrets -> reconcile -> timer", C.G3)
        bullet("Quickstart: curl -fsSL https://raw.githubusercontent.com/sxrubyo/omnisync/main/install.sh | bash", C.G3)
        bullet("Default entrypoint: run `omni` and choose SSH Connect / Maleta / Restore / Migrate Sync", C.G3)
        print("  " + q(C.G3, f"OmniSync v{OMNI_VERSION} '{OMNI_CODENAME}'"))
        print("  " + q(C.G3, "Run 'omni <command>' to execute"))
        print()

    def init_workspace(self, profile: str = ""):
        bootstrap_mode = os.environ.get("OMNI_BOOTSTRAP_INIT", "").strip().lower() in {"1", "true", "yes", "on"}
        if not bootstrap_mode:
            print_logo(compact=True)
            render_help_overview()
            section("Workspace Init")

        requested_profile = str(profile or "").strip().lower().replace("_", "-")
        manifest_path = CONFIG_DIR / "system_manifest.json"
        manifest_was_present = manifest_path.exists()
        workspace_changed = False

        for path in (OMNI_HOME, CONFIG_DIR, STATE_DIR, BACKUP_DIR, BUNDLE_DIR, AUTO_BUNDLE_DIR, LOG_DIR):
            path.mkdir(parents=True, exist_ok=True)

        template_pairs = [
            (OMNI_HOME / ".env", OMNI_HOME / ".env.example"),
            (CONFIG_DIR / "repos.json", CONFIG_DIR / "repos.example.json"),
            (CONFIG_DIR / "servers.json", CONFIG_DIR / "servers.example.json"),
            (CONFIG_DIR / "system_manifest.json", CONFIG_DIR / "system_manifest.example.json"),
        ]

        created: List[Path] = []
        existing: List[Path] = []
        missing_templates: List[Path] = []

        for target, template in template_pairs:
            if target.exists():
                existing.append(target)
                continue
            if template.exists():
                shutil.copy2(template, target)
                created.append(target)
                workspace_changed = True
            else:
                missing_templates.append(template)

        manifest_path = CONFIG_DIR / "system_manifest.json"
        if profile and manifest_path in created:
            save_manifest(manifest_path, build_default_manifest(str(Path.home()), profile=profile))

        if not TASKS_FILE.exists():
            TASKS_FILE.write_text("[]\n", encoding="utf-8")
            created.append(TASKS_FILE)
        else:
            existing.append(TASKS_FILE)

        if requested_profile:
            manifest = build_default_manifest(str(Path.home()), profile=requested_profile)
            save_manifest(manifest_path, manifest)
            if manifest_path in created:
                created.remove(manifest_path)
            if manifest_path in existing:
                existing.remove(manifest_path)
            if manifest_was_present:
                existing.append(manifest_path)
            else:
                created.append(manifest_path)
            workspace_changed = True
            if not bootstrap_mode:
                ok(f"Activated profile {manifest['profile']} in {manifest_path}")

        servers_path = CONFIG_DIR / "servers.json"
        if servers_path.exists():
            try:
                payload = json.loads(servers_path.read_text(encoding="utf-8"))
                servers = payload.get("servers", []) if isinstance(payload, dict) else []
                host_identity = detect_host_identity()
                replacement_host = host_identity.public_ip or host_identity.private_ip or host_identity.hostname
                changed = False
                if replacement_host:
                    for server in servers:
                        if str(server.get("host", "")).strip() == "1.2.3.4":
                            server["host"] = replacement_host
                            changed = True
                    if changed:
                        servers_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                        self.servers = self.load_servers()
                        workspace_changed = True
                        if not bootstrap_mode:
                            ok(f"Updated placeholder host in {servers_path} -> {replacement_host}")
            except Exception as err:
                if not bootstrap_mode:
                    warn(f"Failed to normalize servers.json automatically: {err}")

        if not bootstrap_mode:
            for path in created:
                ok(f"Created {path}")
            for path in existing:
                dim(f"Already present: {path}")
            for path in missing_templates:
                warn(f"Template not found: {path}")

        if workspace_changed and AUTO_BACKUP_ON_CHANGE and not bootstrap_mode:
            info("Creando backup automático post-init...")
            self.run_backup(profile=requested_profile or profile)

        sync_report = sync_agent_integrations(AGENT_SKILL_DIR, home_root=Path.home(), repo_root=OMNI_HOME)
        linked_targets = sum(len(item.written) for item in sync_report["integrations"])
        if linked_targets and not bootstrap_mode:
            ok(f"Agent integrations refreshed across {linked_targets} target files.")

        if not bootstrap_mode:
            nl()
            bullet("Next steps", C.PRIMARY, bold=True)
            dim("1. Edit .env and config/*.json if needed")
            if requested_profile:
                dim(f"2. Manifest profile active: {requested_profile}")
                dim("3. Run ./install.sh --compose --sync --timer")
                dim("4. Validate with omni status and omni inventory")
            else:
                dim("2. Run ./install.sh --compose --sync --timer")
                dim("3. Validate with omni status and omni inventory")
            nl()

    def start_guided(self, *, accept_all: bool = False) -> None:
        info_obj = detect_platform_info()
        effective_accept_all = should_accept_all(accept_all=accept_all, env=os.environ)
        chosen_flow = ""
        requested_flow_raw = os.environ.get("OMNI_START_FLOW", "").strip()
        requested_flow = normalize_flow_choice(requested_flow_raw) if requested_flow_raw else ""
        profile = self.normalize_profile("")
        if self.manifest_path.exists():
            try:
                profile = self.normalize_profile(load_manifest(self.manifest_path, str(Path.home())).get("profile", DEFAULT_PROFILE))
            except Exception:
                profile = self.normalize_profile("")

        print()
        render_guided_start_surface(
            self.host_snapshot,
            [
                "Quickstart: omni  |  omni guide  |  omni connect --host <ip> --user <user>",
                "Maleta portable: omni briefcase --full --output ~/briefcase.json",
                "Ruta recomendada: SSH Connect -> Maleta -> Restore -> Migrate Sync",
                "Secretos fuera de git: tokens y material SSH se quedan en el bundle cifrado.",
            ],
            version=OMNI_VERSION,
            codename=OMNI_CODENAME,
            mode="accept-all" if effective_accept_all else "guided",
            scope=profile,
        )
        print()
        scan_root = str(Path.home())
        if self.manifest_path.exists():
            try:
                scan_root = str(load_manifest(self.manifest_path, str(Path.home())).get("host_root", scan_root))
            except Exception:
                pass
        self.render_host_drift_summary(self.build_host_drift_report(root=scan_root), compact=True)
        nl()
        flow_options = build_flow_options(info_obj)

        if requested_flow:
            chosen_flow = requested_flow
            info(f"Using OMNI_START_FLOW={chosen_flow}")
        elif effective_accept_all or not self.is_interactive():
            warn("No interactive terminal detected for `omni start`.")
            hint("Use an explicit command such as `omni capture --accept-all` or set OMNI_START_FLOW.")
            return
        else:
            recommended_idx = next((idx for idx, option in enumerate(flow_options) if option.recommended), 0)
            labels = [option.title for option in flow_options]
            icons = ["🛫", "📦", "♻️", "🚚", "🩺", "🧠", "⚙️", "🧰"]
            descriptions = []
            for option in flow_options:
                suffix = " Recomendado en este host." if option.recommended else ""
                descriptions.append(option.description + suffix)
            try:
                selected = select_menu(
                    labels,
                    title="¿Qué quieres hacer primero?",
                    descriptions=descriptions,
                    icons=icons,
                    default=recommended_idx,
                    show_index=True,
                    footer="↑/↓ elegir flujo · Enter confirmar · número salto directo",
                )
            except KeyboardInterrupt:
                raise
            chosen_flow = flow_options[selected].key

        if chosen_flow in {"briefcase", "restore", "migrate-sync"}:
            profile = self.choose_profile(accept_all=effective_accept_all, current_profile=profile)

        if chosen_flow == "advanced":
            self.show_help()
            return
        if chosen_flow == "connect":
            self.connect_cmd(profile=profile or FULL_HOME_PROFILE)
            return
        if chosen_flow == "briefcase":
            self.show_briefcase(profile=profile or FULL_HOME_PROFILE, full=True)
            return
        if chosen_flow == "restore":
            self.restore_host_cmd(accept_all=effective_accept_all, install_timer=effective_accept_all, profile=profile)
            return
        if chosen_flow == "migrate-sync":
            self.migrate_sync_cmd(
                "create",
                accept_all=effective_accept_all,
                profile=profile or FULL_HOME_PROFILE,
                full=True,
            )
            return
        if chosen_flow == "doctor":
            self.show_doctor()
            return
        if chosen_flow == "agent":
            self.agent_cmd(accept_all=effective_accept_all)
            return
        if chosen_flow == "chat":
            self.chat_cmd("")
            return
        self.show_help()

    def guide_cmd(self) -> None:
        print_logo(tagline=False)
        render_command_header(
            "Omni Guide",
            "Launchpad con flechas para conectar, empaquetar, restaurar y delegar.",
            dry_run=self.is_dry_run(),
            snapshot=self.host_snapshot,
        )
        entries = build_guide_entries()
        if not self.is_interactive():
            section("Guide")
            for entry in entries:
                bullet(f"{entry.title} · ETA {entry.estimated_time}", C.GRN)
                dim(f"{entry.description} :: {entry.command}")
            return

        selected = select_menu(
            [entry.title for entry in entries],
            title="Selecciona el flujo que quieres ejecutar",
            descriptions=[f"{entry.description} · ETA {entry.estimated_time}" for entry in entries],
            icons=["🔐", "🧳", "♻️", "🧠", "🚚"],
            default=0,
            show_index=True,
            footer="↑/↓ elegir flujo · Enter confirmar",
        )
        entry = entries[selected]
        info(f"Abriendo {entry.title}")
        if entry.key == "connect":
            self.connect_cmd()
            return
        if entry.key == "briefcase":
            self.show_briefcase(profile=self.normalize_profile("full-home"), full=True)
            return
        if entry.key == "restore":
            self.restore_host_cmd(accept_all=self.is_dry_run())
            return
        if entry.key == "agent":
            self.agent_cmd(accept_all=False)
            return
        self.migrate_sync_cmd("create", profile=self.normalize_profile("full-home"), full=True)

    def connect_cmd(
        self,
        *,
        host: str = "",
        user: str = "",
        port: int | None = None,
        key_path: str = "",
        remote_path: str = "",
        transport: str = "rsync",
        route: str = "",
        target_system: str = "",
        auth_mode: str = "",
        password_env: str = "OMNI_SSH_PASSWORD",
        briefcase_path: str = "",
        manifest_path: str = "",
        home_root: str = "",
        profile: str = "",
    ) -> None:
        print_logo(compact=True)
        render_command_header(
            "SSH Connect",
            "Sonda el host remoto y mueve la maleta segura por SSH.",
            dry_run=self.is_dry_run(),
            snapshot=self.host_snapshot,
        )
        section("Conexión remota")

        pending_state = self.pending_continue_state("connect")
        has_explicit_overrides = any(
            [
                host,
                user,
                key_path,
                briefcase_path,
                manifest_path,
                home_root,
                profile,
                route,
                auth_mode,
                target_system,
                remote_path,
            ]
        )
        edit_saved_connection = False
        if pending_state and self.is_interactive() and not has_explicit_overrides:
            pending_params = pending_state.get("params") if isinstance(pending_state.get("params"), dict) else {}
            selected_resume = select_menu(
                [
                    self.t("Reanudar conexión guardada", "Resume saved connection"),
                    self.t("Editar conexión guardada", "Edit saved connection"),
                    self.t("Empezar una conexión nueva", "Start a new connection"),
                ],
                title=self.t("Encontré una conexión pendiente", "I found a pending connection"),
                descriptions=[
                    self.t(
                        f"Retoma {pending_params.get('user', '')}@{pending_params.get('host', '')}:{pending_params.get('port', 22)} sin volver a teclear host, usuario o puerto.",
                        f"Resume {pending_params.get('user', '')}@{pending_params.get('host', '')}:{pending_params.get('port', 22)} without typing host, user or port again.",
                    ),
                    self.t(
                        "Carga host, usuario, puerto y auth anteriores como base, pero te deja corregirlos antes de reconectar.",
                        "Load the previous host, user, port and auth as defaults, but let you edit them before reconnecting.",
                    ),
                    self.t("Descarta el checkpoint actual y vuelve a comenzar.", "Discard the current checkpoint and start over."),
                ],
                icons=["🧭", "✏️", "🆕"],
                default=0,
                show_index=True,
                footer=self.t("↑/↓ elegir ruta · Enter confirmar", "↑/↓ choose path · Enter confirm"),
            )
            if selected_resume == 0:
                host = str(pending_params.get("host", host))
                user = str(pending_params.get("user", user))
                port = int(pending_params.get("port", port) or port)
                key_path = str(pending_params.get("key_path", key_path))
                remote_path = str(pending_params.get("remote_path", remote_path))
                transport = str(pending_params.get("transport", transport or "auto"))
                route = str(pending_params.get("route", route))
                target_system = str(pending_params.get("target_system", target_system))
                auth_mode = str(pending_params.get("auth_mode", auth_mode))
                password_env = str(pending_params.get("password_env", password_env))
                briefcase_path = str(pending_params.get("briefcase_path", briefcase_path))
                manifest_path = str(pending_params.get("manifest_path", manifest_path))
                home_root = str(pending_params.get("home_root", home_root))
                profile = str(pending_params.get("profile", profile))
                info(self.t("Reanudo el último intento guardado.", "Resuming the last saved attempt."))
            elif selected_resume == 1:
                host = str(pending_params.get("host", host))
                user = str(pending_params.get("user", user))
                port = int(pending_params.get("port", port) or port)
                key_path = str(pending_params.get("key_path", key_path))
                remote_path = str(pending_params.get("remote_path", remote_path))
                transport = str(pending_params.get("transport", transport or "auto"))
                route = str(pending_params.get("route", route))
                target_system = str(pending_params.get("target_system", target_system))
                auth_mode = str(pending_params.get("auth_mode", auth_mode))
                password_env = str(pending_params.get("password_env", password_env))
                briefcase_path = str(pending_params.get("briefcase_path", briefcase_path))
                manifest_path = str(pending_params.get("manifest_path", manifest_path))
                home_root = str(pending_params.get("home_root", home_root))
                profile = str(pending_params.get("profile", profile))
                edit_saved_connection = True
                info(self.t("Cargo la conexión anterior para que la edites antes de reintentar.", "Loading the previous connection so you can edit it before retrying."))
            else:
                self.clear_continue_state("connect")

        resolved_route = str(route or "").strip().lower().replace("-", "_")
        if not resolved_route and host and not edit_saved_connection:
            resolved_route = "direct"
        if self.is_interactive() and not resolved_route:
            route_options = [
                ("tailscale", "Tailscale / MagicDNS", "Recomendado si ambos hosts están en la misma tailnet. Usa IP 100.x o nombre MagicDNS."),
                ("direct", "Directo (IP pública / LAN)", "Usa IP pública, IP privada de la LAN o DNS normal cuando ya existe ruta directa."),
            ]
            selected_route = select_menu(
                [title for _, title, _ in route_options],
                title=self.t("¿Cómo quieres llegar al host remoto?", "How do you want to reach the remote host?"),
                descriptions=[description for _, _, description in route_options],
                icons=["🪄", "🌐"],
                default=0,
                show_index=True,
                footer=self.t("↑/↓ elegir ruta · Enter confirmar", "↑/↓ choose path · Enter confirm"),
            )
            resolved_route = route_options[selected_route][0]
        if resolved_route not in {"", "direct", "tailscale"}:
            resolved_route = "direct"

        resolved_target_system = normalize_remote_system(target_system)
        if resolved_route == "tailscale":
            host_prompt = self.t(
                "Destino Tailscale (100.x o MagicDNS, opcional :puerto)",
                "Tailscale destination (100.x or MagicDNS, optional :port)",
            )
        else:
            host_prompt = self.t(
                "Destino SSH (host o IP, opcional :puerto)",
                "SSH destination (host or IP, optional :port)",
            )
        explicit_port_provided = port is not None
        default_host_value = host
        if host and explicit_port_provided and int(port or 22) != 22 and ":" not in host and not host.endswith("]"):
            default_host_value = f"{host}:{int(port or 22)}"
        if self.is_interactive() and edit_saved_connection:
            resolved_host_raw = self.prompt_text(host_prompt, default_host_value)
        else:
            resolved_host_raw = host or self.prompt_text(host_prompt, "")
        host_includes_port = False
        resolved_host, parsed_port = split_host_and_port(resolved_host_raw, int(port or 22))
        raw_host_value = str(resolved_host_raw or "").strip()
        if raw_host_value.startswith("[") and "]:" in raw_host_value:
            host_includes_port = True
        elif raw_host_value.count(":") == 1:
            host_part, port_part = raw_host_value.rsplit(":", 1)
            host_includes_port = bool(host_part) and port_part.isdigit()

        default_user = user or getpass.getuser()
        if self.is_interactive() and edit_saved_connection:
            resolved_user = self.prompt_text("Usuario SSH", default_user)
        else:
            resolved_user = user or self.prompt_text("Usuario SSH", getpass.getuser())

        if self.is_interactive() and (edit_saved_connection or (not host_includes_port and not explicit_port_provided)):
            raw_port = self.prompt_text("Puerto SSH", str(parsed_port or 22)).strip()
            try:
                resolved_port = int(raw_port or parsed_port or 22)
            except ValueError:
                render_human_error(
                    "El puerto SSH debe ser numérico.",
                    suggestion="Usa un entero como `22`, `2222` o `8022`.",
                )
                return
        else:
            resolved_port = parsed_port

        default_auth_mode = str(auth_mode or ("key" if key_path else "password")).strip().lower()
        resolved_auth_mode = default_auth_mode
        if self.is_interactive() and (not auth_mode or edit_saved_connection):
            auth_options = [
                ("password", "Contraseña", "Solo pide host, usuario y contraseña. Ideal para mover rápido a otro host."),
                ("agent", "SSH Agent / clave cargada", "Usa la identidad ya cargada en ssh-agent o el método por defecto del sistema."),
                ("key", "Llave OpenSSH / PEM", "Ideal para AWS, Ubuntu cloud y la mayoría de servidores Linux modernos."),
                ("ppk", "PuTTY .ppk", "Útil en Windows/PuTTY. Omni intentará convertirla o te guiará paso a paso."),
            ]
            default_auth_index = 0
            for index, (value, _, _) in enumerate(auth_options):
                if value == resolved_auth_mode:
                    default_auth_index = index
                    break
            selected_auth = select_menu(
                [title for _, title, _ in auth_options],
                title="Método de conexión SSH",
                descriptions=[description for _, _, description in auth_options],
                icons=["🔑", "🪪", "🗝️", "🧷"],
                default=default_auth_index,
                show_index=True,
                footer="↑/↓ elegir método · Enter confirmar · número salto directo",
            )
            resolved_auth_mode = auth_options[selected_auth][0]

        default_key = ""
        for candidate in (Path.home() / ".ssh" / "id_ed25519", Path.home() / ".ssh" / "id_rsa"):
            if candidate.exists():
                default_key = str(candidate)
                break

        resolved_key_path = str(Path(key_path).expanduser()) if key_path else ""
        resolved_password: str | None = os.environ.get(password_env, "").strip() if password_env else ""

        checkpoint_key_path = str(Path(key_path).expanduser()) if key_path else ""
        identity_display = ""

        if resolved_auth_mode in {"key", "ppk"}:
            if not resolved_key_path:
                prompt_label = "Ruta de llave (.pem / OpenSSH / .ppk)"
                resolved_key_path = self.prompt_text(prompt_label, default_key)
            key_file = Path(resolved_key_path).expanduser()
            if not key_file.exists() or key_file.is_dir():
                render_human_error(
                    "La ruta indicada no parece una clave privada SSH válida.",
                    suggestion="Elige `Contraseña`, `SSH Agent / clave cargada` o una ruta válida a `.pem`, OpenSSH o `.ppk`.",
                )
                return
            checkpoint_key_path = str(key_file)
            resolved_key_path = str(key_file)
            identity_display = resolved_key_path
            if resolved_auth_mode == "ppk" or resolved_key_path.lower().endswith(".ppk"):
                puttygen_bin = shutil.which("puttygen") or shutil.which("puttygen.exe")
                if puttygen_bin:
                    temp_key_dir = Path(tempfile.mkdtemp(prefix="omni-ppk-"))
                    converted_key = temp_key_dir / f"{key_file.stem}.openssh"
                    conversion = subprocess.run(
                        [puttygen_bin, str(key_file), "-O", "private-openssh", "-o", str(converted_key)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if conversion.returncode != 0 or not converted_key.exists():
                        render_human_error(
                            "No pude convertir la llave `.ppk` a OpenSSH automáticamente.",
                            suggestion=self.t(
                                "Abre PuTTYgen -> Conversions -> Export OpenSSH key, o instala `puttygen` que soporte `-O private-openssh`.",
                                "Open PuTTYgen -> Conversions -> Export OpenSSH key, or install `puttygen` with `-O private-openssh` support.",
                            ),
                        )
                        return
                    resolved_key_path = str(converted_key)
                    identity_display = f"{checkpoint_key_path} -> OpenSSH temporal"
                else:
                    render_human_error(
                        "La llave `.ppk` necesita convertirse a OpenSSH antes de usar Paramiko.",
                        suggestion=self.t(
                            "PuTTY docs: load the `.ppk` in PuTTYgen y usa Conversions -> Export OpenSSH key. Luego vuelve con esa ruta.",
                            "PuTTY docs: load the `.ppk` in PuTTYgen and use Conversions -> Export OpenSSH key. Then come back with that file path.",
                        ),
                    )
                    return
            resolved_auth_mode = "key"
            resolved_password = None
        elif resolved_auth_mode == "agent":
            resolved_key_path = ""
            resolved_password = None
        else:
            if not resolved_password and self.is_interactive():
                try:
                    resolved_password = getpass.getpass("Contraseña SSH: ").strip()
                except KeyboardInterrupt:
                    print()
                    raise
            if not self.is_dry_run() and not resolved_password:
                render_human_error(
                    "No recibí una contraseña SSH para el modo password.",
                    suggestion=f"Escríbela cuando Omni la pida, exporta `{password_env}` o cambia a `SSH Agent / clave cargada`.",
                )
                return
            resolved_key_path = ""

        resolved_transport = "sftp"

        if not resolved_host:
            render_human_error(
                "Falta el host remoto para iniciar la conexión.",
                suggestion="Usa `omni connect --host <ip|fqdn> --user <usuario>` o escribe `host:puerto` en el primer campo.",
            )
            return

        target = SSHDestination(
            host=resolved_host,
            user=resolved_user or getpass.getuser(),
            port=resolved_port,
            key_path=resolved_key_path,
            auth_mode=resolved_auth_mode,
            password=resolved_password,
            target_system=resolved_target_system,
        )
        checkpoint_params = {
            "host": target.host,
            "user": target.user,
            "port": target.port,
            "key_path": checkpoint_key_path,
            "route": resolved_route or "direct",
            "auth_mode": resolved_auth_mode,
            "password_env": password_env,
            "target_system": resolved_target_system or "auto",
            "remote_path": remote_path or "~/omni-transfer",
            "transport": resolved_transport,
            "briefcase_path": briefcase_path,
            "manifest_path": manifest_path,
            "home_root": home_root,
            "profile": profile or FULL_HOME_PROFILE,
        }
        self.save_continue_state(flow="connect", status="probe_pending", params=checkpoint_params)
        kv("Target", target.target(), color=C.GRN)
        kv("Route", resolved_route or "direct", color=C.GRN)
        kv("Remote OS", resolved_target_system or "auto", color=C.GRN)
        kv("Transport", "paramiko+sftp", color=C.GRN)
        kv("Remote Path", remote_path or "~/omni-transfer", color=C.GRN)
        kv("Auth", resolved_auth_mode, color=C.GRN)
        if target.key_path:
            kv("Identity", identity_display or target.key_path, color=C.GRN)
        elif resolved_auth_mode == "agent":
            kv("Identity", self.t("ssh-agent / identidad por defecto", "ssh-agent / default identity"), color=C.GRN)
        elif resolved_auth_mode == "password":
            identity_hint = self.t("contraseña SSH", "SSH password")
            kv("Identity", identity_hint, color=C.GRN)
        nl()

        if self.is_dry_run():
            warn("Dry run activo: no se abrirá la conexión SSH ni se transferirán archivos.")
            return

        def run_remote_probe(active_target: SSHDestination) -> Dict[str, Any]:
            info(self.t("Paso 1/3 · Validando acceso SSH y detectando el host remoto.", "Step 1/3 · Validating SSH access and detecting the remote host."))
            with Spinner("Sondeando host remoto...", color=C.PRIMARY) as spinner:
                probe_timeout = 45 if resolved_auth_mode == "password" else (12 if resolved_target_system == "auto" else 20)
                payload = probe_remote_host(active_target, timeout=probe_timeout)
                spinner.finish("Host remoto detectado", success=True)
                return payload

        def maybe_prepare_reverse_tunnel() -> SSHDestination | None:
            relay_host_default = suggest_relay_host()
            relay_user_default = getpass.getuser()
            relay_ssh_port_default = 22
            relay_bind_port_default = random.randint(46022, 46999)
            device_ssh_port_default = int(resolved_port or 8022)

            relay_host_value = self.prompt_text(
                self.t("Host del relay (tu servidor público o Tailscale)", "Relay host (your public server or Tailscale node)"),
                relay_host_default,
            )
            relay_user_value = self.prompt_text(self.t("Usuario del relay", "Relay user"), relay_user_default)
            relay_port_value = self.prompt_text(self.t("Puerto SSH del relay", "Relay SSH port"), str(relay_ssh_port_default)).strip()
            relay_bind_port_value = self.prompt_text(
                self.t("Puerto que abriré en el relay", "Port to expose on the relay"),
                str(relay_bind_port_default),
            ).strip()
            device_ssh_port_value = self.prompt_text(
                self.t("Puerto SSH del dispositivo oculto", "Hidden device SSH port"),
                str(device_ssh_port_default),
            ).strip()

            try:
                relay_ssh_port = int(relay_port_value or relay_ssh_port_default)
                relay_bind_port = int(relay_bind_port_value or relay_bind_port_default)
                device_ssh_port = int(device_ssh_port_value or device_ssh_port_default)
            except ValueError:
                render_human_error(
                    self.t("Los puertos del túnel inverso deben ser numéricos.", "Reverse tunnel ports must be numeric."),
                    suggestion=self.t("Usa enteros como `22`, `8022` o `46022`.", "Use integers like `22`, `8022` or `46022`."),
                )
                return None

            tunnel_command = build_reverse_tunnel_command(
                relay_host=relay_host_value,
                relay_user=relay_user_value,
                relay_ssh_port=relay_ssh_port,
                relay_bind_port=relay_bind_port,
                local_ssh_port=device_ssh_port,
            )
            tunnel_lines = [
                self.t("1. Ejecuta este comando en Termux o en el host oculto y déjalo abierto:", "1. Run this command on Termux or the hidden host and keep it open:"),
                *textwrap.wrap(tunnel_command, width=max(48, TERM_WIDTH - 16)),
                self.t(f"2. Omni esperará que el relay abra 127.0.0.1:{relay_bind_port}.", f"2. Omni will wait for the relay to open 127.0.0.1:{relay_bind_port}."),
                self.t("3. Cuando el túnel esté arriba, vuelve aquí y confirma.", "3. Once the tunnel is up, come back here and confirm."),
            ]
            render_action_summary(self.t("Túnel inverso", "Reverse tunnel"), tunnel_lines, accent=C.PRIMARY)
            if not self.confirm_step(
                self.t("¿Ya dejaste corriendo el comando del túnel inverso?", "Is the reverse tunnel command already running?"),
                default=True,
            ):
                warn(self.t("Túnel inverso cancelado por el operador.", "Reverse tunnel cancelled by the operator."))
                return None

            info(self.t("Espero el túnel inverso en localhost para reintentar la conexión.", "Waiting for the reverse tunnel on localhost before retrying the connection."))
            with Spinner("Esperando túnel inverso...", color=C.PRIMARY) as spinner:
                ready = wait_for_tcp_port("127.0.0.1", relay_bind_port, timeout=20, interval=0.5)
                spinner.finish("Túnel inverso listo", success=ready)

            checkpoint_params.update(
                {
                    "route": "reverse-tunnel",
                    "relay_host": relay_host_value,
                    "relay_user": relay_user_value,
                    "relay_port": relay_ssh_port,
                    "relay_bind_port": relay_bind_port,
                    "device_ssh_port": device_ssh_port,
                }
            )
            self.save_continue_state(flow="connect", status="probe_pending", params=checkpoint_params)

            if not ready:
                render_human_error(
                    self.t(
                        f"No vi abrirse el túnel en 127.0.0.1:{relay_bind_port}.",
                        f"I did not see the tunnel open on 127.0.0.1:{relay_bind_port}.",
                    ),
                    suggestion=tunnel_command,
                )
                return None

            return SSHDestination(
                host="127.0.0.1",
                user=resolved_user or getpass.getuser(),
                port=relay_bind_port,
                key_path=resolved_key_path,
                auth_mode=resolved_auth_mode,
                password=resolved_password,
                target_system=resolved_target_system,
            )

        try:
            remote = run_remote_probe(target)
        except Exception as err:
            err_text = str(err)
            recovered_via_tunnel = False
            if self.is_interactive() and "No pude abrir TCP hacia" in err_text:
                selected_route = select_menu(
                    [
                        self.t("Preparar túnel inverso", "Prepare reverse tunnel"),
                        self.t("Salir por ahora", "Exit for now"),
                    ],
                    title=self.t("No veo ruta directa hacia ese host", "I do not see a direct route to that host"),
                    descriptions=[
                        self.t(
                            "Útil para Termux, CGNAT o redes privadas: Omni genera el comando `ssh -R`, espera el túnel y reintenta por localhost.",
                            "Useful for Termux, CGNAT or private networks: Omni generates the `ssh -R` command, waits for the tunnel and retries through localhost.",
                        ),
                        self.t(
                            "Mantén el checkpoint y vuelve luego con `omni continue`.",
                            "Keep the checkpoint and come back later with `omni continue`.",
                        ),
                    ],
                    icons=["🪄", "⏸️"],
                    default=0,
                    show_index=True,
                    footer=self.t("↑/↓ elegir ruta · Enter confirmar", "↑/↓ choose path · Enter confirm"),
                )
                if selected_route == 0:
                    tunnel_target = maybe_prepare_reverse_tunnel()
                    if tunnel_target is not None:
                        target = tunnel_target
                        checkpoint_params["host"] = target.host
                        checkpoint_params["port"] = target.port
                        checkpoint_params["user"] = target.user
                        try:
                            remote = run_remote_probe(target)
                            recovered_via_tunnel = True
                        except Exception as tunnel_err:
                            self.save_continue_state(flow="connect", status="probe_failed", params=checkpoint_params, error=str(tunnel_err))
                            render_human_error(
                                f"No se pudo inspeccionar el host remoto: {tunnel_err}",
                                suggestion=self.t(
                                    "Sigue así: 1) ejecuta `omni continue`; 2) elige `Editar conexión guardada` si quieres cambiar relay, puerto o auth; 3) verifica que el comando `ssh -R` siga vivo en Termux.",
                                    "Next steps: 1) run `omni continue`; 2) choose `Edit saved connection` if you want to change relay, port or auth; 3) verify the `ssh -R` command is still alive in Termux.",
                                ),
                            )
                            return
                    else:
                        return
                else:
                    warn(self.t("Conexión pausada. Puedes retomarla luego con `omni continue`.", "Connection paused. You can resume it later with `omni continue`."))
                    return
            if recovered_via_tunnel:
                pass
            elif "Authentication failed" in err_text or "publickey" in err_text.lower():
                self.save_continue_state(flow="connect", status="probe_failed", params=checkpoint_params, error=err_text)
                render_human_error(
                    f"No se pudo inspeccionar el host remoto: {err_text}",
                    suggestion=self.t(
                        "Ese servidor parece aceptar solo `publickey`. Opciones: 1) cambia a `SSH Agent / clave cargada`; 2) usa una llave `.pem` o OpenSSH; 3) si solo tienes `.ppk`, conviértela con PuTTYgen; 4) Tailscale suele ser la ruta recomendada si ambos nodos la tienen.",
                        "That server appears to accept only `publickey`. Options: 1) switch to `SSH Agent / loaded key`; 2) use a `.pem` or OpenSSH private key; 3) if you only have a `.ppk`, convert it with PuTTYgen; 4) Tailscale is usually the recommended route if both nodes have it.",
                    ),
                )
                return
            elif not recovered_via_tunnel:
                extra_hint = self.t(
                    " Si ambos nodos tienen Tailscale, prueba esa ruta primero.",
                    " If both nodes run Tailscale, try that route first.",
                ) if resolved_route != "tailscale" else ""
                self.save_continue_state(flow="connect", status="probe_failed", params=checkpoint_params, error=str(err))
                render_human_error(
                    f"No se pudo inspeccionar el host remoto: {err}",
                    suggestion=self.t(
                        "Sigue así: 1) ejecuta `omni continue` y elige `Editar conexión guardada`; 2) corrige host, puerto, usuario o auth; 3) si el host usa OpenSSH en Windows, puedes pasar `--target-system windows`; 4) si el destino está detrás de NAT, usa `Preparar túnel inverso`." + extra_hint,
                        "Next steps: 1) run `omni continue` and choose `Edit saved connection`; 2) fix host, port, user or auth; 3) if the host runs OpenSSH on Windows, you can pass `--target-system windows`; 4) if the target sits behind NAT, use `Prepare reverse tunnel`." + extra_hint,
                    ),
                )
                return

        freshness = "Servidor limpio" if remote.get("fresh_server") else ("Host Windows existente" if remote.get("system_family") == "windows" else "Host Unix existente")
        render_action_summary(
            "Host remoto",
            [
                f"Sistema: {remote.get('system', 'unknown')}",
                f"Gestor de paquetes: {remote.get('package_manager', 'unknown')}",
                f"Entradas en HOME: {remote.get('home_entries', 0)}",
                f"Repos Git: {remote.get('git_repos', 0)}",
                f"Paquetes instalados: {remote.get('package_count', 0)}",
                f"Transporte: paramiko+sftp",
                f"Heurística: {freshness}",
            ],
            accent=C.GRN if remote.get("fresh_server") else C.YLW,
        )
        self.save_continue_state(
            flow="connect",
            status="transfer_pending",
            params=checkpoint_params,
            context={"remote": remote},
        )

        sources: List[str] = []
        if briefcase_path:
            sources.append(str(Path(briefcase_path).expanduser()))
        else:
            info(self.t("Paso 2/3 · Generando la maleta y el restore script para el destino.", "Step 2/3 · Building the briefcase and restore script for the target."))
            selected_path, manifest = self.resolve_manifest(manifest_path, home_root, create=True, profile=profile or FULL_HOME_PROFILE)
            report = scan_home(home_root or manifest.get("host_root") or str(Path.home()), manifest)
            effective_home_root = home_root or manifest.get("host_root") or str(Path.home())
            full_inventory = collect_full_inventory(home_root=effective_home_root)
            briefcase = build_briefcase_manifest(
                manifest,
                detect_platform_info(),
                inventory_report=report,
                full_inventory=full_inventory,
            )
            temp_dir = Path(tempfile.mkdtemp(prefix="omni-connect-"))
            generated = temp_dir / "briefcase.json"
            generated.write_text(json.dumps(briefcase, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            sources.append(str(generated))
            restore_script = temp_dir / "briefcase.restore.sh"
            restore_script.write_text(build_restore_script(briefcase, fresh_server=bool(remote.get("fresh_server"))), encoding="utf-8")
            restore_script.chmod(0o755)
            sources.append(str(restore_script))
            dim(f"Briefcase generado desde {selected_path}")

        latest_state = latest_or_explicit(self.bundle_dir, "", "state_bundle")
        latest_secrets = latest_or_explicit(self.bundle_dir, "", "secrets_bundle")
        if latest_state:
            sources.append(str(latest_state))
        if latest_secrets:
            sources.append(str(latest_secrets))

        try:
            info(self.t("Paso 3/3 · Enviando la maleta al host remoto.", "Step 3/3 · Sending the briefcase to the remote host."))
            with Spinner("Transfiriendo payload...", color=C.PRIMARY) as spinner:
                result = transfer_payload(
                    sources,
                    target,
                    remote_path=remote_path or "~/omni-transfer",
                    transport=resolved_transport,
                )
                spinner.finish("Transferencia terminada", success=result.get("success", False))
        except Exception as err:
            self.save_continue_state(flow="connect", status="transfer_failed", params=checkpoint_params, context={"remote": remote}, error=str(err))
            render_human_error(
                f"La transferencia falló: {err}",
                suggestion=self.t(
                    "Sigue así: 1) ejecuta `omni continue` para reintentar con este mismo destino; 2) valida permisos del usuario remoto sobre `~/omni-transfer`; 3) si el host es Android/Termux, confirma que OpenSSH y el HOME remoto estén sanos.",
                    "Next steps: 1) run `omni continue` to retry with the same destination; 2) validate remote user permissions over `~/omni-transfer`; 3) if the host is Android/Termux, confirm OpenSSH and the remote HOME are healthy.",
                ),
            )
            return

        if not result.get("success"):
            self.save_continue_state(
                flow="connect",
                status="transfer_failed",
                params=checkpoint_params,
                context={"remote": remote, "transport": result.get("transport", resolved_transport)},
                error=result.get("stderr") or result.get("stdout") or "SSH transfer failed",
            )
            render_human_error(
                result.get("stderr") or result.get("stdout") or "SSH transfer failed",
                suggestion=self.t(
                    "Sigue así: 1) ejecuta `omni continue` para reusar este destino; 2) valida permisos del directorio remoto; 3) si el usuario remoto no puede escribir en su HOME, crea un directorio alterno y pásalo con `--remote-path`.",
                    "Next steps: 1) run `omni continue` to reuse this destination; 2) validate permissions on the remote directory; 3) if the remote user cannot write to HOME, create an alternate directory and pass it with `--remote-path`.",
                ),
            )
            return

        self.clear_continue_state("connect")
        render_action_summary(
            "Payload enviado",
            [
                f"Destino: {target.target()}:{remote_path or '~/omni-transfer'}",
                f"Transporte: {result.get('transport', resolved_transport)}",
                f"Archivos: {len(sources)}",
                "Siguiente paso: inicia sesión en el host destino y ejecuta `omni guide` o `omni restore`.",
            ],
            accent=C.GRN,
        )

    def show_doctor(self):
        print_logo(compact=True)
        section(self.t("Doctor", "Doctor"))

        disk = self.fixer.check_disk_space()
        mem = self.fixer.check_memory()
        pm2 = self.fixer.check_and_fix_pm2()
        global_config = self.global_config()
        github_cfg = global_config.get("github") or {}
        tool_checks = {
            "paramiko": "python" if __import__("importlib").util.find_spec("paramiko") else "",
            "git": shutil.which("git"),
            "gh": shutil.which("gh"),
        }
        warnings: List[str] = []

        kv(self.t("Disco", "Disk"), disk.get("message", "Unknown"), color=C.GRN if disk.get("status") in {"ok", "skipped"} else C.YLW)
        kv(self.t("Memoria", "Memory"), mem.get("message", "Unknown"), color=C.GRN if mem.get("status") in {"ok", "skipped"} else C.YLW)
        kv("PM2", pm2.get("message", "Unknown"), color=C.GRN if pm2.get("status") in {"ok", "skipped"} and not pm2.get("restarted") else C.YLW)
        kv("Manifest", str(self.manifest_path), color=C.GRN)
        try:
            manifest = load_manifest(self.manifest_path, str(Path.home()))
            kv(self.t("Perfil", "Profile"), str(manifest.get("profile", "unknown")), color=C.GRN)
            kv(self.t("Raíz del host", "Host Root"), str(manifest.get("host_root", "unknown")), color=C.GRN)
            drift = self.build_host_drift_report(root=str(manifest.get("host_root", str(Path.home()))))
            context = drift["context"]
            plan = drift["plan"]
            if not context["summary_found"]:
                kv(self.t("Drift del host", "Host Drift"), self.t("Sin capture summary todavía", "No capture summary yet"), color=C.G3)
            elif plan and plan.changed_files:
                kv(self.t("Drift del host", "Host Drift"), self.t(f"{plan.changed_files} archivos necesitan rewrite", f"{plan.changed_files} files need rewrite"), color=C.YLW)
            else:
                kv(self.t("Drift del host", "Host Drift"), self.t("Alineado o sin coincidencias", "Aligned or no matches"), color=C.GRN)
        except Exception:
            pass
        kv(self.t("Directorio de bundles", "Bundle Dir"), str(self.bundle_dir), color=C.GRN)
        kv(self.t("Auth de GitHub", "GitHub Auth"), self.t("listo", "ready") if github_cfg.get("token") or gh_cli_token() else self.t("faltante", "missing"), color=C.GRN if github_cfg.get("token") or gh_cli_token() else C.YLW)
        kv("Language", f"{self.current_language()} ({SUPPORTED_LANGUAGES[self.current_language()]})", color=C.GRN)
        nl()

        bundle_summary = summarize_bundle_pair(bundle_dir=self.bundle_dir)
        if bundle_summary.get("state_bundle"):
            kv(self.t("Último state bundle", "Latest State Bundle"), str(bundle_summary["state_bundle"]["path"]), color=C.GRN)
        else:
            warn(self.t("No hay state bundle todavía. Ejecuta `omni capture`.", "No state bundle found yet. Run `omni capture`."))
            warnings.append(self.t("No hay state bundle reciente.", "There is no recent state bundle."))
        if bundle_summary.get("secrets_bundle"):
            kv(self.t("Último secrets bundle", "Latest Secrets Bundle"), str(bundle_summary["secrets_bundle"]["path"]), color=C.GRN)
        else:
            warn(self.t("No hay secrets bundle todavía. Ejecuta `omni capture`.", "No secrets bundle found yet. Run `omni capture`."))
            warnings.append(self.t("No hay secrets bundle reciente.", "There is no recent secrets bundle."))
        nl()

        section(self.t("Checks de runtime", "Runtime Checks"))
        for tool_name, path in tool_checks.items():
            kv(tool_name, path or "missing", color=C.GRN if path else C.YLW, key_width=14)
        if not tool_checks["paramiko"]:
            warnings.append(self.t("Falta `paramiko`; `omni connect` no podrá abrir conexiones remotas.", "Missing `paramiko`; `omni connect` cannot open remote connections."))
        if not tool_checks["gh"] and not github_cfg.get("token"):
            warnings.append(self.t("No hay sesión de GitHub ni token guardado; la maleta no podrá subirse automáticamente.", "There is no GitHub session or saved token; the briefcase cannot be uploaded automatically."))
        if mem.get("available_mb", 0) and mem.get("available_mb", 0) < 1024:
            warnings.append(self.t(f"Memoria disponible baja: {mem.get('available_mb')} MB.", f"Low available memory: {mem.get('available_mb')} MB."))
        if disk.get("usage_percent", 0) and disk.get("usage_percent", 0) >= 85:
            warnings.append(self.t(f"Disco muy lleno: {disk.get('usage_percent')}% usado.", f"Disk is nearly full: {disk.get('usage_percent')}% used."))
        nl()

        if not self.servers:
            warn(self.t(f"No hay servidores remotos configurados en {SERVERS_FILE}", f"No remote servers configured in {SERVERS_FILE}"))
            warnings.append(self.t("No hay servidores remotos configurados en servers.json.", "No remote servers are configured in servers.json."))
        else:
            for server in self.servers:
                host = str(server.get("host", ""))
                if host == "1.2.3.4":
                    warn(self.t(f"Placeholder host todavía presente en servers.json para {server.get('name', 'server')}", f"Placeholder host still present in servers.json for {server.get('name', 'server')}"))
                    warnings.append(self.t(f"Placeholder host en servers.json para {server.get('name', 'server')}.", f"Placeholder host remains in servers.json for {server.get('name', 'server')}."))
                else:
                    ok(self.t(f"Servidor remoto configurado: {server.get('name', host)} -> {host}", f"Remote server configured: {server.get('name', host)} -> {host}"))

        nl()
        section(self.t("Resumen de Doctor", "Doctor Summary"))
        if warnings:
            for item in warnings:
                warn(item)
        else:
            ok(self.t("No encontré fallos críticos ocultos. El host está listo para migración guiada.", "I did not find hidden critical failures. The host is ready for guided migration."))

    def build_host_drift_report(
        self,
        root: str = "",
        *,
        target_public_ip: str = "",
        target_private_ip: str = "",
        target_hostname: str = "",
    ) -> Dict[str, Any]:
        scan_root = Path(root).expanduser() if root else Path.home()
        context = build_host_rewrite_context(
            self.bundle_dir,
            target_public_ip=target_public_ip,
            target_private_ip=target_private_ip,
            target_hostname=target_hostname,
        )
        if not context.get("summary_found") and self.servers:
            identity = detect_host_identity()
            fallback_host = str(self.servers[0].get("host") or "").strip()
            replacement = identity.public_ip or identity.private_ip or identity.hostname or ""
            if fallback_host and replacement:
                context = dict(context)
                context["summary_found"] = True
                context["summary"] = {"source": "server-config-fallback"}
                context["replacements"] = {fallback_host: replacement}
        if context.get("summary", {}).get("source") == "server-config-fallback":
            plan = None
        else:
            plan = build_rewrite_plan(scan_root, context["replacements"]) if context["replacements"] else None
        return {
            "scan_root": str(scan_root),
            "context": context,
            "plan": plan,
            "changed_files": plan.changed_files if plan else 0,
            "total_replacements": plan.total_replacements if plan else 0,
        }

    def render_host_drift_summary(self, drift: Dict[str, Any], *, compact: bool = False) -> None:
        context = drift["context"]
        plan = drift["plan"]
        if not context["summary_found"]:
            hint("Sin capture summary: el auto-rewrite de host se activa después de un capture o restore.")
            return
        if plan and plan.changed_files:
            warn(f"Host drift detectado: {plan.changed_files} archivos siguen apuntando al host anterior.")
            hint("`omni migrate` los corregirá automáticamente o puedes ejecutar `omni rewrite-ip --apply`.")
            return
        if context["replacements"]:
            info("La identidad del host cambió, pero no encontré archivos allowlisted que necesiten rewrite.")
            return
        if not compact:
            ok("La identidad del host ya está alineada con el último capture summary.")

    def capture_host_cmd(
        self,
        manifest_path: str = "",
        home_root: str = "",
        output: str = "",
        passphrase_env: str = "OMNI_SECRET_PASSPHRASE",
        *,
        accept_all: bool = False,
        profile: str = "",
    ):
        print_logo(compact=True)
        section("Capture Recovery Pack")
        selected_path, manifest = self.resolve_manifest(manifest_path, home_root, create=True, profile=profile)
        bundle_dir = self.capture_output_dir(output)
        passphrase = self.read_passphrase(passphrase_env)
        report = scan_home(home_root or manifest.get("host_root") or str(Path.home()), manifest)

        if self.is_interactive():
            discovered = sorted(report["discovered"], key=lambda item: item.get("size_bytes", 0), reverse=True)
            preflight_lines = [
                f"Perfil activo: {manifest.get('profile', DEFAULT_PROFILE)}",
                f"Raíz de captura: {manifest.get('host_root', str(Path.home()))}",
                f"Estado total declarado: {human_size(sum(int(item.get('size_bytes', 0)) for item in report['included'] if item.get('kind') == 'state'))}",
                f"Secretos separados: {len([item for item in report['included'] if item.get('kind') == 'secret'])}",
                "",
                "Directorios grandes dentro del scope:",
            ]
            for item in discovered[:8]:
                classification = str(item.get("classification", "uncategorized")).upper()
                preflight_lines.append(f"{classification}: {item['path']} · {human_size(int(item.get('size_bytes', 0)))}")
            if any(str(item.get("name")) == ".codex" for item in discovered):
                preflight_lines.extend(
                    [
                        "",
                        "Nota: `.codex` sí entra en full-home. Lo mismo aplica para skills, `.agents` y backups locales.",
                    ]
                )
            if any(str(item.get("name")) == "melissa-backups" for item in discovered):
                preflight_lines.append(
                    "Nota: `melissa-backups` también entra en full-home. Suele ser el bloque más pesado porque guarda respaldos históricos de Melissa."
                )
            render_action_summary("Preflight de captura", preflight_lines, accent=C.YLW)

        if not self.confirm_step("Create state bundle now?", accept_all=accept_all):
            warn("Capture cancelled before state bundle creation.")
            return
        if not self.confirm_step("Create secrets bundle now?", accept_all=accept_all):
            warn("Capture stopped before secrets bundle creation.")
            return
        pack = self.create_recovery_pack(
            manifest_path=str(selected_path),
            home_root=home_root,
            output=str(bundle_dir),
            passphrase_env=passphrase_env,
            profile=profile or str(manifest.get("profile", "")),
        )
        state_bundle = pack["state_bundle"]
        secrets_bundle = pack["secrets_bundle"]
        summary_path = pack["summary_path"]
        ok(f"State bundle created: {state_bundle}")
        ok(f"Secrets bundle created: {secrets_bundle}")
        ok(f"Capture summary written: {summary_path}")
        if not pack["encrypted"]:
            warn("No passphrase configured. Secrets bundle was exported without encryption.")

        summary = summarize_bundle_pair(bundle_dir=bundle_dir, state_bundle=str(state_bundle), secrets_bundle=str(secrets_bundle))
        if self.is_interactive():
            summary_lines = [
                f"Perfil activo: {manifest.get('profile', DEFAULT_PROFILE)}",
                f"Bundle de estado: {state_bundle}",
                f"Bundle de secretos: {secrets_bundle}",
                f"Resumen: {summary_path}",
                f"Directorio: {bundle_dir}",
            ]
            if not passphrase:
                summary_lines.append("Atención: el bundle de secretos quedó sin cifrar.")
            summary_lines.extend(
                [
                    "",
                    "Siguiente paso recomendado:",
                    "$ omni bridge",
                    "$ ls -lah /home/ubuntu/omni-core/backups/host-bundles",
                ]
            )
            render_action_summary("Capture listo", summary_lines, accent=C.GRN)
        else:
            self.write_json_output(summary)

    def restore_host_cmd(
        self,
        manifest_path: str = "",
        home_root: str = "",
        bundle_path: str = "",
        secrets_path: str = "",
        target_root: str = "/",
        passphrase_env: str = "OMNI_SECRET_PASSPHRASE",
        *,
        accept_all: bool = False,
        install_timer: bool = False,
        on_calendar: str = "daily",
        profile: str = "",
        show_summary: bool = True,
        auto_backup: bool = True,
        allow_missing_bundles: bool = False,
        recover_apps_ips: bool = False,
        before_services=None,
    ):
        print_logo(compact=True)
        section("Restore Host")
        self.init_workspace(profile=profile)
        selected_path, manifest = self.resolve_manifest(manifest_path, home_root, create=True, profile=profile)
        passphrase = self.read_passphrase(passphrase_env)
        search_dirs = self.bundle_search_dirs(include_auto=not allow_missing_bundles)
        resolved_bundle = str(resolve_latest_bundle_across_dirs(search_dirs, bundle_path, "state_bundle") or "")
        resolved_secrets = str(resolve_latest_bundle_across_dirs(search_dirs, secrets_path, "secrets_bundle") or "")
        used_bundles = bool(resolved_bundle or resolved_secrets)
        bootstrap_only = False
        hydration_result: Dict[str, Any] | None = None
        resolve_installed_inventory_across_dirs(search_dirs)

        if not resolved_bundle or not resolved_secrets:
            if not allow_missing_bundles:
                if not resolved_bundle:
                    fail("State bundle not found. Run `omni capture` or pass --bundle.")
                if not resolved_secrets:
                    fail("Secrets bundle not found. Run `omni capture` or pass --secrets.")
                return {"success": False, "bootstrap_only": False, "used_bundles": False}
            bootstrap_only = True
            resolved_bundle = ""
            resolved_secrets = ""

        local_runtime = discover_local_runtime_paths(home_root or str(manifest.get("host_root") or ""), manifest)
        if bootstrap_only:
            if recover_apps_ips and local_runtime.get("ready"):
                manifest = dict(manifest)
                manifest["install_targets"] = sorted(set(list(manifest.get("install_targets", [])) + list(local_runtime.get("install_targets", []))))
                manifest["compose_projects"] = sorted(set(list(manifest.get("compose_projects", [])) + list(local_runtime.get("compose_projects", []))))
                manifest["pm2_ecosystems"] = sorted(set(list(manifest.get("pm2_ecosystems", [])) + list(local_runtime.get("pm2_ecosystems", []))))
                hydration_result = {"success": True, "source": "local_recover_apps_ips", "runtime": local_runtime}
            elif self.servers and not local_runtime.get("ready") and not any(server.get("paths") for server in self.servers):
                hydration_result = self.hydrate_from_remote_servers(target_root=target_root, manifest=manifest)
        if not self.confirm_step("Restore and reconcile this host now?", accept_all=accept_all):
            warn("Restore cancelled.")
            return {"success": False, "bootstrap_only": bootstrap_only, "used_bundles": used_bundles}

        report = reconcile_host(
            manifest,
            bundle_path=resolved_bundle,
            secrets_path=resolved_secrets,
            passphrase=passphrase,
            target_root=target_root,
            repos=self.repo_entries,
            before_services=before_services,
        )
        ok(f"Restore completed using {selected_path}")
        timer_installed = False
        if install_timer and self.confirm_step("Install daily Omni timer?", accept_all=accept_all):
            self.install_timer_cmd("omni-update", on_calendar)
            timer_installed = True
        if auto_backup and AUTO_BACKUP_ON_CHANGE:
            info("Creando backup automático post-restore...")
            self.run_backup(
                manifest_path=str(selected_path),
                home_root=home_root,
                passphrase_env=passphrase_env,
                profile=profile or str(manifest.get("profile", "")),
            )

        if show_summary and self.is_interactive():
            step_map = {step.get("name"): step for step in report.get("steps", []) if isinstance(step, dict)}
            restore_state = step_map.get("restore_state", {})
            restore_secrets = step_map.get("restore_secrets", {})
            compose_step = step_map.get("compose", {})
            compose_started = len([item for item in compose_step.get("results", []) if item.get("status") == "started"])
            pm2_step = step_map.get("pm2", {})
            summary_lines = [
                f"Perfil activo: {manifest.get('profile', DEFAULT_PROFILE)}",
                f"Archivos de estado restaurados: {restore_state.get('restored', 0)}",
                f"Archivos de secretos restaurados: {restore_secrets.get('restored', 0)}",
                f"Proyectos Compose levantados: {compose_started}",
                f"PM2: {pm2_step.get('status', 'sin estado')}",
                f"Timer diario: {'instalado' if timer_installed else 'pendiente'}",
                "",
                "Siguiente paso recomendado:",
                "$ omni status",
                "$ omni inventory",
                "$ omni detect-ip",
            ]
            render_action_summary("Restore completo", summary_lines, accent=C.GRN)
        else:
            self.write_json_output(report)
        return {
            "success": True,
            "bootstrap_only": bootstrap_only,
            "used_bundles": used_bundles,
            "hydration_result": hydration_result,
            "report": report,
        }

    def detect_ip_cmd(self):
        print_logo(compact=True)
        section("Host Identity")
        drift = self.build_host_drift_report(root=str(Path.home()))
        identity = detect_host_identity()
        capture_summary = drift["context"]["summary"]

        kv("Public IP", identity.public_ip or "unknown", color=C.GRN if identity.public_ip else C.YLW)
        kv("Private IP", identity.private_ip or "unknown", color=C.GRN if identity.private_ip else C.YLW)
        kv("Hostname", identity.hostname or "unknown", color=C.GRN)
        kv("FQDN", identity.fqdn or "unknown", color=C.GRN)
        kv("Source", identity.source, color=C.G3)
        if identity.ip_candidates:
            kv("Candidates", ", ".join(identity.ip_candidates), color=C.G3)
        if drift["context"]["summary_found"]:
            kv("Drift Files", str(drift["changed_files"]), color=C.YLW if drift["changed_files"] else C.GRN)
            kv("Replacements", str(drift["total_replacements"]), color=C.YLW if drift["total_replacements"] else C.GRN)
        nl()

        if capture_summary and capture_summary.get("source_identity"):
            source = capture_summary["source_identity"]
            bullet("Latest capture summary source identity", C.PRIMARY, bold=True)
            dim(f"public_ip={source.get('public_ip') or 'unknown'}")
            dim(f"private_ip={source.get('private_ip') or 'unknown'}")
            dim(f"hostname={source.get('hostname') or 'unknown'}")
            dim(f"fqdn={source.get('fqdn') or 'unknown'}")
            nl()
            self.render_host_drift_summary(drift)
        else:
            warn("No capture summary found. Capture a bundle set to persist old host identity.")

    def rewrite_ip_cmd(
        self,
        root: str = "",
        *,
        target_public_ip: str = "",
        target_private_ip: str = "",
        target_hostname: str = "",
        apply_changes: bool = False,
        accept_all: bool = False,
        context_lines: int = 2,
    ):
        print_logo(compact=True)
        section("Rewrite Host References")
        drift = self.build_host_drift_report(
            root=root or str(Path.home()),
            target_public_ip=target_public_ip,
            target_private_ip=target_private_ip,
            target_hostname=target_hostname,
        )
        plan = drift["plan"]
        context = drift["context"]

        if not context["summary_found"]:
            warn("No capture summary found. Restore or capture first so Omni knows the old host identity.")
            return
        if not context["replacements"]:
            warn("No replacement candidates found. The old host identity already matches this host.")
            return
        print(preview_rewrite_plan(plan, context_lines=context_lines))
        if plan.changed_files == 0:
            warn("No matching references found in allowlisted files.")
            return

        if apply_changes or self.confirm_step("Apply these replacements now?", accept_all=accept_all):
            result = apply_rewrite_plan(plan)
            ok(f"Updated {len(result.applied)} files")
            if result.applied and AUTO_BACKUP_ON_CHANGE:
                info("Creando backup automático post-rewrite...")
                self.run_backup()
        else:
            warn("Preview only. Re-run with --apply or confirm interactively.")

    def migrate_host_cmd(
        self,
        manifest_path: str = "",
        home_root: str = "",
        bundle_path: str = "",
        secrets_path: str = "",
        target_root: str = "/",
        passphrase_env: str = "OMNI_SECRET_PASSPHRASE",
        *,
        accept_all: bool = False,
        install_timer: bool = False,
        on_calendar: str = "daily",
        apply_rewrite: bool = True,
        profile: str = "",
    ):
        print_logo(compact=True)
        section("Migrate Host")
        info_obj = detect_platform_info()
        kv("Detected Platform", f"{info_obj.system} / {info_obj.shell} / {info_obj.package_manager}", color=C.GRN)
        nl()

        rewrite_status = "disabled"
        rewrite_files = 0

        def before_services_hook(_report: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal rewrite_status, rewrite_files
            if not apply_rewrite:
                rewrite_status = "disabled"
                return {"status": rewrite_status}
            drift = self.build_host_drift_report(root=home_root or str(Path.home()))
            context = drift["context"]
            plan = drift["plan"]
            if not context["summary_found"]:
                rewrite_status = "missing-capture-summary"
                return {"status": rewrite_status}
            if not context["replacements"]:
                rewrite_status = "aligned"
                return {"status": rewrite_status}
            if not plan or plan.changed_files == 0:
                rewrite_status = "no-matches"
                return {"status": rewrite_status}
            result = apply_rewrite_plan(plan)
            rewrite_files = len(result.applied)
            rewrite_status = "applied" if rewrite_files else "no-matches"
            return {
                "status": rewrite_status,
                "files": rewrite_files,
                "replacements": drift["total_replacements"],
            }

        result = self.restore_host_cmd(
            manifest_path=manifest_path,
            home_root=home_root,
            bundle_path=bundle_path,
            secrets_path=secrets_path,
            target_root=target_root,
            passphrase_env=passphrase_env,
            accept_all=accept_all,
            install_timer=install_timer,
            on_calendar=on_calendar,
            profile=profile,
            show_summary=False,
            auto_backup=False,
            before_services=before_services_hook,
        )
        if not result or not result.get("success"):
            return result
        if AUTO_BACKUP_ON_CHANGE:
            info("Creando backup automático post-migrate...")
            self.run_backup(
                manifest_path=manifest_path,
                home_root=home_root,
                passphrase_env=passphrase_env,
                profile=profile,
            )

        if self.is_interactive():
            lines = [
                f"Plataforma detectada: {info_obj.system} / {info_obj.shell}",
                f"Reescritura de referencias: {rewrite_status}",
                f"Archivos corregidos: {rewrite_files}",
                "",
                "Validación inmediata:",
                "$ omni status",
                "$ omni inventory",
                "$ omni detect-ip",
            ]
            if rewrite_status not in {"applied", "aligned"}:
                lines.append("$ omni rewrite-ip --apply")
            render_action_summary("Migración finalizada", lines, accent=C.GRN)
        return result

    def hydrate_from_remote_servers(
        self,
        *,
        target_root: str,
        manifest: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        active_manifest = dict(manifest or {})
        profile = str(active_manifest.get("profile", ""))
        host_root = str(active_manifest.get("host_root", "")).strip()

        for server in self.servers:
            remote_roots = [host_root] if profile == FULL_HOME_PROFILE and host_root else list(server.get("paths", []) or [])
            if not remote_roots:
                remote_roots = [host_root or "/home/ubuntu"]
            for remote_root in remote_roots:
                if str(remote_root) == str(Path(self.root_dir)):
                    results.append({"server": server.get("name", server.get("host", "server")), "path": remote_root, "status": "skipped_omni_home"})
                    continue
                entries = self.list_remote_directory_entries(server, remote_root)
                if not entries:
                    entries = [{"path": remote_root, "kind": "dir"}]
                for entry in entries:
                    source_path = str(entry.get("path") or remote_root)
                    source_kind = str(entry.get("kind") or "dir")
                    source_target = Path(target_root) / source_path.lstrip("/")
                    target_dir = source_target.parent if source_kind == "file" else source_target
                    target_dir.mkdir(parents=True, exist_ok=True)
                    command = build_remote_sync_command(
                        server,
                        source_path,
                        target_dir,
                        delete=False,
                        source_kind=source_kind,
                    )
                    code, out, err = self._run_transfer_cmd_visible(command, f"hydrate :: {source_path}")
                    imported_entries = 0
                    if source_kind == "file":
                        imported_entries = 1 if source_target.exists() else 0
                    elif source_target.exists():
                        imported_entries = sum(1 for _ in source_target.rglob("*"))
                    status = "ok" if imported_entries > 0 else "empty_import"
                    results.append(
                        {
                            "server": server.get("name", server.get("host", "server")),
                            "path": source_path,
                            "status": status,
                            "after": {"entries": imported_entries},
                            "command": command,
                            "success": code == 0 and imported_entries > 0,
                        }
                    )
        return {"success": all(item.get("status") in {"ok", "skipped_omni_home"} for item in results) and bool(results), "results": results}

    def bridge_mode(self, *, accept_all: bool = False, dest: str = "", protocol: str = "rsync", profile: str = ""):
        print_logo(compact=True)
        section("Bridge Mode")
        profile = self.normalize_profile(profile)
        action = "create"
        if not accept_all:
            options = ["create", "send", "receive"]
            descriptions = [
                "Crear bundles de estado y secretos en este host.",
                "Enviar los últimos bundles al host destino.",
                "Restaurar en este host desde los bundles ya presentes.",
            ]
            icons = ["📦", "📡", "♻️"]
            try:
                selected = select_menu(
                    options,
                    title="Bridge mode",
                    descriptions=descriptions,
                    icons=icons,
                    default=0,
                    show_index=True,
                    footer="↑/↓ elegir acción · Enter confirmar",
                )
            except KeyboardInterrupt:
                raise
            action = options[selected]
        if action in {"2", "send"}:
            destination = dest or self.prompt_text("Remote destination (example ubuntu@host:/home/ubuntu/omni-bundles)", "")
            if not destination:
                fail("Remote destination required for bridge send.")
                return
            result = self.transfer.transfer_directory(str(self.bundle_dir), destination, {"protocol": protocol, "compress": True})
            if result.get("success"):
                ok(f"Bridge send complete: {destination}")
                if self.is_interactive():
                    render_action_summary(
                        "Bridge listo",
                        [
                            f"Destino: {destination}",
                            f"Origen enviado: {self.bundle_dir}",
                            "",
                            "Siguiente paso recomendado en el host destino:",
                            "$ omni restore --profile full-home",
                            "$ omni migrate --profile full-home",
                        ],
                        accent=C.GRN,
                    )
            else:
                fail(result.get("error", "Bridge send failed"))
            return
        profile = self.choose_profile(profile, accept_all=accept_all)
        if action in {"3", "receive", "restore"}:
            self.restore_host_cmd(accept_all=accept_all, install_timer=accept_all, profile=profile)
            return
        self.capture_host_cmd(accept_all=accept_all, profile=profile)

    def show_install_guide(self):
        print_logo(tagline=False)
        render_command_header(
            "Install OmniSync",
            "Instalación de una línea y primer arranque listo para operar.",
            dry_run=self.is_dry_run(),
            snapshot=self.host_snapshot,
        )
        render_help_overview()
        section("Portable Install")
        bullet("1. Linux/macOS/WSL: curl -fsSL https://raw.githubusercontent.com/sxrubyo/omnisync/main/install.sh | bash", C.GRN)
        bullet("2. PowerShell: irm https://raw.githubusercontent.com/sxrubyo/omnisync/main/install.ps1 | iex", C.GRN)
        bullet("3. npm global: npm install -g omnisync", C.GRN)
        bullet("4. El instalador deja Omni en ~/.omni y el wrapper en ~/.local/bin/omni", C.GRN)
        bullet("5. Ejecuta `omni` o `omni guide` para entrar al flujo guiado", C.GRN)
        bullet("6. Usa `omni connect` para enlazar el host origen con el destino por SSH", C.GRN)
        bullet("7. Usa `omni briefcase --full` para generar maleta + restore script", C.GRN)
        bullet("8. Usa `omni restore` o `omni migrate sync restore` en el destino", C.GRN)
        nl()

    def show_inventory(self, manifest_path: str = "", home_root: str = "", output: str = "", profile: str = ""):
        print_logo(compact=True)
        section("Host Inventory")
        selected_path, manifest = self.resolve_manifest(manifest_path, home_root, create=True, profile=profile)
        report = scan_home(home_root or manifest.get("host_root") or str(Path.home()), manifest)

        state_count = len([item for item in report["included"] if item["kind"] == "state"])
        secret_count = len([item for item in report["included"] if item["kind"] == "secret"])
        product_count = len([item for item in report["discovered"] if item["classification"] == "product"])
        noise_count = len([item for item in report["discovered"] if item["classification"] == "noise"])

        kv("Manifest", str(selected_path))
        kv("Profile", str(manifest.get("profile", "unknown")), color=C.GRN)
        kv("State Paths", str(state_count), color=C.GRN)
        kv("Secret Paths", str(secret_count), color=C.YLW)
        kv("Product Dirs", str(product_count), color=C.GRN)
        kv("Noise Dirs", str(noise_count), color=C.YLW if noise_count else C.GRN)
        nl()

        for item in report["included"]:
            color = C.YLW if item["kind"] == "secret" else C.GRN
            label = f"{item['kind'].upper()} :: {item['path']}"
            if item["exists"]:
                kv(label, human_size(item["size_bytes"]), color=color, key_width=14)
            else:
                warn(f"Missing {item['kind']} path: {item['path']}")

        discovered = sorted(report["discovered"], key=lambda item: item.get("size_bytes", 0), reverse=True)
        if discovered:
            nl()
            section("Top Dirs In Scope")
            for item in discovered[:10]:
                classification = str(item.get("classification", "uncategorized")).upper()
                color = C.GRN if classification == "PRODUCT" else C.YLW if classification in {"NOISE", "SECRET"} else C.G3
                label = f"{classification} :: {item['path']}"
                kv(label, human_size(int(item.get("size_bytes", 0))), color=color, key_width=14)

            if any(str(item.get("name")) == ".codex" for item in discovered):
                nl()
                hint("`.codex` está dentro de full-home porque el scope activo es /home/ubuntu completo.")
                hint("Si luego quieres una captura más liviana, toca excluirlo explícitamente o usar production-clean.")
            if any(str(item.get("name")) == "melissa-backups" for item in discovered):
                hint("`melissa-backups` también entra en full-home y puede inflar mucho el bundle por sus respaldos históricos.")

        if output:
            payload = {
                "manifest_path": str(selected_path),
                "manifest": manifest,
                "inventory": report,
            }
            self.write_json_output(payload, output)

    def show_briefcase(
        self,
        manifest_path: str = "",
        home_root: str = "",
        output: str = "",
        profile: str = "",
        *,
        full: bool = False,
        restore_script_output: str = "",
    ):
        print_logo(compact=True)
        section(self.t("Maleta portable", "Portable briefcase"))

        with Spinner(self.t("Leyendo manifest y perfil activo...", "Reading manifest and active profile..."), color=C.PRIMARY) as spinner:
            selected_path, manifest = self.resolve_manifest(manifest_path, home_root, create=True, profile=profile)
            effective_home_root = home_root or manifest.get("host_root") or str(Path.home())
            spinner.finish(self.t("Manifest resuelto", "Manifest resolved"), success=True)

        self._briefcase_step(
            self.t("1. Analizando estado del host", "1. Scanning host state"),
            self.t(f"Manifest: {selected_path}", f"Manifest: {selected_path}"),
        )
        with Spinner(self.t("Clasificando estado, secretos y ruido...", "Classifying state, secrets and noise..."), color=C.PRIMARY) as spinner:
            report = scan_home(effective_home_root, manifest)
            spinner.finish(self.t("Inventario base listo", "Base inventory ready"), success=True)

        full_inventory = None
        if full:
            self._briefcase_step(
                self.t("2. Recolectando inventario completo", "2. Collecting full inventory"),
                self.t("Paquetes, runtimes, VS Code, Docker y señales portables.", "Packages, runtimes, VS Code, Docker and portable signals."),
            )
            with Spinner(self.t("Recolectando paquetes y runtimes...", "Collecting packages and runtimes..."), color=C.PRIMARY) as spinner:
                full_inventory = collect_full_inventory(home_root=effective_home_root)
                spinner.finish(self.t("Inventario completo listo", "Full inventory ready"), success=True)

        self._briefcase_step(
            self.t("3. Construyendo la maleta", "3. Building the briefcase"),
            self.t("Generando contrato portable y restore script.", "Generating portable contract and restore script."),
        )
        with Spinner(self.t("Empaquetando metadata portable...", "Packing portable metadata..."), color=C.PRIMARY) as spinner:
            briefcase = build_briefcase_manifest(
                manifest,
                detect_platform_info(),
                inventory_report=report,
                full_inventory=full_inventory,
            )
            spinner.finish(self.t("Maleta construida", "Briefcase built"), success=True)

        summary = briefcase["inventory"]["summary"]
        default_output, default_restore = self.default_briefcase_paths()
        resolved_output = Path(output).expanduser() if output else default_output
        restore_path = Path(restore_script_output).expanduser() if restore_script_output else default_restore
        if output and not restore_script_output:
            restore_path = resolved_output.with_name(resolved_output.stem + ".restore.sh")

        self._briefcase_step(
            self.t("4. Escribiendo artefactos", "4. Writing artifacts"),
            self.t(f"Salida: {resolved_output}", f"Output: {resolved_output}"),
        )
        if self.is_dry_run():
            warn(self.t("Dry run activo: no se escribieron archivos.", "Dry run active: no files were written."))
        else:
            resolved_output.parent.mkdir(parents=True, exist_ok=True)
            resolved_output.write_text(json.dumps(briefcase, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            restore_path.parent.mkdir(parents=True, exist_ok=True)
            restore_path.write_text(build_restore_script(briefcase, fresh_server=True), encoding="utf-8")
            restore_path.chmod(0o755)
            ok(self.t(f"Maleta guardada en {resolved_output}", f"Briefcase saved to {resolved_output}"))
            ok(self.t(f"Restore script guardado en {restore_path}", f"Restore script saved to {restore_path}"))

        kv("Manifest", str(selected_path))
        kv(self.t("Perfil", "Profile"), str(briefcase["source"]["profile"]), color=C.GRN)
        kv(self.t("Sistema origen", "Source System"), str(briefcase["source"]["platform"].get("system", "unknown")), color=C.GRN)
        kv(self.t("Gestor de paquetes", "Package Manager"), str(briefcase["source"]["platform"].get("package_manager", "unknown")), color=C.GRN)
        kv(self.t("Paths de estado", "State Paths"), str(summary["included_state_count"]), color=C.GRN)
        kv(self.t("Paths secretos", "Secret Paths"), str(summary["included_secret_count"]), color=C.YLW if summary["included_secret_count"] else C.GRN)
        kv(self.t("Productos", "Products"), str(summary["discovered_product_count"]), color=C.GRN)
        kv(self.t("Ruido", "Noise"), str(summary["discovered_noise_count"]), color=C.YLW if summary["discovered_noise_count"] else C.GRN)
        if full_inventory:
            counts = full_inventory.get("counts") or {}
            kv(self.t("Paquetes del sistema", "System Packages"), str(counts.get("system_packages", 0)), color=C.GRN)
            kv(self.t("Paquetes Python", "Python Packages"), str(counts.get("python_packages", 0)), color=C.GRN)
            kv(self.t("Node global", "Node Global"), str(counts.get("node_global_packages", 0)), color=C.GRN)
            kv(self.t("Extensiones VS Code", "VS Code Ext"), str(counts.get("vscode_extensions", 0)), color=C.GRN)
        kv(self.t("Archivo de maleta", "Briefcase File"), str(resolved_output), color=C.GRN)
        kv(self.t("Restore script", "Restore Script"), str(restore_path), color=C.GRN)
        nl()
        hint(self.t("GitHub queda como metadata/control plane. El payload real debe viajar por SSH/SFTP/rsync.", "GitHub stays as metadata/control plane. The real payload should move over SSH/SFTP/rsync."))
        bullet(self.t("Siguiente paso: usa `omni connect` para mover la maleta al destino.", "Next: use `omni connect` to move the briefcase to the target host."), C.GRN)
        bullet(self.t("En el destino: ejecuta `omni restore` o `omni migrate sync restore`.", "On the target: run `omni restore` or `omni migrate sync restore`."), C.GRN)
        if not self.is_dry_run():
            self._offer_github_briefcase_sync(resolved_output, profile=profile)

    def show_restore_plan(
        self,
        manifest_path: str = "",
        home_root: str = "",
        output: str = "",
        profile: str = "",
        briefcase_path: str = "",
    ):
        print_logo(compact=True)
        section("Restore Plan")

        if briefcase_path:
            source_briefcase = json.loads(Path(briefcase_path).expanduser().read_text(encoding="utf-8"))
            selected_path = Path(briefcase_path).expanduser()
        else:
            selected_path, manifest = self.resolve_manifest(manifest_path, home_root, create=True, profile=profile)
            report = scan_home(home_root or manifest.get("host_root") or str(Path.home()), manifest)
            source_briefcase = build_briefcase_manifest(
                manifest,
                detect_platform_info(),
                inventory_report=report,
            )

        plan = build_restore_plan(source_briefcase, detect_platform_info())
        kv("Source", str(plan["source"]["platform"].get("system", "unknown")), color=C.GRN)
        kv("Target", str(plan["target"].get("system", "unknown")), color=C.GRN)
        kv("Cross Platform", "yes" if plan["cross_platform"] else "no", color=C.YLW if plan["cross_platform"] else C.GRN)
        kv("Reference", str(selected_path))
        nl()

        for step in plan["steps"]:
            status = str(step.get("status", "unknown"))
            color = C.GRN if status == "applicable" else C.YLW if status == "manual" else C.G3
            kv(step["id"], f"{status} :: {step['title']}", color=color, key_width=22)

        if plan["capability_gaps"]:
            nl()
            section("Capability Gaps")
            for gap in plan["capability_gaps"]:
                warn(gap)

        if output:
            self.write_json_output(plan, output)
            return
        print(json.dumps(plan, indent=2, ensure_ascii=False))

    def migrate_sync_cmd(
        self,
        subaction: str = "",
        *,
        manifest_path: str = "",
        home_root: str = "",
        output: str = "",
        passphrase_env: str = "OMNI_SECRET_PASSPHRASE",
        profile: str = "",
        briefcase_path: str = "",
        accept_all: bool = False,
        target_root: str = "/",
        on_calendar: str = "daily",
        full: bool = False,
        restore_script_output: str = "",
    ):
        normalized = (subaction or "").strip().lower()
        if normalized in {"", "help"}:
            render_action_summary(
                "Omni Migrate Sync",
                [
                    "$ omni migrate sync create   # export portable briefcase metadata",
                    "$ omni migrate sync plan     # derive the target restore plan",
                    "$ omni migrate sync capture  # create state + secrets recovery pack",
                    "$ omni migrate sync restore  # restore from latest bundle + secrets",
                ],
                accent=C.PRIMARY,
            )
            return

        if normalized in {"create", "briefcase"}:
            self.show_briefcase(
                manifest_path,
                home_root,
                output,
                profile=profile,
                full=full,
                restore_script_output=restore_script_output,
            )
            return
        if normalized in {"plan", "restore-plan"}:
            self.show_restore_plan(manifest_path, home_root, output, profile=profile, briefcase_path=briefcase_path)
            return
        if normalized == "capture":
            self.capture_host_cmd(
                manifest_path,
                home_root,
                output,
                passphrase_env,
                accept_all=accept_all,
                profile=profile,
            )
            return
        if normalized == "restore":
            self.restore_host_cmd(
                manifest_path=manifest_path,
                home_root=home_root,
                bundle_path="",
                secrets_path="",
                target_root=target_root,
                passphrase_env=passphrase_env,
                accept_all=accept_all,
                install_timer=accept_all,
                on_calendar=on_calendar,
                profile=profile,
            )
            return

        fail(f"Unknown migrate sync action: {subaction}")
        hint("Use: omni migrate sync [create|plan|capture|restore]")

    def create_state_bundle_cmd(self, manifest_path: str = "", home_root: str = "", output: str = "", profile: str = ""):
        print_logo(compact=True)
        section("State Bundle")
        selected_path, manifest = self.resolve_manifest(manifest_path, home_root, create=True, profile=profile)
        bundle_path = self.resolve_output_path(output, "state_bundle", encrypted=False)
        created = create_state_bundle(self.bundle_dir, manifest, bundle_path=bundle_path)
        ok(f"State bundle created: {created}")
        dim(f"Manifest: {selected_path}")

    def export_secrets_cmd(self, manifest_path: str = "", home_root: str = "", output: str = "", passphrase_env: str = "OMNI_SECRET_PASSPHRASE", profile: str = ""):
        print_logo(compact=True)
        section("Secrets Pack")
        selected_path, manifest = self.resolve_manifest(manifest_path, home_root, create=True, profile=profile)
        passphrase = self.read_passphrase(passphrase_env)
        bundle_path = self.resolve_output_path(output, "secrets_bundle", encrypted=bool(passphrase))
        created = create_secrets_bundle(self.bundle_dir, manifest, bundle_path=bundle_path, passphrase=passphrase)
        ok(f"Secrets bundle created: {created}")
        dim(f"Manifest: {selected_path}")
        if not passphrase:
            warn("No passphrase configured. Secrets pack was exported without encryption.")

    def restore_state_bundle_cmd(self, bundle_path: str = "", target_root: str = "/"):
        print_logo(compact=True)
        section("Restore State")
        resolved = latest_or_explicit(self.bundle_dir, bundle_path, "state_bundle")
        if not resolved:
            fail("State bundle not found")
            return
        restored = restore_bundle(resolved, target_root=target_root)
        ok(f"Restored {len(restored)} files from {resolved}")
        dim(f"Target root: {target_root}")

    def import_secrets_cmd(
        self,
        secrets_path: str = "",
        target_root: str = "/",
        passphrase_env: str = "OMNI_SECRET_PASSPHRASE",
    ):
        print_logo(compact=True)
        section("Import Secrets")
        resolved = latest_or_explicit(self.bundle_dir, secrets_path, "secrets_bundle")
        if not resolved:
            fail("Secrets bundle not found")
            return
        passphrase = self.read_passphrase(passphrase_env)
        restored = restore_bundle(resolved, target_root=target_root, passphrase=passphrase)
        ok(f"Restored {len(restored)} secret files from {resolved}")
        dim(f"Target root: {target_root}")

    def reconcile_host_cmd(
        self,
        manifest_path: str = "",
        home_root: str = "",
        bundle_path: str = "",
        secrets_path: str = "",
        target_root: str = "/",
        passphrase_env: str = "OMNI_SECRET_PASSPHRASE",
        profile: str = "",
    ):
        print_logo(compact=True)
        section("Host Reconcile")
        selected_path, manifest = self.resolve_manifest(manifest_path, home_root, create=True, profile=profile)
        passphrase = self.read_passphrase(passphrase_env)
        report = reconcile_host(
            manifest,
            bundle_path=bundle_path,
            secrets_path=secrets_path,
            passphrase=passphrase,
            target_root=target_root,
            repos=self.repo_entries,
        )
        ok(f"Reconcile completed using {selected_path}")
        for step in report.get("steps", []):
            name = step.get("name", "step")
            if "restored" in step:
                kv(name, str(step["restored"]), color=C.GRN, key_width=16)
            elif "changed" in step:
                kv(name, str(len(step.get("changed", []))), color=C.GRN, key_width=16)
            elif step.get("results") is not None:
                kv(name, str(len(step.get("results", []))), color=C.GRN, key_width=16)
            elif step.get("status"):
                kv(name, str(step.get("status")), color=C.GRN, key_width=16)
        nl()
        self.write_json_output(
            {
                "manifest_path": str(selected_path),
                "report": report,
            }
        )

    def install_timer_cmd(self, service_name: str = "omni-update", on_calendar: str = "daily"):
        print_logo(compact=True)
        section("Maintenance Services")
        timer_data = install_systemd_timer(omni_home=OMNI_HOME, service_name=service_name, on_calendar=on_calendar)
        watch_data = install_systemd_service(
            omni_home=OMNI_HOME,
            template_name="omni-watch.service",
            service_name="omni-watch",
        )
        ok(f"Installed {service_name}.timer")
        kv("Service", timer_data["service"], color=C.GRN)
        kv("Timer", timer_data["timer"], color=C.GRN)
        kv("Watch Service", watch_data["service"], color=C.GRN)

    def purge_cmd(
        self,
        manifest_path: str = "",
        home_root: str = "",
        include_secrets: bool = False,
        confirm: bool = False,
        profile: str = "",
    ):
        print_logo(compact=True)
        section("Purge Installed State")
        _, manifest = self.resolve_manifest(manifest_path, home_root, create=True, profile=profile)
        plan = build_purge_plan(
            manifest,
            omni_home=OMNI_HOME,
            bundle_dir=self.bundle_dir,
            backup_dir=BACKUP_DIR,
            state_dir=STATE_DIR,
            log_dir=LOG_DIR,
            include_secrets=include_secrets,
        )
        total = sum(int(item.get("size_bytes", 0)) for item in plan)
        if not plan:
            ok("Nothing to purge")
            return

        kv("Candidates", str(len(plan)), color=C.YLW)
        kv("Reclaimable", human_size(total), color=C.YLW)
        nl()
        for item in plan[:20]:
            bullet(f"{item['reason']}: {item['path']} ({human_size(int(item['size_bytes']))})", C.G3)
        if len(plan) > 20:
            dim(f"... {len(plan) - 20} more paths")
        nl()

        result = execute_purge(plan, dry_run=not confirm)
        if not confirm:
            warn("Dry run only. Re-run with --yes to delete these paths.")
            return

        ok(f"Removed {len(result['removed'])} paths")
        kv("Reclaimed", human_size(int(result["reclaimed_bytes"])), color=C.GRN)

    def sync_remote_servers(self):
        print_logo(compact=True)
        section("Remote Snapshot")
        result = self.sync_servers()
        if not result.get("results"):
            fail(result.get("message", "No remote servers configured"))
            hint(f"Create {SERVERS_FILE}")
            return

        for item in result["results"]:
            label = f"{item['server']} :: {item['path']} -> {item['target']}"
            if item.get("success"):
                ok(label)
            else:
                fail(label)
                dim(item.get("error", "Unknown error"))
        nl()
        if result.get("success"):
            ok(result["message"])
        else:
            warn(result["message"])

    def show_version(self):
        """Show version info."""
        print_logo(compact=True)
        section("Version Information")
        kv("Version", OMNI_VERSION)
        kv("Build", OMNI_BUILD)
        kv("Codename", OMNI_CODENAME)
        kv("Python", platform.python_version())
        kv("Platform", PLATFORM)
        nl()
        ok("OmniSync is up to date")

    def show_monitor(self, interval=5):
        """Continuous monitoring mode with live updates."""
        print_logo(compact=True)
        section("Live Monitor")
        print("  Press Ctrl+C to exit")
        print()

        try:
            while True:
                os.system('clear')
                print_logo(minimal=True)
                print("  " + q(C.W, "LIVE MONITOR", bold=True) + "  " + q(C.G3, f"(refresh: {interval}s)"))
                print()

                disk = self.fixer.check_disk_space()
                mem = self.fixer.check_memory()
                pm2 = self.fixer.check_and_fix_pm2()

                # Disk bar
                disk_pct = disk.get('usage_percent', 0)
                disk_color = C.GRN if disk_pct < 70 else C.YLW if disk_pct < 90 else C.RED
                print("  " + q(C.G3, "Disk".rjust(10)) + "  ", end="")
                print(score_bar(disk_pct, 30, color=disk_color) + "  " + q(C.W, f"{disk_pct}%"))

                # Memory bar
                mem_pct = mem.get('percent', 0)
                mem_color = C.GRN if mem_pct < 70 else C.YLW if mem_pct < 90 else C.RED
                print("  " + q(C.G3, "Memory".rjust(10)) + "  ", end="")
                print(score_bar(int(mem_pct), 30, color=mem_color) + "  " + q(C.W, f"{mem_pct:.1f}%"))

                # PM2 status
                pm2_count = pm2.get('total_processes', 0)
                restarted = len(pm2.get('restarted', []))
                pm2_color = C.GRN if restarted == 0 else C.RED
                print("  " + q(C.G3, "PM2".rjust(10)) + "  " + q(pm2_color, f"{pm2_count} processes") + (q(C.YLW, f" ({restarted} restarted)") if restarted else ""))

                print()
                hr()
                print("  " + q(C.G3, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                time.sleep(interval)

        except KeyboardInterrupt:
            print("\n  " + q(C.G3, "Monitor stopped."))

    def show_processes(self):
        """Show PM2 processes."""
        print_logo(compact=True)
        section("PM2 Processes")

        code, out, err = self.fixer.run_cmd("pm2 jlist")
        if code != 0:
            fail("Failed to get PM2 processes")
            return

        try:
            processes = json.loads(out)
            headers = ["ID", "Name", "Status", "CPU", "Mem"]
            rows = []
            for p in processes:
                pid = p.get('pm_id', '?')
                name = p.get('name', 'unknown')
                status = p.get('pm2_env', {}).get('status', 'unknown')
                cpu = p.get('monit', {}).get('cpu', 0)
                mem = p.get('monit', {}).get('memory', 0) / 1024 / 1024
                status_color = C.GRN if status == 'online' else C.RED if status in ['stopped', 'errored'] else C.YLW
                rows.append([str(pid), name, status, f"{cpu:.1f}%", f"{mem:.1f}MB"])

            print_table(headers, rows, colors={1: C.W, 3: C.GRN, 4: C.G3})

        except Exception as e:
            fail(f"Error: {e}")

    def show_repos(self):
        """Show repository status."""
        print_logo(compact=True)
        section("Repositories")

        git_res = self.fixer.check_git_repos(self.repos)
        repos = git_res.get('repos', {})

        for name, status in repos.items():
            branch = status.get('branch', 'unknown')
            has_changes = status.get('has_changes', False)
            pull_status = status.get('pull_status', 'unknown')

            status_icon = q(C.GRN, "✓") if not has_changes else q(C.YLW, "!")
            pull_icon = q(C.GRN, "synced") if pull_status == 'up_to_date' else q(C.G3, pull_status)

            print(f"  {status_icon}  " + q(C.W, name, bold=True))
            dim(f"     Branch: {branch}  ·  {pull_icon}")
            if has_changes:
                dim("     Uncommitted changes detected")
            print()

    def clean_temp(self):
        """Clean temporary files and caches."""
        print_logo(compact=True)
        section("Cleanup")

        with Spinner("Cleaning temporary files...", color=C.PRIMARY) as sp:
            try:
                # Clean apt cache
                self.fixer.run_cmd("sudo apt-get clean")
                # Clean journal logs
                self.fixer.run_cmd("journalctl --vacuum-time=3d")
                # Clean tmp
                self.fixer.run_cmd("find /tmp -type f -atime +7 -delete 2>/dev/null")
                sp.finish("Cleanup complete", success=True)
            except Exception as e:
                sp.finish(f"Cleanup error: {e}", success=False)


# ══════════════════════════════════════════════════════════════════════════════
# TABLE RENDERING
# ══════════════════════════════════════════════════════════════════════════════

def score_bar(score, width=20, color=None):
    """Render a score bar."""
    filled = int(width * score / 100)
    empty = width - filled
    c = color or (C.GRN if score < 70 else C.YLW if score < 90 else C.RED)
    return q(c, "█" * filled) + q(C.G3, "·" * empty)

def print_table(headers, rows, colors=None, max_col_width=40):
    """Render a formatted table."""
    if not rows:
        return

    col_count = len(headers)
    col_widths = [len(h) for h in headers]

    for row in rows:
        for i, cell in enumerate(row):
            if i < col_count:
                col_widths[i] = min(max(col_widths[i], len(str(cell))), max_col_width)

    top = "┌" + "┬".join(["─" * w for w in col_widths]) + "┐"
    mid = "├" + "┼".join(["─" * w for w in col_widths]) + "┤"
    bot = "└" + "┴".join(["─" * w for w in col_widths]) + "┘"

    def _line(cells, header=False):
        parts = []
        for i, cell in enumerate(cells):
            w = col_widths[i]
            cell_str = str(cell)[:w].ljust(w)
            c = colors.get(i, C.W) if colors else C.W
            parts.append(q(c, cell_str))
        return "│" + "│".join(parts) + "│"

    print("  " + q(C.G3, top))
    print("  " + _line(headers, header=True))
    print("  " + q(C.G3, mid))
    for row in rows:
        print("  " + _line([row[i] if i < len(row) else "" for i in range(col_count)]))
    print("  " + q(C.G3, bot))


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

import logging
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "omni.log")
    ]
)
logger = logging.getLogger("omni.core")

def main():
    parser = argparse.ArgumentParser(description="OmniSync - Portable migration CLI", add_help=False)
    parser.add_argument("action", nargs="?", default="start", help="Action to perform")
    parser.add_argument("--interval", type=int, default=300, help="Interval for watch mode (seconds)")
    parser.add_argument("--lines", type=int, default=50, help="Number of log lines")
    parser.add_argument("--follow", "-f", action="store_true", help="Follow logs")
    parser.add_argument("--protocol", type=str, default="scp", help="Transfer protocol")
    parser.add_argument("--compress", action="store_true", default=True, help="Enable compression")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without mutating local or remote state")
    parser.add_argument("--help", "-h", action="store_true", help="Show help")
    parser.add_argument("--manifest", type=str, default=str(SYSTEM_MANIFEST_FILE), help="Path to system manifest")
    parser.add_argument("--output", type=str, default="", help="Output file or directory")
    parser.add_argument("--bundle", type=str, default="", help="Path to state bundle")
    parser.add_argument("--bundle-latest", action="store_true", help="Use latest state bundle from bundle dir")
    parser.add_argument("--secrets", type=str, default="", help="Path to secrets bundle")
    parser.add_argument("--secrets-latest", action="store_true", help="Use latest secrets bundle from bundle dir")
    parser.add_argument("--target-root", type=str, default="/", help="Restore target root")
    parser.add_argument("--home-root", type=str, default=str(Path.home()), help="Home root to inventory")
    parser.add_argument("--profile", type=str, default=os.environ.get("OMNI_PROFILE", "").strip(), help="Manifest profile (production-clean|full-home)")
    parser.add_argument("--passphrase-env", type=str, default="OMNI_SECRET_PASSPHRASE", help="Environment variable containing secrets passphrase")
    parser.add_argument("--service-name", type=str, default="omni-update", help="Systemd service/timer name")
    parser.add_argument("--on-calendar", type=str, default="daily", help="systemd OnCalendar value")
    parser.add_argument("--yes", action="store_true", help="Confirm destructive operations")
    parser.add_argument("--accept-all", action="store_true", help="Accept Omni prompts non-interactively")
    parser.add_argument("--include-secrets", action="store_true", help="Include secret paths in purge")
    parser.add_argument("--target-public-ip", type=str, default="", help="Target public IP for rewrite/migrate")
    parser.add_argument("--target-private-ip", type=str, default="", help="Target private IP for rewrite/migrate")
    parser.add_argument("--target-hostname", type=str, default="", help="Target hostname/FQDN for rewrite/migrate")
    parser.add_argument("--context-lines", type=int, default=2, help="Context lines for rewrite previews")
    parser.add_argument("--apply", action="store_true", help="Apply changes for rewrite-style commands")
    parser.add_argument("--skip-rewrite", action="store_true", help="Skip automatic host reference rewrite during migrate")
    parser.add_argument("--dest", type=str, default="", help="Remote destination for bridge send")
    parser.add_argument("--briefcase", type=str, default="", help="Path to an exported briefcase JSON")
    parser.add_argument("--restore-script", type=str, default="", help="Path for the generated restore shell script")
    parser.add_argument("--full", action="store_true", help="Capture the full maleta inventory and emit a restore script")
    parser.add_argument("--repo", type=str, default="", help="GitHub repo slug (owner/repo) for auth/push/pull flows")
    parser.add_argument("--language", type=str, default="", help="UI language preference (es|en)")
    parser.add_argument("--host", type=str, default="", help="SSH destination host for omni connect")
    parser.add_argument("--user", type=str, default="", help="SSH user for omni connect")
    parser.add_argument("--port", type=int, default=None, help="SSH port for omni connect")
    parser.add_argument("--key-path", type=str, default="", help="Path to SSH identity file")
    parser.add_argument("--auth-mode", type=str, default="", help="SSH auth mode for omni connect (agent|key|password)")
    parser.add_argument("--password-env", type=str, default="OMNI_SSH_PASSWORD", help="Environment variable containing the SSH password")
    parser.add_argument("--target-system", type=str, default="", help="Remote host family for omni connect (auto|linux|windows|macos|wsl)")
    parser.add_argument("--remote-path", type=str, default="~/omni-transfer", help="Remote directory for payload transfer")

    args, remaining = parser.parse_known_args()
    args.profile = str(args.profile or "").strip().lower().replace("_", "-")

    if args.debug:
        global OMNI_DEBUG
        OMNI_DEBUG = True
    if args.verbose:
        global OMNI_VERBOSE
        OMNI_VERBOSE = True
    if args.dry_run:
        global OMNI_DRY_RUN
        OMNI_DRY_RUN = True
        os.environ["OMNI_DRY_RUN"] = "1"

    # Resolve alias
    normalized_action = str(args.action or "start").strip()
    action = ALIASES.get(normalized_action.lower(), normalized_action.lower())

    core = OmniCore()

    try:
        if action in ["help", "?"] or args.help:
            core.show_help()
        elif action == "start":
            core.start_guided(accept_all=should_accept_all(args.accept_all, args.yes, env=os.environ))
        elif action == "check":
            core.run_health_check()
        elif action == "fix":
            core.run_full_fix()
        elif action == "watch":
            core.watch_mode(
                args.interval,
                manifest_path=args.manifest,
                home_root=args.home_root,
                profile=args.profile,
            )
        elif action == "status":
            core.show_status()
        elif action == "guide":
            core.guide_cmd()
        elif action == "continue":
            core.continue_cmd()
        elif action == "chat":
            core.chat_cmd(" ".join(remaining), accept_all=should_accept_all(args.accept_all, args.yes, env=os.environ))
        elif action == "auth":
            core.auth_cmd(remaining[0] if remaining else "", repo_slug=args.repo)
        elif action == "push":
            core.push_cmd(
                manifest_path=args.manifest,
                home_root=args.home_root,
                profile=args.profile,
                briefcase_path=args.briefcase,
                repo_slug=args.repo,
            )
        elif action == "pull":
            core.pull_cmd(output=args.output, apply_restore=args.apply, repo_slug=args.repo)
        elif action == "doctor":
            core.show_doctor()
        elif action == "logs":
            core.show_logs(args.lines, args.follow)
        elif action == "restart":
            core.restart_services()
        elif action == "backup":
            core.run_backup(
                target=args.output or None,
                manifest_path=args.manifest,
                home_root=args.home_root,
                passphrase_env=args.passphrase_env,
                profile=args.profile,
            )
        elif action in ["transfer", "tr"]:
            if len(remaining) >= 2:
                core.run_transfer(remaining[0], remaining[1], {"protocol": args.protocol, "compress": args.compress})
            else:
                fail("Source and destination required")
                hint("Usage: omni transfer <src> <dest>")
        elif action == "config":
            core.config_cmd(remaining[0] if remaining else "", value=args.language or (remaining[1] if len(remaining) > 1 else ""))
        elif action == "connect":
            core.connect_cmd(
                host=args.host,
                user=args.user,
                port=args.port,
                key_path=args.key_path,
                auth_mode=args.auth_mode,
                password_env=args.password_env,
                target_system=args.target_system,
                remote_path=args.remote_path,
                transport=args.protocol,
                briefcase_path=args.briefcase,
                manifest_path=args.manifest,
                home_root=args.home_root,
                profile=args.profile,
            )
        elif action == "version":
            core.show_version()
        elif action == "monitor":
            core.show_monitor(5)
        elif action == "clean":
            core.clean_temp()
        elif action == "repos":
            core.show_repos()
        elif action == "processes":
            core.show_processes()
        elif action == "install":
            core.show_install_guide()
        elif action == "init":
            core.init_workspace(profile=args.profile)
        elif action == "sync":
            core.sync_remote_servers()
        elif action == "capture":
            core.capture_host_cmd(args.manifest, args.home_root, args.output, args.passphrase_env, accept_all=should_accept_all(args.accept_all, args.yes, env=os.environ), profile=args.profile)
        elif action == "restore":
            core.restore_host_cmd(
                manifest_path=args.manifest,
                home_root=args.home_root,
                bundle_path=args.bundle,
                secrets_path=args.secrets,
                target_root=args.target_root,
                passphrase_env=args.passphrase_env,
                accept_all=should_accept_all(args.accept_all, args.yes, env=os.environ),
                install_timer=args.yes or args.accept_all,
                on_calendar=args.on_calendar,
                profile=args.profile,
            )
        elif action == "migrate":
            if remaining[:1] == ["sync"]:
                core.migrate_sync_cmd(
                    remaining[1] if len(remaining) > 1 else "",
                    manifest_path=args.manifest,
                    home_root=args.home_root,
                    output=args.output,
                    passphrase_env=args.passphrase_env,
                    profile=args.profile,
                    briefcase_path=args.briefcase,
                    accept_all=should_accept_all(args.accept_all, args.yes, env=os.environ),
                    target_root=args.target_root,
                    on_calendar=args.on_calendar,
                    full=args.full,
                    restore_script_output=args.restore_script,
                )
                return
            core.migrate_host_cmd(
                manifest_path=args.manifest,
                home_root=args.home_root,
                bundle_path=args.bundle,
                secrets_path=args.secrets,
                target_root=args.target_root,
                passphrase_env=args.passphrase_env,
                accept_all=should_accept_all(args.accept_all, args.yes, env=os.environ),
                install_timer=args.yes or args.accept_all,
                on_calendar=args.on_calendar,
                apply_rewrite=not args.skip_rewrite,
                profile=args.profile,
            )
        elif action == "detect-ip":
            core.detect_ip_cmd()
        elif action == "rewrite-ip":
            root = remaining[0] if remaining else args.home_root
            core.rewrite_ip_cmd(
                root=root,
                target_public_ip=args.target_public_ip,
                target_private_ip=args.target_private_ip,
                target_hostname=args.target_hostname,
                apply_changes=args.apply,
                accept_all=should_accept_all(args.accept_all, args.yes, env=os.environ),
                context_lines=args.context_lines,
            )
        elif action == "agent":
            agent_action = remaining[0] if remaining else ""
            core.agent_cmd(agent_action, accept_all=should_accept_all(args.accept_all, args.yes, env=os.environ))
        elif action == "bridge":
            bridge_action = remaining[0] if remaining else ""
            if bridge_action in {"create", ""}:
                core.capture_host_cmd(args.manifest, args.home_root, args.output, args.passphrase_env, accept_all=should_accept_all(args.accept_all, args.yes, env=os.environ), profile=args.profile)
            elif bridge_action == "send":
                core.bridge_mode(accept_all=should_accept_all(args.accept_all, args.yes, env=os.environ), dest=args.dest or (remaining[1] if len(remaining) > 1 else ""), protocol=args.protocol)
            elif bridge_action in {"receive", "restore"}:
                core.restore_host_cmd(
                    manifest_path=args.manifest,
                    home_root=args.home_root,
                    bundle_path=args.bundle,
                    secrets_path=args.secrets,
                    target_root=args.target_root,
                    passphrase_env=args.passphrase_env,
                    accept_all=should_accept_all(args.accept_all, args.yes, env=os.environ),
                    install_timer=args.yes or args.accept_all,
                    on_calendar=args.on_calendar,
                    profile=args.profile,
                )
            else:
                fail(f"Unknown bridge action: {bridge_action}")
                hint("Use: omni bridge create|send|receive")
        elif action == "inventory":
            core.show_inventory(args.manifest, args.home_root, args.output, profile=args.profile)
        elif action == "briefcase":
            core.show_briefcase(
                args.manifest,
                args.home_root,
                args.output,
                profile=args.profile,
                full=args.full,
                restore_script_output=args.restore_script,
            )
        elif action == "restore-plan":
            core.show_restore_plan(args.manifest, args.home_root, args.output, profile=args.profile, briefcase_path=args.briefcase)
        elif action == "bundle-create":
            core.create_state_bundle_cmd(args.manifest, args.home_root, args.output, profile=args.profile)
        elif action == "bundle-restore":
            bundle_path = args.bundle
            if args.bundle_latest and not bundle_path:
                bundle_path = ""
            core.restore_state_bundle_cmd(bundle_path, args.target_root)
        elif action == "secrets-export":
            core.export_secrets_cmd(args.manifest, args.home_root, args.output, args.passphrase_env, profile=args.profile)
        elif action == "secrets-import":
            secrets_path = args.secrets
            if args.secrets_latest and not secrets_path:
                secrets_path = ""
            core.import_secrets_cmd(secrets_path, args.target_root, args.passphrase_env)
        elif action == "reconcile":
            resolved_bundle = ""
            resolved_secrets = ""
            if args.bundle or args.bundle_latest:
                resolved_bundle = str(latest_or_explicit(core.bundle_dir, args.bundle, "state_bundle") or "")
            if args.secrets or args.secrets_latest:
                resolved_secrets = str(latest_or_explicit(core.bundle_dir, args.secrets, "secrets_bundle") or "")
            core.reconcile_host_cmd(
                args.manifest,
                args.home_root,
                resolved_bundle,
                resolved_secrets,
                args.target_root,
                args.passphrase_env,
                profile=args.profile,
            )
        elif action == "timer-install":
            core.install_timer_cmd(args.service_name, args.on_calendar)
        elif action == "purge":
            core.purge_cmd(args.manifest, args.home_root, args.include_secrets, args.yes, profile=args.profile)
        else:
            render_human_error(
                f"Unknown action: {action}",
                suggestion="Run `omni help` or `omni guide` for available commands.",
            )
    except KeyboardInterrupt:
        print()
        warn("Operación cancelada por el usuario.")
        sys.exit(130)

if __name__ == "__main__":
    main()

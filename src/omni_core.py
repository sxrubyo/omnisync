#!/usr/bin/env python3
"""
Omni Core v2.0 - The Supreme Coordinator
Enterprise-grade system orchestration with premium UI.
2026 Edition.
"""

import sys
import os
import json
import time
import threading
import random
import argparse
import subprocess
import shlex
import shutil
import platform
import textwrap
import ipaddress
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
from pathlib import Path

from bundle_ops import (
    create_secrets_bundle,
    create_state_bundle,
    latest_or_explicit,
    restore_bundle,
)
from agent_ops import env_has_value, get_provider, load_agent_config, provider_catalog, save_agent_config, upsert_env_value
from chat_ops import (
    chat_completion,
    clean_assistant_output,
    ensure_activation_prompt,
    ensure_chat_permissions,
    latest_chat_session_path,
    load_chat_session,
    load_env_value,
    new_chat_session,
    parse_action_block,
    save_chat_session,
)
from operator_ops import build_operator_response, infer_migration_mode
from permissions_ops import (
    build_permission_prompt,
    ensure_permissions_state,
    evaluate_permission_decision,
    parse_permissions_request,
    render_permissions_lines,
)
from bridge_ops import (
    build_host_rewrite_context,
    load_capture_summary,
    summarize_bundle_pair,
    write_capture_summary,
)
from cleanup_ops import build_purge_plan, execute_purge
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
from playbook_ops import (
    DEFAULT_REF_NAME,
    DEFAULT_REMOTE_USER,
    DEFAULT_REPO_URL,
    build_examples_catalog,
    build_powershell_auto_command,
    build_powershell_dropper_script,
    build_powershell_auto_script,
    build_windows_ps1_path,
)
from reconcile_ops import install_systemd_service, install_systemd_timer, reconcile_host
from runtime_inventory_ops import (
    capture_installed_inventory,
    load_installed_inventory,
    merge_manifest_runtime_inventory,
    summarize_installed_inventory,
    write_installed_inventory,
)
from watch_ops import capture_watch_snapshot, load_watch_snapshot, save_watch_snapshot, summarize_snapshot_diff


APP_DIR = Path(__file__).resolve().parents[1]
OMNI_HOME = Path(os.environ.get("OMNI_HOME", APP_DIR)).resolve()
CONFIG_DIR = Path(os.environ.get("OMNI_CONFIG_DIR", OMNI_HOME / "config")).resolve()
STATE_DIR = Path(os.environ.get("OMNI_STATE_DIR", OMNI_HOME / "data")).resolve()
BACKUP_DIR = Path(os.environ.get("OMNI_BACKUP_DIR", OMNI_HOME / "backups")).resolve()
BUNDLE_DIR = Path(os.environ.get("OMNI_BUNDLE_DIR", BACKUP_DIR / "host-bundles")).resolve()
AUTO_BUNDLE_DIR = Path(os.environ.get("OMNI_AUTO_BUNDLE_DIR", BACKUP_DIR / "auto-bundles")).resolve()
LOG_DIR = Path(os.environ.get("OMNI_LOG_DIR", OMNI_HOME / "logs")).resolve()
WATCH_STATE_FILE = Path(os.environ.get("OMNI_WATCH_STATE_FILE", STATE_DIR / "watch_snapshot.json")).resolve()
ENV_FILE = Path(os.environ.get("OMNI_ENV_FILE", OMNI_HOME / ".env")).resolve()
AGENT_CONFIG_FILE = Path(os.environ.get("OMNI_AGENT_CONFIG_FILE", CONFIG_DIR / "omni_agent.json")).resolve()
AGENT_ACTIVATION_FILE = Path(
    os.environ.get("OMNI_AGENT_ACTIVATION_FILE", CONFIG_DIR / "omni_agent_activation.txt")
).resolve()
AGENT_CHAT_DIR = Path(os.environ.get("OMNI_CHAT_DIR", STATE_DIR / "agent-chat")).resolve()
TASKS_FILE = Path(os.environ.get("OMNI_TASKS_FILE", OMNI_HOME / "tasks.json")).resolve()
REPOS_FILE = Path(os.environ.get("OMNI_REPOS_FILE", CONFIG_DIR / "repos.json")).resolve()
SERVERS_FILE = Path(os.environ.get("OMNI_SERVERS_FILE", CONFIG_DIR / "servers.json")).resolve()
SYSTEM_MANIFEST_FILE = Path(
    os.environ.get("OMNI_MANIFEST_FILE", CONFIG_DIR / "system_manifest.json")
).resolve()
AUTO_BACKUP_ON_CHANGE = os.environ.get("OMNI_AUTO_BACKUP_ON_CHANGE", "1").strip().lower() in {"1", "true", "yes", "on"}
AUTO_BACKUP_KEEP = max(1, int(os.environ.get("OMNI_AUTO_BACKUP_KEEP", "5")))
WATCH_BACKUP_COOLDOWN = max(30, int(os.environ.get("OMNI_WATCH_BACKUP_COOLDOWN", "600")))


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

SSH_METADATA_FILES = {"authorized_keys", "config"}


def discover_ssh_identity_candidates(ssh_dir: Path | None = None) -> List[Path]:
    base_dir = Path(ssh_dir).expanduser() if ssh_dir else (Path.home() / ".ssh")
    if not base_dir.exists() or not base_dir.is_dir():
        return []

    candidates: List[Path] = []
    for candidate in sorted(base_dir.iterdir()):
        name = candidate.name
        if not candidate.is_file():
            continue
        if name in SSH_METADATA_FILES or name.endswith(".pub") or name.startswith("known_hosts"):
            continue
        candidates.append(candidate.resolve())
    return candidates


def resolve_server_identity_file(
    server: Dict[str, Any],
    ssh_dir: Path | None = None,
    env: Optional[Dict[str, str]] = None,
) -> str:
    env_map = os.environ if env is None else env
    explicit = str(server.get("identity_file") or env_map.get("OMNI_SSH_IDENTITY_FILE") or "").strip()
    if explicit:
        return str(Path(os.path.expandvars(explicit)).expanduser())

    candidates = discover_ssh_identity_candidates(ssh_dir)
    if len(candidates) == 1:
        return str(candidates[0])
    return ""


def _normalize_ssh_options(raw_options: Any) -> List[str]:
    if not raw_options:
        return []
    if isinstance(raw_options, str):
        return [raw_options]
    if isinstance(raw_options, list):
        return [str(option).strip() for option in raw_options if str(option).strip()]
    return []


def build_ssh_transport_command(
    server: Dict[str, Any],
    ssh_dir: Path | None = None,
    env: Optional[Dict[str, str]] = None,
) -> str:
    port = int(server.get("port", 22))
    command: List[str] = ["ssh", "-p", str(port), "-o", "StrictHostKeyChecking=accept-new"]
    identity_file = resolve_server_identity_file(server, ssh_dir=ssh_dir, env=env)
    if identity_file:
        command.extend(["-i", identity_file])
    for option in _normalize_ssh_options(server.get("ssh_options")):
        if option.startswith("-"):
            command.append(option)
        else:
            command.extend(["-o", option])
    return " ".join(shlex.quote(part) for part in command)


def build_remote_sync_command(
    server: Dict[str, Any],
    remote_path: str,
    target_dir: Path,
    *,
    ssh_dir: Path | None = None,
    env: Optional[Dict[str, str]] = None,
    delete: bool = True,
) -> str:
    user = str(server.get("user", "ubuntu"))
    host = str(server.get("host", "")).strip()
    port = int(server.get("port", 22))
    protocol = str(server.get("protocol", "rsync")).strip().lower()
    excludes = [str(pattern) for pattern in server.get("excludes", []) or [] if str(pattern).strip()]
    identity_file = resolve_server_identity_file(server, ssh_dir=ssh_dir, env=env)

    if protocol == "scp":
        parts: List[str] = ["scp", "-P", str(port), "-o", "StrictHostKeyChecking=accept-new"]
        if identity_file:
            parts.extend(["-i", identity_file])
        for option in _normalize_ssh_options(server.get("ssh_options")):
            if option.startswith("-"):
                parts.append(option)
            else:
                parts.extend(["-o", option])
        parts.extend(["-r", f"{user}@{host}:{remote_path}", str(target_dir)])
        return " ".join(shlex.quote(part) for part in parts)

    exclude_flags = " ".join(f"--exclude {shlex.quote(pattern)}" for pattern in excludes)
    transport = build_ssh_transport_command(server, ssh_dir=ssh_dir, env=env)
    remote_spec = f"{user}@{host}:{shlex.quote(remote_path.rstrip('/') + '/')}"
    delete_flag = " --delete" if delete else ""
    return (
        f"rsync -az{delete_flag} -e {shlex.quote(transport)} {exclude_flags} "
        f"{remote_spec} {shlex.quote(str(target_dir))}/"
    ).strip()


def resolve_latest_bundle_across_dirs(
    bundle_dirs: List[Path],
    explicit_path: str,
    prefix: str,
) -> Optional[Path]:
    if explicit_path:
        explicit = Path(explicit_path).expanduser()
        return explicit if explicit.exists() else explicit

    seen: set[str] = set()
    for bundle_dir in bundle_dirs:
        bundle_root = Path(bundle_dir).expanduser()
        key = str(bundle_root.resolve()) if bundle_root.exists() else str(bundle_root)
        if key in seen:
            continue
        seen.add(key)
        candidate = latest_or_explicit(bundle_root, "", prefix)
        if candidate and candidate.exists():
            return candidate
    return None


def resolve_installed_inventory_across_dirs(
    bundle_dirs: List[Path],
    explicit_path: str = "",
) -> Optional[Dict[str, Any]]:
    if explicit_path:
        explicit = Path(explicit_path).expanduser()
        return load_installed_inventory(explicit.parent, explicit_path=str(explicit))

    seen: set[str] = set()
    for bundle_dir in bundle_dirs:
        bundle_root = Path(bundle_dir).expanduser()
        key = str(bundle_root.resolve()) if bundle_root.exists() else str(bundle_root)
        if key in seen:
            continue
        seen.add(key)
        payload = load_installed_inventory(bundle_root)
        if payload:
            return payload
    return None


def _is_ip_literal(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def enrich_rewrite_context_from_servers(
    context: Dict[str, Any],
    servers: List[Dict[str, Any]],
    identity: Any,
) -> Dict[str, Any]:
    if context.get("summary_found") or not servers:
        return context

    current_targets = {
        str(getattr(identity, "public_ip", "") or "").strip(),
        str(getattr(identity, "private_ip", "") or "").strip(),
        str(getattr(identity, "hostname", "") or "").strip(),
        str(getattr(identity, "fqdn", "") or "").strip(),
    }
    candidates: List[str] = []
    for server in servers:
        host = str(server.get("host", "")).strip()
        if not host or host == "1.2.3.4" or host in current_targets:
            continue
        if host not in candidates:
            candidates.append(host)

    if not candidates:
        return context

    replacements = dict(context.get("replacements") or {})
    target_ip = str(getattr(identity, "public_ip", "") or getattr(identity, "private_ip", "") or "").strip()
    target_host = str(getattr(identity, "hostname", "") or getattr(identity, "fqdn", "") or "").strip()
    chosen_source = candidates[0]
    for candidate in candidates:
        if _is_ip_literal(candidate) and target_ip:
            replacements.setdefault(candidate, target_ip)
        elif target_host:
            replacements.setdefault(candidate, target_host)

    source_identity = dict(context.get("source_identity") or {})
    if _is_ip_literal(chosen_source):
        source_identity.setdefault("public_ip", chosen_source)
    else:
        source_identity.setdefault("hostname", chosen_source)

    enriched = dict(context)
    enriched["summary_found"] = bool(replacements)
    enriched["summary"] = enriched.get("summary") or {
        "source": "servers_json",
        "source_identity": source_identity,
    }
    enriched["source_identity"] = source_identity
    enriched["replacements"] = replacements
    return enriched

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

OMNI_VERSION = "2.1.0"
OMNI_BUILD = "2026.03.portable"
OMNI_CODENAME = "Titan"

_TAGLINES = [
    "The Supreme Coordinator.",
    "Your system, orchestrated.",
    "Automation at scale.",
    "The layer between chaos and order.",
    "System health, guaranteed.",
    "Every process, accounted for.",
    "Governance at machine speed.",
    "Sleep well. Your system is supervised.",
]

ALIASES = {
    "s": "status", "f": "fix", "w": "watch", "c": "check", "h": "help",
    "?": "help", "r": "restart", "l": "logs", "t": "transfer", "b": "backup",
    "m": "monitor", "cfg": "config", "v": "version", "st": "stats",
    "proc": "processes", "repo": "repos", "up": "update", "cl": "clean",
    "i": "init",
    "tr": "transfer",
    "ex": "examples",
    "pb": "examples",
    "a": "auto",
    "cmd": "commands",
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
    return option_count >= 10


def _apply_menu_digit_input(buffer: str, key: str, option_count: int) -> tuple[str, Optional[int]]:
    if not key.isdigit():
        return buffer, None
    if not _should_buffer_menu_digits(option_count):
        numeric = int(key) - 1
        return "", numeric if 0 <= numeric < option_count else None
    max_digits = max(2, len(str(option_count)))
    next_buffer = (buffer + key)[:max_digits]
    return next_buffer, None


def _resolve_buffered_menu_selection(buffer: str, current: int, option_count: int) -> int:
    if buffer.isdigit():
        numeric = int(buffer) - 1
        if 0 <= numeric < option_count:
            return numeric
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
    digit_buffer = ""

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

    def draw(first: bool = False) -> None:
        nonlocal scroll_offset
        if current < scroll_offset:
            scroll_offset = current
        elif current >= scroll_offset + page_size:
            scroll_offset = current - page_size + 1

        visible = range(scroll_offset, min(len(options), scroll_offset + page_size))
        out: List[str] = []
        if not first:
            out.append("\033[u\033[J")
        else:
            out.append("\033[s")

        if title:
            out.append("\n  " + q(C.G2, title) + "\n")
            out.append("  " + q(C.G3, "Usa ↑/↓ y Enter. También puedes saltar con un número.") + "\n\n")

        for idx in visible:
            prefix = q(C.PRIMARY, f"{idx + 1}.", bold=True) + "  " if show_index else ""
            icon = f"{icons[idx]}  " if idx < len(icons) and icons[idx] else ""
            if idx == current:
                out.append("  " + q(C.B6, "▸", bold=True) + "  " + prefix + icon + q(C.W, options[idx], bold=True) + "\n")
            else:
                out.append("     " + prefix + icon + q(C.G2, options[idx]) + "\n")

            if idx < len(descriptions) and descriptions[idx]:
                out.append("       " + q(C.G2 if idx == current else C.G3, descriptions[idx]) + "\n")

        if scroll_offset > 0:
            out.append("       " + q(C.G3, "↑ hay más arriba") + "\n")
        if scroll_offset + page_size < len(options):
            out.append("       " + q(C.G3, "↓ hay más abajo") + "\n")

        out.append("\n")
        if digit_buffer:
            out.append("  " + q(C.PRIMARY, f"número: {digit_buffer}") + "\n")
        dynamic_footer = footer or (
            "↑/↓ seleccionar · j/k mover · Enter confirmar · número + Enter"
            if _should_buffer_menu_digits(len(options))
            else "↑/↓ seleccionar · j/k mover · Enter confirmar · número salto directo"
        )
        out.append("  " + q(C.G3, dynamic_footer) + "\n")
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    if IS_WINDOWS:
        import msvcrt

        draw(first=True)
        while True:
            ch = msvcrt.getch()
            if ch in (b"\r", b"\n"):
                return _resolve_buffered_menu_selection(digit_buffer, current, len(options))
            if ch == b"\x03":
                raise KeyboardInterrupt
            if ch in (b"\x00", b"\xe0"):
                ch2 = msvcrt.getch()
                if ch2 == b"H" and current > 0:
                    current -= 1
                    digit_buffer = ""
                    draw()
                elif ch2 == b"P" and current < len(options) - 1:
                    current += 1
                    digit_buffer = ""
                    draw()
                continue
            try:
                key = ch.decode(errors="ignore")
            except Exception:
                continue
            if key in ("k", "K") and current > 0:
                current -= 1
                digit_buffer = ""
                draw()
            elif key in ("j", "J") and current < len(options) - 1:
                current += 1
                digit_buffer = ""
                draw()
            elif key in ("\b", "\x08"):
                digit_buffer = digit_buffer[:-1]
                draw()
            elif key.isdigit():
                digit_buffer, selection = _apply_menu_digit_input(digit_buffer, key, len(options))
                if selection is not None:
                    return selection
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
                return _resolve_buffered_menu_selection(digit_buffer, current, len(options))
            if key == "\x03":
                raise KeyboardInterrupt
            if key in ("UP", "k", "K") and current > 0:
                current -= 1
                digit_buffer = ""
                draw()
            elif key in ("DOWN", "j", "J") and current < len(options) - 1:
                current += 1
                digit_buffer = ""
                draw()
            elif key in ("\x7f", "\b"):
                digit_buffer = digit_buffer[:-1]
                draw()
            elif key.isdigit():
                digit_buffer, selection = _apply_menu_digit_input(digit_buffer, key, len(options))
                if selection is not None:
                    return selection
                draw()

    return current


def prompt_paste_friendly_value(prompt: str, default: str = "", *, uppercase: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    print()
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        print()
        return default
    except KeyboardInterrupt:
        print()
        raise
    value = answer or default
    return value.upper() if uppercase else value


def prompt_paste_friendly_secret(prompt: str) -> str:
    print()
    dim("Pega normal. Esta entrada se muestra para maximizar compatibilidad con PowerShell, SSH y terminales mixtos.")
    try:
        return input(f"{prompt}: ").strip()
    except EOFError:
        print()
        return ""
    except KeyboardInterrupt:
        print()
        raise


def render_action_summary(title: str, lines: List[str], *, accent: Optional[str] = None, width: int = 88):
    clean_lines = [line for line in lines if line is not None]
    box(title, clean_lines, width=min(width, max(72, TERM_WIDTH - 4)), accent=accent or C.PRIMARY)


def render_help_overview():
    tips = [
        "Quickstart: cp .env.example .env  |  edit config/repos.json  |  docker compose up -d",
        "Portable state stays clean: config/, data/, backups/, logs/, tasks.json and host bundles",
        "To migrate: inventory -> bundle-create -> secrets-export -> reconcile -> timer-install",
        "Keep secrets out of git: .env, tokens and SSH material go in the encrypted secrets pack",
    ]
    box("OMNI CONTROL SURFACE", tips, width=84, accent=C.PRIMARY)


def path_to_snapshot_name(raw_path: str) -> str:
    clean = raw_path.strip().replace("\\", "/").strip("/")
    if not clean:
        return "root"
    return clean.replace("/", "__").replace(":", "")

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
        banner = f"✦ omni · v{OMNI_VERSION} · Supreme Coordinator"
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
        print("  " + q(C.GLD_BRIGHT, "✦") + " " + q(C.G3, "Omni Core · Enterprise Edition"))
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
        self.ensure_runtime_dirs()
        self.manifest_path = SYSTEM_MANIFEST_FILE
        self.bundle_dir = BUNDLE_DIR
        self.repo_entries = self.load_repo_entries()
        self.repos = self.repo_paths_from_entries(self.repo_entries)
        self.servers = self.load_servers()
        self.load_tasks()

    def ensure_runtime_dirs(self):
        for path in (OMNI_HOME, CONFIG_DIR, STATE_DIR, BACKUP_DIR, BUNDLE_DIR, AUTO_BUNDLE_DIR, LOG_DIR, AGENT_CHAT_DIR):
            path.mkdir(parents=True, exist_ok=True)

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
            if not isinstance(servers, list):
                return []
            normalized: List[Dict[str, Any]] = []
            for server in servers:
                if not isinstance(server, dict):
                    continue
                item = dict(server)
                identity_file = str(item.get("identity_file") or "").strip()
                if identity_file:
                    item["identity_file"] = str(Path(os.path.expandvars(identity_file)).expanduser())
                normalized.append(item)
            return normalized
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

    def prune_bundle_dir(self, bundle_dir: Path, keep: int = AUTO_BACKUP_KEEP) -> None:
        for pattern in ("state_bundle_*", "secrets_bundle_*", "capture_summary_*.json", "installed_inventory_*.json"):
            candidates = sorted(bundle_dir.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
            for stale in candidates[keep:]:
                try:
                    stale.unlink()
                except OSError:
                    continue

    def bundle_search_dirs(self, *, include_auto: bool = True) -> List[Path]:
        directories = [self.bundle_dir]
        if include_auto:
            directories.append(self.auto_backup_dir())
        unique: List[Path] = []
        seen: set[str] = set()
        for candidate in directories:
            resolved = str(candidate.resolve()) if candidate.exists() else str(candidate)
            if resolved in seen:
                continue
            seen.add(resolved)
            unique.append(candidate)
        return unique

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
        installed_inventory = capture_installed_inventory()
        installed_inventory_path = write_installed_inventory(target_dir, installed_inventory)
        summary_path = write_capture_summary(
            bundle_dir=target_dir,
            manifest_path=selected_path,
            state_bundle=state_bundle,
            secrets_bundle=secrets_bundle,
            installed_inventory_path=installed_inventory_path,
            installed_inventory=installed_inventory,
        )
        if prune:
            self.prune_bundle_dir(target_dir, keep=AUTO_BACKUP_KEEP)
        return {
            "manifest_path": str(selected_path),
            "manifest": manifest,
            "bundle_dir": str(target_dir),
            "state_bundle": str(state_bundle),
            "secrets_bundle": str(secrets_bundle),
            "installed_inventory_path": str(installed_inventory_path),
            "installed_inventory": installed_inventory,
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
                target_dir = server_root / path_to_snapshot_name(remote_path)
                target_dir.mkdir(parents=True, exist_ok=True)
                cmd = build_remote_sync_command(
                    {
                        "user": user,
                        "host": host,
                        "port": port,
                        "protocol": protocol,
                        "excludes": excludes,
                        "identity_file": server.get("identity_file", ""),
                        "ssh_options": server.get("ssh_options", []),
                    },
                    remote_path,
                    target_dir,
                    delete=True,
                )

                logger.info("Syncing %s:%s", name, remote_path)
                code, out, err = self.transfer._run_cmd(cmd)
                error = err if code != 0 else ""
                if code != 0 and "Permission denied (publickey)" in error:
                    hint = "Configure `identity_file` in config/servers.json or leave a single private key in ~/.ssh."
                    error = f"{error}\n{hint}"
                results.append({
                    "server": name,
                    "path": remote_path,
                    "protocol": protocol,
                    "success": code == 0,
                    "target": str(target_dir),
                    "error": error,
                    "output": out if code == 0 else "",
                })

        ok_count = sum(1 for item in results if item.get("success"))
        return {
            "success": ok_count == len(results) and len(results) > 0,
            "message": f"Synced {ok_count}/{len(results)} remote paths",
            "results": results,
        }

    def has_ready_remote_source(self) -> bool:
        for server in self.servers:
            host = str(server.get("host", "")).strip()
            paths = server.get("paths", [])
            if host and host != "1.2.3.4" and paths:
                return True
        return False

    def _run_transfer_cmd_visible(self, cmd: str, label: str) -> Tuple[int, str, str]:
        info(label)
        if self.is_interactive():
            try:
                proc = subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                output_lines: List[str] = []
                assert proc.stdout is not None
                for line in proc.stdout:
                    text = line.rstrip("\n")
                    output_lines.append(text)
                    if text:
                        print(f"     {text}", flush=True)
                code = proc.wait()
                return code, "\n".join(output_lines).strip(), ""
            except Exception as exc:
                return -1, "", str(exc)
        return self.transfer._run_cmd(cmd)

    def hydrate_from_remote_servers(self, target_root: str = "/") -> Dict[str, Any]:
        logger = logging.getLogger("omni.core")
        results: List[Dict[str, Any]] = []
        root = Path(target_root).resolve()

        if not self.servers:
            return {"success": False, "message": f"No servers configured in {SERVERS_FILE}", "results": results}

        for server in self.servers:
            name = server.get("name") or server.get("host", "server")
            user = server.get("user", "ubuntu")
            host = str(server.get("host", "")).strip()
            port = int(server.get("port", 22))
            protocol = server.get("protocol", "rsync")
            paths = server.get("paths", [])
            excludes = server.get("excludes", [])

            if not host or host == "1.2.3.4" or not paths:
                results.append({"server": name, "success": False, "error": "Missing host or paths"})
                continue

            for remote_path in paths:
                destination = root / remote_path.lstrip("/")
                destination.mkdir(parents=True, exist_ok=True)
                cmd = build_remote_sync_command(
                    {
                        "user": user,
                        "host": host,
                        "port": port,
                        "protocol": protocol,
                        "excludes": excludes,
                        "identity_file": server.get("identity_file", ""),
                        "ssh_options": server.get("ssh_options", []),
                    },
                    remote_path,
                    destination,
                    delete=False,
                )
                logger.info("Hydrating %s:%s into %s", name, remote_path, destination)
                code, out, err = self._run_transfer_cmd_visible(
                    cmd,
                    f"Importando contenido remoto {name}:{remote_path} -> {destination}",
                )
                error = err if code != 0 else ""
                if code != 0 and "Permission denied (publickey)" in error:
                    hint = "Configure `identity_file` in config/servers.json o deja una única clave privada utilizable en ~/.ssh."
                    error = f"{error}\n{hint}"
                results.append({
                    "server": name,
                    "path": remote_path,
                    "protocol": protocol,
                    "success": code == 0,
                    "target": str(destination),
                    "error": error,
                    "output": out if code == 0 else "",
                })

        ok_count = sum(1 for item in results if item.get("success"))
        return {
            "success": ok_count == len(results) and len(results) > 0,
            "message": f"Imported {ok_count}/{len(results)} remote paths",
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
        logger.info("Starting Omni Core watch mode", extra={"interval": interval, "profile": manifest.get("profile")})

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
        section("Configuration")

        kv("Version", OMNI_VERSION)
        kv("Build", OMNI_BUILD)
        kv("Codename", OMNI_CODENAME)
        kv("Tasks File", self.tasks_file)
        kv("Repos File", str(REPOS_FILE))
        kv("Manifest", str(self.manifest_path))
        kv("Bundle Dir", str(self.bundle_dir))
        kv("Agent Config", str(AGENT_CONFIG_FILE))
        kv("Logs", str(LOG_DIR / "omni.log"))
        kv("Repos", str(len(self.repos)))
        kv("Telegram", "configured" if os.getenv("OMNI_TELEGRAM_TOKEN") else "not configured")
        agent_config = load_agent_config(AGENT_CONFIG_FILE)
        if agent_config:
            kv("Agent Provider", str(agent_config.get("provider", "unknown")), color=C.GRN)
        nl()

        if self.tasks:
            bullet("Tasks:", C.G3)
            for task in self.tasks:
                dim("  • " + task.get("name", "Unnamed"))

    def show_agent_status(self):
        print_logo(compact=True)
        section("Omni Agent")
        config = load_agent_config(AGENT_CONFIG_FILE)
        if not config:
            warn("Omni Agent todavía no está configurado.")
            hint("Usa `omni agent` para elegir proveedor y guardar la configuración.")
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
        kv("Activation", str(AGENT_ACTIVATION_FILE), color=C.GRN)
        if config.get("docs_url"):
            kv("Docs", str(config.get("docs_url")), color=C.GRN)
        if config.get("notes"):
            dim(str(config.get("notes")))
        dim("  Usa `omni chat` para abrir la interfaz conversacional.")
        nl()

    def show_agent_catalog(self):
        print_logo(compact=True)
        section("Omni Agent Catalog")
        for provider in provider_catalog():
            bullet(provider.title, C.GRN)
            dim(f"  key: {provider.key}")
            dim(f"  protocol: {provider.protocol}")
            dim(f"  env: {provider.env_var}")
            dim(f"  base: {provider.base_url}")
            dim(f"  default: {provider.default_model}")
            dim(f"  models: {', '.join(provider.sample_models)}")
            dim(f"  docs: {provider.docs_url}")
            if provider.notes:
                dim(f"  note: {provider.notes}")
            nl()

    def show_chat_status(self):
        print_logo(compact=True)
        section("Omni Chat")
        config = load_agent_config(AGENT_CONFIG_FILE)
        if not config:
            warn("Omni Chat necesita primero una configuración de `omni agent`.")
            hint("Usa `omni agent` para elegir proveedor y modelo.")
            return

        provider = get_provider(str(config.get("provider", "")))
        title = provider.title if provider else str(config.get("provider_title", config.get("provider", "unknown")))
        env_var = str(config.get("env_var", ""))
        latest_session = latest_chat_session_path(AGENT_CHAT_DIR)
        kv("Provider", title, color=C.GRN)
        kv("Model", str(config.get("model", "unknown")), color=C.GRN)
        kv("Base URL", str(config.get("base_url", "unknown")), color=C.GRN)
        kv("Secret", "loaded" if env_var and load_env_value(ENV_FILE, env_var) else "missing", color=C.GRN if env_var and load_env_value(ENV_FILE, env_var) else C.YLW)
        kv("Activation", str(AGENT_ACTIVATION_FILE), color=C.GRN)
        kv("Latest Session", latest_session.name if latest_session else "none", color=C.GRN if latest_session else C.YLW)
        if latest_session:
            try:
                session = load_chat_session(latest_session)
                permissions = ensure_chat_permissions(session)
                kv("Permissions", permissions.get("mode", "smart"), color=C.GRN)
            except Exception:
                kv("Permissions", "unknown", color=C.YLW)
        if AGENT_ACTIVATION_FILE.exists():
            activation_preview = ensure_activation_prompt(AGENT_ACTIVATION_FILE).splitlines()[0]
            dim(f"  activation: {activation_preview}")
        nl()

    def render_chat_command_help(self):
        box(
            "Omni Chat Commands",
            [
                "/help  ver comandos del chat",
                "/status  ver provider, modelo y sesión activa",
                "/new  abrir una sesión limpia",
                "/clear  limpiar el historial de la sesión actual",
                "/save  guardar sesión en disco",
                "/run  ejecutar el último comando sugerido por Omni",
                "/todo  ver la última lista de tareas sugerida",
                "/exec on|off  activar o desactivar ejecución rápida de comandos",
                "/permissions  ver o cambiar permisos: smart|ask|auto|all",
                "/quit  salir del chat",
            ],
            width=min(92, TERM_WIDTH - 4),
            accent=C.CYN,
        )

    def resolve_chat_runtime(self) -> Dict[str, str]:
        config = load_agent_config(AGENT_CONFIG_FILE)
        if not config:
            raise RuntimeError("Omni Agent no está configurado todavía.")

        env_var = str(config.get("env_var", "")).strip()
        api_key = load_env_value(ENV_FILE, env_var) if env_var else ""
        if not api_key:
            raise RuntimeError(f"Falta la API key en {env_var or 'la variable configurada'}")

        activation_prompt = ensure_activation_prompt(AGENT_ACTIVATION_FILE)
        workspace_lines = [
            f"Workspace principal: {Path.home()}",
            f"OMNI_HOME: {OMNI_HOME}",
            f"Activation file: {AGENT_ACTIVATION_FILE}",
        ]
        codex_dir = Path.home() / ".codex"
        if codex_dir.exists():
            workspace_lines.append(f"Codex workspace disponible en {codex_dir}. Úsalo como contexto, no como proveedor principal.")
        system_prompt = activation_prompt.strip() + "\n\nContexto del workspace:\n- " + "\n- ".join(workspace_lines)
        return {
            "provider": str(config.get("provider", "")),
            "provider_title": str(config.get("provider_title", config.get("provider", "unknown"))),
            "protocol": str(config.get("protocol", "openai-compatible")),
            "env_var": env_var,
            "base_url": str(config.get("base_url", "")),
            "model": str(config.get("model", "")),
            "api_key": api_key,
            "system_prompt": system_prompt,
        }

    def open_chat_session(self, runtime: Dict[str, str], *, force_new: bool = False) -> Dict[str, Any]:
        latest_path = None if force_new else latest_chat_session_path(AGENT_CHAT_DIR)
        if latest_path and latest_path.exists():
            try:
                session = load_chat_session(latest_path)
                session.setdefault("messages", [])
                ensure_chat_permissions(session)
                return session
            except Exception:
                pass
        session = new_chat_session(
            AGENT_CHAT_DIR,
            provider_title=runtime["provider_title"],
            model=runtime["model"],
            base_url=runtime["base_url"],
            provider_key=runtime["provider"],
            protocol=runtime["protocol"],
            activation_file=str(AGENT_ACTIVATION_FILE),
        )
        ensure_chat_permissions(session)
        save_chat_session(Path(session["path"]), session)
        return session

    def render_assistant_message(self, text: str, *, title: str = "Omni") -> None:
        lines = [segment.strip() for segment in text.splitlines() if segment.strip()]
        box(title, lines or ["(sin contenido)"], width=min(94, TERM_WIDTH - 4), accent=C.GLD_BRIGHT)

    def build_operator_context(self, profile: str = "") -> Dict[str, Any]:
        try:
            _, manifest = self.resolve_manifest("", str(Path.home()), create=True, profile=profile)
        except Exception:
            manifest = build_default_manifest(str(Path.home()), profile=profile or DEFAULT_PROFILE)
        state_paths = list(manifest.get("state_paths", []))
        has_product_state = any(
            Path(path).expanduser().exists()
            for path in state_paths
            if path and not str(path).endswith("dump.pm2")
        )
        return {
            "profile": str(manifest.get("profile", DEFAULT_PROFILE)),
            "has_state_bundle": bool(latest_or_explicit(self.bundle_dir, "", "state_bundle")),
            "has_secrets_bundle": bool(latest_or_explicit(self.bundle_dir, "", "secrets_bundle")),
            "has_capture_summary": bool(load_capture_summary(self.bundle_dir)),
            "has_product_state": has_product_state,
            "migration_mode": infer_migration_mode(
                {
                    "has_state_bundle": bool(latest_or_explicit(self.bundle_dir, "", "state_bundle")),
                    "has_secrets_bundle": bool(latest_or_explicit(self.bundle_dir, "", "secrets_bundle")),
                    "has_capture_summary": bool(load_capture_summary(self.bundle_dir)),
                    "has_product_state": has_product_state,
                }
            ),
        }

    def current_chat_permissions(self, session: Dict[str, Any], *, accept_all: bool = False) -> Dict[str, Any]:
        permissions = ensure_chat_permissions(session)
        if accept_all:
            permissions = ensure_permissions_state({"mode": "all"})
            session["permissions"] = permissions
        return permissions

    def render_chat_permissions(self, session: Dict[str, Any]) -> None:
        permissions = self.current_chat_permissions(session)
        box(
            "Omni Permissions",
            render_permissions_lines(permissions),
            width=min(92, TERM_WIDTH - 4),
            accent=C.CYN,
        )

    def render_action_hint(self, action: Dict[str, Any]) -> None:
        if action.get("type") == "command":
            render_action_summary(
                action.get("title", "Comando sugerido"),
                [
                    f"Comando: {action.get('command', '')}",
                    "Usa `/run` para ejecutarlo desde el chat.",
                ],
                accent=C.CYN,
            )
            return
        if action.get("type") == "workflow":
            steps = action.get("steps") or []
            lines = [action.get("title", "Flujo sugerido")]
            for idx, step in enumerate(steps, start=1):
                if not isinstance(step, dict):
                    continue
                lines.append(f"{idx}. {step.get('command', '')}")
            lines.append("Usa `/run` para ejecutarlo dentro del chat.")
            box("Workflow sugerido", lines, width=min(94, TERM_WIDTH - 4), accent=C.CYN)
            return
        if action.get("type") == "todo":
            items = action.get("items") or []
            lines = [action.get("title", "Tareas sugeridas")] + [f"- {item}" for item in items if item]
            box("Plan sugerido", lines, width=min(94, TERM_WIDTH - 4), accent=C.CYN)

    def run_chat_action(self, action: Dict[str, Any], *, permissions: Dict[str, Any] | None = None, prompt_for_permission: bool = True) -> Dict[str, Any]:
        action_type = str(action.get("type", "command")).strip().lower()
        permissions_state = ensure_permissions_state(permissions)
        decision = evaluate_permission_decision(action, permissions_state)

        if prompt_for_permission and decision["needs_confirmation"]:
            if not self.confirm_step(build_permission_prompt(action, decision), accept_all=False, default=False):
                raise RuntimeError("Acción cancelada por permisos.")

        if action_type == "workflow":
            steps = action.get("steps") or []
            results = []
            for step in steps:
                if not isinstance(step, dict):
                    continue
                step_action = {
                    "type": "command",
                    "command": step.get("command", ""),
                    "title": step.get("title") or step.get("command") or "Paso",
                    "confirm": False,
                }
                results.append(self.run_chat_action(step_action, permissions={"mode": "all"}, prompt_for_permission=False))
            return {
                "type": "workflow",
                "title": action.get("title", "Workflow"),
                "results": results,
            }

        if action_type != "command":
            raise RuntimeError("La última acción no es ejecutable.")

        command = str(action.get("command", "")).strip()
        if not command:
            raise RuntimeError("La última acción no contiene comando.")
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(Path.home()),
            text=True,
            capture_output=True,
            timeout=300,
        )
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        lines: List[str] = [f"exit_code={completed.returncode}"]
        if stdout:
            lines.append("stdout:")
            lines.extend(stdout.splitlines()[-10:])
        if stderr:
            lines.append("stderr:")
            lines.extend(stderr.splitlines()[-10:])
        render_action_summary("Resultado del comando", lines, accent=C.GRN if completed.returncode == 0 else C.RED)
        return {
            "type": "command",
            "command": command,
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }

    def summarize_command_result_for_chat(self, result: Dict[str, Any]) -> str:
        if result.get("type") == "workflow":
            parts = [f"Resultado del flujo `{result.get('title', 'workflow')}`:"]
            for index, item in enumerate(result.get("results", []), start=1):
                parts.append(f"paso_{index}: `{item.get('command', '')}` exit_code={item.get('exit_code', 'unknown')}")
            return "\n".join(parts).strip()

        def _tail(text: str, label: str) -> List[str]:
            if not text:
                return []
            lines = text.splitlines()[-12:]
            return [f"{label}:"] + lines

        parts = [f"Resultado del comando `{result['command']}`:", f"exit_code={result['exit_code']}"]
        parts.extend(_tail(result.get("stdout", ""), "stdout"))
        parts.extend(_tail(result.get("stderr", ""), "stderr"))
        return "\n".join(parts).strip()

    def chat_once(self, runtime: Dict[str, str], session: Dict[str, Any], prompt: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        operator_response = build_operator_response(prompt, context=self.build_operator_context())
        if operator_response:
            clean_text = operator_response.get("response", "").strip() or "Listo."
            action = operator_response.get("action")
            session_messages = list(session.get("messages", []))
            session_messages.append({"role": "user", "content": prompt})
            session_messages.append({"role": "assistant", "content": clean_text})
            session["messages"] = session_messages
            save_chat_session(Path(session["path"]), session)
            return clean_text, action

        session_messages = list(session.get("messages", []))
        request_messages = [{"role": "system", "content": runtime["system_prompt"]}] + session_messages + [{"role": "user", "content": prompt}]
        result = chat_completion(
            protocol=runtime["protocol"],
            base_url=runtime["base_url"],
            model=runtime["model"],
            api_key=runtime["api_key"],
            messages=request_messages,
        )
        raw_text = result.get("text", "").strip()
        action = parse_action_block(raw_text)
        clean_text = clean_assistant_output(raw_text) or "No tuve texto útil para devolverte."
        session_messages.append({"role": "user", "content": prompt})
        session_messages.append({"role": "assistant", "content": clean_text})
        session["messages"] = session_messages
        save_chat_session(Path(session["path"]), session)
        return clean_text, action

    def chat_cmd(self, subaction: str = "", *, accept_all: bool = False, prompt: str = ""):
        normalized = str(subaction or "").strip().lower()
        if normalized in {"status", "show"}:
            self.show_chat_status()
            return

        try:
            runtime = self.resolve_chat_runtime()
        except RuntimeError as err:
            print_logo(compact=True)
            section("Omni Chat")
            fail(str(err))
            hint("Usa `omni agent` para configurar proveedor/modelo y guardar la API key.")
            return

        if prompt.strip():
            session = self.open_chat_session(runtime)
            response, action = self.chat_once(runtime, session, prompt.strip())
            print_logo(compact=True)
            section("Omni Chat")
            kv("Provider", runtime["provider_title"], color=C.GRN)
            kv("Model", runtime["model"], color=C.GRN)
            nl()
            self.render_assistant_message(response)
            if action:
                self.render_action_hint(action)
            return

        if accept_all or not self.is_interactive():
            print_logo(compact=True)
            section("Omni Chat")
            warn("Necesitas un terminal interactivo para abrir la interfaz conversacional.")
            hint("También puedes usar `omni chat \"tu mensaje\"` para una consulta puntual.")
            return

        print_logo(compact=True)
        section("Omni Chat")
        kv("Provider", runtime["provider_title"], color=C.GRN)
        kv("Model", runtime["model"], color=C.GRN)
        kv("Base URL", runtime["base_url"], color=C.GRN)
        kv("Activation", str(AGENT_ACTIVATION_FILE), color=C.GRN)
        dim("Chat conversacional normal. Slash commands disponibles con /help.")
        nl()

        session = self.open_chat_session(runtime, force_new=normalized in {"new", "fresh"})
        permissions = self.current_chat_permissions(session, accept_all=accept_all)
        if session.get("messages"):
            info(f"Sesión recuperada: {Path(session['path']).name}")
            dim(f"Mensajes guardados: {len(session['messages'])}")
        else:
            info(f"Sesión nueva: {Path(session['path']).name}")

        exec_enabled = accept_all
        last_action: Optional[Dict[str, Any]] = None

        while True:
            try:
                print()
                user_input = input(q(C.PRIMARY, "  you > ")).strip()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                command = user_input[1:].strip()
                lowered = command.lower()
                if lowered in {"quit", "exit"}:
                    save_chat_session(Path(session["path"]), session)
                    ok("Sesión guardada.")
                    break
                if lowered == "help":
                    self.render_chat_command_help()
                    continue
                if lowered == "status":
                    self.show_chat_status()
                    continue
                if lowered.startswith("permissions"):
                    remainder = command.split(" ", 1)[1].strip() if " " in command else ""
                    parsed = parse_permissions_request(remainder)
                    if parsed["action"] == "show":
                        self.render_chat_permissions(session)
                    elif parsed["action"] == "set":
                        session["permissions"] = ensure_permissions_state({"mode": parsed["mode"]})
                        permissions = self.current_chat_permissions(session)
                        save_chat_session(Path(session["path"]), session)
                        ok(f"Permisos del chat actualizados a `{permissions['mode']}`.")
                        self.render_chat_permissions(session)
                    else:
                        warn("Modo inválido. Usa: /permissions smart|ask|auto|all")
                    continue
                if lowered == "new":
                    session = self.open_chat_session(runtime, force_new=True)
                    permissions = self.current_chat_permissions(session, accept_all=accept_all)
                    last_action = None
                    info(f"Sesión nueva: {Path(session['path']).name}")
                    continue
                if lowered == "clear":
                    session["messages"] = []
                    save_chat_session(Path(session["path"]), session)
                    last_action = None
                    ok("Historial limpiado para esta sesión.")
                    continue
                if lowered == "save":
                    save_chat_session(Path(session["path"]), session)
                    ok(f"Sesión guardada en {session['path']}")
                    continue
                if lowered.startswith("exec "):
                    toggle = lowered.split(" ", 1)[1].strip()
                    exec_enabled = toggle in {"on", "true", "1", "yes", "si"}
                    ok(f"Ejecución rápida {'activada' if exec_enabled else 'desactivada'}.")
                    continue
                if lowered == "run":
                    if not last_action:
                        warn("No hay comando sugerido listo para ejecutar.")
                        continue
                    try:
                        result = self.run_chat_action(last_action, permissions=permissions, prompt_for_permission=True)
                    except Exception as err:
                        fail(str(err))
                        continue
                    session["messages"].append(
                        {
                            "role": "user",
                            "content": self.summarize_command_result_for_chat(result),
                        }
                    )
                    save_chat_session(Path(session["path"]), session)
                    continue
                if lowered == "todo":
                    if not last_action or last_action.get("type") != "todo":
                        warn("No hay lista de tareas sugerida en memoria.")
                        continue
                    self.render_action_hint(last_action)
                    continue
                warn(f"Comando desconocido: /{command}")
                continue

            with Spinner("Pensando...", color=C.PRIMARY):
                try:
                    response, action = self.chat_once(runtime, session, user_input)
                except Exception as err:
                    print()
                    fail(f"Omni Chat falló: {err}")
                    continue

            self.render_assistant_message(response)
            last_action = action
            if action:
                self.render_action_hint(action)
                decision = evaluate_permission_decision(action, permissions)
                if exec_enabled and action.get("type") in {"command", "workflow"} and decision["auto_execute"] and not decision["needs_confirmation"]:
                    try:
                        result = self.run_chat_action(action, permissions=permissions, prompt_for_permission=False)
                        session["messages"].append(
                            {
                                "role": "user",
                                "content": self.summarize_command_result_for_chat(result),
                            }
                        )
                        save_chat_session(Path(session["path"]), session)
                    except Exception as err:
                        fail(str(err))

    def show_examples(self):
        print_logo(tagline=True)
        section("Omni Playbooks")
        for example in build_examples_catalog():
            bullet(example.title, C.GRN)
            dim(example.description)
            dim(f"  Cuándo usarlo: {example.when_to_use}")
            print()
            print("  " + q(C.PRIMARY, example.command))
            nl()

    def show_auto_status(
        self,
        *,
        powershell: bool = False,
        target_host: str = "",
        remote_user: str = DEFAULT_REMOTE_USER,
        identity_file: str = "",
        repo_url: str = DEFAULT_REPO_URL,
        ref_name: str = DEFAULT_REF_NAME,
        destination: str = "",
        ps1_out: str = "",
        windows_dir: str = "",
    ):
        print_logo(compact=True)
        section("Omni Auto")
        kv("Timer service", "omni-update.timer", color=C.GRN)
        kv("Watch service", "omni-watch.service", color=C.GRN)
        kv("Auto backup", "on change + every 24h", color=C.GRN)
        nl()
        if powershell:
            command = build_powershell_auto_command(
                target_host=target_host,
                remote_user=remote_user,
                identity_file=identity_file,
                repo_url=repo_url,
                ref_name=ref_name,
                destination=destination,
                install_timer=True,
            )
            info("Comando listo para PowerShell")
            dim("Si omites -Destination, bootstrap.ps1 escanea el host remoto y recomienda la ruta.")
            if ps1_out:
                output_path = Path(ps1_out).expanduser()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(build_powershell_auto_script(command), encoding="utf-8")
                ok(f"Script PowerShell generado en {output_path}")
            if windows_dir.strip():
                kv("Windows dir", windows_dir, color=C.GRN)
                kv("Suggested .ps1", build_windows_ps1_path(windows_dir), color=C.GRN)
            print()
            print(q(C.PRIMARY, command))
            if windows_dir.strip():
                print()
                info("Bloque listo para crear el .ps1 en Windows")
                print()
                print(q(C.PRIMARY, build_powershell_dropper_script(command, windows_dir=windows_dir)))
            nl()
            return

        bullet("Playbooks guiados  -> omni examples", C.GRN)
        bullet("One-liner PowerShell -> omni auto --p", C.GRN)
        dim("Añade --target-host y --identity-file si quieres que salga listo para pegar.")
        dim("Añade --ps1-out ruta.ps1 si además quieres el archivo PowerShell generado.")
        dim("Añade --windows-dir C:\\ruta\\carpeta para que Omni te dé el bloque que crea omni-auto.ps1 en Windows.")
        nl()

    def agent_cmd(self, subaction: str = "", *, accept_all: bool = False):
        normalized = str(subaction or "").strip().lower()
        if normalized in {"status", "show"}:
            self.show_agent_status()
            return
        if normalized in {"list", "catalog", "providers"}:
            self.show_agent_catalog()
            return

        print_logo(compact=True)
        section("Omni Agent")
        current = load_agent_config(AGENT_CONFIG_FILE)
        if current:
            info("Configuración actual detectada.")
            provider = get_provider(str(current.get("provider", "")))
            kv("Provider", provider.title if provider else str(current.get("provider", "unknown")), color=C.GRN)
            kv("Model", str(current.get("model", "unknown")), color=C.GRN)
            kv("Base URL", str(current.get("base_url", "unknown")), color=C.GRN)
            nl()

        if accept_all or not self.is_interactive():
            warn("Omni Agent necesita un terminal interactivo para configurarse.")
            if current:
                hint("Mostrando configuración actual en vez de modificarla.")
                self.show_agent_status()
            else:
                hint("Usa `omni agent` desde una terminal interactiva para elegir proveedor y guardar claves.")
            return

        providers = provider_catalog()
        default_idx = 0
        if current:
            default_idx = next((idx for idx, item in enumerate(providers) if item.key == current.get("provider")), 0)
        provider_icons = {
            "claude-direct": "🟠",
            "openai-direct": "🟢",
            "azure-openai": "🔷",
            "gemini-direct": "✨",
            "gemini-openai": "🔁",
            "openrouter": "🌐",
            "aws-bedrock": "🟤",
            "xai-direct": "⚡",
            "groq": "🚀",
            "qwen-intl": "🈶",
            "deepseek-direct": "🧭",
            "mistral-direct": "🌬️",
            "cohere-direct": "🧩",
            "together": "🤝",
            "perplexity": "🔎",
            "custom-openai": "🛠️",
        }

        selected = select_menu(
            [item.title for item in providers],
            title="¿Qué proveedor quieres usar para Omni Agent?",
            descriptions=[item.description for item in providers],
            icons=[provider_icons.get(item.key, "•") for item in providers],
            default=default_idx,
            show_index=True,
            footer="↑/↓ elegir proveedor · Enter confirmar · número salto directo",
        )

        provider = providers[selected]
        base_url = provider.base_url
        env_var = provider.env_var

        if provider.requires_custom_base_url and self.is_interactive():
            raw_base = prompt_paste_friendly_value("Base URL", provider.base_url)
            if raw_base:
                base_url = raw_base
        if provider.requires_custom_env_var and self.is_interactive():
            raw_env = prompt_paste_friendly_value("Variable para API key", provider.env_var, uppercase=True)
            if raw_env:
                env_var = raw_env

        model_choices = list(provider.sample_models) + ["Custom"]
        model_default_idx = 0
        if current and current.get("provider") == provider.key and current.get("model") in model_choices:
            model_default_idx = model_choices.index(str(current.get("model")))
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
            custom_model = prompt_paste_friendly_value("Modelo personalizado", provider.default_model)
            model = custom_model or provider.default_model
        else:
            model = model_choices[model_idx]

        wrote_secret = False
        if self.is_interactive():
            raw_key = prompt_paste_friendly_secret(f"API key para {provider.title} (Enter para omitir)")
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
                "Chat: omni chat",
            ],
            accent=C.PRIMARY,
        )

    def show_help(self):
        """Show help menu."""
        print_logo(tagline=True)
        render_help_overview()
        section("Common Flows")
        bullet("Mover todo /home/ubuntu  -> omni start -> Migrate", C.GRN)
        dim("Omni restaura bundles, secretos, dependencias, compose y PM2.")
        bullet("Usar esta terminal como puente  -> omni start -> Bridge", C.GRN)
        dim("Ideal desde PowerShell o una máquina con poco disco local.")
        bullet("Crear respaldo real  -> omni capture --profile full-home", C.GRN)
        dim("Luego saca `backups/host-bundles` fuera del host actual.")
        bullet("Configurar Omni Agent  -> omni agent", C.GRN)
        dim("Selector visual para Claude, OpenAI, Azure OpenAI, Gemini, Bedrock, OpenRouter, xAI, Groq, Qwen, DeepSeek, Mistral, Cohere, Together, Perplexity o endpoint compatible.")
        bullet("Hablar con Omni Agent  -> omni chat", C.GRN)
        dim("Interfaz conversacional con historial, slash commands, `/permissions` y acciones operativas.")
        bullet("Ver playbooks listos  -> omni examples", C.GRN)
        dim("Comandos listos para captura, migración, bridge, rewrite, agent y chat.")
        bullet("Inventario del stack  -> omni packages", C.GRN)
        dim("Enumera APT, Python, npm global y PM2 del host actual.")
        bullet("One-liner PowerShell  -> omni auto --p", C.GRN)
        dim("Imprime el comando de auto-actualización listo para pegar en PowerShell.")
        nl()

        section("Omni Core - Command Reference")

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
        bullet("omni commands  - Show the full Omni command surface", C.GRN)
        nl()

        print("  " + q(C.W, "ADVANCED COMMANDS", bold=True))
        nl()
        bullet("omni restart   - Restart PM2 services", C.PRIMARY)
        bullet("omni backup    - Create system backup", C.PRIMARY)
        bullet("omni transfer  - Transfer files to remote", C.PRIMARY)
        bullet("omni config    - Show configuration", C.PRIMARY)
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
        bullet("omni packages  - Capture the installed host stack (APT/Python/npm/PM2)", C.PRIMARY)
        bullet("omni bundle-create - Export state bundle from the active profile", C.PRIMARY)
        bullet("omni bundle-restore - Restore latest or explicit state bundle", C.PRIMARY)
        bullet("omni secrets-export - Export encrypted secrets pack", C.PRIMARY)
        bullet("omni secrets-import - Import encrypted secrets pack", C.PRIMARY)
        bullet("omni reconcile - Rebuild host from manifest + bundles", C.PRIMARY)
        bullet("omni detect-ip - Detect current host identity", C.PRIMARY)
        bullet("omni rewrite-ip - Rewrite old host references safely", C.PRIMARY)
        bullet("omni agent     - Configure Omni Agent provider and model", C.PRIMARY)
        dim("    Use `omni agent list` to inspect the full provider/model catalog")
        bullet("omni chat      - Open a conversational terminal with Omni Agent", C.PRIMARY)
        dim("    También soporta `omni chat \"tu mensaje\"` y `/permissions smart|ask|auto|all`")
        bullet("omni examples  - Show ready-to-copy operational playbooks", C.PRIMARY)
        bullet("omni auto      - Show automation status or emit PowerShell auto-update command", C.PRIMARY)
        bullet("omni bridge    - Create/send/receive migration packs", C.PRIMARY)
        bullet("omni timer-install - Install daily timer + change watcher service", C.PRIMARY)
        bullet("omni purge - Delete transferred state and repo artifacts to free disk", C.PRIMARY)
        nl()

        print("  " + q(C.W, "ALIASES", bold=True))
        nl()
        dim("  s=status  f=fix  w=watch  c=check  r=restart  l=logs")
        dim("  t=transfer  b=backup  m=monitor  cfg=config")
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
        bullet("--bundle        Explicit state bundle path", C.G3)
        bullet("--secrets       Explicit secrets bundle path", C.G3)
        bullet("--target-root   Restore target root", C.G3)
        bullet("--passphrase-env  Env var containing secrets passphrase", C.G3)
        bullet("--yes           Confirm destructive purge", C.G3)
        bullet("--include-secrets  Include secret paths in purge", C.G3)
        nl()

        hr()
        bullet("Migration: inventory -> bundle -> secrets -> reconcile -> timer", C.G3)
        bullet("Quickstart: init -> install.sh --compose --sync --timer", C.G3)
        bullet("Default entrypoint: run `omni` and choose bridge/capture/restore/migrate", C.G3)
        print("  " + q(C.G3, f"Omni Core v{OMNI_VERSION} '{OMNI_CODENAME}'"))
        print("  " + q(C.G3, "Run 'omni <command>' to execute"))
        print()

    def init_workspace(self, profile: str = ""):
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
            (AGENT_ACTIVATION_FILE, CONFIG_DIR / "omni_agent_activation.example.txt"),
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
                        ok(f"Updated placeholder host in {servers_path} -> {replacement_host}")
            except Exception as err:
                warn(f"Failed to normalize servers.json automatically: {err}")

        for path in created:
            ok(f"Created {path}")
        for path in existing:
            dim(f"Already present: {path}")
        for path in missing_templates:
            warn(f"Template not found: {path}")

        if workspace_changed and AUTO_BACKUP_ON_CHANGE:
            info("Creando backup automático post-init...")
            self.run_backup(profile=requested_profile or profile)

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

        print_logo(tagline=False)
        render_help_overview()
        section("Guided Start")
        kv("Detected Platform", f"{info_obj.system} / {info_obj.shell} / {info_obj.package_manager}", color=C.GRN)
        kv("Mode", "accept-all" if effective_accept_all else "guided", color=C.YLW if effective_accept_all else C.GRN)
        kv("Default Scope", profile, color=C.GRN)
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
            icons = ["🛫", "📦", "♻️", "🚚", "🩺", "🧠", "💬", "⚙️"]
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

        if chosen_flow in {"bridge", "capture", "restore", "migrate"}:
            profile = self.choose_profile(accept_all=effective_accept_all, current_profile=profile)

        if chosen_flow == "advanced":
            self.show_help()
            return
        if chosen_flow == "bridge":
            self.bridge_mode(accept_all=effective_accept_all, profile=profile)
            return
        if chosen_flow == "capture":
            self.capture_host_cmd(accept_all=effective_accept_all, profile=profile)
            return
        if chosen_flow == "restore":
            self.restore_host_cmd(accept_all=effective_accept_all, install_timer=effective_accept_all, profile=profile)
            return
        if chosen_flow == "migrate":
            self.migrate_host_cmd(accept_all=effective_accept_all, install_timer=effective_accept_all, profile=profile)
            return
        if chosen_flow == "doctor":
            self.show_doctor()
            return
        if chosen_flow == "agent":
            self.agent_cmd(accept_all=effective_accept_all)
            return
        if chosen_flow == "chat":
            self.chat_cmd(accept_all=effective_accept_all)
            return
        self.show_help()

    def show_doctor(self):
        print_logo(compact=True)
        section("Doctor")

        disk = self.fixer.check_disk_space()
        mem = self.fixer.check_memory()
        pm2 = self.fixer.check_and_fix_pm2()

        kv("Disk", disk.get("message", "Unknown"), color=C.GRN if disk.get("status") in {"ok", "skipped"} else C.YLW)
        kv("Memory", mem.get("message", "Unknown"), color=C.GRN if mem.get("status") in {"ok", "skipped"} else C.YLW)
        kv("PM2", pm2.get("message", "Unknown"), color=C.GRN if pm2.get("status") in {"ok", "skipped"} and not pm2.get("restarted") else C.YLW)
        kv("Manifest", str(self.manifest_path), color=C.GRN)
        try:
            manifest = load_manifest(self.manifest_path, str(Path.home()))
            kv("Profile", str(manifest.get("profile", "unknown")), color=C.GRN)
            kv("Host Root", str(manifest.get("host_root", "unknown")), color=C.GRN)
            drift = self.build_host_drift_report(root=str(manifest.get("host_root", str(Path.home()))))
            context = drift["context"]
            plan = drift["plan"]
            if not context["summary_found"]:
                kv("Host Drift", "No capture summary yet", color=C.G3)
            elif plan and plan.changed_files:
                kv("Host Drift", f"{plan.changed_files} files need rewrite", color=C.YLW)
            else:
                kv("Host Drift", "Aligned or no matches", color=C.GRN)
        except Exception:
            pass
        kv("Bundle Dir", str(self.bundle_dir), color=C.GRN)
        nl()

        bundle_dirs = self.bundle_search_dirs()
        latest_state_bundle = resolve_latest_bundle_across_dirs(bundle_dirs, "", "state_bundle")
        latest_secrets_bundle = resolve_latest_bundle_across_dirs(bundle_dirs, "", "secrets_bundle")
        if latest_state_bundle:
            kv("Latest State Bundle", str(latest_state_bundle), color=C.GRN)
        else:
            warn("No state bundle found yet. Run `omni capture`.")
        if latest_secrets_bundle:
            kv("Latest Secrets Bundle", str(latest_secrets_bundle), color=C.GRN)
        else:
            warn("No secrets bundle found yet. Run `omni capture`.")
        nl()

        if not self.servers:
            warn(f"No remote servers configured in {SERVERS_FILE}")
        else:
            for server in self.servers:
                host = str(server.get("host", ""))
                if host == "1.2.3.4":
                    warn(f"Placeholder host still present in servers.json for {server.get('name', 'server')}")
                else:
                    ok(f"Remote server configured: {server.get('name', host)} -> {host}")

    def build_host_drift_report(
        self,
        root: str = "",
        *,
        target_public_ip: str = "",
        target_private_ip: str = "",
        target_hostname: str = "",
    ) -> Dict[str, Any]:
        scan_root = Path(root).expanduser() if root else Path.home()
        current_identity = detect_host_identity()
        context = None
        source_bundle_dir = self.bundle_dir
        for bundle_dir in self.bundle_search_dirs():
            candidate = build_host_rewrite_context(
                bundle_dir,
                target_public_ip=target_public_ip,
                target_private_ip=target_private_ip,
                target_hostname=target_hostname,
            )
            if candidate.get("summary_found"):
                context = candidate
                source_bundle_dir = bundle_dir
                break
            if context is None:
                context = candidate
        context = context or build_host_rewrite_context(
            self.bundle_dir,
            target_public_ip=target_public_ip,
            target_private_ip=target_private_ip,
            target_hostname=target_hostname,
        )
        context = enrich_rewrite_context_from_servers(context, self.servers, current_identity)
        plan = build_rewrite_plan(scan_root, context["replacements"]) if context["replacements"] else None
        return {
            "scan_root": str(scan_root),
            "context": context,
            "bundle_dir": str(source_bundle_dir),
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
        installed_inventory_path = pack["installed_inventory_path"]
        installed_inventory = pack["installed_inventory"]
        ok(f"State bundle created: {state_bundle}")
        ok(f"Secrets bundle created: {secrets_bundle}")
        ok(f"Installed inventory written: {installed_inventory_path}")
        ok(f"Capture summary written: {summary_path}")
        if not pack["encrypted"]:
            warn("No passphrase configured. Secrets bundle was exported without encryption.")

        summary = summarize_bundle_pair(bundle_dir=bundle_dir, state_bundle=str(state_bundle), secrets_bundle=str(secrets_bundle))
        if self.is_interactive():
            summary_lines = [
                f"Perfil activo: {manifest.get('profile', DEFAULT_PROFILE)}",
                f"Bundle de estado: {state_bundle}",
                f"Bundle de secretos: {secrets_bundle}",
                f"Inventario instalado: {installed_inventory_path}",
                f"Resumen: {summary_path}",
                f"Directorio: {bundle_dir}",
            ]
            summary_lines.extend([""] + summarize_installed_inventory(installed_inventory))
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
        before_services=None,
        allow_missing_bundles: bool = False,
    ):
        print_logo(compact=True)
        section("Restore Host")
        self.init_workspace(profile=profile)
        selected_path, manifest = self.resolve_manifest(manifest_path, home_root, create=True, profile=profile)
        passphrase = self.read_passphrase(passphrase_env)
        bundle_dirs = self.bundle_search_dirs(include_auto=False)
        resolved_bundle_path = resolve_latest_bundle_across_dirs(bundle_dirs, bundle_path, "state_bundle")
        resolved_secrets_path = resolve_latest_bundle_across_dirs(bundle_dirs, secrets_path, "secrets_bundle")
        resolved_bundle = str(resolved_bundle_path or "")
        resolved_secrets = str(resolved_secrets_path or "")
        runtime_inventory = resolve_installed_inventory_across_dirs(self.bundle_search_dirs())
        effective_manifest = merge_manifest_runtime_inventory(manifest, runtime_inventory)
        bootstrap_only = False
        hydration_result = None

        if not resolved_bundle or not resolved_secrets:
            if not allow_missing_bundles:
                if not resolved_bundle:
                    fail("State bundle not found. Run `omni capture` or pass --bundle.")
                if not resolved_secrets:
                    fail("Secrets bundle not found. Run `omni capture` or pass --secrets.")
                return {"success": False, "reason": "missing_bundle"}
            bootstrap_only = True
            warn("No bundle set found. Continuing in bootstrap mode from manifest and installed inventory only.")
            resolved_bundle = ""
            resolved_secrets = ""
        if not self.confirm_step("Restore and reconcile this host now?", accept_all=accept_all):
            warn("Restore cancelled.")
            return {"success": False, "reason": "cancelled"}

        if bootstrap_only:
            if self.has_ready_remote_source():
                hydration_result = self.hydrate_from_remote_servers(target_root=target_root)
                if hydration_result.get("success"):
                    ok(hydration_result.get("message", "Remote content imported"))
                else:
                    warn(hydration_result.get("message", "Remote content import was incomplete"))
            else:
                warn("Bootstrap mode sin fuente remota real: Omni instalará runtime, pero no puede poblar /home/ubuntu completo sin bundle o servidor origen.")

        report = reconcile_host(
            effective_manifest,
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
                f"Modo: {'bootstrap' if bootstrap_only else 'bundle-restore'}",
                f"Contenido remoto importado: {sum(1 for item in (hydration_result or {}).get('results', []) if item.get('success'))}" if hydration_result else "Contenido remoto importado: 0",
                f"Archivos de estado restaurados: {restore_state.get('restored', 0)}",
                f"Archivos de secretos restaurados: {restore_secrets.get('restored', 0)}",
                f"Inventario instalado: {'detectado' if runtime_inventory else 'no'}",
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
            "report": report,
            "bootstrap_only": bootstrap_only,
            "used_bundles": bool(resolved_bundle and resolved_secrets),
            "runtime_inventory": runtime_inventory,
            "hydration_result": hydration_result,
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

        restore_result = self.restore_host_cmd(
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
            allow_missing_bundles=True,
        )
        if not restore_result or not restore_result.get("success"):
            return
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
                f"Modo de migracion: {'bootstrap' if restore_result.get('bootstrap_only') else 'bundle-restore'}",
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
        render_help_overview()
        section("Portable Install")
        bullet("1. Desde PowerShell ejecuta bootstrap.ps1 sin -Destination para escanear rutas y elegir ubicación", C.GRN)
        bullet("2. O copia/clona este repo manualmente en la ruta Linux que prefieras", C.GRN)
        bullet("3. Run: omni init --profile full-home", C.GRN)
        bullet("4. Edit .env, config/repos.json, config/servers.json and system_manifest.json", C.GRN)
        bullet("5. Run: ./install.sh --compose --sync --timer", C.GRN)
        bullet("6. Run `omni` to enter the guided start flow", C.GRN)
        bullet("7. Capture recovery set: omni capture", C.GRN)
        bullet("8. Rebuild host: omni migrate or omni restore", C.GRN)
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

    def show_packages(self, output: str = ""):
        print_logo(compact=True)
        section("Installed Stack")
        runtime_inventory = capture_installed_inventory()

        kv("APT packages", str(len(runtime_inventory.get("apt_packages", []))), color=C.GRN)
        kv("Python packages", str(len(runtime_inventory.get("python_packages", []))), color=C.GRN)
        kv("npm global", str(len(runtime_inventory.get("npm_global_packages", []))), color=C.GRN)
        kv("PM2 processes", str(len(runtime_inventory.get("pm2_processes", []))), color=C.GRN)
        nl()

        for line in summarize_installed_inventory(runtime_inventory):
            bullet(line, C.GRN)

        apt_preview = runtime_inventory.get("apt_packages", [])[:12]
        python_preview = runtime_inventory.get("python_packages", [])[:12]
        npm_preview = runtime_inventory.get("npm_global_packages", [])[:12]
        pm2_preview = runtime_inventory.get("pm2_processes", [])[:8]

        if apt_preview:
            nl()
            section("APT Preview")
            for item in apt_preview:
                bullet(item, C.PRIMARY)
        if python_preview:
            nl()
            section("Python Preview")
            for item in python_preview:
                bullet(item, C.PRIMARY)
        if npm_preview:
            nl()
            section("npm Global Preview")
            for item in npm_preview:
                bullet(item, C.PRIMARY)
        if pm2_preview:
            nl()
            section("PM2 Preview")
            for item in pm2_preview:
                bullet(f"{item.get('name', 'unknown')} [{item.get('status', 'unknown')}]", C.PRIMARY)

        if output:
            self.write_json_output(runtime_inventory, output)

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
        ok("Omni Core is up to date")

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
    parser = argparse.ArgumentParser(description="Omni Core - The Supreme Coordinator", add_help=False, allow_abbrev=False)
    parser.add_argument("action", nargs="?", default="start", help="Action to perform")
    parser.add_argument("--interval", type=int, default=300, help="Interval for watch mode (seconds)")
    parser.add_argument("--lines", type=int, default=50, help="Number of log lines")
    parser.add_argument("--follow", "-f", action="store_true", help="Follow logs")
    parser.add_argument("--protocol", type=str, default="scp", help="Transfer protocol")
    parser.add_argument("--compress", action="store_true", default=True, help="Enable compression")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
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
    parser.add_argument("--target-host", type=str, default="", help="Remote host for generated PowerShell auto commands")
    parser.add_argument("--remote-user", type=str, default=DEFAULT_REMOTE_USER, help="Remote SSH user for generated PowerShell auto commands")
    parser.add_argument("--identity-file", type=str, default="", help="Identity file for generated PowerShell auto commands")
    parser.add_argument("--repo-url", type=str, default=DEFAULT_REPO_URL, help="Repository URL for generated PowerShell auto commands")
    parser.add_argument("--ref-name", type=str, default=DEFAULT_REF_NAME, help="Git branch/ref for generated PowerShell auto commands")
    parser.add_argument("--ps1-out", type=str, default="", help="Write generated PowerShell auto command to a .ps1 file")
    parser.add_argument("--windows-dir", type=str, default="", help="Windows directory where omni-auto.ps1 should be created")
    parser.add_argument("--context-lines", type=int, default=2, help="Context lines for rewrite previews")
    parser.add_argument("--apply", action="store_true", help="Apply changes for rewrite-style commands")
    parser.add_argument("--powershell", "--p", "-p", action="store_true", help="Render PowerShell-oriented output where supported")
    parser.add_argument("--skip-rewrite", action="store_true", help="Skip automatic host reference rewrite during migrate")
    parser.add_argument("--dest", type=str, default="", help="Remote destination for bridge send")

    args, remaining = parser.parse_known_args()
    args.profile = str(args.profile or "").strip().lower().replace("_", "-")

    if args.debug:
        global OMNI_DEBUG
        OMNI_DEBUG = True
    if args.verbose:
        global OMNI_VERBOSE
        OMNI_VERBOSE = True

    # Resolve alias
    action = ALIASES.get(args.action, args.action)

    core = OmniCore()

    try:
        if action in ["help", "?"] or args.help:
            core.show_help()
        elif action == "commands":
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
            core.show_config()
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
        elif action == "chat":
            chat_action = remaining[0] if remaining and remaining[0].lower() in {"status", "show", "new"} else ""
            chat_prompt = " ".join(remaining[1:] if chat_action else remaining).strip()
            core.chat_cmd(
                chat_action,
                accept_all=should_accept_all(args.accept_all, args.yes, env=os.environ),
                prompt=chat_prompt,
            )
        elif action in {"examples", "playbook", "playbooks"}:
            core.show_examples()
        elif action == "auto":
            core.show_auto_status(
                powershell=args.powershell,
                target_host=args.target_host,
                remote_user=args.remote_user,
                identity_file=args.identity_file,
                repo_url=args.repo_url,
                ref_name=args.ref_name,
                destination=args.dest,
                ps1_out=args.ps1_out,
                windows_dir=args.windows_dir,
            )
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
        elif action == "packages":
            core.show_packages(args.output)
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
            print(f"Unknown action: {action}")
            hint("Run 'omni help' or 'omni commands' for available commands")
    except KeyboardInterrupt:
        print()
        warn("Operación cancelada por el usuario.")
        sys.exit(130)

if __name__ == "__main__":
    main()

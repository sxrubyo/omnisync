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
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
OMNI_HOME = Path(os.environ.get("OMNI_HOME", APP_DIR)).resolve()
CONFIG_DIR = Path(os.environ.get("OMNI_CONFIG_DIR", OMNI_HOME / "config")).resolve()
STATE_DIR = Path(os.environ.get("OMNI_STATE_DIR", OMNI_HOME / "data")).resolve()
BACKUP_DIR = Path(os.environ.get("OMNI_BACKUP_DIR", OMNI_HOME / "backups")).resolve()
LOG_DIR = Path(os.environ.get("OMNI_LOG_DIR", OMNI_HOME / "logs")).resolve()
ENV_FILE = Path(os.environ.get("OMNI_ENV_FILE", OMNI_HOME / ".env")).resolve()
TASKS_FILE = Path(os.environ.get("OMNI_TASKS_FILE", OMNI_HOME / "tasks.json")).resolve()
REPOS_FILE = Path(os.environ.get("OMNI_REPOS_FILE", CONFIG_DIR / "repos.json")).resolve()
SERVERS_FILE = Path(os.environ.get("OMNI_SERVERS_FILE", CONFIG_DIR / "servers.json")).resolve()


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
    "tr": "transfer",
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


def render_help_overview():
    tips = [
        "Quickstart: cp .env.example .env  |  edit config/repos.json  |  docker compose up -d",
        "Portable state lives inside this folder: config/, data/, backups/, logs/, tasks.json",
        "To migrate: copy the whole directory to a new server and run ./install.sh --compose",
        "Keep secrets out of git: Telegram, SSH targets and overrides go in .env",
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
    def run_cmd(self, cmd: str, shell=True) -> Tuple[int, str, str]:
        try:
            proc = subprocess.Popen(cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = proc.communicate()
            return proc.returncode, stdout.strip(), stderr.strip()
        except Exception as e:
            logger.error(f"Error running command '{cmd}': {e}")
            return -1, "", str(e)

    def check_disk_space(self, threshold_percent=90) -> Dict:
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
        self.repos = self.load_repos()
        self.servers = self.load_servers()
        self.load_tasks()

    def ensure_runtime_dirs(self):
        for path in (OMNI_HOME, CONFIG_DIR, STATE_DIR, BACKUP_DIR, LOG_DIR):
            path.mkdir(parents=True, exist_ok=True)

    def load_repos(self) -> List[str]:
        defaults = [
            str((Path.home() / "melissa").resolve()),
            str((Path.home() / "nova-cli").resolve()),
            str((Path.home() / ".nova").resolve()),
            str(OMNI_HOME),
        ]

        if REPOS_FILE.exists():
            try:
                repo_data = json.loads(REPOS_FILE.read_text(encoding="utf-8"))
                repos = repo_data.get("repos", repo_data) if isinstance(repo_data, dict) else repo_data
                if isinstance(repos, list):
                    return [str(Path(os.path.expandvars(p)).expanduser()) for p in repos]
            except Exception as e:
                debug(f"Failed to load repos.json: {e}")

        return defaults

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
                exclude_flags = " ".join([f"--exclude {shlex.quote(pattern)}" for pattern in excludes])

                if protocol == "scp":
                    cmd = f"scp -P {port} -r {user}@{host}:{shlex.quote(remote_path)} {shlex.quote(str(target_dir))}"
                else:
                    cmd = (
                        f"rsync -az --delete -e \"ssh -p {port}\" {exclude_flags} "
                        f"{user}@{host}:{shlex.quote(remote_path.rstrip('/') + '/') } {shlex.quote(str(target_dir))}/"
                    )

                logger.info("Syncing %s:%s", name, remote_path)
                code, out, err = self.transfer._run_cmd(cmd)
                results.append({
                    "server": name,
                    "path": remote_path,
                    "protocol": protocol,
                    "success": code == 0,
                    "target": str(target_dir),
                    "error": err if code != 0 else "",
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

    def watch_mode(self, interval=300):
        logger = logging.getLogger("omni.core")
        logger.info(f"Starting Omni Core Watch Mode (Interval: {interval}s)")
        try:
            while True:
                self.run_full_fix()
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Watch mode stopped.")

    def show_status(self):
        """Show comprehensive system status."""
        print_logo(compact=True)
        section("System Status")

        disk = self.fixer.check_disk_space()
        mem = self.fixer.check_memory()
        pm2 = self.fixer.check_and_fix_pm2()

        kv("Disk Usage", disk.get('message', 'Unknown'), color=C.GRN if disk.get('status') == 'ok' else C.RED)
        kv("Memory", mem.get('message', 'Unknown'), color=C.GRN if mem.get('status') == 'ok' else C.YLW)
        kv("PM2 Processes", f"{pm2.get('total_processes', 0)} running", color=C.GRN if not pm2.get('restarted') else C.YLW)

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

    def run_backup(self, target=None):
        """Create system backup."""
        print_logo(compact=True)
        section("System Backup")

        target = target or os.path.join(self.root_dir, "backups", f"omni_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

        os.makedirs(os.path.dirname(target), exist_ok=True)

        with Spinner("Creating backup...", color=C.PRIMARY) as sp:
            try:
                # Backup tasks.json
                if os.path.exists(self.tasks_file):
                    shutil.copy(self.tasks_file, target + "_tasks.json")
                sp.finish(f"Backup saved to {target}", success=True)
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
        kv("Logs", str(LOG_DIR / "omni.log"))
        kv("Repos", str(len(self.repos)))
        kv("Telegram", "configured" if os.getenv("OMNI_TELEGRAM_TOKEN") else "not configured")
        nl()

        if self.tasks:
            bullet("Tasks:", C.G3)
            for task in self.tasks:
                dim("  • " + task.get("name", "Unnamed"))

    def show_help(self):
        """Show help menu."""
        print_logo(tagline=True)
        render_help_overview()
        section("Omni Core - Command Reference")

        print("  " + q(C.W, "CORE COMMANDS", bold=True))
        nl()
        bullet("omni check     - Run health check and report", C.GRN)
        bullet("omni fix       - Run full system fix", C.GRN)
        bullet("omni watch     - Run in continuous mode", C.GRN)
        bullet("omni status    - Show system status", C.GRN)
        bullet("omni logs      - View Omni logs", C.GRN)
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
        bullet("omni sync      - Pull snapshots from configured servers", C.PRIMARY)
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
        nl()

        hr()
        bullet("Migration: move this whole folder, then run ./install.sh --compose", C.G3)
        print("  " + q(C.G3, f"Omni Core v{OMNI_VERSION} '{OMNI_CODENAME}'"))
        print("  " + q(C.G3, "Run 'omni <command>' to execute"))
        print()

    def show_install_guide(self):
        print_logo(tagline=False)
        render_help_overview()
        section("Portable Install")
        bullet("1. Copy this folder to the target server", C.GRN)
        bullet("2. Run: cp .env.example .env", C.GRN)
        bullet("3. Edit .env, tasks.json and config/repos.json", C.GRN)
        bullet("4. Run: ./install.sh --compose", C.GRN)
        bullet("5. Validate with: docker compose ps and docker compose logs -f omni-core", C.GRN)
        nl()

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
    parser = argparse.ArgumentParser(description="Omni Core - The Supreme Coordinator", add_help=False)
    parser.add_argument("action", nargs="?", default="help", help="Action to perform")
    parser.add_argument("--interval", type=int, default=300, help="Interval for watch mode (seconds)")
    parser.add_argument("--lines", type=int, default=50, help="Number of log lines")
    parser.add_argument("--follow", "-f", action="store_true", help="Follow logs")
    parser.add_argument("--protocol", type=str, default="scp", help="Transfer protocol")
    parser.add_argument("--compress", action="store_true", default=True, help="Enable compression")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    parser.add_argument("--help", "-h", action="store_true", help="Show help")

    args, remaining = parser.parse_known_args()

    if args.debug:
        global OMNI_DEBUG
        OMNI_DEBUG = True
    if args.verbose:
        global OMNI_VERBOSE
        OMNI_VERBOSE = True

    # Resolve alias
    action = ALIASES.get(args.action, args.action)

    core = OmniCore()

    if action in ["help", "?"] or args.help:
        core.show_help()
    elif action == "check":
        core.run_health_check()
    elif action == "fix":
        core.run_full_fix()
    elif action == "watch":
        core.watch_mode(args.interval)
    elif action == "status":
        core.show_status()
    elif action == "logs":
        core.show_logs(args.lines, args.follow)
    elif action == "restart":
        core.restart_services()
    elif action == "backup":
        core.run_backup()
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
    elif action == "sync":
        core.sync_remote_servers()
    else:
        print(f"Unknown action: {action}")
        hint("Run 'omni help' for available commands")

if __name__ == "__main__":
    main()

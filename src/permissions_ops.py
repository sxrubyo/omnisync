#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Dict, Iterable, List


DEFAULT_PERMISSION_MODE = "smart"
PERMISSION_MODES = ("smart", "ask", "auto", "all")

MODE_ALIASES = {
    "smart": "smart",
    "normal": "smart",
    "default": "smart",
    "ask": "ask",
    "preguntar": "ask",
    "confirm": "ask",
    "auto": "auto",
    "automatico": "auto",
    "automático": "auto",
    "all": "all",
    "todo": "all",
    "full": "all",
}

LEVEL_ORDER = {
    "safe": 0,
    "rewrite": 1,
    "install": 2,
    "shell": 3,
    "danger": 4,
}

SAFE_PREFIXES = (
    "omni status",
    "omni doctor",
    "omni inventory",
    "omni detect-ip",
    "omni commands",
    "omni help",
    "omni examples",
    "omni packages",
    "ls ",
    "pwd",
    "whoami",
    "cat ",
    "rg ",
    "grep ",
    "find ",
    "head ",
    "tail ",
    "df ",
    "free ",
    "pm2 jlist",
    "git status",
    "git branch",
    "python3 -m pip list",
    "dpkg-query",
    "npm list -g",
)

DANGER_MARKERS = (
    "rm -rf",
    "mkfs",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "dd if=",
    "chmod -r 777 /",
    "git reset --hard",
)

INSTALL_MARKERS = (
    "apt-get ",
    " apt ",
    "npm install",
    "pip install",
    "python3 -m pip install",
    "docker compose up",
    "docker-compose up",
    "pm2 restart",
    "systemctl ",
    "service ",
    "git clone",
    "git pull",
    "./install.sh",
    "omni init",
    "omni capture",
    "omni restore",
    "omni migrate",
    "omni reconcile",
    "omni bridge",
    "omni timer-install",
    "omni purge",
)

REWRITE_MARKERS = (
    "omni rewrite-ip",
    "sed -i",
    "perl -pi",
)


def normalize_permission_mode(value: str = "") -> str:
    normalized = str(value or "").strip().lower()
    return MODE_ALIASES.get(normalized, DEFAULT_PERMISSION_MODE)


def ensure_permissions_state(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    data = dict(payload or {})
    mode = normalize_permission_mode(str(data.get("mode", DEFAULT_PERMISSION_MODE)))
    return {"mode": mode}


def classify_command_permission(command: str) -> str:
    normalized = " ".join(str(command or "").strip().lower().split())
    if not normalized:
        return "safe"
    if any(marker in normalized for marker in DANGER_MARKERS):
        return "danger"
    if any(marker in normalized for marker in REWRITE_MARKERS):
        return "rewrite"
    if any(normalized.startswith(prefix) for prefix in SAFE_PREFIXES):
        return "safe"
    if any(marker in normalized for marker in INSTALL_MARKERS):
        return "install"
    return "shell"


def _max_permission_level(levels: Iterable[str]) -> str:
    chosen = "safe"
    best_rank = LEVEL_ORDER[chosen]
    for level in levels:
        candidate = str(level or "safe").strip().lower()
        rank = LEVEL_ORDER.get(candidate, LEVEL_ORDER["shell"])
        if rank > best_rank:
            chosen = candidate if candidate in LEVEL_ORDER else "shell"
            best_rank = rank
    return chosen


def classify_action_permission(action: Dict[str, Any] | None) -> str:
    payload = dict(action or {})
    explicit = str(payload.get("permission", "")).strip().lower()
    if explicit in LEVEL_ORDER:
        return explicit
    action_type = str(payload.get("type", "command")).strip().lower()
    if action_type == "workflow":
        steps = payload.get("steps") or []
        levels: List[str] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            if step.get("permission") in LEVEL_ORDER:
                levels.append(str(step.get("permission")))
            else:
                levels.append(classify_command_permission(str(step.get("command", ""))))
        return _max_permission_level(levels)
    if action_type == "command":
        return classify_command_permission(str(payload.get("command", "")))
    return "safe"


def evaluate_permission_decision(action: Dict[str, Any] | None, permissions: Dict[str, Any] | None = None) -> Dict[str, Any]:
    state = ensure_permissions_state(permissions)
    mode = state["mode"]
    level = classify_action_permission(action)
    explicit_confirm = bool((action or {}).get("confirm"))

    auto_execute = False
    if mode == "all":
        auto_execute = True
    elif mode == "auto":
        auto_execute = level != "danger"
    elif mode == "smart":
        auto_execute = level == "safe" and not explicit_confirm

    needs_confirmation = not auto_execute and ((action or {}).get("type") in {"command", "workflow"})
    if explicit_confirm and mode != "all":
        needs_confirmation = True
        auto_execute = False

    return {
        "mode": mode,
        "level": level,
        "auto_execute": auto_execute,
        "needs_confirmation": needs_confirmation,
    }


def render_permissions_lines(permissions: Dict[str, Any] | None = None) -> List[str]:
    state = ensure_permissions_state(permissions)
    mode = state["mode"]
    descriptions = {
        "smart": "auto solo para acciones seguras; pregunta en installs, rewrite o shell",
        "ask": "pregunta antes de cada acción ejecutable",
        "auto": "auto para casi todo; solo frena acciones peligrosas",
        "all": "auto para todo, incluso acciones peligrosas",
    }
    return [
        f"Modo activo: {mode}",
        f"safe -> {'auto' if mode in {'smart', 'auto', 'all'} else 'preguntar'}",
        f"rewrite/install/shell -> {'auto' if mode in {'auto', 'all'} else 'preguntar'}",
        f"danger -> {'auto' if mode == 'all' else 'preguntar'}",
        f"Perfil: {descriptions.get(mode, descriptions[DEFAULT_PERMISSION_MODE])}",
    ]


def build_permission_prompt(action: Dict[str, Any], decision: Dict[str, Any]) -> str:
    title = str(action.get("title") or action.get("command") or action.get("type") or "acción").strip()
    return f"Permitir esta acción ahora? [{decision['mode']}/{decision['level']}] {title}"


def parse_permissions_request(raw: str) -> Dict[str, str]:
    text = str(raw or "").strip()
    if not text:
        return {"action": "show", "mode": ""}
    lowered = text.lower()
    if lowered == "reset":
        return {"action": "set", "mode": DEFAULT_PERMISSION_MODE}
    mode = normalize_permission_mode(lowered)
    if lowered in MODE_ALIASES:
        return {"action": "set", "mode": mode}
    return {"action": "unknown", "mode": lowered}

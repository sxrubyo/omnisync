#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class AgentRuntime:
    key: str
    title: str
    commands: tuple[str, ...]
    install_hint: str


@dataclass(frozen=True)
class AgentRuntimeStatus:
    key: str
    title: str
    command: str
    installed: bool
    path: str
    version: str
    skill_path: str
    install_hint: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


RUNTIMES = (
    AgentRuntime(
        key="claude-code",
        title="Claude Code",
        commands=("claude",),
        install_hint="Instala Claude Code o conecta el binario `claude` para reutilizarlo desde Omni.",
    ),
    AgentRuntime(
        key="codex-cli",
        title="Codex CLI",
        commands=("codex",),
        install_hint="Instala Codex CLI o deja el binario `codex` disponible en PATH.",
    ),
    AgentRuntime(
        key="gemini-cli",
        title="Gemini CLI",
        commands=("gemini", "gemini-cli"),
        install_hint="Instala Gemini CLI o expón `gemini`/`gemini-cli` en PATH.",
    ),
)


def _detect_command(commands: tuple[str, ...]) -> tuple[str, str]:
    for command in commands:
        path = shutil.which(command)
        if path:
            return command, path
    return commands[0], ""


def _read_version(command: str) -> str:
    if not command:
        return ""
    for flag in ("--version", "version", "-v"):
        try:
            result = subprocess.run([command, flag], capture_output=True, text=True, check=False, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        text = (result.stdout or result.stderr or "").strip().splitlines()
        if result.returncode == 0 and text:
            return text[0].strip()
    return ""


def detect_agent_runtimes(skill_root: Path) -> List[AgentRuntimeStatus]:
    statuses: List[AgentRuntimeStatus] = []
    for runtime in RUNTIMES:
        command, path = _detect_command(runtime.commands)
        skill_path = skill_root / runtime.key / "SKILL.md"
        statuses.append(
            AgentRuntimeStatus(
                key=runtime.key,
                title=runtime.title,
                command=command,
                installed=bool(path),
                path=path,
                version=_read_version(command) if path else "",
                skill_path=str(skill_path),
                install_hint=runtime.install_hint,
            )
        )
    return statuses


def ensure_agent_skill_bridges(skill_root: Path) -> List[AgentRuntimeStatus]:
    statuses = detect_agent_runtimes(skill_root)
    skill_root.mkdir(parents=True, exist_ok=True)
    for status in statuses:
        target_dir = skill_root / status.key
        target_dir.mkdir(parents=True, exist_ok=True)
        skill_doc = target_dir / "SKILL.md"
        skill_doc.write_text(
            "\n".join(
                [
                    f"# {status.title} bridge",
                    "",
                    "Omni usa este bridge para detectar, resumir y coordinar el runtime del agente desde el flujo de migración.",
                    "",
                    f"- Runtime key: `{status.key}`",
                    f"- Command: `{status.command}`",
                    f"- Installed: `{'yes' if status.installed else 'no'}`",
                    f"- Path: `{status.path or 'missing'}`",
                    "",
                    "Comandos sugeridos:",
                    "- `omni guide`",
                    "- `omni briefcase --full --output ~/briefcase.json`",
                    "- `omni connect --host <destino> --user <usuario>`",
                    "- `omni chat \"explica el siguiente paso\"`",
                    "",
                    f"Nota: {status.install_hint}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    metadata = skill_root / "agent-skills.json"
    metadata.write_text(
        json.dumps({"runtimes": [item.to_dict() for item in statuses]}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return statuses

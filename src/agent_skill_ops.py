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


@dataclass(frozen=True)
class AgentIntegrationAsset:
    source: str
    target: str


@dataclass(frozen=True)
class AgentIntegrationStatus:
    key: str
    title: str
    detected: bool
    targets: List[str]
    written: List[str]

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
    AgentRuntime(
        key="opencode-cli",
        title="OpenCode CLI",
        commands=("opencode",),
        install_hint="Instala OpenCode CLI o deja el binario `opencode` disponible en PATH.",
    ),
)

INTEGRATION_ASSETS: Dict[str, tuple[AgentIntegrationAsset, ...]] = {
    "claude-code": (
        AgentIntegrationAsset(
            source=".claude/skills/omni-sync/SKILL.md",
            target=".claude/skills/omni-sync/SKILL.md",
        ),
    ),
    "codex-cli": (
        AgentIntegrationAsset(
            source=".codex/skills/omni-sync/SKILL.md",
            target=".codex/skills/omni-sync/SKILL.md",
        ),
    ),
    "gemini-cli": (
        AgentIntegrationAsset(
            source=".gemini/commands/omni-sync.toml",
            target=".gemini/commands/omni-sync.toml",
        ),
        AgentIntegrationAsset(
            source=".gemini/commands/omni-agent.toml",
            target=".gemini/commands/omni-agent.toml",
        ),
    ),
    "opencode-cli": (
        AgentIntegrationAsset(
            source=".opencode/commands/omni-sync.md",
            target=".config/opencode/commands/omni-sync.md",
        ),
        AgentIntegrationAsset(
            source=".opencode/commands/omni-agent.md",
            target=".config/opencode/commands/omni-agent.md",
        ),
        AgentIntegrationAsset(
            source=".opencode/commands/omni-sync.md",
            target=".opencode/commands/omni-sync.md",
        ),
        AgentIntegrationAsset(
            source=".opencode/commands/omni-agent.md",
            target=".opencode/commands/omni-agent.md",
        ),
    ),
}

INTEGRATION_MARKERS: Dict[str, tuple[str, ...]] = {
    "claude-code": (".claude",),
    "codex-cli": (".codex",),
    "gemini-cli": (".gemini",),
    "opencode-cli": (".config/opencode", ".opencode"),
}


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
                    f"- `{' '.join([status.command, '.']) if status.installed else status.command}`",
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


def sync_agent_integrations(
    skill_root: Path,
    *,
    home_root: Path | None = None,
    repo_root: Path | None = None,
) -> Dict[str, Any]:
    statuses = ensure_agent_skill_bridges(skill_root)
    runtime_by_key = {item.key: item for item in statuses}
    resolved_home = (home_root or Path.home()).expanduser()
    resolved_repo = (repo_root or Path(__file__).resolve().parents[1]).resolve()

    integrations: List[AgentIntegrationStatus] = []
    for runtime in RUNTIMES:
        status = runtime_by_key[runtime.key]
        marker_hits = [resolved_home / marker for marker in INTEGRATION_MARKERS.get(runtime.key, ())]
        detected = status.installed or any(path.exists() for path in marker_hits)
        written: List[str] = []
        targets: List[str] = []
        if detected:
            for asset in INTEGRATION_ASSETS.get(runtime.key, ()):
                source_path = resolved_repo / asset.source
                if not source_path.exists():
                    continue
                target_path = resolved_home / asset.target
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
                written.append(str(target_path))
                targets.append(str(target_path))
        integrations.append(
            AgentIntegrationStatus(
                key=runtime.key,
                title=runtime.title,
                detected=detected,
                targets=targets,
                written=written,
            )
        )

    metadata = skill_root / "agent-integrations.json"
    metadata.write_text(
        json.dumps({"integrations": [item.to_dict() for item in integrations]}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "runtimes": statuses,
        "integrations": integrations,
        "metadata_path": str(metadata),
    }

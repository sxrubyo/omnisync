#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Mapping

from platform_ops import PlatformInfo, detect_platform_info, detect_shell_family, is_non_interactive


FLOW_ORDER = ("connect", "briefcase", "restore", "migrate-sync", "doctor", "agent", "chat", "advanced")

FLOW_ALIASES = {
    "1": "connect",
    "connect": "connect",
    "ssh": "connect",
    "ssh connect": "connect",
    "omni connect": "connect",
    "bridge": "connect",
    "puente": "connect",
    "bridge mode": "connect",
    "2": "briefcase",
    "briefcase": "briefcase",
    "maleta": "briefcase",
    "omni briefcase": "briefcase",
    "capture": "briefcase",
    "capturar": "briefcase",
    "backup": "briefcase",
    "3": "restore",
    "restore": "restore",
    "restaurar": "restore",
    "recover": "restore",
    "4": "migrate-sync",
    "migrate-sync": "migrate-sync",
    "migrate sync": "migrate-sync",
    "sync": "migrate-sync",
    "omni migrate sync": "migrate-sync",
    "migrate": "migrate-sync",
    "migrar": "migrate-sync",
    "rebuild": "migrate-sync",
    "5": "doctor",
    "doctor": "doctor",
    "health": "doctor",
    "cleanup": "doctor",
    "6": "agent",
    "agent": "agent",
    "ia": "agent",
    "ai": "agent",
    "omni agent": "agent",
    "7": "chat",
    "chat": "chat",
    "omni chat": "chat",
    "8": "advanced",
    "advanced": "advanced",
    "expert": "advanced",
}


@dataclass(frozen=True)
class FlowOption:
    key: str
    title: str
    description: str
    recommended: bool = False

    def to_dict(self) -> dict[str, str | bool]:
        return asdict(self)


@dataclass(frozen=True)
class GuidedQuestion:
    key: str
    prompt: str
    choices: tuple[str, ...]
    default: str
    required: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "prompt": self.prompt,
            "choices": list(self.choices),
            "default": self.default,
            "required": self.required,
        }


def normalize_flow_choice(raw_choice: str | None) -> str:
    if not raw_choice:
        return "connect"
    normalized = raw_choice.strip().lower()
    return FLOW_ALIASES.get(normalized, normalized if normalized in FLOW_ORDER else "connect")


def recommended_start_flow(platform_info: PlatformInfo | None = None, env: Mapping[str, str] | None = None) -> str:
    info = platform_info or detect_platform_info(env)
    if info.system == "windows" or detect_shell_family(info.shell) == "powershell":
        return "connect"
    if info.system == "darwin":
        return "briefcase"
    return "migrate-sync"


def build_flow_options(platform_info: PlatformInfo | None = None) -> list[FlowOption]:
    info = platform_info or detect_platform_info()
    recommended = recommended_start_flow(info)
    return [
        FlowOption("connect", "SSH Connect", "Conecta dos máquinas por SSH, detecta el host remoto y envía la maleta.", recommended == "connect"),
        FlowOption("briefcase", "Maleta", "Empaqueta el inventario portátil del sistema y genera el restore script.", recommended == "briefcase"),
        FlowOption("restore", "Restore", "Restore a target host from bundle plus secrets.", recommended == "restore"),
        FlowOption("migrate-sync", "Migrate Sync", "Reconstruye o mueve un host completo con create/plan/capture/restore.", recommended == "migrate-sync"),
        FlowOption("doctor", "Doctor", "Inspect health, disk, timers and cleanup opportunities.", recommended == "doctor"),
        FlowOption("agent", "Agent", "Configure Omni Agent with Claude, Gemini, OpenRouter, Qwen or a custom endpoint.", recommended == "agent"),
        FlowOption("chat", "Chat", "Open the operator chat surface and example prompts.", recommended == "chat"),
        FlowOption("advanced", "Advanced", "Use lower-level Omni commands directly.", recommended == "advanced"),
    ]


def build_start_questions(
    platform_info: PlatformInfo | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> list[GuidedQuestion]:
    info = platform_info or detect_platform_info(env)
    recommended = recommended_start_flow(info, env=env)
    return [
        GuidedQuestion(
            key="entry_mode",
            prompt="¿Qué flujo quieres abrir primero?",
            choices=("connect", "briefcase", "restore", "migrate-sync", "doctor", "agent", "chat", "advanced"),
            default=recommended,
        ),
        GuidedQuestion(
            key="prompt_policy",
            prompt="Quieres que Omni pregunte por bloques o que acepte todo de una vez?",
            choices=("guided", "accept-all"),
            default="guided" if not is_non_interactive(env) else "accept-all",
        ),
    ]


def build_start_menu(
    platform_info: PlatformInfo | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    info = platform_info or detect_platform_info(env)
    options = build_flow_options(info)
    questions = build_start_questions(info, env=env)
    return {
        "title": "OmniSync Guided Start",
        "subtitle": "Choose a recovery path. The CLI can guide the first run or run non-interactively.",
        "platform": info.to_dict(),
        "recommended_flow": recommended_start_flow(info, env=env),
        "options": [option.to_dict() for option in options],
        "questions": [question.to_dict() for question in questions],
        "non_interactive": is_non_interactive(env) or not info.interactive,
    }


def should_accept_all(
    accept_all: bool = False,
    yes: bool = False,
    env: Mapping[str, str] | None = None,
) -> bool:
    if accept_all or yes:
        return True
    return is_non_interactive(env)


def build_flow_prompt(
    platform_info: PlatformInfo | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    info = platform_info or detect_platform_info(env)
    recommended = recommended_start_flow(info, env=env)
    return (
        "OmniSync ready.\n"
        f"Detected platform: {info.system} / {info.shell} / {info.package_manager}\n"
        "What do you want to do first?\n"
        "1. SSH connect two hosts\n"
        "2. Build the full briefcase contract\n"
        "3. Restore a server from bundle + secrets\n"
        "4. Run migrate sync on this host\n"
        "5. Doctor / cleanup / disk recovery\n"
        "6. Configure Omni Agent\n"
        "7. Open chat surface\n"
        f"Recommended default: {recommended}\n"
        "Answer with a number or a flow name."
    )

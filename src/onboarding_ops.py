#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Mapping

from platform_ops import PlatformInfo, detect_platform_info, detect_shell_family, is_non_interactive


FLOW_ORDER = ("bridge", "capture", "restore", "migrate", "doctor", "agent", "advanced")

FLOW_ALIASES = {
    "1": "bridge",
    "bridge": "bridge",
    "puente": "bridge",
    "bridge mode": "bridge",
    "2": "capture",
    "capture": "capture",
    "capturar": "capture",
    "backup": "capture",
    "3": "restore",
    "restore": "restore",
    "restaurar": "restore",
    "recover": "restore",
    "4": "migrate",
    "migrate": "migrate",
    "migrar": "migrate",
    "rebuild": "migrate",
    "5": "doctor",
    "doctor": "doctor",
    "health": "doctor",
    "cleanup": "doctor",
    "6": "agent",
    "agent": "agent",
    "ia": "agent",
    "ai": "agent",
    "omni agent": "agent",
    "7": "advanced",
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
        return "bridge"
    normalized = raw_choice.strip().lower()
    return FLOW_ALIASES.get(normalized, normalized if normalized in FLOW_ORDER else "bridge")


def recommended_start_flow(platform_info: PlatformInfo | None = None, env: Mapping[str, str] | None = None) -> str:
    info = platform_info or detect_platform_info(env)
    if info.system == "windows" or detect_shell_family(info.shell) == "powershell":
        return "bridge"
    if info.system == "darwin":
        return "capture"
    return "migrate"


def build_flow_options(platform_info: PlatformInfo | None = None) -> list[FlowOption]:
    info = platform_info or detect_platform_info()
    recommended = recommended_start_flow(info)
    return [
        FlowOption("bridge", "Bridge", "Use this terminal as a bridge to prepare or transfer Omni state.", recommended == "bridge"),
        FlowOption("capture", "Capture", "Package state and secrets into a recovery set.", recommended == "capture"),
        FlowOption("restore", "Restore", "Restore a target host from bundle plus secrets.", recommended == "restore"),
        FlowOption("migrate", "Migrate", "Rebuild or move a full host end to end.", recommended == "migrate"),
        FlowOption("doctor", "Doctor", "Inspect health, disk, timers and cleanup opportunities.", recommended == "doctor"),
        FlowOption("agent", "Agent", "Configure Omni Agent with Claude, Gemini, OpenRouter, Qwen or a custom endpoint.", recommended == "agent"),
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
            prompt="Prefieres usar Omni como puente o como migracion?",
            choices=("bridge", "capture", "restore", "migrate", "doctor", "agent", "advanced"),
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
        "title": "Omni Core Guided Start",
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
        "Omni Core ready.\n"
        f"Detected platform: {info.system} / {info.shell} / {info.package_manager}\n"
        "What do you want to do first?\n"
        "1. Use this machine as a bridge\n"
        "2. Capture a full migration pack\n"
        "3. Restore a server from bundle + secrets\n"
        "4. Migrate or rebuild this host\n"
        "5. Doctor / cleanup / disk recovery\n"
        "6. Configure Omni Agent\n"
        f"Recommended default: {recommended}\n"
        "Answer with a number or a flow name."
    )

#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class ProviderOption:
    key: str
    title: str
    description: str
    env_var: str
    base_url: str
    docs_url: str
    protocol: str
    default_model: str
    sample_models: tuple[str, ...]
    notes: str = ""
    requires_custom_base_url: bool = False
    requires_custom_env_var: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["sample_models"] = list(self.sample_models)
        return payload


def provider_catalog() -> List[ProviderOption]:
    return [
        ProviderOption(
            key="openai-direct",
            title="OpenAI Direct",
            description="OpenAI nativo para GPT-4.1, GPT-4o o GPT-5.x sin router intermedio.",
            env_var="OPENAI_API_KEY",
            base_url="https://api.openai.com/v1",
            docs_url="https://platform.openai.com/docs/api-reference",
            protocol="openai-compatible",
            default_model="gpt-4.1",
            sample_models=("gpt-4.1", "gpt-4o", "gpt-5.2"),
            notes="Útil cuando quieres GPT directo y sin capas adicionales.",
        ),
        ProviderOption(
            key="claude-direct",
            title="Claude Direct",
            description="Anthropic directo, ideal si quieres usar Claude sin router intermedio.",
            env_var="ANTHROPIC_API_KEY",
            base_url="https://api.anthropic.com",
            docs_url="https://docs.anthropic.com/en/api/client-sdks",
            protocol="anthropic",
            default_model="claude-sonnet-4-20250514",
            sample_models=("claude-sonnet-4-20250514", "claude-3-7-sonnet-latest"),
            notes="Configura la clave y luego Omni Agent podrá usar Claude directo.",
        ),
        ProviderOption(
            key="gemini-direct",
            title="Gemini Direct",
            description="Gemini nativo vía Google AI Studio / Gemini API.",
            env_var="GEMINI_API_KEY",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            docs_url="https://ai.google.dev/docs",
            protocol="gemini",
            default_model="gemini-2.5-flash",
            sample_models=("gemini-2.5-flash", "gemini-2.5-pro"),
            notes="Usa el endpoint nativo de Gemini.",
        ),
        ProviderOption(
            key="mistral-direct",
            title="Mistral Direct",
            description="Mistral nativo sobre su endpoint OpenAI-compatible.",
            env_var="MISTRAL_API_KEY",
            base_url="https://api.mistral.ai/v1",
            docs_url="https://docs.mistral.ai/api/",
            protocol="openai-compatible",
            default_model="mistral-large-latest",
            sample_models=("mistral-large-latest", "mistral-small-latest"),
            notes="Bueno para un lane rápido sin depender de OpenRouter.",
        ),
        ProviderOption(
            key="ollama-local",
            title="Ollama Local",
            description="Ollama local o remoto compatible con OpenAI-style APIs.",
            env_var="OLLAMA_API_KEY",
            base_url="http://127.0.0.1:11434/v1",
            docs_url="https://github.com/ollama/ollama/blob/main/docs/openai.md",
            protocol="openai-compatible",
            default_model="qwen2.5-coder:14b",
            sample_models=("qwen2.5-coder:14b", "llama3.2:latest", "deepseek-coder-v2"),
            notes="La API key es opcional; deja Enter vacío si tu host Ollama no la exige.",
            requires_custom_base_url=True,
        ),
        ProviderOption(
            key="gemini-openai",
            title="Gemini OpenAI-Compatible",
            description="Gemini expuesto por la capa OpenAI-compatible de Google.",
            env_var="GEMINI_API_KEY",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            docs_url="https://ai.google.dev/docs",
            protocol="openai-compatible",
            default_model="gemini-2.5-flash",
            sample_models=("gemini-2.5-flash", "gemini-2.5-pro"),
            notes="Útil si quieres hablarle como a un proveedor OpenAI-compatible.",
        ),
        ProviderOption(
            key="openrouter",
            title="OpenRouter",
            description="Router multi-modelo: Claude, Gemini, OpenAI y otros detrás de una sola API.",
            env_var="OPENROUTER_API_KEY",
            base_url="https://openrouter.ai/api/v1",
            docs_url="https://openrouter.ai/docs/quickstart",
            protocol="openai-compatible",
            default_model="google/gemini-2.5-flash",
            sample_models=("google/gemini-2.5-flash", "anthropic/claude-sonnet-4", "openai/gpt-5.2"),
            notes="Buena opción si quieres cambiar de modelo sin recablear Omni Agent.",
        ),
        ProviderOption(
            key="qwen-intl",
            title="Qwen Model Studio",
            description="Qwen sobre Alibaba Cloud Model Studio, OpenAI-compatible internacional.",
            env_var="DASHSCOPE_API_KEY",
            base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            docs_url="https://www.alibabacloud.com/help/en/model-studio/qwen-api-reference/",
            protocol="openai-compatible",
            default_model="qwen-max",
            sample_models=("qwen-max", "qwen-plus", "qwen-turbo"),
            notes="Puedes cambiar luego la región o usar DashScope nativo si te conviene.",
        ),
        ProviderOption(
            key="custom-openai",
            title="Custom OpenAI-Compatible",
            description="Endpoint propio o proveedor OpenAI-compatible por URL.",
            env_var="OMNI_AGENT_API_KEY",
            base_url="https://api.example.com/v1",
            docs_url="https://platform.openai.com/docs/api-reference",
            protocol="openai-compatible",
            default_model="custom-model",
            sample_models=("custom-model",),
            notes="Sirve para Qwen privado, gateways internos o proveedores compatibles.",
            requires_custom_base_url=True,
            requires_custom_env_var=True,
        ),
    ]


def load_agent_config(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_agent_config(config_path: Path, payload: Dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_provider(provider_key: str) -> ProviderOption | None:
    for provider in provider_catalog():
        if provider.key == provider_key:
            return provider
    return None


def env_has_value(env_file: Path, key: str) -> bool:
    if key in os.environ and str(os.environ[key]).strip():
        return True
    if not env_file.exists():
        return False
    prefix = f"{key}="
    return any(line.strip().startswith(prefix) and line.strip() != prefix for line in env_file.read_text(encoding="utf-8").splitlines())


def upsert_env_value(env_file: Path, key: str, value: str) -> None:
    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()

    prefix = f"{key}="
    replaced = False
    updated: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix):
            updated.append(f"{key}={value}")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        updated.append(f"{key}={value}")
    env_file.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")


def redact_secret(value: str) -> str:
    text = str(value or "")
    if len(text) <= 8:
        return "*" * len(text)
    return text[:4] + "…" + text[-4:]

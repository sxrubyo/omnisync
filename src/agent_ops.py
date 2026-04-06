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
            key="claude-direct",
            title="Claude Direct",
            description="Anthropic directo, ideal si quieres usar Claude sin router intermedio.",
            env_var="ANTHROPIC_API_KEY",
            base_url="https://api.anthropic.com",
            docs_url="https://docs.anthropic.com/en/docs/about-claude/models/all-models",
            protocol="anthropic",
            default_model="claude-sonnet-4-20250514",
            sample_models=(
                "claude-opus-4-1-20250805",
                "claude-opus-4-20250514",
                "claude-sonnet-4-20250514",
                "claude-3-7-sonnet-latest",
                "claude-3-5-haiku-latest",
            ),
            notes="Anthropic directo publica hoy Opus 4.1, Opus 4, Sonnet 4, Sonnet 3.7 y Haiku 3.5. Si quieres Claude 4.6, usa Bedrock.",
        ),
        ProviderOption(
            key="openai-direct",
            title="OpenAI Direct",
            description="OpenAI directo para GPT-5.x y modelos frontier.",
            env_var="OPENAI_API_KEY",
            base_url="https://api.openai.com/v1",
            docs_url="https://platform.openai.com/docs/models",
            protocol="openai-compatible",
            default_model="gpt-5.2",
            sample_models=("gpt-5.2", "gpt-5.2-pro", "gpt-5-mini", "gpt-5-nano", "gpt-4.1"),
            notes="Útil si quieres usar el catálogo oficial de OpenAI sin router.",
        ),
        ProviderOption(
            key="azure-openai",
            title="Azure OpenAI",
            description="Azure OpenAI / Foundry para despliegues empresariales y regiones propias.",
            env_var="AZURE_OPENAI_API_KEY",
            base_url="https://YOUR-RESOURCE.openai.azure.com/openai/v1",
            docs_url="https://learn.microsoft.com/en-us/azure/ai-services/openai/reference",
            protocol="openai-compatible",
            default_model="gpt-5.2",
            sample_models=("gpt-5.2", "gpt-5-mini", "gpt-5-nano", "gpt-4.1"),
            notes="En Azure el valor del modelo suele terminar siendo el deployment name real. Ajusta la URL base a tu recurso.",
            requires_custom_base_url=True,
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
            sample_models=("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"),
            notes="Usa el endpoint nativo de Gemini.",
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
            sample_models=("google/gemini-2.5-flash", "anthropic/claude-sonnet-4", "openai/gpt-5.2", "deepseek/deepseek-chat-v3.2"),
            notes="Buena opción si quieres cambiar de modelo sin recablear Omni Agent.",
        ),
        ProviderOption(
            key="aws-bedrock",
            title="AWS Bedrock",
            description="Bedrock con Anthropic 4.6, Amazon Nova y otros modelos gestionados por AWS.",
            env_var="AWS_BEARER_TOKEN_BEDROCK",
            base_url="https://bedrock-mantle.us-east-1.api.aws/v1",
            docs_url="https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html",
            protocol="openai-compatible",
            default_model="anthropic.claude-sonnet-4-6-v1",
            sample_models=(
                "anthropic.claude-opus-4-6-v1",
                "anthropic.claude-sonnet-4-6-v1",
                "anthropic.claude-haiku-4-5-v1",
                "amazon.nova-pro-v1:0",
            ),
            notes="Bedrock hoy ya expone Claude Opus 4.6, Sonnet 4.6 y Amazon Nova. Ajusta región si no trabajas en us-east-1.",
            requires_custom_base_url=True,
        ),
        ProviderOption(
            key="xai-direct",
            title="xAI Grok Direct",
            description="xAI directo para Grok y su Responses API.",
            env_var="XAI_API_KEY",
            base_url="https://api.x.ai/v1",
            docs_url="https://docs.x.ai/developers/models",
            protocol="openai-compatible",
            default_model="grok-4",
            sample_models=("grok-4", "grok-4-latest", "grok-4.20"),
            notes="xAI documenta hoy Grok 4 y Grok 4.20; el alias estable suele ser la opción más cómoda.",
        ),
        ProviderOption(
            key="groq",
            title="Groq",
            description="Groq API OpenAI-compatible, enfocada en baja latencia.",
            env_var="GROQ_API_KEY",
            base_url="https://api.groq.com/openai/v1",
            docs_url="https://console.groq.com/docs/openai",
            protocol="openai-compatible",
            default_model="openai/gpt-oss-120b",
            sample_models=("openai/gpt-oss-120b", "llama-3.1-8b-instant", "groq-compound"),
            notes="Groq es buena vía si priorizas velocidad y compatibilidad OpenAI.",
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
            key="deepseek-direct",
            title="DeepSeek Direct",
            description="DeepSeek directo con chat y reasoning oficiales.",
            env_var="DEEPSEEK_API_KEY",
            base_url="https://api.deepseek.com",
            docs_url="https://api-docs.deepseek.com/quick_start/pricing/",
            protocol="openai-compatible",
            default_model="deepseek-chat",
            sample_models=("deepseek-chat", "deepseek-reasoner"),
            notes="DeepSeek publica oficialmente `deepseek-chat` y `deepseek-reasoner`.",
        ),
        ProviderOption(
            key="mistral-direct",
            title="Mistral Direct",
            description="Mistral API directa para sus modelos frontier y open-weight.",
            env_var="MISTRAL_API_KEY",
            base_url="https://api.mistral.ai/v1",
            docs_url="https://docs.mistral.ai/",
            protocol="openai-compatible",
            default_model="mistral-large-latest",
            sample_models=("mistral-large-latest", "mistral-medium-latest", "devstral-medium-latest"),
            notes="Mistral mantiene su propio catálogo y endpoint de modelos.",
        ),
        ProviderOption(
            key="cohere-direct",
            title="Cohere Direct",
            description="Cohere directo para Command A, razonamiento y agentes enterprise.",
            env_var="COHERE_API_KEY",
            base_url="https://api.cohere.com/v2",
            docs_url="https://docs.cohere.com/docs/models",
            protocol="cohere",
            default_model="command-a-03-2025",
            sample_models=("command-a-03-2025", "command-a-reasoning-08-2025", "command-r7b-12-2024"),
            notes="Cohere documenta hoy Command A como su modelo más fuerte para agentes enterprise.",
        ),
        ProviderOption(
            key="together",
            title="Together AI",
            description="Router serverless con Qwen, DeepSeek, Kimi, GPT-OSS y otros open-weight.",
            env_var="TOGETHER_API_KEY",
            base_url="https://api.together.xyz/v1",
            docs_url="https://docs.together.ai/docs/serverless-models",
            protocol="openai-compatible",
            default_model="Qwen/Qwen3.5-397B-A17B",
            sample_models=(
                "Qwen/Qwen3.5-397B-A17B",
                "Qwen/Qwen3-Coder-Next-FP8",
                "deepseek-ai/DeepSeek-V3.1",
                "MiniMaxAI/MiniMax-M2.5",
            ),
            notes="Together sirve bien si quieres moverte rápido entre open-weight y reasoning sin operar infraestructura propia.",
        ),
        ProviderOption(
            key="perplexity",
            title="Perplexity Sonar",
            description="Perplexity para búsqueda y research con grounding de web.",
            env_var="PERPLEXITY_API_KEY",
            base_url="https://api.perplexity.ai",
            docs_url="https://docs.perplexity.ai/docs/sonar/models",
            protocol="openai-compatible",
            default_model="sonar-pro",
            sample_models=("sonar", "sonar-pro", "sonar-reasoning-pro", "sonar-deep-research"),
            notes="Perplexity separa búsqueda, reasoning y deep research en la familia Sonar.",
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

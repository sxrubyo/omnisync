#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from permissions_ops import ensure_permissions_state


DEFAULT_ACTIVATION_PROMPT = """Eres Omni Agent, el operador conversacional de Omni Core.
Tu proveedor principal es el que el usuario eligió en `omni agent`; no lo sustituyas ni lo ocultes.
Habla en español por defecto, con tono directo, útil y técnico cuando haga falta.
Ayudas con migración, reconstrucción de hosts, bundles, secretos, rewrite de IP/hostname, Docker, PM2, Linux y operación del workspace.
Si conviene ejecutar algo, puedes proponer una acción estructurada al final usando exactamente una línea `ACTION:{...}`.
Acciones soportadas:
- comando shell: ACTION:{"type":"command","command":"omni doctor","confirm":true,"title":"Diagnóstico"}
- lista de tareas: ACTION:{"type":"todo","title":"Siguiente paso","items":["...","..."]}
No metas Markdown alrededor de ACTION. El texto visible para el usuario debe quedar limpio y separado.
Si no sabes algo, dilo sin inventar.
"""

ACTION_RE = re.compile(r"(?:\r?\n)?ACTION:(\{.*\})\s*$", re.DOTALL)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_activation_prompt(prompt_path: Path) -> str:
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    if not prompt_path.exists():
        prompt_path.write_text(DEFAULT_ACTIVATION_PROMPT.rstrip() + "\n", encoding="utf-8")
    return prompt_path.read_text(encoding="utf-8").strip()


def load_env_value(env_file: Path, key: str) -> str:
    env_value = os.environ.get(key, "").strip()
    if env_value:
        return env_value
    if not env_file.exists():
        return ""
    prefix = f"{key}="
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip().strip("'").strip('"')
    return ""


def new_chat_session(
    session_dir: Path,
    *,
    provider_title: str,
    model: str,
    base_url: str,
    provider_key: str = "",
    protocol: str = "",
    activation_file: str = "",
) -> Dict[str, Any]:
    session_dir.mkdir(parents=True, exist_ok=True)
    session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = session_dir / f"chat-{session_id}.json"
    payload: Dict[str, Any] = {
        "id": session_id,
        "path": str(path),
        "provider_key": provider_key,
        "provider_title": provider_title,
        "protocol": protocol,
        "model": model,
        "base_url": base_url,
        "activation_file": activation_file,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "messages": [],
        "permissions": ensure_permissions_state(),
    }
    return payload


def save_chat_session(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["path"] = str(path)
    payload["updated_at"] = utc_now()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_chat_session(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["permissions"] = ensure_permissions_state(payload.get("permissions"))
    return payload


def ensure_chat_permissions(session: Dict[str, Any]) -> Dict[str, Any]:
    permissions = ensure_permissions_state(session.get("permissions"))
    session["permissions"] = permissions
    return permissions


def latest_chat_session_path(session_dir: Path) -> Optional[Path]:
    if not session_dir.exists():
        return None
    candidates = sorted(session_dir.glob("chat-*.json"))
    return candidates[-1] if candidates else None


def trim_chat_messages(messages: List[Dict[str, str]], *, max_messages: int = 14) -> List[Dict[str, str]]:
    if len(messages) <= max_messages:
        return list(messages)
    system_messages = [msg for msg in messages if msg.get("role") == "system"]
    non_system = [msg for msg in messages if msg.get("role") != "system"]
    trimmed = non_system[-max_messages:]
    return system_messages[:1] + trimmed if system_messages else trimmed


def parse_action_block(raw_text: str) -> Optional[Dict[str, Any]]:
    match = ACTION_RE.search(raw_text or "")
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        return None


def clean_assistant_output(raw_text: str) -> str:
    if not raw_text:
        return ""
    clean = ACTION_RE.sub("", raw_text).strip()
    return clean


def _content_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part).strip()
    return ""


def _join_url(base_url: str, suffix: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith(suffix):
        return base
    return f"{base}{suffix}"


def build_chat_request(
    *,
    protocol: str,
    base_url: str,
    model: str,
    api_key: str,
    messages: List[Dict[str, str]],
) -> Dict[str, Any]:
    protocol = protocol.strip().lower()
    trimmed = trim_chat_messages(messages, max_messages=18)

    if protocol == "openai-compatible":
        url = _join_url(base_url, "/chat/completions")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {"model": model, "messages": trimmed, "temperature": 0.4}
        return {"url": url, "headers": headers, "body": json.dumps(payload).encode("utf-8")}

    if protocol == "anthropic":
        base = base_url.rstrip("/")
        if base.endswith("/messages"):
            url = base
        elif base.endswith("/v1"):
            url = f"{base}/messages"
        else:
            url = f"{base}/v1/messages"
        system_text = "\n\n".join(msg["content"] for msg in trimmed if msg.get("role") == "system").strip()
        chat_messages = [
            {"role": "assistant" if msg.get("role") == "assistant" else "user", "content": msg.get("content", "")}
            for msg in trimmed
            if msg.get("role") != "system"
        ]
        payload: Dict[str, Any] = {"model": model, "max_tokens": 1200, "messages": chat_messages}
        if system_text:
            payload["system"] = system_text
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        return {"url": url, "headers": headers, "body": json.dumps(payload).encode("utf-8")}

    if protocol == "gemini":
        base = base_url.rstrip("/")
        quoted_model = urllib.parse.quote(model, safe="")
        url = f"{base}/models/{quoted_model}:generateContent?key={urllib.parse.quote(api_key, safe='')}"
        system_text = "\n\n".join(msg["content"] for msg in trimmed if msg.get("role") == "system").strip()
        contents = []
        for msg in trimmed:
            role = msg.get("role")
            if role == "system":
                continue
            contents.append(
                {
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": msg.get("content", "")}],
                }
            )
        payload: Dict[str, Any] = {"contents": contents}
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}
        headers = {"Content-Type": "application/json"}
        return {"url": url, "headers": headers, "body": json.dumps(payload).encode("utf-8")}

    if protocol == "cohere":
        url = _join_url(base_url, "/chat")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": model, "messages": trimmed}
        return {"url": url, "headers": headers, "body": json.dumps(payload).encode("utf-8")}

    raise ValueError(f"Unsupported protocol for chat: {protocol}")


def extract_chat_text(protocol: str, payload: Dict[str, Any]) -> str:
    protocol = protocol.strip().lower()

    if protocol == "openai-compatible":
        choices = payload.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            return _content_to_text(message.get("content")).strip()
        return ""

    if protocol == "anthropic":
        return _content_to_text(payload.get("content") or []).strip()

    if protocol == "gemini":
        candidates = payload.get("candidates") or []
        if not candidates:
            return ""
        content = candidates[0].get("content") or {}
        return _content_to_text((content.get("parts") or [])).strip()

    if protocol == "cohere":
        message = payload.get("message") or {}
        if isinstance(message, dict) and message.get("content"):
            return _content_to_text(message.get("content")).strip()
        text = payload.get("text")
        return text.strip() if isinstance(text, str) else ""

    return ""


def chat_completion(
    *,
    protocol: str,
    base_url: str,
    model: str,
    api_key: str,
    messages: List[Dict[str, str]],
    timeout: int = 90,
) -> Dict[str, Any]:
    request_payload = build_chat_request(
        protocol=protocol,
        base_url=base_url,
        model=model,
        api_key=api_key,
        messages=messages,
    )
    request = urllib.request.Request(
        request_payload["url"],
        data=request_payload["body"],
        headers=request_payload["headers"],
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8")
            payload = json.loads(raw_body)
            text = extract_chat_text(protocol, payload)
            return {"text": text, "payload": payload, "status": response.status}
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {err.code}: {body}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"Network error: {err}") from err

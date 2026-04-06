#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Dict, Optional


def infer_migration_mode(context: Dict[str, Any] | None = None) -> str:
    payload = dict(context or {})
    has_state_bundle = bool(payload.get("has_state_bundle"))
    has_secrets_bundle = bool(payload.get("has_secrets_bundle"))
    has_capture_summary = bool(payload.get("has_capture_summary"))
    has_product_state = bool(payload.get("has_product_state"))

    if has_state_bundle and has_secrets_bundle:
        return "destination"
    if has_product_state and not has_state_bundle and not has_secrets_bundle:
        return "source"
    if has_capture_summary and (has_state_bundle or has_secrets_bundle):
        return "destination"
    return "ambiguous"


def detect_operator_intent(prompt: str) -> str:
    normalized = " ".join(str(prompt or "").strip().lower().split())
    if not normalized:
        return ""
    if any(term in normalized for term in ("migr", "reconstru", "restaura todo", "instala todo", "deja todo listo")):
        return "migrate"
    if any(term in normalized for term in ("paquetes", "instalado", "python", "n8n", "npm", "apt", "pm2")):
        return "packages"
    if any(term in normalized for term in ("rewrite", "ip antigua", "corrige la ip", "host antiguo", "hostname")):
        return "rewrite"
    if any(term in normalized for term in ("captura", "respaldo", "backup", "bundle")):
        return "capture"
    if any(term in normalized for term in ("doctor", "diagnost", "salud", "estado")):
        return "doctor"
    return ""


def _workflow(title: str, response: str, *commands: str) -> Dict[str, Any]:
    return {
        "response": response,
        "action": {
            "type": "workflow",
            "title": title,
            "confirm": True,
            "steps": [{"title": command, "command": command} for command in commands],
        },
    }


def build_operator_response(prompt: str, *, context: Dict[str, Any] | None = None) -> Optional[Dict[str, Any]]:
    payload = dict(context or {})
    profile = str(payload.get("profile") or "full-home").strip() or "full-home"
    intent = detect_operator_intent(prompt)
    if not intent:
        return None
    if intent in {"migrate", "capture"} and profile != "full-home":
        profile = "full-home"

    if intent == "packages":
        return {
            "response": "Sí. Puedo listar el stack instalado de este host: APT, Python, npm global y PM2.",
            "action": {
                "type": "command",
                "title": "Inventario del stack instalado",
                "command": "omni packages",
                "confirm": False,
            },
        }

    if intent == "doctor":
        return {
            "response": "Voy a correr el diagnóstico operativo para revisar estado, drift y superficie de recuperación.",
            "action": {
                "type": "command",
                "title": "Diagnóstico del host",
                "command": "omni doctor",
                "confirm": False,
            },
        }

    if intent == "rewrite":
        return _workflow(
            "Corregir referencias de host",
            "Sí. Primero detecto la identidad actual del host y luego reescribo las referencias viejas donde aplique.",
            "omni detect-ip",
            "omni rewrite-ip --apply --accept-all",
        )

    if intent == "capture":
        return _workflow(
            "Capturar recovery pack",
            "Voy a preparar el recovery pack completo de este host: inventario, estado y secretos.",
            f"omni init --profile {profile}",
            f"omni inventory --profile {profile}",
            f"omni capture --profile {profile} --accept-all",
        )

    if intent == "migrate":
        mode = str(payload.get("migration_mode") or infer_migration_mode(payload))
        if mode == "destination":
            return _workflow(
                "Migración completa del host destino",
                "Sí. Detecté que este host está en modo destino, así que voy con init, detección de host y migración completa.",
                f"omni init --profile {profile}",
                "omni detect-ip",
                f"omni migrate --profile {profile} --accept-all",
            )
        if mode == "source":
            return _workflow(
                "Preparar host origen para migración",
                "Sí. Detecté que este host parece origen, así que primero preparo el recovery pack completo para moverlo.",
                f"omni init --profile {profile}",
                f"omni inventory --profile {profile}",
                f"omni capture --profile {profile} --accept-all",
            )
        return {
            "response": "Puedo hacerlo, pero antes necesito saber si este host es origen o destino. Si es origen capturo bundles; si es destino hago restore+migrate.",
            "action": {
                "type": "todo",
                "title": "Define el modo de migración",
                "items": [
                    "Responder: este host es origen",
                    "o responder: este host es destino",
                ],
            },
        }

    return None

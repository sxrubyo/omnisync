#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List


DEFAULT_REPO_URL = "git@github.com:sxrubyo/omni-core.git"
DEFAULT_REMOTE_USER = "ubuntu"
DEFAULT_REF_NAME = "main"


@dataclass(frozen=True)
class ExampleEntry:
    key: str
    title: str
    description: str
    when_to_use: str
    command: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def build_examples_catalog() -> List[ExampleEntry]:
    return [
        ExampleEntry(
            key="guided-start",
            title="Arranque guiado",
            description="Abre la puerta principal de Omni y deja que el selector te lleve al flujo correcto.",
            when_to_use="Cuando no quieres memorizar comandos y prefieres elegir entre bridge, capture, restore, migrate o doctor.",
            command="omni",
        ),
        ExampleEntry(
            key="full-home-capture",
            title="Captura completa del host",
            description="Crea el recovery pack de TODO /home/ubuntu usando el perfil full-home.",
            when_to_use="Antes de apagar un servidor, migrarlo o congelar un estado real de producción.",
            command="omni init --profile full-home\nexport OMNI_SECRET_PASSPHRASE='tu-clave-fuerte'\nomni capture --profile full-home",
        ),
        ExampleEntry(
            key="full-home-migrate",
            title="Migración completa",
            description="Reconstruye el host con bundles, secretos y rewrite automático de referencias viejas.",
            when_to_use="Cuando ya moviste los bundles al host nuevo y quieres que Omni haga el resto.",
            command="omni init --profile full-home\nexport OMNI_SECRET_PASSPHRASE='la-misma-clave-fuerte'\nomni migrate --profile full-home --accept-all",
        ),
        ExampleEntry(
            key="doctor-pass",
            title="Diagnóstico y reparación rápida",
            description="Audita salud, timers, drift, bundles y estado básico del runtime.",
            when_to_use="Antes de migrar, después de restaurar o cuando el host empieza a oler mal.",
            command="omni doctor\nomni detect-ip",
        ),
        ExampleEntry(
            key="rewrite-host",
            title="Reescritura de IP y hostname",
            description="Busca referencias del host viejo y las corrige de forma segura.",
            when_to_use="Después de mover el stack a otra IP o dominio y quieres corregir .env, JSON, compose, ecosystem y configs.",
            command="omni rewrite-ip /home/ubuntu --apply --accept-all",
        ),
        ExampleEntry(
            key="agent-setup",
            title="Configurar Omni Agent",
            description="Abre el selector de IA y deja el host listo con Claude, OpenAI, Gemini, Bedrock u otro proveedor.",
            when_to_use="Cuando quieres que Omni tenga un provider LLM operativo sin editar JSON a mano.",
            command="omni agent\nomni agent list\nomni agent status",
        ),
        ExampleEntry(
            key="bridge-send",
            title="Modo puente",
            description="Prepara bundles y luego los empuja al destino remoto.",
            when_to_use="Desde una terminal intermedia, PowerShell o una máquina con poco disco local.",
            command="omni bridge create --profile full-home\nomni bridge send --dest ubuntu@host:/ruta/remota",
        ),
        ExampleEntry(
            key="free-space",
            title="Liberar espacio",
            description="Hace dry-run o limpieza real de bundles, artefactos y estado transferido.",
            when_to_use="Cuando ya restauraste el host o te estás quedando corto de disco.",
            command="omni purge\nomni purge --yes",
        ),
    ]


def build_powershell_auto_command(
    *,
    target_host: str = "",
    remote_user: str = DEFAULT_REMOTE_USER,
    identity_file: str = "",
    repo_url: str = DEFAULT_REPO_URL,
    ref_name: str = DEFAULT_REF_NAME,
    destination: str = "",
    install_timer: bool = True,
) -> str:
    host = target_host or "EC2_DNS_O_IP"
    key = identity_file or "C:\\ruta\\llave.pem"
    dest_fragment = ""
    if destination.strip():
        dest_fragment = f" `\n  -Destination {quote_powershell(destination)}"
    timer_fragment = " `\n  -InstallTimer" if install_timer else ""
    return (
        "pwsh .\\bootstrap.ps1 `\n"
        f"  -TargetHost {quote_powershell(host)} `\n"
        f"  -User {quote_powershell(remote_user)} `\n"
        f"  -IdentityFile {quote_powershell(key)} `\n"
        f"  -RepoUrl {quote_powershell(repo_url)} `\n"
        f"  -Branch {quote_powershell(ref_name)}"
        f"{dest_fragment}"
        f"{timer_fragment}"
    )


def quote_powershell(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"

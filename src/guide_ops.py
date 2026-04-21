#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class GuideEntry:
    key: str
    title: str
    description: str
    estimated_time: str
    command: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_guide_entries() -> List[GuideEntry]:
    return [
        GuideEntry(
            key="connect",
            title="SSH Connect",
            description="Conecta dos máquinas por SSH, detecta el host remoto y envía la maleta con rsync o SFTP.",
            estimated_time="2-5 min",
            command="omni connect",
        ),
        GuideEntry(
            key="briefcase",
            title="Maleta",
            description="Empaqueta el inventario portátil del sistema y genera el plan de restauración.",
            estimated_time="1-3 min",
            command="omni briefcase --full",
        ),
        GuideEntry(
            key="restore",
            title="Restore",
            description="Restaura bundles, secretos y dependencias sobre el host destino.",
            estimated_time="5-20 min",
            command="omni restore",
        ),
        GuideEntry(
            key="agent",
            title="AI Agent",
            description="Configura Omni Agent, detecta CLIs de agentes y prepara el modelo activo.",
            estimated_time="2-4 min",
            command="omni agent",
        ),
        GuideEntry(
            key="migrate-sync",
            title="Migrate Sync",
            description="Usa el flujo nuevo create/plan/capture/restore sobre la briefcase contract.",
            estimated_time="5-30 min",
            command="omni migrate sync",
        ),
    ]


def build_guide_payload() -> Dict[str, Any]:
    return {
        "title": "Omni Guide",
        "entries": [entry.to_dict() for entry in build_guide_entries()],
    }

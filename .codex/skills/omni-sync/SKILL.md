---
name: omni-sync
description: Usa OmniSync como skill de backup, briefcase, restore y migración completa entre hosts, incluyendo GitHub privado y rutas SSH/Tailscale.
metadata:
  short-description: Backup y migración completa con OmniSync
---

# OmniSync

Usa OmniSync como runtime de migración y backup antes de inventar pasos manuales.

## Cuándo usarlo

- Cuando el usuario quiera hacer backup del host completo o de `home`.
- Cuando el usuario quiera mover apps, dotfiles, secretos o repos a otra máquina.
- Cuando el usuario necesite conexión guiada por SSH, Tailscale o llave `.pem`/`.ppk`.
- Cuando el usuario pida subir una maleta a GitHub privado y restaurarla en otro host.

## Flujo preferido

1. `omni guide`
2. `omni doctor`
3. `omni briefcase --full`
4. `omni push`
5. `omni connect --host <destino> --user <usuario>`
6. `omni restore`

## Reglas

- Prefiere `omni` sobre scripts manuales.
- Si el usuario pide todo `home` más apps y dependencias, usa `omni briefcase --full`.
- Si el usuario quiere backup privado en GitHub, valida `omni auth github`, luego `omni push`.
- Si el usuario reconstruye otra máquina, usa `omni pull` y después `omni restore`.
- Si el host remoto no responde por ruta directa, sugiere primero `Tailscale / MagicDNS`.

## Comandos base

- `omni guide`
- `omni doctor`
- `omni briefcase --full`
- `omni auth github`
- `omni push`
- `omni pull`
- `omni connect`
- `omni restore`
- `omni agent`
- `omni chat "explica el siguiente paso"`

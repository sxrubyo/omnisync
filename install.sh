#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_TARGET="/usr/local/bin/omni"
USE_COMPOSE=false
AUTO_SYNC=false
USE_PM2=false
INSTALL_TIMER=false
TIMER_ON_CALENDAR="${OMNI_TIMER_ON_CALENDAR:-daily}"

for arg in "$@"; do
  case "$arg" in
    --compose) USE_COMPOSE=true ;;
    --sync) AUTO_SYNC=true ;;
    --pm2) USE_PM2=true ;;
    --timer) INSTALL_TIMER=true ;;
    --on-calendar=*) TIMER_ON_CALENDAR="${arg#*=}" ;;
  esac
done

mkdir -p "$ROOT_DIR/config" "$ROOT_DIR/config/systemd" "$ROOT_DIR/data/servers" "$ROOT_DIR/backups/host-bundles" "$ROOT_DIR/logs"

if [ ! -f "$ROOT_DIR/.env" ] && [ -f "$ROOT_DIR/.env.example" ]; then
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
fi

if [ ! -f "$ROOT_DIR/config/repos.json" ]; then
  cp "$ROOT_DIR/config/repos.example.json" "$ROOT_DIR/config/repos.json"
fi

if [ ! -f "$ROOT_DIR/config/servers.json" ]; then
  cp "$ROOT_DIR/config/servers.example.json" "$ROOT_DIR/config/servers.json"
fi

if [ ! -f "$ROOT_DIR/config/system_manifest.json" ] && [ -f "$ROOT_DIR/config/system_manifest.example.json" ]; then
  cp "$ROOT_DIR/config/system_manifest.example.json" "$ROOT_DIR/config/system_manifest.json"
fi

chmod +x "$ROOT_DIR/bin/omni"

if command -v sudo >/dev/null 2>&1; then
  sudo ln -sf "$ROOT_DIR/bin/omni" "$BIN_TARGET"
else
  ln -sf "$ROOT_DIR/bin/omni" "$BIN_TARGET"
fi

"$ROOT_DIR/bin/omni" init >/dev/null || true

if $AUTO_SYNC; then
  "$ROOT_DIR/bin/omni" sync || true
fi

if $USE_PM2; then
  pm2 start "$ROOT_DIR/ecosystem.config.js"
fi

if $USE_COMPOSE; then
  docker compose -f "$ROOT_DIR/docker-compose.yml" up -d --build
fi

if $INSTALL_TIMER; then
  "$ROOT_DIR/bin/omni" timer-install --service-name omni-update --on-calendar "$TIMER_ON_CALENDAR"
fi

cat <<EOF
Omni Core instalado en: $ROOT_DIR

Modo automático:
  install.sh --compose --sync --timer

Archivos clave:
  .env
  config/repos.json
  config/servers.json
  config/system_manifest.json
  tasks.json

Comandos:
  omni
  omni start
  omni doctor
  omni capture
  omni restore
  omni migrate
  omni install
  omni inventory
  omni bundle-create
  omni secrets-export
  omni reconcile
  omni timer-install
  omni sync
  docker compose ps
EOF

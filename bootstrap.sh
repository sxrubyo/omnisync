#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${1:-}"
DEST_DIR="${2:-/opt/omni-core}"
REF_NAME="${3:-main}"
INSTALL_TIMER="${INSTALL_TIMER:-0}"
TIMER_ON_CALENDAR="${TIMER_ON_CALENDAR:-daily}"

if [ -z "$REPO_URL" ]; then
  echo "Uso: ./bootstrap.sh <git@github.com:org/repo.git> [destino] [branch]"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y git rsync openssh-client ca-certificates curl docker.io docker-compose-plugin
fi

if [ -d "$DEST_DIR/.git" ]; then
  git -C "$DEST_DIR" fetch --all --prune
  git -C "$DEST_DIR" checkout "$REF_NAME"
  git -C "$DEST_DIR" pull --ff-only origin "$REF_NAME"
else
  git clone --branch "$REF_NAME" "$REPO_URL" "$DEST_DIR"
fi

cd "$DEST_DIR"
chmod +x install.sh bin/omni bootstrap.sh
./install.sh --compose --sync

if [ "$INSTALL_TIMER" = "1" ]; then
  "$DEST_DIR/bin/omni" timer-install --service-name omni-update --on-calendar "$TIMER_ON_CALENDAR"
fi

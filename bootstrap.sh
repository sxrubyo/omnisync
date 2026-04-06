#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${1:-}"
DEST_DIR="${2:-/opt/omni-core}"
REF_NAME="${3:-main}"
INSTALL_TIMER="${INSTALL_TIMER:-0}"
TIMER_ON_CALENDAR="${TIMER_ON_CALENDAR:-daily}"
STASH_NAME="omni-bootstrap-$(date +%Y%m%d_%H%M%S)"

if [ -z "$REPO_URL" ]; then
  echo "Uso: ./bootstrap.sh <repo-url> [destino] [branch]"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

safe_update_repo() {
  local repo_dir="$1"
  local repo_url="$2"
  local ref_name="$3"

  git -C "$repo_dir" remote set-url origin "$repo_url" || true

  if [ -n "$(git -C "$repo_dir" status --porcelain)" ]; then
    echo "Cambios locales detectados. Guardando stash: $STASH_NAME"
    git -C "$repo_dir" stash push --include-untracked -m "$STASH_NAME" >/dev/null
  fi

  git -C "$repo_dir" fetch --all --prune
  git -C "$repo_dir" checkout "$ref_name"
  git -C "$repo_dir" pull --ff-only origin "$ref_name"
}

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y git rsync openssh-client ca-certificates curl docker.io
  if ! sudo apt-get install -y docker-compose-plugin; then
    echo "docker-compose-plugin no disponible. Intentando fallback a docker-compose..."
    sudo apt-get install -y docker-compose || true
  fi
fi

if [ -d "$DEST_DIR/.git" ]; then
  safe_update_repo "$DEST_DIR" "$REPO_URL" "$REF_NAME"
elif [ -d "$DEST_DIR" ]; then
  BACKUP_DIR="${DEST_DIR}.pre-bootstrap.$(date +%Y%m%d_%H%M%S)"
  echo "Directorio existente no-git detectado. Moviendo a: $BACKUP_DIR"
  mv "$DEST_DIR" "$BACKUP_DIR"
  git clone --branch "$REF_NAME" "$REPO_URL" "$DEST_DIR"
else
  git clone --branch "$REF_NAME" "$REPO_URL" "$DEST_DIR"
fi

cd "$DEST_DIR"
chmod +x install.sh bin/omni bootstrap.sh
./install.sh --compose --sync

if [ "$INSTALL_TIMER" = "1" ]; then
  "$DEST_DIR/bin/omni" timer-install --service-name omni-update --on-calendar "$TIMER_ON_CALENDAR"
fi

if git -C "$DEST_DIR" stash list | grep -q "$STASH_NAME"; then
  echo
  echo "Cambios locales preservados en stash:"
  echo "  git -C \"$DEST_DIR\" stash list | sed -n '1,5p'"
  echo "  git -C \"$DEST_DIR\" stash pop"
fi

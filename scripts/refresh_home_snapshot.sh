#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

MODE="safe"
HOME_ROOT="/home/ubuntu"

PUBLIC_SNAPSHOT_ROOT="$ROOT_DIR/home_snapshot"
PUBLIC_TARGET_ROOT="$PUBLIC_SNAPSHOT_ROOT/ubuntu"
PUBLIC_INVENTORY_DIR="$PUBLIC_SNAPSHOT_ROOT/inventory"

PRIVATE_SNAPSHOT_ROOT="$ROOT_DIR/home_private_snapshot"
PRIVATE_ARCHIVE_DIR="$PRIVATE_SNAPSHOT_ROOT/archives"
PRIVATE_INVENTORY_DIR="$PRIVATE_SNAPSHOT_ROOT/inventory"
PRIVATE_CHUNK_SIZE="${HOME_PRIVATE_SNAPSHOT_CHUNK_SIZE:-40m}"

ALLOWLIST_DIRS=(
  ".agents"
  ".aws"
  ".bun"
  ".codex"
  ".nova"
  "Openclaw"
  "Workflows-n8n"
  "eco-nova"
  "melissa"
  "melissa-instances"
  "n8n-workflows"
  "nova"
  "nova-cli"
  "nova-os"
  "nova-test"
  "openclaw-official"
  "omnisync"
  "tv-bridge"
  "whatsapp-bridge"
  "xus-core"
  "xus-https"
  "xus-tv-bridge"
)

ALLOWLIST_FILES=(
  ".bashrc"
  ".gitconfig"
  ".gitignore"
  "AGENTS.md"
  "QUICK_FIX_GUIDE.md"
  "QUICK_REFERENCE.md"
  "RESTART_SUMMARY.md"
  "SECURITY_FIXES_APPLIED.md"
  "check_token.py"
  "install.sh"
  "package-lock.json"
  "package.json"
  "pair_tv.js"
  "verify_fixes.sh"
)

TOP_LEVEL_OMIT_REASONS=(
  ".android:tool-cache"
  ".appium:tool-cache"
  ".appium.env:env-file"
  ".cache:cache"
  ".claude:private-runtime-layer"
  ".claude-flow:runtime"
  ".claude.json:session-config"
  ".config:user-config-may-contain-secrets"
  ".copilot:session-data"
  ".docker:cache"
  ".env.nova:secret"
  ".gemini:private-runtime-layer"
  ".git-credentials:secret"
  ".local:cache"
  ".melissa:private-runtime-layer"
  ".n8n:private-runtime-layer"
  ".npm:cache"
  ".npm-global:global-packages"
  ".npmrc:secret"
  ".ollama:model-cache"
  ".openclaw:runtime-state"
  ".pki:certificates"
  ".playwright-cli:cache"
  ".pm2:private-runtime-layer"
  ".pytest_cache:cache"
  ".ssh:secret"
  ".swarm:runtime-state"
  "android-sdk:tool-cache"
  "backups-test:backup"
  "data:runtime-state"
  "data-test:test-runtime-state"
  "go:tool-cache"
  "logs-test:test-runtime-state"
  "main.py.tmp:temp-file"
  "melissa-backups:backup"
  "node_modules:dependency-cache"
  "omni-core:git-root"
  "opencode_env:venv"
  "output:build-output"
  "tmp:temp-file"
  "vectors.db:database"
  "nova.db:database"
  "data.db:database"
)

RSYNC_EXCLUDES=(
  "--exclude=.git/"
  "--exclude=home_snapshot/"
  "--exclude=home_private_snapshot/"
  "--exclude=node_modules/"
  "--exclude=.venv/"
  "--exclude=venv/"
  "--exclude=__pycache__/"
  "--exclude=.pytest_cache/"
  "--exclude=.cache/"
  "--exclude=.coverage"
  "--exclude=.claude/"
  "--exclude=.codex/"
  "--exclude=.gemini/"
  "--exclude=.n8n/"
  "--exclude=.pm2/"
  "--exclude=.env"
  "--exclude=.env.*"
  "--exclude=*.env"
  "--exclude=*.pem"
  "--exclude=*.key"
  "--exclude=gcp-sa.json"
  "--exclude=authorized_keys"
  "--exclude=.git-credentials"
  "--exclude=*.db"
  "--exclude=*.db-*"
  "--exclude=*.sqlite"
  "--exclude=*.sqlite-*"
  "--exclude=*.sql.gz"
  "--exclude=logs/"
  "--exclude=*.log"
  "--exclude=backups/"
  "--exclude=backup*/"
  "--exclude=sessions/"
  "--exclude=vendor/"
  "--exclude=.tmp/"
  "--exclude=tmp/"
)

PRIVATE_ARCHIVE_TARGETS=(
  ".claude"
  ".codex"
  ".gemini"
  ".melissa"
  ".n8n"
  ".nova"
  ".pm2"
  "Openclaw"
  "Workflows-n8n"
  "melissa"
  "melissa-instances"
  "nova-os"
  "openclaw-official"
  "tv-bridge"
  "whatsapp-bridge"
  "xus-core"
  "xus-https"
  "xus-tv-bridge"
)

PRIVATE_OMIT_REASONS=(
  ".cache:cache"
  ".npm:cache"
  "android-sdk:tool-cache"
  "go:tool-cache"
  "backups-test:backup"
  "data-test:test-runtime-state"
  "output:build-output"
  "tmp:temp-file"
)

PRIVATE_TAR_EXCLUDES=(
  "--exclude=omnisync/home_snapshot"
  "--exclude=omnisync/home_private_snapshot"
  "--exclude=omnisync/imports"
  "--exclude=omnisync/exports"
  "--exclude=omnisync/logs"
  "--exclude=__pycache__"
  "--exclude=.pytest_cache"
  "--exclude=.cache"
  "--exclude=.npm"
  "--exclude=.codex/vendor"
  "--exclude=.codex/cache"
  "--exclude=.codex/.tmp"
  "--exclude=.gemini/tmp"
  "--exclude=.claude/cache"
)

usage() {
  cat <<'EOF'
Usage:
  ./scripts/refresh_home_snapshot.sh [--mode safe|private] [HOME_ROOT]

Modes:
  safe     Refresh the public GitHub-safe snapshot only.
  private  Refresh the public snapshot and build encrypted private overlays.
EOF
}

parse_args() {
  while (($#)); do
    case "$1" in
      --mode)
        MODE="${2:-}"
        shift 2
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      --*)
        printf 'Unknown option: %s\n' "$1" >&2
        exit 1
        ;;
      *)
        HOME_ROOT="$1"
        shift
        ;;
    esac
  done

  if [[ "$MODE" != "safe" && "$MODE" != "private" ]]; then
    printf 'Unsupported mode: %s\n' "$MODE" >&2
    exit 1
  fi
}

reset_dir() {
  local path="$1"
  rm -rf "$path"
  mkdir -p "$path"
}

top_level_inventory() {
  find "$HOME_ROOT" -mindepth 1 -maxdepth 1 -printf '%y\t%f\n' | sort > "$PUBLIC_INVENTORY_DIR/top_level_entries.tsv"
  du -sh "$HOME_ROOT"/* "$HOME_ROOT"/.[!.]* 2>/dev/null | sort -h > "$PUBLIC_INVENTORY_DIR/top_level_sizes.txt" || true
}

write_omissions() {
  : > "$PUBLIC_INVENTORY_DIR/omitted_top_level.tsv"
  for item in "${TOP_LEVEL_OMIT_REASONS[@]}"; do
    printf '%s\t%s\n' "${item%%:*}" "${item#*:}" >> "$PUBLIC_INVENTORY_DIR/omitted_top_level.tsv"
  done
}

copy_dir() {
  local name="$1"
  local src="$HOME_ROOT/$name"
  local dest="$PUBLIC_TARGET_ROOT/$name"

  if [[ ! -e "$src" ]]; then
    return 0
  fi

  mkdir -p "$dest"

  if [[ "$name" == ".codex" ]]; then
    for entry in AGENTS.override.md config.toml instructions.md version.json rules skills superpowers; do
      if [[ -e "$src/$entry" ]]; then
        rsync -a "$src/$entry" "$dest/"
      fi
    done
    return 0
  fi

  if [[ "$name" == ".nova" ]]; then
    for entry in .gitignore nova nova.py profiles.json protected.json shell_setup.sh; do
      if [[ -e "$src/$entry" ]]; then
        rsync -a "$src/$entry" "$dest/"
      fi
    done
    if [[ -d "$src/agents" ]]; then
      while IFS= read -r rules_dir; do
        rel_dir="${rules_dir#"$src/"}"
        mkdir -p "$dest/$rel_dir"
        rsync -a "$rules_dir/" "$dest/$rel_dir/"
      done < <(find "$src/agents" -type d -name rules | sort)
    fi
    return 0
  fi

  rsync -a "${RSYNC_EXCLUDES[@]}" "$src/" "$dest/"
}

copy_file() {
  local name="$1"
  local src="$HOME_ROOT/$name"
  local dest="$PUBLIC_TARGET_ROOT/$name"

  if [[ -f "$src" ]]; then
    install -D -m 0644 "$src" "$dest"
  fi
}

write_public_manifest() {
  cat > "$PUBLIC_INVENTORY_DIR/snapshot_scope.txt" <<EOF
GitHub-safe fallback snapshot generated from: $HOME_ROOT

Included top-level directories:
$(printf '%s\n' "${ALLOWLIST_DIRS[@]}")

Included top-level files:
$(printf '%s\n' "${ALLOWLIST_FILES[@]}")

Global exclusions inside copied directories:
$(printf '%s\n' "${RSYNC_EXCLUDES[@]}")
EOF
}

refresh_public_snapshot() {
  mkdir -p "$PUBLIC_SNAPSHOT_ROOT" "$PUBLIC_INVENTORY_DIR"
  reset_dir "$PUBLIC_TARGET_ROOT"
  top_level_inventory
  write_omissions

  for dir_name in "${ALLOWLIST_DIRS[@]}"; do
    copy_dir "$dir_name"
  done

  for file_name in "${ALLOWLIST_FILES[@]}"; do
    copy_file "$file_name"
  done

  write_public_manifest
  du -sh "$PUBLIC_TARGET_ROOT" > "$PUBLIC_INVENTORY_DIR/snapshot_size.txt" || true
  find "$PUBLIC_TARGET_ROOT" -type f | sed "s#^$PUBLIC_TARGET_ROOT/##" | sort > "$PUBLIC_INVENTORY_DIR/snapshot_files.txt"
}

slugify_target() {
  local target="$1"
  target="${target#.}"
  target="${target//\//__}"
  target="${target// /_}"
  if [[ "$1" == .* ]]; then
    printf 'dot_%s' "$target"
  else
    printf '%s' "$target"
  fi
}

ensure_private_passphrase_file() {
  if [[ -n "${HOME_PRIVATE_SNAPSHOT_PASSPHRASE_FILE:-}" ]]; then
    printf '%s\n' "$HOME_PRIVATE_SNAPSHOT_PASSPHRASE_FILE"
    return 0
  fi

  local passphrase_value="${HOME_PRIVATE_SNAPSHOT_PASSPHRASE:-${OMNI_SECRET_PASSPHRASE:-}}"
  local passphrase_file="$ROOT_DIR/backups/home_private_snapshot.passphrase"
  mkdir -p "$(dirname "$passphrase_file")"

  if [[ -n "$passphrase_value" ]]; then
    umask 077
    printf '%s' "$passphrase_value" > "$passphrase_file"
    printf '%s\n' "$passphrase_file"
    return 0
  fi

  if [[ ! -f "$passphrase_file" ]]; then
    umask 077
    openssl rand -hex 32 > "$passphrase_file"
  fi
  printf '%s\n' "$passphrase_file"
}

write_private_inventory() {
  : > "$PRIVATE_INVENTORY_DIR/omitted_targets.tsv"
  for item in "${PRIVATE_OMIT_REASONS[@]}"; do
    printf '%s\t%s\n' "${item%%:*}" "${item#*:}" >> "$PRIVATE_INVENTORY_DIR/omitted_targets.tsv"
  done
  : > "$PRIVATE_INVENTORY_DIR/included_targets.txt"

  cat > "$PRIVATE_INVENTORY_DIR/README.txt" <<EOF
Private encrypted overlay generated from: $HOME_ROOT

Archives live in:
  $PRIVATE_ARCHIVE_DIR

Restore with:
  ./scripts/restore_home_private_snapshot.sh /home/ubuntu
EOF
}

private_target_is_omitted() {
  local name="$1"
  for item in "${PRIVATE_OMIT_REASONS[@]}"; do
    if [[ "${item%%:*}" == "$name" ]]; then
      return 0
    fi
  done
  return 1
}

list_home_top_level_entries() {
  find "$HOME_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort
}

archive_target() {
  local name="$1"
  local src="$HOME_ROOT/$name"
  local slug
  local prefix
  local passphrase_file="$2"
  local target_type="dir"
  local part_count=0
  local tar_stderr
  local pipeline_rc=0
  local tar_rc=0
  local pipe_status=()

  if [[ ! -e "$src" ]]; then
    return 0
  fi

  if [[ -f "$src" ]]; then
    target_type="file"
  fi

  slug="$(slugify_target "$name")"
  prefix="$PRIVATE_ARCHIVE_DIR/$slug.tar.gz.enc.part-"
  rm -f "$prefix"*

  tar_stderr="$(mktemp)"
  set +e
  tar -czf - -C "$HOME_ROOT" "${PRIVATE_TAR_EXCLUDES[@]}" "$name" 2>"$tar_stderr" \
    | openssl enc -aes-256-cbc -pbkdf2 -salt -pass "file:$passphrase_file" \
    | split -b "$PRIVATE_CHUNK_SIZE" - "$prefix"
  pipe_status=("${PIPESTATUS[@]}")
  set -e
  tar_rc="${pipe_status[0]:-0}"
  pipeline_rc=0
  for status in "${pipe_status[@]}"; do
    if (( status != 0 )); then
      pipeline_rc="$status"
      break
    fi
  done

  if (( pipeline_rc != 0 )); then
    if (( tar_rc == 1 )) && grep -q "file changed as we read it" "$tar_stderr"; then
      printf 'warning: snapshot target changed while archiving: %s\n' "$name" >&2
    else
      cat "$tar_stderr" >&2 || true
      rm -f "$tar_stderr"
      rm -f "$prefix"*
      return "$pipeline_rc"
    fi
  fi
  rm -f "$tar_stderr"

  while IFS= read -r _part; do
    part_count=$((part_count + 1))
  done < <(find "$PRIVATE_ARCHIVE_DIR" -maxdepth 1 -type f -name "$(basename "$prefix")*" | sort)

  printf '%s\t%s\t%s\t%d\n' "$name" "$slug" "$target_type" "$part_count" >> "$PRIVATE_INVENTORY_DIR/archive_manifest.tsv"
}

refresh_private_snapshot() {
  local passphrase_file
  passphrase_file="$(ensure_private_passphrase_file)"

  mkdir -p "$PRIVATE_SNAPSHOT_ROOT" "$PRIVATE_INVENTORY_DIR"
  reset_dir "$PRIVATE_ARCHIVE_DIR"
  : > "$PRIVATE_INVENTORY_DIR/archive_manifest.tsv"
  write_private_inventory

  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    if private_target_is_omitted "$name"; then
      continue
    fi
    printf '%s\n' "$name" >> "$PRIVATE_INVENTORY_DIR/included_targets.txt"
    archive_target "$name" "$passphrase_file"
  done < <(list_home_top_level_entries)

  find "$PRIVATE_ARCHIVE_DIR" -type f | sed "s#^$PRIVATE_SNAPSHOT_ROOT/##" | sort > "$PRIVATE_INVENTORY_DIR/archive_files.txt"
  du -sh "$PRIVATE_ARCHIVE_DIR" > "$PRIVATE_INVENTORY_DIR/archive_size.txt" || true
  printf '%s\n' "$passphrase_file" > "$PRIVATE_INVENTORY_DIR/passphrase_path.txt"
}

main() {
  parse_args "$@"
  refresh_public_snapshot
  if [[ "$MODE" == "private" ]]; then
    refresh_private_snapshot
    printf 'Private snapshot refreshed at %s\n' "$PRIVATE_SNAPSHOT_ROOT"
  fi
  printf 'Snapshot refreshed at %s\n' "$PUBLIC_TARGET_ROOT"
}

main "$@"

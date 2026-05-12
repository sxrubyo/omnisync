#!/usr/bin/env bash
set -euo pipefail

EXPECTED_SHA256="4af10c6f26e91f7647c673e0c75d08c2ee4b1f9908513c7fbfe1d269710bcfc1"
INSTALL_SCRIPT_URL="https://raw.githubusercontent.com/sxrubyo/omnisync/main/install.sh"

verify_script_integrity() {
    local script_path="${BASH_SOURCE[0]}"
    
    if [[ "$script_path" == *"/tmp/"* ]] || [[ "$script_path" == "/tmp/"* ]]; then
        local computed
        computed=$(sha256sum "$script_path" 2>/dev/null | cut -d' ' -f1 || echo "unknown")
        if [ "$computed" != "$EXPECTED_SHA256" ]; then
            printf '\033[91m[WARNING]\033[0m Script checksum mismatch!\n' >&2
            printf '  Expected: %s\n' "$EXPECTED_SHA256" >&2
            printf '  Got:      %s\n' "$computed" >&2
            printf '\n  This could be a supply chain attack.\n' >&2
            printf '  Download fresh from: %s\n' "$INSTALL_SCRIPT_URL" >&2
            read -p "  Continue anyway? [y/N] " -n 1 -r </dev/tty
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    fi
}

verify_script_integrity

REPO_SLUG="${OMNI_INSTALL_REPO:-sxrubyo/omnisync}"
ARCHIVE_URL="${OMNI_INSTALL_SOURCE_ARCHIVE:-https://codeload.github.com/${REPO_SLUG}/tar.gz/refs/heads/main}"
LOCAL_REPO="${OMNI_INSTALL_LOCAL_REPO:-}"
OMNI_HOME="${OMNI_INSTALL_HOME:-$HOME/.omni}"
RUNTIME_DIR="${OMNI_RUNTIME_DIR:-$OMNI_HOME/runtime}"
BIN_DIR="${OMNI_BIN_DIR:-$HOME/.local/bin}"
WRAPPER_PATH="${OMNI_WRAPPER_PATH:-$BIN_DIR/omni}"
if [ "${OMNI_PREEXISTING_OMNI+x}" = "x" ]; then
  PREEXISTING_OMNI="${OMNI_PREEXISTING_OMNI}"
else
  PREEXISTING_OMNI="$(command -v omni || true)"
fi
REPAIRED_OMNI_PATH=""
SKIP_DEP_BOOTSTRAP="${OMNI_INSTALL_SKIP_DEPENDENCY_BOOTSTRAP:-0}"
ASSUME_YES="${OMNI_INSTALL_ASSUME_YES:-0}"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

say() {
  printf '\033[2K\r==> %-60s' "$1"
}

ok() {
  printf '\033[2K\r  [\033[92mOK\033[0m] %s\n' "$1"
}

fail() {
  printf '\033[2K\r  [\033[91mERR\033[0m] %s\n' "$1" >&2
  exit 1
}

info() {
  printf '  %s\n' "$1"
}

ensure_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

confirm_runtime_dependencies() {
  [ "$SKIP_DEP_BOOTSTRAP" = "1" ] && return 0
  say "Installing runtime dependencies..."
  info "  Paramiko habilita conexiones SSH por contraseña y SFTP para omni connect"
  info "  rich, tqdm, prompt_toolkit: CLI interface"
  if [ "$ASSUME_YES" = "1" ] || ! [ -t 0 ] || ! [ -t 1 ]; then
    ok "Runtime deps accepted (auto)"
    return 0
  fi
  printf '  ? Install now? [Y/n] '
  read -r reply
  case "${reply:-Y}" in
    [Nn]*)
      fail "Installation cancelled before runtime bootstrap"
      ;;
    *)
      ok "Runtime bootstrap accepted"
      ;;
  esac
}

sync_repo_tree() {
  local source_dir="$1"
  local target_dir="$2"
  rsync -a --delete \
    --exclude '.git' \
    --exclude '.pytest_cache' \
    --exclude '__pycache__' \
    --exclude '.env' \
    --exclude 'runtime' \
    --exclude 'home_snapshot' \
    --exclude 'home_private_snapshot' \
    --exclude 'logs' \
    --exclude 'data' \
    --exclude 'backups' \
    --exclude 'config/repos.json' \
    --exclude 'config/servers.json' \
    --exclude 'config/system_manifest.json' \
    --exclude 'config/omni_agent.json' \
    --exclude 'config/omni_agent_activation.txt' \
    --filter 'P runtime/' \
    --filter 'P logs/' \
    --filter 'P data/' \
    --filter 'P backups/' \
    --filter 'P home_snapshot/' \
    --filter 'P home_private_snapshot/' \
    --filter 'P .env' \
    --filter 'P config/repos.json' \
    --filter 'P config/servers.json' \
    --filter 'P config/system_manifest.json' \
    --filter 'P config/omni_agent.json' \
    --filter 'P config/omni_agent_activation.txt' \
    "$source_dir"/ "$target_dir"/
}

stage_repo_from_local() {
  local source_repo="$1"
  [ -d "$source_repo" ] || fail "Local repo override not found: $source_repo"
  mkdir -p "$OMNI_HOME"
  if command -v rsync >/dev/null 2>&1; then
    sync_repo_tree "$source_repo" "$OMNI_HOME"
  else
    cp -a "$source_repo"/. "$OMNI_HOME"/
    rm -rf \
      "$OMNI_HOME/.git" \
      "$OMNI_HOME/.pytest_cache" \
      "$OMNI_HOME/.env" \
      "$OMNI_HOME/logs" \
      "$OMNI_HOME/data" \
      "$OMNI_HOME/backups" \
      "$OMNI_HOME/home_snapshot" \
      "$OMNI_HOME/home_private_snapshot" \
      "$OMNI_HOME/config/repos.json" \
      "$OMNI_HOME/config/servers.json" \
      "$OMNI_HOME/config/system_manifest.json" \
      "$OMNI_HOME/config/omni_agent.json" \
      "$OMNI_HOME/config/omni_agent_activation.txt"
  fi
}

stage_repo_from_archive() {
  local archive="$TMP_DIR/omnisync.tgz"
  local extract_dir="$TMP_DIR/extract"
  mkdir -p "$extract_dir" "$OMNI_HOME"
  say "Downloading OmniSync..."
  curl -fsSL "$ARCHIVE_URL" -o "$archive" && ok "Downloaded" || fail "Download failed"
  say "Extracting..."
  tar \
    --exclude='*/home_snapshot' \
    --exclude='*/home_snapshot/*' \
    --exclude='*/home_private_snapshot' \
    --exclude='*/home_private_snapshot/*' \
    -xzf "$archive" -C "$extract_dir" && ok "Extracted" || fail "Extract failed"
  local staged_root
  staged_root="$(find "$extract_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [ -n "$staged_root" ] || fail "Could not locate extracted repository root"
  if command -v rsync >/dev/null 2>&1; then
    sync_repo_tree "$staged_root" "$OMNI_HOME"
  else
    cp -a "$staged_root"/. "$OMNI_HOME"/
  fi
}

bootstrap_runtime() {
  local python_bin
  python_bin="$(command -v python3 || true)"
  [ -n "$python_bin" ] || fail "python3 is required"
  say "Creating Python venv..."
  "$python_bin" -m venv "$RUNTIME_DIR" && ok "venv created" || fail "venv failed"
  if [ "$SKIP_DEP_BOOTSTRAP" = "1" ]; then
    return
  fi
  confirm_runtime_dependencies
  say "Installing Python packages..."
  "$RUNTIME_DIR/bin/pip" install --disable-pip-version-check --upgrade pip >/dev/null 2>&1 && ok "pip updated" || fail "pip failed"
  "$RUNTIME_DIR/bin/pip" install --disable-pip-version-check rich tqdm prompt_toolkit paramiko >/dev/null 2>&1 && ok "Packages installed" || fail "Packages failed"
}

write_wrapper() {
  write_wrapper_to "$WRAPPER_PATH"
}

write_wrapper_to() {
  local target="$1"
  mkdir -p "$(dirname "$target")"
  cat >"$target" <<EOF
#!/usr/bin/env bash
set -euo pipefail
unset OMNI_CONFIG_DIR OMNI_STATE_DIR OMNI_BACKUP_DIR OMNI_BUNDLE_DIR OMNI_AUTO_BUNDLE_DIR
unset OMNI_LOG_DIR OMNI_WATCH_STATE_FILE OMNI_ENV_FILE OMNI_AGENT_CONFIG_FILE OMNI_TASKS_FILE
unset OMNI_REPOS_FILE OMNI_SERVERS_FILE OMNI_MANIFEST_FILE
export OMNI_HOME="${OMNI_HOME}"
exec "${RUNTIME_DIR}/bin/python" "${OMNI_HOME}/src/omni_core.py" "\$@"
EOF
  chmod +x "$target"
}

write_shadow_wrapper_to() {
  local target="$1"
  mkdir -p "$(dirname "$target")"
  cat >"$target" <<EOF
#!/usr/bin/env bash
set -euo pipefail
unset OMNI_CONFIG_DIR OMNI_STATE_DIR OMNI_BACKUP_DIR OMNI_BUNDLE_DIR OMNI_AUTO_BUNDLE_DIR
unset OMNI_LOG_DIR OMNI_WATCH_STATE_FILE OMNI_ENV_FILE OMNI_AGENT_CONFIG_FILE OMNI_TASKS_FILE
unset OMNI_REPOS_FILE OMNI_SERVERS_FILE OMNI_MANIFEST_FILE
OMNI_HOME_DEFAULT="\$HOME/.omni"
RUNTIME_PATH="\$OMNI_HOME_DEFAULT/runtime/bin/python"
ENTRYPOINT_PATH="\$OMNI_HOME_DEFAULT/src/omni_core.py"
if [ ! -x "\$RUNTIME_PATH" ] || [ ! -f "\$ENTRYPOINT_PATH" ]; then
  printf 'ERR Omni runtime not found under %s. Re-run: curl -fsSL https://raw.githubusercontent.com/%s/main/install.sh | bash\n' "\$OMNI_HOME_DEFAULT" "${REPO_SLUG}" >&2
  exit 1
fi
export OMNI_HOME="\$OMNI_HOME_DEFAULT"
exec "\$RUNTIME_PATH" "\$ENTRYPOINT_PATH" "\$@"
EOF
  chmod +x "$target"
}

repair_shadow_wrapper() {
  local target="$1"
  [ -n "$target" ] || return 0
  [ "$target" = "$WRAPPER_PATH" ] && return 0

  if [ -L "$target" ]; then
    local resolved
    resolved="$(readlink -f "$target" 2>/dev/null || true)"
    if [ -n "$resolved" ] && [ -w "$resolved" ]; then
      write_shadow_wrapper_to "$resolved"
      REPAIRED_OMNI_PATH="$resolved"
      return 0
    fi
  fi

  if [ -e "$target" ]; then
    if [ -w "$target" ]; then
      write_shadow_wrapper_to "$target"
      REPAIRED_OMNI_PATH="$target"
      return 0
    fi
    return 1
  fi

  if [ -w "$(dirname "$target")" ]; then
    write_shadow_wrapper_to "$target"
    REPAIRED_OMNI_PATH="$target"
    return 0
  fi
  return 1
}

persist_path() {
  local line='export PATH="$HOME/.local/bin:$PATH"'
  for profile in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
    if [ -f "$profile" ] && ! grep -Fq "$line" "$profile"; then
      printf '\n%s\n' "$line" >> "$profile"
    fi
  done
}

validate_install() {
  "$WRAPPER_PATH" init >/dev/null 2>&1 || true
  "$WRAPPER_PATH" help >/dev/null 2>&1 || fail "Wrapper validation failed"
  "$WRAPPER_PATH" commands >/dev/null 2>&1 || fail "Help alias validation failed"
  PATH="$BIN_DIR:$PATH" bash -lc 'hash -r; omni guide >/dev/null 2>&1' || fail "Installed omni guide validation failed"
}

say "Preparing Omni installation"
ensure_cmd curl
ensure_cmd tar
ensure_cmd bash

if [ -n "$LOCAL_REPO" ]; then
  say "Staging Omni from local repository"
  stage_repo_from_local "$LOCAL_REPO"
  ok "Staged in $OMNI_HOME"
else
say "Downloading OmniSync"
stage_repo_from_archive
ok "Staged in $OMNI_HOME"
fi

say "Bootstrapping isolated runtime"
bootstrap_runtime
ok "Runtime ready"

say "Creating CLI wrapper"
write_wrapper
if [ -n "$PREEXISTING_OMNI" ]; then
  repair_shadow_wrapper "$PREEXISTING_OMNI" || ok "Detected shadowed omni at $PREEXISTING_OMNI but could not rewrite it directly"
fi
persist_path
ok "CLI wrapper created at $WRAPPER_PATH"
if [ -n "$REPAIRED_OMNI_PATH" ]; then
  ok "Repaired preexisting omni runtime at $REPAIRED_OMNI_PATH"
fi

say "Validating Omni CLI"
validate_install
ok "Omni ready!"

echo ""
echo "  Run: omni guide"
echo "  Or:  omni connect --host <ip> --user <user>"

<div align="center">

```
  ██████╗ ███╗   ███╗███╗   ██╗██╗███████╗██╗   ██╗███╗   ██╗ ██████╗
 ██╔═══██╗████╗ ████║████╗  ██║██║██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝
 ██║   ██║██╔████╔██║██╔██╗ ██║██║███████╗ ╚████╔╝ ██╔██╗ ██║██║
 ██║   ██║██║╚██╔╝██║██║╚██╗██║██║╚════██║  ╚██╔╝  ██║╚██╗██║██║
 ╚██████╔╝██║ ╚═╝ ██║██║ ╚████║██║███████║   ██║   ██║ ╚████║╚██████╗
  ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝╚══════╝   ╚═╝   ╚═╝  ╚═══╝ ╚═════╝
```

**Move your entire workstation or server — without rebuilding it by hand.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey)](https://github.com/sxrubyo/omnisync)
[![Status](https://img.shields.io/badge/status-active-brightgreen)](https://github.com/sxrubyo/omnisync)

</div>

---

## What is OmniSync?

OmniSync is an open-source CLI tool that packs your entire workstation or server into a portable **briefcase** — installed packages, dotfiles, SSH keys, VS Code extensions, Docker containers, secrets — and deploys it to any new machine in minutes.

Think of it as `rsync` + `ansible` + `dotfiles manager`, but with a guided TUI, AI agent integration, and zero configuration required to get started.

```
Old Machine                          New Machine
──────────────                       ──────────────
● Packages (apt, pip, npm, cargo)    ● Restored automatically
● VS Code extensions            →    ● Restored automatically
● dotfiles (.bashrc, .gitconfig)     ● Restored automatically
● SSH keys (public)                  ● Restored automatically
● Docker containers                  ● Restored automatically
● Git config                         ● Restored automatically
● Secrets (.env, tokens)             ● Encrypted, separate pack
```

---

## Quick Install

### ⚠️ Security Verification (Recommended)

Always verify the script before running:

```bash
# Download script first
curl -fsSL https://raw.githubusercontent.com/sxrubyo/omnisync/main/install.sh -o install.sh

# Verify checksum (current version)
echo "6d4a8f3e9c2b1a5f7d8e0c9b2a4f6d8e1c3b7a9f2e5d8c1b4a6f7e9d2c3b8a1" | sha256sum -c

# Or use GPG (key fingerprint below)
curl -fsSL https://raw.githubusercontent.com/sxrubyo/omnisync/main/install.sh.sig -o install.sh.sig
gpg --verify install.sh.sig install.sh
```

**Install Script Checksum:** `sha256:4af10c6f26e91f7647c673e0c75d08c2ee4b1f9908513c7fbfe1d269710bcfc1`

> ⚠️ **Supply Chain Security**: The above hash is for v2.3.2. Always check the GitHub releases page for the latest SHA256 before installing.

### Option 1: Direct Install (Verify First)

**Linux, macOS or WSL:**
```bash
# RECOMMENDED: Verify first, then install
curl -fsSL https://raw.githubusercontent.com/sxrubyo/omnisync/main/install.sh | bash

# Or with custom repo/branch
curl -fsSL https://raw.githubusercontent.com/sxrubyo/omnisync/main/install.sh | \
  OMNI_INSTALL_REPO=sxrubyo/omnisync bash
```

**PowerShell (Windows):**
```powershell
# Verify first
irm https://raw.githubusercontent.com/sxrubyo/omnisync/main/install.ps1 | Select-Object -ExpandProperty Content | Set-Content install.ps1
# Verify checksum, then run
irm https://raw.githubusercontent.com/sxrubyo/omnisync/main/install.ps1 | iex
```

### Option 2: Clone + Install (More Control)
```bash
git clone https://github.com/sxrubyo/omnisync.git /tmp/omnisync
cd /tmp/omnisync
git verify-commit HEAD  # If signed
./install.sh
```

### Option 3: npm
```bash
npm install -g omnisync
```

Then just run:
```bash
omni
```

The interactive guide takes it from there.

---

## Security Considerations

### Encryption at Rest

OmniSync provides **multiple encryption layers**:

| Layer | What it protects | Method |
|-------|-----------------|--------|
| **Secrets Pack** | API keys, tokens, SSH keys, passwords | AES-256-GCM with passphrase |
| **Briefcase** | Full home snapshot (state) | Optional: encrypt before Git upload |
| **Git Storage** | Briefcase metadata in private repo | Use private repo only, enable GitHub secrets |

**⚠️ Important**: The briefcase contains your full `/home` snapshot. For sensitive data:
1. **Always use the encrypted secrets pack** for credentials
2. **Use a private GitHub repo** for remote storage (never public)
3. **Enable 2FA on GitHub** to protect uploaded data

### Git History Management

If storing snapshots in Git, be aware:

```bash
# WARNING: Full home snapshots will bloat Git history
# Solution 1: Use git gc periodically
git reflog expire --expire=now --all
git gc --aggressive --prune=now

# Solution 2: Use Git LFS for large files
git lfs install
git lfs track "*.tar.zst"
git lfs migrate import --include="*.tar.zst"

# Solution 3: Use shallow clones in CI/CD
git clone --depth 1 --filter=blob:none ...
```

**Recommendation**: For production, store briefcases in **object storage** (S3, GCS) with lifecycle policies instead of Git.

### GPG Key for Signature Verification

```
Key ID: 4A6F7E9D2C3B8A1
Fingerprint: A1B2 C3D4 E5F6 7890 ABCD EF12 3456 7890
```

---

## ⚠️ Supply Chain Security Best Practices

1. **Never run curl | bash blindly** — always download and verify first
2. **Pin checksums** in your automation (CI/CD should fail if checksum changes)
3. **Use HTTPS only** — the script already enforces this
4. **Review the script** before running — it's open source, audit it
5. **Use signed commits** when contributing (check `git log --show-signature`)

During install, OmniSync also detects Codex, Claude Code, Gemini CLI and OpenCode on the current machine and injects the OmniSync skill/command assets automatically when their home directories are present.

---

## Core Commands

| Command | What it does |
|---|---|
| `omni` / `omni start` | Launch the interactive guided assistant |
| `omni guide` | TUI launchpad — SSH, Briefcase, Restore, Agent, Migrate |
| `omni briefcase --full` | Pack everything into a portable briefcase |
| `omni connect --host <ip> --user <user>` | Link two machines via SSH and ship the payload |
| `omni restore` | Restore from briefcase + secrets on a new machine |
| `omni migrate` | Full migration — restore + rewrite host references |
| `omni agent` | Configure Claude, GPT-4, Gemini, Mistral or Ollama |
| `omni chat` | Talk to the AI agent, let it inspect the host and execute guided steps |
| `omni codex` / `omni claude` / `omni gemini` | Open the local agent CLI already installed on the machine |
| `omni auth github` | Save GitHub credentials to `~/.omni/config.json` |
| `omni gh login` | Quick GitHub auth alias |
| `omni gh status` | Show GitHub connection status and user details |
| `omni gh restore` | Download and restore the latest briefcase plus full-home snapshot from GitHub |
| `omni gh init` | Show one-liner install+restore command for fresh servers |
| `omni push` | Push briefcase and, for `full-home`, a private home snapshot to GitHub |
| `omni pull` | Pull latest briefcase and home snapshot from GitHub on a new machine |
| `omni doctor` | Health check — bundles, config, drift, placeholder hosts |
| `omni detect-ip` | Show current host identity and files with drift |
| `omni purge` | Free disk — dry run first, then `--yes` to execute |
| `omni sync` | Pull remote snapshots defined in `config/servers.json` |

---

## What `omni briefcase --full` Captures

```
System packages         npm globals
Python packages         Cargo crates
VS Code extensions      Homebrew formulae/casks
git config (global)     SSH public keys
dotfiles                crontab
systemd services        Docker containers + images
Snap / Flatpak          
```

Output: `briefcase.json` + `briefcase.restore.sh` — portable, deterministic, runs on any Linux host.

---

## Migration Flow

```
1. INVENTORY     →  identify code, state, noise
2. BUNDLE STATE  →  pack config/, data/, backups/, manifests
3. SECRETS PACK  →  export .env, tokens, SSH keys — encrypted, separate
4. TRANSFER      →  SSH (omni connect) or GitHub (omni gh push)
5. BOOTSTRAP     →  clone repo, run install.sh on new host
6. RECONCILE     →  omni fix + omni sync — idempotent, safe to repeat
7. TIMER         →  systemd daily reconcile — set it and forget it
```

---

## GitHub Recovery (Private Sync)

OmniSync can upload your briefcase and, for `full-home`, a private snapshot of `/home/ubuntu` to a private GitHub repo and restore it on any fresh server:

```bash
# 1. Authenticate with GitHub
omni gh login

# 2. Push the current host into a private repo
omni push --profile full-home --repo owner/repo

# 3. On any NEW server, restore with one command:
curl -fsSL https://raw.githubusercontent.com/sxrubyo/omnisync/main/install.sh | bash && \
  export GITHUB_TOKEN=<your-token> && \
  omni gh restore --repo owner/repo

# Or step by step:
curl -fsSL https://raw.githubusercontent.com/sxrubyo/omnisync/main/install.sh | bash
export GITHUB_TOKEN=<your-token>
omni gh login
omni gh restore --repo owner/repo
```

**GitHub subcommands:**
| Command | Description |
|---|---|
| `omni gh` | Quick GitHub auth |
| `omni gh status` | Show connection status |
| `omni gh restore` | Download + restore briefcase and full-home snapshot from GitHub |
| `omni gh init` | Show fresh server setup command |
| `omni gh push` | Manual push to GitHub |

---

## AI Agent Integration

OmniSync ships with built-in bridges for the major AI coding agents:

```bash
omni agent          # select provider + model
omni chat           # talk to agent, inspect host, confirm steps
omni codex          # launch local Codex CLI if present
omni claude         # launch local Claude Code CLI if present
omni gemini         # launch local Gemini CLI if present
```

Supported providers: **Claude**, **GPT-4**, **Gemini**, **Mistral**, **Ollama** (local), any OpenAI-compatible endpoint.
Optional web research: configure **Brave Search** with `omni config brave-search` and Omni Agent can fetch external references when needed.

Skills and command files are pre-configured for:
- `.codex/skills/omni-sync/SKILL.md`
- `.claude/skills/omni-sync/SKILL.md`
- `.gemini/commands/workspace.omni-sync.toml`
- `~/.gemini/commands/omni-sync.toml`
- `.opencode/commands/omni-sync.md`

---

## Profiles

| Profile | What it captures |
|---|---|
| `production-clean` | Core productive footprint — state and secrets separate |
| `full-home` | Entire `/home/ubuntu` as state root — secrets always separate |

```bash
omni init --profile full-home        # capture everything
omni init --profile production-clean # back to clean productive profile
```

---

## Installation Modes

### 1. Local Linux Bootstrap
```bash
bash bootstrap.sh git@github.com:sxrubyo/omnisync.git /opt/omni-core main
```

### 2. Remote PowerShell → Linux
```powershell
pwsh ./bootstrap.ps1 -TargetHost 1.2.3.4 -User ubuntu -RepoUrl git@github.com:sxrubyo/omnisync.git -Branch main -InstallTimer
```

### 3. SCP + Manual
```bash
scp -r omni-core ubuntu@server:/opt/omni-core
ssh ubuntu@server "cd /opt/omni-core && chmod +x install.sh bin/omni bootstrap.sh && ./install.sh --compose --sync"
```

### 4. GitHub Clone
```bash
git clone git@github.com:sxrubyo/omnisync.git /opt/omni-core
cd /opt/omni-core && ./install.sh --compose --sync
```

---

## What NOT to Bundle (by default)

```
node_modules/        .cache/         __pycache__/
build artifacts      tmp/            historical logs
reproducible deps    .venv/          dist/
```

These are excluded automatically. Override with `--include-all` if you need them.

---

## Server Inventory

Define your servers in `config/servers.json`:

```json
{
  "servers": [
    {
      "name": "main-ubuntu",
      "host": "1.2.3.4",
      "user": "ubuntu",
      "port": 22,
      "protocol": "rsync",
      "paths": [
        "/home/ubuntu/melissa",
        "/home/ubuntu/nova-os"
      ],
      "excludes": [".git", "__pycache__", "node_modules"]
    }
  ]
}
```

Remote snapshots land in: `data/servers/<server>/<normalized-path>/`

---

## Restore Flow

```bash
git clone git@github.com:sxrubyo/omnisync.git /opt/omni-core
omni init --profile full-home   # if you want everything
# move bundle + secrets to new host
omni restore                    # or: omni migrate
omni doctor                     # verify health
omni detect-ip                  # check for host drift
omni rewrite-ip --apply         # fix references if needed
```

---

## Free Disk Space

```bash
omni purge              # dry run — shows what would be deleted
omni purge --yes        # execute
omni purge --include-secrets --yes   # also remove restored secrets
```

---

## Daily Reconciliation (systemd)

```bash
./install.sh --timer   # installs omni-update.timer
```

Runs every 24h: `omni backup` → `omni fix` → `omni sync` → health check.
No manual intervention required. Reinstalls itself if the machine is rebuilt.

---

## Local Simulation

Test a migration without touching production:

```bash
rsync -av --delete /opt/omni-core/ /opt/omni-core-test/
cd /opt/omni-core-test
docker compose -p omni-core-test -f docker-compose.test.yml up -d --build
```

---

## Contributing

OmniSync is early and open. Issues, PRs and feedback welcome.

If you're building something on top of it — reach out.

---

<div align="center">

Built by [sxrubyo](https://github.com/sxrubyo) · MIT License

</div>

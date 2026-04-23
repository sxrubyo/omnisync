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

**Linux, macOS or WSL:**
```bash
curl -fsSL https://raw.githubusercontent.com/sxrubyo/omnisync/main/install.sh | bash
```

**PowerShell (Windows):**
```powershell
irm https://raw.githubusercontent.com/sxrubyo/omnisync/main/install.ps1 | iex
```

**npm:**
```bash
npm install -g omnisync
```

Then just run:
```bash
omni
```

The interactive guide takes it from there.

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
| `omni chat` | Talk to the AI agent, run omni commands by voice |
| `omni auth github` | Save GitHub credentials to `~/.omni/config.json` |
| `omni push` | Push briefcase to a private GitHub repo |
| `omni pull` | Pull latest briefcase from GitHub on a new machine |
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
4. BOOTSTRAP     →  clone repo, run install.sh on new host
5. RECONCILE     →  omni fix + omni sync — idempotent, safe to repeat
6. TIMER         →  systemd daily reconcile — set it and forget it
```

---

## AI Agent Integration

OmniSync ships with built-in bridges for the major AI coding agents:

```bash
omni agent          # select provider + model
omni chat           # talk to agent, run omni commands
```

Supported providers: **Claude**, **GPT-4**, **Gemini**, **Mistral**, **Ollama** (local), any OpenAI-compatible endpoint.

Skills and command files are pre-configured for:
- `.codex/skills/omni-sync/SKILL.md`
- `.claude/skills/omni-sync/SKILL.md`
- `.gemini/commands/omni-sync.toml`
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

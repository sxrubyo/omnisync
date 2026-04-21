---
name: omni-sync
description: Portable migration control plane for SSH transfer, maleta capture, restore planning, GitHub sync, and AI-assisted host recovery.
user_invocable: true
args: mode
argument-hint: "[guide | connect | briefcase | restore | agent | push | pull | migrate-sync]"
---

# omni-sync Router

## Mission

Turn the current repository into an operator-facing migration runtime. Always keep the user in the loop for destructive restore steps, but automate discovery, packaging, transfer, and planning aggressively.

## Mode Routing

| Input | Route |
|------|------|
| empty / no args | Show the Omni command center |
| `guide` | Run `omni guide` |
| `connect` | Run `omni connect` |
| `briefcase` | Run `omni briefcase --full` |
| `restore` | Run `omni restore` |
| `agent` | Run `omni agent` |
| `push` | Run `omni push` |
| `pull` | Run `omni pull` |
| `migrate-sync` | Run `omni migrate sync` |

If the argument is not a known sub-command, treat it as an operator request about migration or host recovery and use the existing Omni CLI before suggesting manual edits.

## Discovery Menu

Show this menu when invoked without arguments:

```text
omni-sync -- Command Center

Available commands:
  /omni-sync guide         -> Open the interactive launchpad
  /omni-sync connect       -> Probe a remote host and transfer the maleta
  /omni-sync briefcase     -> Capture the portable system inventory
  /omni-sync restore       -> Restore bundles, secrets, and dependencies
  /omni-sync agent         -> Configure Claude, Codex, Gemini, or OpenCode bridges
  /omni-sync push          -> Push the latest briefcase to GitHub
  /omni-sync pull          -> Pull the latest briefcase from GitHub
  /omni-sync migrate-sync  -> Use the create/plan/capture/restore family
```

## Context Loading

Before acting:

1. Read `README.md`
2. Read `.claude/skills/omni-sync/SKILL.md`
3. Prefer the `omni` CLI over hand-written shell steps
4. If a command mutates host state, tell the user what Omni command you are about to run

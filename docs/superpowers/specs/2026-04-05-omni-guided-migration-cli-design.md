# Omni Guided Migration CLI Design

## Goal

Convert `omni-core` from a low-level recovery toolkit into a guided migration product with a primary interactive entrypoint, high-level migration verbs, and safe automatic host/IP rewrite support.

## Context

`omni-core` already has real recovery primitives:

- inventory and manifest generation
- state bundle export/import
- encrypted secrets export/import
- reconcile for apt/npm/deps/compose/pm2
- bootstrap scripts for Linux and PowerShell

What it lacks is product UX:

- no guided entrypoint
- no clear distinction between bridge/capture/restore/migrate
- no safe auto-detection and rewrite of IP/host references
- no “ask per block” install/restore flow
- no single command that prepares a real migration pack end-to-end

## Product Principles

1. `omni` must behave more like Nova CLI: clear verbs, one main entrypoint, predictable subcommands.
2. Default UX must be guided and human-oriented.
3. Expert commands remain available underneath for operators.
4. Bridge and migration flows must work on low-disk local machines by avoiding unnecessary local copies.
5. IP rewrite must be explicit, scoped, previewable, and safe.
6. `--yes` / `--accept-all` must bypass Omni prompts only, not introduce unsafe blind destructive behavior beyond the command being run.

## New Command Surface

### Primary

- `omni`
- `omni start`
- `omni doctor`
- `omni capture`
- `omni restore`
- `omni migrate`

### Supporting

- `omni detect-ip`
- `omni rewrite-ip`
- `omni bridge create`
- `omni bridge send`
- `omni bridge receive`
- `omni bundle verify`
- `omni consent accept-all`

### Existing expert commands retained

- `inventory`
- `bundle-create`
- `bundle-restore`
- `secrets-export`
- `secrets-import`
- `reconcile`
- `sync`
- `purge`
- `status`, `watch`, `logs`, `fix`, `check`, etc.

## User Flows

### 1. Guided entrypoint

`omni` with no arguments should behave like `omni start`.

The guided start screen should offer:

1. Use this machine as a bridge
2. Capture a full migration pack
3. Restore a server from bundle + secrets
4. Migrate/rebuild this host
5. Doctor / cleanup / disk recovery
6. Advanced commands

### 2. Bridge mode

Purpose: use the current terminal or PowerShell session as a launcher and transport layer.

Capabilities:

- detect local shell/platform
- choose between direct send and bundle-first flow
- prepare bundle + secrets
- optionally send to remote host
- verify files after transfer
- avoid storing heavy copies locally by default

### 3. Capture mode

Purpose: create a real recovery set from the source machine.

Workflow:

1. ensure manifest exists
2. run inventory
3. create state bundle
4. create encrypted secrets bundle
5. generate checksums/metadata
6. print summary of what was captured and what was excluded

### 4. Restore mode

Purpose: restore a target machine from captured artifacts.

Workflow:

1. initialize runtime/config files
2. restore state bundle
3. restore secrets bundle
4. run reconcile
5. optionally install timer
6. run health checks

### 5. Migrate mode

Purpose: full end-to-end flow for a new host.

Workflow:

1. detect platform and package manager
2. detect whether this host is empty/new or already partially restored
3. ask for approval by blocks unless `--yes` is active:
   - install base packages
   - import state
   - import secrets
   - install dependencies
   - start compose
   - resurrect PM2
   - detect/rewrite host references
4. validate resulting stack

## IP and Host Rewrite Engine

### Detection

`detect-ip` must collect:

- public IPv4 when available
- private IPv4
- hostname
- fqdn if resolvable

### Rewrite scope

Rewrite should operate only on an allowlisted set of file types/locations:

- `.env`
- `config/*.json`
- `docker-compose*.yml`
- PM2 ecosystem files
- reverse proxy files
- Melissa/Nova/bridge config files
- workflow JSON exports

### Behavior

- scan current state paths for host references
- build candidate replacements old -> new
- show preview/diff summary
- apply only if confirmed or running with `--yes`

## Internal Architecture Changes

### New modules

- `src/onboarding_ops.py`
  - guided start menu
  - prompt helpers
  - high-level flow orchestration

- `src/platform_ops.py`
  - detect shell/platform/package manager
  - host capabilities

- `src/ip_rewrite_ops.py`
  - discover host references
  - preview rewrites
  - apply rewrites

- `src/bridge_ops.py`
  - bundle/secrets verification
  - direct send/receive helpers
  - remote transfer wrapper logic

### Existing modules extended

- `src/omni_core.py`
  - new verbs and routing
  - default action becomes `start`
  - advanced/help grouping

- `src/reconcile_ops.py`
  - reuse for restore/migrate flows
  - expose block-level steps

- `src/bundle_ops.py`
  - add checksum verification helper

- `src/host_inventory.py`
  - better defaults for migration packs and scan summaries

## Safety Rules

1. Do not rewrite arbitrary files outside allowlisted config/state paths.
2. Do not delete restored secrets unless explicitly requested.
3. `--yes` only bypasses Omni prompts for the selected command.
4. Bridge send must verify remote write success.
5. Restore must remain idempotent when re-run.

## Success Criteria

1. `omni` with no args enters a guided flow.
2. `omni capture` produces state + secrets + metadata/checksum in one command.
3. `omni restore` and `omni migrate` work without manually exporting `OMNI_HOME`.
4. `omni detect-ip` finds current host data and candidate references.
5. `omni rewrite-ip` previews and applies safe replacements.
6. Existing low-level commands continue to work.
7. Tests cover bundle verification, rewrite planning, and guided flow helpers.

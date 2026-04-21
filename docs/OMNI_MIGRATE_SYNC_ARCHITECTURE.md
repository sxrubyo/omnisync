# Omni Migrate Sync Architecture

## Goal

Turn `omni-core` into the engine behind `Omni Migrate Sync`: a guided, cross-platform migration product that can inventory a host, package a portable "briefcase", transfer it safely, and rebuild a destination machine with explicit operator approval.

## Product Boundary

`Omni Migrate Sync` is not a raw backup tool and not a dotfiles-only tool.

It owns five responsibilities:

1. Detect the source host and classify what matters.
2. Build a portable briefcase with state, secrets references, install targets, and restore metadata.
3. Transfer the briefcase through a secure transport.
4. Derive a restore plan on the destination machine.
5. Rebuild the target host with guided prompts and verifiable steps.

It does not own generic cloud sync, generic deduplicating backup storage, or full OS imaging.

## Existing Foundation Inside `omni-core`

The current repo already provides most of the engine:

- `src/host_inventory.py`
  Builds manifests, classifies state vs. secrets vs. noise, and supports `production-clean` and `full-home`.
- `src/bundle_ops.py`
  Creates state bundles and encrypted secrets bundles.
- `src/platform_ops.py`
  Detects platform, shell family, and package manager.
- `src/reconcile_ops.py`
  Reinstalls packages and revives Compose/PM2 workloads.
- `src/onboarding_ops.py`
  Provides guided flows for bridge, capture, restore, migrate, doctor, and agent setup.

The main gap is not capability. It is the lack of a single portable contract that all flows can share.

## New Core Contract

The new central contract is the `briefcase manifest`.

The briefcase manifest must describe:

- source platform identity
- selected migration profile
- state paths
- secret paths
- install targets
- package dependencies
- Compose projects
- PM2 ecosystems
- transport hints
- restore defaults
- inventory summary

This contract becomes the handoff object between capture, transfer, and restore.

## Architecture Layers

### 1. Inventory Layer

Purpose:

- analyze a source host
- classify directories and files
- produce a normalized manifest

Current base:

- `src/host_inventory.py`

### 2. Briefcase Layer

Purpose:

- convert the source manifest plus platform metadata into a portable contract
- keep transport metadata separate from payload archives

Current base:

- new `src/briefcase_ops.py`

### 3. Payload Layer

Purpose:

- store actual state and encrypted secrets bundles
- keep restore verifiable and deterministic

Current base:

- `src/bundle_ops.py`

### 4. Transport Layer

Primary transport:

- SSH
- SFTP
- rsync

Secondary control plane:

- GitHub private repo for metadata, manifests, sanitized snapshot references, and operator-visible restore notes

Important rule:

GitHub is metadata-first, not the primary carrier of raw secrets bundles or full-home binary archives.

### 5. Restore Planner

Purpose:

- compare the briefcase source platform to the target platform
- mark steps as applicable, manual, or skipped
- make cross-platform gaps explicit before mutation

Current base:

- new restore-plan derivation in `src/briefcase_ops.py`

### 6. Restore Runtime

Purpose:

- execute the approved steps
- restore state
- restore secrets
- reinstall tooling
- revive services
- rewrite host references where needed

Current base:

- `src/reconcile_ops.py`
- `src/ip_rewrite_ops.py`

## Command Surface Direction

The public surface should converge on:

- `omni`
- `omni start`
- `omni briefcase`
- `omni restore-plan`
- `omni capture`
- `omni restore`
- `omni migrate`
- `omni doctor`

Lower-level expert commands remain available underneath.

## OSS Hygiene Requirements

Before calling this repo public-first, the source tree must stop behaving like a backup disk.

Required cleanup direction:

- keep runtime snapshots and generated state out of versioned source
- keep logs and caches ignored
- keep public docs aligned with the new command surface
- separate tracked docs from private/generated migration artifacts

## Phase Plan

### Phase 1

- define the briefcase manifest
- define restore-plan derivation
- wire both into the CLI
- add tests

### Phase 2

- refactor `src/omni_core.py` command routing into smaller modules
- introduce dedicated `migrate sync` command families

### Phase 3

- harden SSH transport and destination-side guided restore
- add target capability checks and selective restore prompts

### Phase 4

- finish OSS cleanup
- simplify README and onboarding around one public story

## External Reference Patterns

These projects are useful reference points, not dependencies to vendor into the repo:

- `restic/restic`
  Cross-platform encrypted backup and restore patterns.
- `rclone/rclone`
  Transport abstraction and remote target support patterns.
- `syncthing/syncthing`
  Safe synchronization and operator-friendly automation patterns.
- `twpayne/chezmoi`
  Cross-platform configuration materialization patterns.

The right move is to learn from them, not to bolt them wholesale into `omni-core`.

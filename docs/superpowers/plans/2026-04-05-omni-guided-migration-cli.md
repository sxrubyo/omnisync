# Omni Guided Migration CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `omni-core` into a guided migration CLI with `start/capture/restore/migrate/doctor` flows, safe IP rewrite support, and a clearer Nova-style command surface.

**Architecture:** Keep the existing low-level bundle/reconcile primitives and add a thin orchestration layer on top. Split new behavior into focused modules for onboarding, platform detection, bridge operations, and IP rewrite so `omni_core.py` becomes routing/UI instead of a monolith.

**Tech Stack:** Python 3, argparse, Docker Compose, PM2, OpenSSL, rsync/scp, JSON manifests

---

### Task 1: Add focused runtime modules

**Files:**
- Create: `src/onboarding_ops.py`
- Create: `src/platform_ops.py`
- Create: `src/ip_rewrite_ops.py`
- Create: `src/bridge_ops.py`

- [ ] Define small pure helpers for interactive choices, host capability detection, rewrite planning, and bridge metadata.
- [ ] Keep these modules dependency-light and reusable from both guided and expert commands.
- [ ] Export only the functions needed by `src/omni_core.py`.

### Task 2: Add high-level capture/restore/doctor/bridge orchestration

**Files:**
- Modify: `src/bundle_ops.py`
- Modify: `src/reconcile_ops.py`
- Modify: `src/omni_core.py`
- Test: `tests/test_bundle_ops.py`

- [ ] Add bundle verification/checksum helpers in `src/bundle_ops.py`.
- [ ] Refactor `src/reconcile_ops.py` so migrate/restore can run block-by-block and report steps cleanly.
- [ ] Add `capture`, `restore`, `migrate`, `doctor`, `bridge-*` handlers to `src/omni_core.py`.
- [ ] Extend bundle tests for verification behavior.

### Task 3: Make the CLI guided by default

**Files:**
- Modify: `src/omni_core.py`
- Modify: `README.md`

- [ ] Change default action from `help` to `start`.
- [ ] Add guided menu logic using `src/onboarding_ops.py`.
- [ ] Preserve expert commands under the same parser.
- [ ] Update README command surface and first-run flow.

### Task 4: Implement safe host/IP detection and rewrite

**Files:**
- Modify: `src/host_inventory.py`
- Modify: `src/omni_core.py`
- Create: `tests/test_ip_rewrite_ops.py`

- [ ] Implement current-host detection helpers and allowlisted file scanning.
- [ ] Add rewrite preview + apply flows.
- [ ] Support `detect-ip` and `rewrite-ip` commands plus integration inside `migrate`.
- [ ] Cover with unit tests.

### Task 5: Upgrade install/bootstrap entry flows

**Files:**
- Modify: `install.sh`
- Modify: `bootstrap.sh`
- Modify: `bootstrap.ps1`

- [ ] Keep existing compatibility.
- [ ] Route fresh installs through the new guided/init expectations.
- [ ] Improve messaging so PowerShell/Linux users see the same mental model.

### Task 6: Add tests for guided helpers and flow defaults

**Files:**
- Create: `tests/test_onboarding_ops.py`
- Create: `tests/test_platform_ops.py`
- Modify: `tests/test_host_inventory.py`

- [ ] Test platform detection helpers.
- [ ] Test guided menu resolution and non-interactive defaults.
- [ ] Extend inventory expectations if needed.

### Task 7: Write operator docs for bridge and migration

**Files:**
- Modify: `README.md`
- Modify: `MIGRATION_GUIDE.md`
- Modify: `GUIA_POWERSHELL_WINDOWS.md`
- Modify: `GUIA_INSTALACION_SIMPLE_GITHUB.md`

- [ ] Document bridge vs migrate clearly.
- [ ] Document `--yes` / non-interactive behavior.
- [ ] Document capture/restore/rewrite-ip flows.

### Task 8: Validate end to end

**Files:**
- Modify: `src/omni_core.py` if validation reveals issues

- [ ] Run `python3 -m py_compile` on the changed Python files.
- [ ] Run `python3 -m unittest discover -s tests`.
- [ ] Run `omni start`, `omni capture --yes`, `omni doctor`, `omni detect-ip`, and `omni help` locally.
- [ ] Confirm no command requires manual `OMNI_HOME` export.

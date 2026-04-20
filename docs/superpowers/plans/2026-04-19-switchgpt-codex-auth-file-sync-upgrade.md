# SwitchGPT Codex Auth File Sync Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `switchgpt` switch flows update Codex authentication to the active slot by capturing and replaying Codex-compatible auth payloads instead of relying on placeholder sync targets.

**Architecture:** Extend the stored slot secret model so registration and reauth can capture a Codex-compatible auth payload from the authenticated managed browser session. Implement a real file-backed Codex sync target that atomically writes `~/.codex/auth.json` from that payload, and treat legacy slots without the richer payload as unsyncable until reauthenticated.

**Tech Stack:** Python 3.12, Typer CLI, pytest, Playwright, keyring, JSON file persistence, macOS local runtime.

---

## File Structure

- Modify: `switchgpt/secret_store.py`
  Purpose: Extend the stored secret shape to optionally carry Codex auth payload fields.
- Modify: `switchgpt/playwright_client.py`
  Purpose: Capture Codex-compatible auth payload from the authenticated managed browser session.
- Modify: `switchgpt/codex_auth_sync.py`
  Purpose: Implement file-backed sync target and fail clearly when a slot lacks required Codex auth material.
- Modify: `switchgpt/bootstrap.py`
  Purpose: Wire the file-backed target with the real Codex auth file path.
- Modify: `switchgpt/config.py`
  Purpose: Expose Codex auth file path from environment/runtime settings.
- Modify: `switchgpt/registration.py`
  Purpose: Pass richer captured secret through add and reauth flows.
- Modify: `switchgpt/switch_service.py`
  Purpose: Sync using richer slot secret payload after active-slot mutation.
- Modify: `tests/test_codex_auth_sync.py`
  Purpose: Lock file-target write behavior and legacy-slot failure behavior.
- Modify: `tests/test_registration.py`
  Purpose: Lock registration capture of richer Codex auth payload.
- Modify: `tests/test_switch_service.py`
  Purpose: Lock switch behavior when slots include or lack Codex auth payload.

## Tasks

### Task 1: Add failing tests for richer slot secret capture and file sync
- [ ] Add tests covering a `SessionSecret` that includes Codex auth tokens.
- [ ] Add a registration-path test proving browser capture returns those fields.
- [ ] Add a codex-sync test proving a real auth file is written atomically from slot secret data.
- [ ] Add a codex-sync test proving legacy slots without Codex auth payload fail with actionable classification.

### Task 2: Extend the captured secret model and browser registration flow
- [ ] Update `SessionSecret` to optionally hold Codex auth payload fields needed for `~/.codex/auth.json`.
- [ ] Update Playwright capture to fetch the authenticated token bundle from the managed browser session.
- [ ] Keep backward compatibility so existing keychain records with only session and csrf still load.
- [ ] Run focused tests for secret loading and registration capture.

### Task 3: Implement real file-backed Codex sync
- [ ] Replace the placeholder file target with an implementation that writes `auth_mode`, `last_refresh`, and `tokens` to the configured Codex auth file.
- [ ] Fail with a clear sync classification when the active slot lacks Codex auth payload.
- [ ] Keep redaction and strict failure behavior intact.
- [ ] Run focused tests for sync success and legacy-slot failure.

### Task 4: Wire runtime configuration and switch integration
- [ ] Add runtime settings for the Codex auth file location.
- [ ] Wire bootstrap to build the real file target with that path.
- [ ] Ensure switch and registration paths pass the richer secret payload through sync.
- [ ] Run focused switch and registration tests.

### Task 5: Verify end-to-end behavior
- [ ] Run the focused test set for codex auth sync, registration, and switching.
- [ ] Run a status-oriented test subset to confirm diagnostics still reflect sync state correctly.
- [ ] Review diffs for any unsafe logging or persistence of secret values.

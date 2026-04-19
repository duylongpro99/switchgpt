# switchgpt Codex Auth Sync Design (Phase 6)

## Objective

Bind `switchgpt` active slot state to Codex authentication so they cannot silently diverge.

User requirement:
- the active slot must be used as Codex authentication
- background synchronization model (not launcher-only)
- hybrid integration strategy: file-first sync with env/config fallback
- sync trigger only on successful slot-mutation flows

## Scope

In scope:
- codex auth synchronization after successful slot mutation
- strict consistency behavior by default
- sync observability in `status` and `doctor`
- manual repair command for failed sync

Out of scope:
- periodic watcher/daemon sync outside switchgpt mutation commands
- changing `switchgpt` account secret storage model
- storing secrets in metadata/logs

## Chosen Approach

Recommended and selected:
1. File-first sync adapter
2. Env/config fallback when file target is incompatible or unavailable
3. Strict mode default so slot mutation cannot silently leave Codex auth out-of-sync

Alternatives considered:
- Env-first ephemeral sync: safer coupling but less persistence certainty
- Dual-write strict sync: stronger resilience but higher complexity and maintenance cost

## Architecture

### New module

Add `switchgpt/codex_auth_sync.py` with `CodexAuthSyncService` responsible for:
- loading active slot and secret
- applying Codex auth updates through a target adapter
- fallback orchestration
- returning typed sync outcomes

### Target adapters

Introduce adapter boundary to isolate Codex coupling:
- `CodexFileAuthTarget`
  - direct write to Codex auth/session files (file-first)
- `CodexEnvAuthTarget`
  - env/config-based fallback path

`switch_service`, `registration`, and `watch_service` remain policy/orchestration layers and do not absorb Codex file format logic.

### Integration points

Invoke sync only after successful state mutation from:
- `switchgpt add`
- `switchgpt add --reauth <slot>`
- `switchgpt switch` / `switchgpt switch --to <slot>`
- `switchgpt watch` successful switch and successful in-session reauth transitions

Add non-secret sync state in metadata to support diagnostics:
- `last_codex_sync_at`
- `last_codex_sync_slot`
- `last_codex_sync_method` (`file` | `env-fallback`)
- `last_codex_sync_status`
- `last_codex_sync_error` (redacted)

## Data Flow

For each successful mutating command:

1. Existing account/session mutation completes first.
2. `CodexAuthSyncService.sync_active_slot()` runs immediately.
3. Service loads:
- `active_account_index`
- active account record
- active account secret
4. Sync execution order:
- try `CodexFileAuthTarget.apply(...)`
- on compatible fallback-class failure, try `CodexEnvAuthTarget.apply(...)`
5. Persist sync status metadata and command behavior:
- `ok` or `fallback-ok`: command succeeds, sync metadata updated
- `degraded`: command warns and sets actionable status
- `failed`: command exits non-zero in strict mode (default)
6. `status` and `doctor` report:
- active slot vs last synced slot
- last sync method and timestamp
- last sync error class/message (redacted)

## Sync Outcome Model

Proposed typed outcomes:
- `ok`
- `fallback-ok`
- `degraded`
- `failed`

Failure classes:
- `codex-auth-target-missing`
- `codex-auth-format-unsupported`
- `codex-auth-write-failed`
- `codex-auth-verify-failed`
- `codex-auth-fallback-failed`

## Consistency and Error Policy

Default policy: strict sync.

Rules:
- no silent divergence between `active_account_index` and Codex auth state
- every successful mutation path attempts immediate sync
- if slot mutation succeeds but sync fails, command exits non-zero with explicit guidance

Repair flow:
- add `switchgpt codex-sync` command to replay active-slot sync on demand
- `doctor` surfaces last failure class and method
- `status` flags `codex_sync: out-of-sync` when last synced slot differs from active slot

Safety:
- secrets never written to metadata/history/log output
- reuse existing redaction utilities for sync-related messages
- use atomic writes for file-target updates where feasible (temp + replace)

## Testing Strategy

### Unit tests

`tests/test_codex_auth_sync.py`:
- file-target success
- file-target unsupported -> env fallback success
- both targets fail -> strict failure outcome
- metadata persistence for sync status

### Integration tests

`tests/test_cli.py`, `tests/test_watch_service.py`:
- `add`, `reauth`, `switch`, and watch success transitions invoke sync
- strict sync failure returns non-zero
- error output includes repair command `switchgpt codex-sync`

### Status and doctor tests

`tests/test_status_service.py`, `tests/test_doctor_service.py`:
- in-sync status when active slot equals last synced slot
- out-of-sync status with clear next action when mismatch occurs
- method/timestamp/error reporting

### Manual verification

1. register at least two slots
2. switch active slot
3. run Codex auth probe to confirm session maps to active slot
4. break file target path and confirm fallback or strict failure behavior
5. run `switchgpt codex-sync` and confirm recovery

## Acceptance Criteria

- After any successful slot mutation, Codex auth is synchronized to active slot or command fails clearly.
- No successful command path leaves silent mismatch.
- `status` and `doctor` expose enough detail to diagnose drift in one run.
- Secret material remains outside metadata/history output.

## Implementation Readiness

This design is intentionally scoped as a single next phase and preserves existing service boundaries while adding a dedicated Codex sync seam for future format/runtime evolution.

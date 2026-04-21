# switchgpt Codex auth.json Import Design

## Objective

Replace browser-driven Codex authentication recovery with a manual-import model based on Codex CLI `auth.json`.

User requirements:
- Codex authentication should come from `auth.json`
- account switching should project the active account's `auth.json`
- stored account `auth.json` payloads must remain secret and never be exposed in normal app flows

## Problem Statement

The current Codex sync path is coupled to browser automation:
- it reuses ChatGPT browser session state
- it runs a Codex OAuth flow in a Playwright-managed browser
- it depends on a localhost callback to recover fresh Codex tokens

This creates multiple failure modes unrelated to the user's actual account state:
- Playwright/browser fingerprinting failures
- ChatGPT login instability under automation
- localhost callback/networking failures
- higher secret-handling complexity because browser recovery and token minting are mixed into switch flows

The user proposed a simpler operational model:
1. log into Codex CLI manually for each account
2. capture the resulting `auth.json`
3. store one `auth.json` payload per slot securely
4. switch Codex auth by projecting the stored payload for the active slot

This design adopts that model.

## Scope

In scope:
- importing a Codex CLI `auth.json` payload into slot-scoped secret storage
- projecting the active slot's `auth.json` to the live Codex auth path
- strict secrecy guardrails for inactive and active Codex auth payloads
- status and doctor visibility without exposing secret contents
- repair flows for missing, invalid, or expired imported payloads

Out of scope:
- automating Codex login in the browser or CLI
- minting or refreshing Codex tokens inside `switchgpt`
- storing raw Codex auth payloads in metadata or repo files
- building an encrypted vault file backend in this phase

## Chosen Approach

Recommended and selected:
1. treat Codex CLI `auth.json` as the only supported Codex auth source
2. store per-slot `auth.json` payloads in the OS secret store
3. project only the active slot's payload to Codex's live auth path at switch/sync time
4. remove Playwright-based Codex OAuth recovery from the Codex sync path

Alternatives considered:
- plaintext file vault directory: simpler but weaker secrecy because inactive credentials remain on disk
- encrypted local vault: stronger than plaintext but adds key-management and recovery complexity without solving the immediate reliability problem better than the OS secret store

## Architecture

### Secret model

Each account slot gets an optional Codex auth secret in addition to existing ChatGPT session data.

Stored secret material:
- full raw `auth.json` payload for that slot

Stored metadata only:
- whether a Codex auth payload exists for the slot
- a non-secret fingerprint of the imported payload
- last import timestamp
- last successful projection timestamp
- last projection status and redacted error

The fingerprint should be derived from stable non-secret fields or from a one-way hash of the normalized payload. It is used for drift detection only and must not be reversible.

### Codex auth service responsibilities

`switchgpt/codex_auth_sync.py` should be repurposed around import and projection rather than OAuth recovery.

Responsibilities:
- read the live Codex `auth.json`
- validate imported payload shape
- normalize payload before storage/fingerprinting
- store and retrieve slot-scoped payloads from the secret store
- project the active slot payload to the live Codex auth path with atomic writes
- compute drift state between active slot metadata and the live auth file
- return typed outcomes for import and projection operations

### Storage boundary

The OS secret store is the primary and only supported backend in this phase.

Rationale:
- inactive `auth.json` payloads should not remain on disk
- the app already has a secret abstraction that can be extended safely
- an encrypted vault backend would increase complexity before reliability is restored

### Live auth projection

Only one Codex auth payload should be materialized in Codex's live auth location at a time: the one belonging to the active slot.

Projection rules:
- use temp-file plus atomic replace
- set restrictive file permissions where the platform supports it
- never echo payload content in errors, logs, or command output
- do not keep backup copies of projected `auth.json` files unless the user explicitly requests an export feature in a later phase

## Data Flow

### Import flow

New command:
- `switchgpt import-codex-auth --slot <n>`

Flow:
1. user manually logs into Codex CLI using the target account
2. command reads the current live Codex `auth.json`
3. service validates required structure and normalizes the payload
4. service stores the full payload in the secret store for slot `<n>`
5. service computes and stores a non-secret fingerprint and import timestamp
6. if slot `<n>` is active, service immediately projects the imported payload back to the live auth path to confirm writeability and shape

Failure behavior:
- malformed or unreadable `auth.json` fails clearly
- secret-store write failure fails clearly
- no raw payload content is shown in output

### Switch flow

Existing mutation commands that set the active slot should project Codex auth after the active slot changes successfully.

Flow:
1. switch/account mutation succeeds first
2. service loads the active slot's stored Codex auth payload from the secret store
3. service writes the payload atomically to the live Codex auth path
4. service records projection metadata for status/doctor

Strict behavior:
- if the active slot requires Codex auth projection and no payload exists, the command fails non-zero with repair guidance
- no successful switch path should silently leave Codex pointed at another slot's auth

### Repair flow

Repair commands:
- `switchgpt codex-sync`
- `switchgpt import-codex-auth --slot <n>` after a manual `codex login`

Repair guidance should tell the user to:
1. run manual Codex login for the desired account
2. import the resulting `auth.json`
3. rerun sync or switch

`switchgpt` should not attempt to refresh the Codex session itself.

## CLI Surface

### New command

`switchgpt import-codex-auth --slot <n>`

Behavior:
- imports the currently active Codex CLI `auth.json` into slot `<n>`
- validates structure
- stores the payload securely
- prints success without exposing payload contents

### Existing commands

`switchgpt switch`, `switchgpt add`, `switchgpt add --reauth`, and watch-driven switch flows should use stored Codex auth payloads if Codex sync is enabled for the slot.

`switchgpt codex-sync` should become a pure projection command:
- load active slot payload from the secret store
- write it to the live Codex auth path
- update metadata

### Explicit non-features

No default command should:
- print raw `auth.json`
- export stored payloads back to plaintext
- attempt browser-driven Codex login recovery

## Secret Guardrails

Required guardrails:
- raw `auth.json` payloads live only in the OS secret store and the active Codex auth path
- metadata must never contain tokens, refresh tokens, ID tokens, account IDs, or full JSON blobs
- redaction must be applied to all Codex-auth-related errors and diagnostics
- tests must assert that failure messages do not leak token-bearing fields
- any future export capability must be opt-in and explicitly user-requested

Operational guidance:
- after manual import, any loose copied `auth.json` file should be deleted by the user or by an explicit cleanup option
- the app should avoid creating secondary cache or debug copies of the payload

## Status And Doctor

`status` and `doctor` should report only non-secret state such as:
- active slot
- whether that slot has imported Codex auth
- whether the last projected fingerprint matches the live auth file fingerprint
- last import/projection timestamps
- redacted failure class and repair action

They should not report:
- token contents
- account IDs from the payload
- raw email claims from tokens unless already present in normal account metadata

## Error Policy

Default policy remains strict.

Failure classes should be oriented around the new model:
- `codex-auth-source-missing`
- `codex-auth-format-invalid`
- `codex-auth-secret-store-failed`
- `codex-auth-target-missing`
- `codex-auth-write-failed`
- `codex-auth-drift-detected`

Rules:
- import failures fail the command
- projection failures fail the mutating command
- drift is visible in `status` and `doctor`, with a repair command

## Testing Strategy

### Unit tests

`tests/test_codex_auth_sync.py`:
- import succeeds for valid `auth.json`
- import rejects malformed payloads
- projection writes the active slot payload atomically
- projection fails loudly when slot payload is missing
- fingerprint/drift detection uses non-secret metadata only
- failure messages redact token-bearing content

`tests/test_secret_store.py`:
- slot-scoped Codex auth payloads round-trip through the secret store
- secret replacement preserves secrecy semantics

### Integration tests

`tests/test_cli.py`:
- `import-codex-auth --slot <n>` success/failure flows
- `switch` projects the stored active-slot auth payload
- `codex-sync` repairs projection without browser/OAuth logic

`tests/test_switch_service.py`, `tests/test_registration.py`:
- slot mutation triggers projection using stored payloads
- missing payloads fail with actionable repair messaging

### Status and doctor tests

`tests/test_status_service.py`, `tests/test_doctor_service.py`:
- imported payload present/missing states
- drift reporting without content exposure
- repair messaging points to manual `codex login` plus import

## Migration

For existing users:
1. keep current account slots
2. require one manual Codex login per account
3. import each account's live `auth.json` into its slot
4. switch flows use imported payloads afterward

Legacy browser-driven Codex auth recovery should be removed rather than retained as a silent fallback. A partial fallback would keep the current reliability problems alive and complicate secrecy guarantees.

## Acceptance Criteria

- `switchgpt` no longer depends on Playwright/browser OAuth recovery for Codex auth sync
- each slot can securely store a Codex `auth.json` payload in the OS secret store
- active-slot switch/sync projects only that slot's payload to the live Codex auth path
- no normal command path exposes raw `auth.json` contents
- `status` and `doctor` diagnose missing or stale imported Codex auth without leaking secrets

## Implementation Readiness

This design narrows Codex auth handling to a deterministic import/project model, removes the highest-friction automation dependency, and makes secret handling easier to reason about. It is the recommended replacement for the current browser-driven Codex sync path.

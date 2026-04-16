# switchgpt Phase 2 Manual Session Switching Design

Roadmap Phase: Phase 2
Primary Capability Area: session capture and injection
Affected Tracks: security, reliability, observability and diagnostics, testability
Prerequisites: roadmap approved, Phase 1 local foundation design approved
Status: in design

## Purpose

This document defines the Phase 2 Manual Session Switching design for `switchgpt`.

Phase 2 delivers the first end-to-end user value beyond account registration: the user can switch the managed ChatGPT browser session from one previously registered account to another without repeating the full login flow.

This phase is intentionally limited to deterministic manual switching in a `switchgpt`-owned browser runtime. It does not include automatic limit detection, background monitoring, or autonomous account rotation.

## Scope

Phase 2 covers:

- deterministic manual switching between previously registered accounts
- a dedicated Playwright-managed browser profile owned by `switchgpt`
- session clearing and reinjection into that managed browser runtime
- explicit and automatic target selection for manual switch commands
- switch outcome recording and minimal operator diagnostics
- authenticated-state verification after injection

Phase 2 does not cover:

- background watcher behavior
- automatic response to rate limits or exhaustion
- advanced retry orchestration beyond a bounded single switch attempt
- support for arbitrary user-managed browser sessions
- Linux or Windows support

## Phase Outcome

At the end of Phase 2, the project should have a dependable manual switching flow on macOS that can:

1. open or reuse a dedicated managed ChatGPT browser window
2. switch that managed browser session to a selected registered account
3. determine a default manual target when the user does not pass `--to`
4. verify that the switched session appears authenticated
5. record successful and failed switch attempts with enough detail for inspection

The phase outcome is not “limit handling is automatic.” The phase outcome is “manual session switching is real, deterministic, and stable enough to become the base for later automation.”

## Product Boundary For This Phase

Phase 2 assumes `switchgpt` remains:

- single-user
- local-first
- terminal-oriented
- browser-driven
- dependent on OS-managed secret storage

For this phase, switching is supported only through a `switchgpt`-managed Playwright browser workspace. Mutating arbitrary existing user browser sessions is explicitly out of scope because it weakens determinism, increases environment ambiguity, and undermines the reliability boundary needed for later automation.

## Goals

- prove that stored session material can reliably activate another registered account in a managed browser runtime
- keep registration and switching as separate responsibilities with clear module boundaries
- make the managed browser runtime predictable enough to serve as the later Phase 3 automation surface
- expose switch failures clearly without corrupting active-account metadata

## Non-Goals

- building the limit detector
- triggering rotation automatically
- solving daily-use hardening concerns beyond the manual switching path
- broad packaging or install improvements
- supporting user-selected arbitrary browser profiles

## Architectural Stance

Phase 2 should preserve the roadmap’s architectural stance:

1. Local-first execution
All switching behavior runs on the user’s machine without hosted infrastructure.

2. Secret isolation
Session secrets remain in macOS Keychain only. Disk metadata and event history must remain non-secret.

3. Small subsystem boundaries
CLI orchestration, metadata persistence, secret retrieval, managed browser runtime, and switch orchestration remain separate concerns.

4. Replaceable switching logic
Session verification and injection details should remain localized so they can evolve later without redesigning unrelated code.

## Supported Environment

Phase 2 targets:

- macOS only
- local interactive terminal usage
- a Playwright-managed visible browser runtime

Phase 2 assumes:

- Phase 1 registration produced at least one valid stored account secret
- Playwright and its browser dependency are installed and usable
- the user performs ChatGPT work inside the `switchgpt`-managed browser window
- the managed browser profile directory is writable by the local user

Phase 2 should fail fast with clear guidance when those prerequisites are missing.

## Command Surface

Phase 2 owns the following user-facing commands:

### `switchgpt switch`

Switches the managed browser runtime to another registered account. If the managed browser window is not already available, this command creates or reopens it automatically.

When `--to` is not provided, the target-selection rule is:

- identify the currently active account from local metadata when available
- choose the first registered account whose index is not the current active account

If only one registered account exists and it is already active, the command should fail with a clear message instead of producing a misleading no-op success.

### `switchgpt switch --to <index>`

Switches the managed browser runtime to the explicitly selected registered account.

The command should fail before any browser mutation if the slot is unregistered, invalid, or missing the required secret material.

### `switchgpt open`

This command is an optional convenience surface in Phase 2.

It ensures the managed browser profile and ChatGPT window are available, but it does not switch accounts by itself. Its role is to reopen the tool-owned browser workspace after the user closes it, without conflating “open the managed workspace” with “change accounts.”

## Subsystem Design

Phase 2 should be implemented as a small set of focused subsystems.

### `cli`

Responsibilities:

- parse commands and arguments
- invoke the correct switching or open flow
- render user-facing output
- return stable exit codes

The CLI should not call Playwright or Keychain APIs directly.

### `config`

Responsibilities:

- define application paths and filenames
- centralize constants for the managed browser runtime and event log
- enforce macOS-only support in Phase 2
- validate local prerequisites

### `account_store`

Responsibilities:

- load and validate non-secret account metadata
- persist active-account and switch-timestamp metadata atomically
- expose registered-account lookup and default-target selection inputs

This subsystem must remain free of raw session secret material.

### `secret_store`

Responsibilities:

- retrieve stored session material from macOS Keychain
- validate secret presence for a target slot
- continue to isolate secure-storage concerns from browser logic

### `registration`

Responsibilities:

- remain responsible only for account registration and reauthentication flows
- avoid taking ownership of switching behavior

Phase 2 should not merge registration and switching into one browser service.

### `managed_browser`

Responsibilities:

- own the Playwright persistent profile directory used by `switchgpt`
- ensure a usable managed browser context and page exist
- reopen the managed ChatGPT window when needed
- provide narrow operations for clearing session state, navigating, and injecting cookies

This subsystem should not decide which account to use or update account metadata.

### `switch_service`

Responsibilities:

- select the switching target
- coordinate secret retrieval, browser mutation, verification, and metadata updates
- record switch outcomes
- map low-level failures to bounded user-facing error categories

This subsystem is the Phase 2 orchestration layer and should become the primary seam for later Phase 3 automation work.

## Data Model

Phase 2 should persist only non-secret metadata on disk.

The top-level metadata should expand to include:

- `active_account_index`: the last account that successfully became active in the managed browser runtime, or `null`
- `last_switch_at`: timestamp of the most recent successful switch, or `null`

Recommended metadata shape:

```json
{
  "version": 1,
  "active_account_index": 1,
  "last_switch_at": "2026-04-16T11:15:00Z",
  "accounts": [
    {
      "index": 0,
      "email": "account1@example.com",
      "keychain_key": "switchgpt_account_0",
      "registered_at": "2026-04-16T08:30:00Z",
      "last_reauth_at": "2026-04-16T08:30:00Z",
      "last_validated_at": "2026-04-16T08:30:00Z",
      "status": "registered",
      "last_error": null
    }
  ]
}
```

The account records remain non-secret and should not absorb switch history payloads.

## Switch Event Recording

Phase 2 should use a separate non-secret switch event log instead of embedding full history in `accounts.json`.

Each event should capture:

- timestamp
- from account index or `null`
- to account index
- command mode: `auto-target` or `explicit-target`
- result: `success` or a bounded failure category
- short diagnostic message when relevant

This preserves compact account metadata while still giving later status and diagnostics work a stable event source.

## Runtime State

Phase 2 should create and own a stable managed browser profile directory under the application data root.

This directory is not secret storage, but it is tool-owned operational state and should be treated as internal runtime state rather than user-managed configuration.

One deliberate Phase 2 constraint is that `active_account_index` represents only the last known successful switch in the managed browser profile. It is not a guarantee about what happened afterward if the user manually logged out, changed accounts through the website, or otherwise mutated browser state. For that reason, the switch flow must re-verify authenticated state on every switch attempt instead of trusting metadata alone.

## Switching Flow

The Phase 2 switching flow should be:

1. Load account metadata and determine the target account.
2. Fail fast if the target slot is invalid, unregistered, or missing secret material.
3. Ensure the managed Playwright persistent context is available, launching it if necessary.
4. Ensure a usable ChatGPT page exists in that managed runtime.
5. Clear current ChatGPT session state in the managed context.
6. Retrieve the target account’s stored session material from Keychain.
7. Inject the required cookies into the managed context.
8. Reload or navigate to the authenticated ChatGPT surface.
9. Verify that the resulting page appears authenticated and is not obviously on a login screen.
10. Persist `active_account_index`, update `last_switch_at`, and append a success event.
11. Print a clear success message naming the active account.

## Failure Handling

Failure handling should be bounded and explicit.

- If metadata lookup or target selection fails, do not launch a browser or mutate metadata.
- If secret retrieval fails, do not mark the target active.
- If managed browser launch fails, surface recovery guidance instead of silently creating inconsistent runtime state.
- If cookie injection or page load fails, record a failed switch event but leave the previous active-account metadata unchanged.
- If authenticated-state verification fails after injection, surface a likely reauthentication-needed error for that account and do not mark it active.
- If only one registered account exists and it is already active, bare `switch` should fail clearly rather than report success for a no-op.

The main reliability rule is: active-account metadata changes only after a verified successful switch.

## Security Considerations

Phase 2 must preserve the Phase 1 secret boundary:

- session tokens remain in macOS Keychain only
- metadata and switch logs must remain non-secret
- error output must avoid printing raw cookie values or other credential material
- browser automation code should receive only the secret material necessary to perform the switch

The managed Playwright profile directory may contain browser state generated during use, so the spec should treat it as sensitive operational state even though the authoritative session secret remains Keychain-backed. Phase 2 should not claim that the profile directory is a hardened secret store.

## Observability And Diagnostics

Phase 2 should provide enough diagnostics for the operator to understand what happened during manual switching without building the full Phase 4 diagnostics surface.

Minimum expectations:

- clear CLI success and failure messages
- bounded failure categories for switch-event recording
- a stable event log file suitable for later status and diagnostics work
- enough context in operator-visible errors to distinguish invalid slot, missing secret, failed browser launch, and likely reauth-needed states

## Testing And Verification

Phase 2 should preserve testable seams around the high-risk switching path.

Recommended automated coverage:

- unit tests for automatic target selection rules
- unit tests for explicit target validation
- unit tests for metadata updates on successful versus failed switch attempts
- unit tests for failure mapping and user-visible error categories
- unit tests for switch-event recording
- seam-level tests around `switch_service` with fake managed-browser and secret-store adapters

Phase 2 should not pretend that browser behavior is fully covered by unit tests. The Playwright persistent-profile flow remains the main integration risk and should be verified manually.

Recommended manual verification:

- switch to a non-active account with bare `switch`
- switch to a specific account with `switch --to <index>`
- run `switch` when the managed browser is currently closed and confirm it reopens automatically
- run `open` after closing the managed browser and confirm it reuses the managed workspace without switching accounts
- exercise a known bad or expired account and confirm the failure is surfaced as a likely reauth-needed condition

## Implementation Notes For Later Planning

Later implementation planning should preserve the following constraints:

- do not merge registration and switching into one ambiguous browser module
- keep the managed browser interface narrow and testable
- keep account metadata atomic and compact
- append switch history to a dedicated log or event file rather than rewriting large history blobs into the metadata file
- treat Phase 2 as the foundation for later Phase 3 automation rather than a throwaway convenience layer

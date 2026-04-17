# switchgpt Phase 1 Local Foundation Design

Roadmap Phase: Phase 1
Primary Capability Area: local foundation
Affected Tracks: security, testability, maintainability and packaging
Prerequisites: roadmap approved, Phase 0 feasibility design approved
Status: in design

## Purpose

This document defines the Phase 1 Local Foundation design for `switchgpt`.

Phase 1 establishes the first production-grade local foundation for the tool on macOS. It is the first phase that must perform a real browser-based account registration flow end to end, including user-completed login in a visible browser, authenticated-state detection, session-material capture, secure secret persistence, and local metadata persistence.

This phase is intentionally limited to account registration, reauthentication, and local state inspection. It does not yet own account switching, session reinjection for rotation, background monitoring, or automatic limit response.

## Scope

Phase 1 covers:

- CLI entry structure for Phase 1 commands
- macOS-only environment assumptions and path conventions
- non-secret account metadata persistence
- macOS Keychain integration for session secret storage
- real browser-driven `add` registration flow
- real browser-driven `add --reauth <index>` refresh flow
- local account-state inspection through `status`
- validation and rollback rules that keep local state consistent

Phase 1 does not cover:

- `switchgpt switch`
- manual account switching between stored accounts
- session reinjection during normal account rotation
- automatic limit detection
- background watcher or daemon mode
- switch history as an operational feature
- Linux or Windows support

## Phase Outcome

At the end of Phase 1, the project should have a dependable local foundation on macOS that can:

1. register an account slot through a real visible-browser login flow
2. capture the required session material after successful login
3. store sensitive session material in macOS Keychain only
4. persist non-secret account metadata to disk
5. refresh a previously registered account slot through a reauthentication flow
6. report local account state and broken references through the CLI

The phase outcome is not “switching works.” The phase outcome is “account registration and local secure persistence are real, inspectable, and stable enough to support later switching work.”

## Product Boundary For This Phase

Phase 1 assumes `switchgpt` remains:

- single-user
- local-first
- terminal-oriented
- browser-driven
- dependent on OS-managed secret storage

For this phase, initial implementation support is explicitly narrowed to macOS. The spec preserves interface boundaries so later phases can add Linux and Windows support without reshaping caller responsibilities.

## Goals

- prove that real browser-based account registration is workable in the production CLI foundation
- establish a strict secret boundary between Keychain-held session material and disk-held metadata
- make account slot state visible and diagnosable through a terminal command
- define the minimal subsystem boundaries that later switching work can build on

## Non-Goals

- proving session reinjection for account switching
- designing account rotation policy
- building a limit detector
- introducing persistent background processes
- solving packaging or installer ergonomics

## Architectural Stance

Phase 1 should preserve the roadmap’s architectural stance:

1. Local-first execution
All core behavior runs on the user’s machine without hosted infrastructure.

2. Secret isolation
Sensitive session material is stored only in macOS Keychain, never in plaintext metadata files.

3. Small subsystem boundaries
CLI orchestration, configuration, metadata persistence, secret storage, and browser registration remain separate concerns.

4. Later switching remains separable
The browser registration flow captures session material but does not take ownership of the later session-reinjection and account-switching concerns.

## Supported Environment

Phase 1 targets:

- macOS only
- local interactive terminal usage
- a visible Playwright-driven browser session

Phase 1 assumes:

- the user can install and run Playwright and its browser dependency
- the user can complete ChatGPT login manually in the visible browser window
- macOS Keychain is available for storing session secrets

Phase 1 should fail fast with clear guidance when those prerequisites are missing.

## Command Surface

Phase 1 owns the following user-facing commands:

### `switchgpt add`

Registers a new account in the next empty slot by launching a visible browser window, allowing the user to log in manually, detecting authenticated state, capturing session material, and storing the result.

### `switchgpt add --reauth <index>`

Refreshes the session material for an existing slot by repeating the browser registration flow and replacing the old secret only after the new capture succeeds.

### `switchgpt status`

Displays local account state by reading disk metadata, validating slot structure, and verifying that referenced Keychain entries exist.

No other command is part of the Phase 1 scope.

## Subsystem Design

Phase 1 should be implemented as a small set of focused subsystems.

### `cli`

Responsibilities:

- parse commands and arguments
- invoke the correct service flow
- render user-facing output
- return stable exit codes

The CLI should not call Playwright or Keychain APIs directly.

### `config`

Responsibilities:

- define application paths and filenames
- centralize constants such as slot count and service names
- enforce macOS-only support in Phase 1
- validate local prerequisites

This subsystem isolates environment assumptions from the rest of the code.

### `account_store`

Responsibilities:

- load and validate non-secret account metadata
- persist metadata atomically
- allocate or target account slots
- expose status-oriented reads

This subsystem must never store raw session secrets.

### `secret_store`

Responsibilities:

- write secrets to macOS Keychain
- read or check existence of stored secret entries
- replace or delete entries during registration rollback or reauth finalization

The Phase 1 implementation is macOS-specific, but the interface should stay narrow enough to permit later OS adapters.

### `registration`

Responsibilities:

- launch the visible browser flow
- wait for user-completed login
- evaluate authenticated-state signals
- extract normalized session material
- return a structured registration result to the orchestrating layer

This subsystem owns acquisition of session material, not later switching behavior.

### `status_service`

Responsibilities:

- combine metadata and secret-reference validation
- map low-level inconsistencies to user-facing status categories

This may be a small service or thin orchestration layer, but the status logic should not be embedded directly in raw CLI printing code.

## Data Model

Phase 1 should persist only non-secret metadata on disk.

Recommended top-level metadata shape:

```json
{
  "version": 1,
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

Recommended per-slot fields:

- `index`
- `email`
- `keychain_key`
- `registered_at`
- `last_reauth_at`
- `last_validated_at`
- `status`
- `last_error`

The metadata file may also include global versioning or future-safe compatibility fields, but it must not contain session tokens, cookies, passwords, or OTP artifacts.

## State Model

Each slot should resolve to one of these user-facing states:

- `empty`: no account metadata exists for the slot
- `registered`: metadata exists and the referenced Keychain secret is present
- `missing-secret`: metadata exists but the referenced Keychain secret is missing or unreadable
- `needs-reauth`: the slot is structurally present but considered invalid for continued use under local validation policy
- `error`: metadata is malformed or the slot cannot be classified safely

In Phase 1, `needs-reauth` should be assigned only from bounded local evidence such as explicit registration failure state or local validity policy, not from live switching attempts.

## Flow Design

### `switchgpt add`

The registration flow should behave as follows:

1. load config and validate macOS prerequisites
2. load account metadata and choose the next empty slot
3. launch a visible Playwright-controlled browser context
4. instruct the user to complete login manually in the browser window
5. wait for user confirmation in the terminal
6. evaluate authenticated-state signals
7. extract required session material from the browser context
8. normalize the registration result, including discovered email if available
9. write session secrets to Keychain
10. persist non-secret metadata atomically
11. report success with the registered slot index

If no empty slot exists, the command should fail with a direct action, such as reauthing or removing an existing slot in a later phase.

### `switchgpt add --reauth <index>`

The reauthentication flow should behave as follows:

1. validate that the target slot exists
2. preserve the current slot state until new session capture succeeds
3. launch the same visible browser registration flow
4. capture replacement session material after authenticated-state confirmation
5. write the replacement secret
6. atomically update metadata fields such as `last_reauth_at`, `last_validated_at`, `status`, and `last_error`
7. only after success, finalize replacement of the old secret reference if needed

If reauth fails, the existing slot should remain intact from the user’s perspective.

### `switchgpt status`

The status flow should behave as follows:

1. load and validate metadata
2. inspect each slot
3. verify whether the referenced Keychain secret exists
4. classify the slot into a user-facing state
5. print a concise summary that makes broken references or reauth needs obvious

Phase 1 status is a local integrity view. It does not attempt a live browser validation pass.

## Authenticated-State Detection

Phase 1 must treat authenticated-state detection as a bounded, explicit decision instead of an ad hoc guess.

The registration flow should use a ranked signal model:

- strong: authenticated URL or page state that clearly indicates successful entry into the ChatGPT experience
- medium: presence of expected authenticated DOM markers
- weak: absence of the login screen without a stronger positive signal

The flow should succeed only when strong evidence exists, or when a documented combination of medium signals is sufficient. Weak signals alone should not mark the registration as successful.

If the state remains ambiguous after the user confirms login, the command should fail with an explicit message that registration could not verify authenticated state.

## Session Material Capture

Phase 1 should capture the minimum session material required for future switching work, but it should not take ownership of proving reinjection behavior in this phase.

Capture design requirements:

- extract session material only after authenticated-state confirmation
- normalize the captured values into a stable internal representation
- store the sensitive material only through `secret_store`
- treat the exact artifact set as an internal registration concern, not a CLI concern

The captured material should be sufficient for later Phase 2 switching experiments, but this spec does not claim that Phase 1 proves reinjection or rotation.

## Secret Storage Boundary

All sensitive session material must be stored in macOS Keychain.

Requirements:

- no raw secret value is written to the metadata file
- Keychain service naming must be centralized in config
- secret writes and deletes must return structured errors that the CLI can surface clearly
- reauth must not discard the old secret until the new secret is stored and metadata is safely updated

The system may store a stable `keychain_key` reference in metadata so long as that reference is not itself sensitive.

## Persistence and Atomicity Rules

Phase 1 must behave transactionally enough to avoid half-registered accounts.

Rules:

1. Secret write happens before metadata persistence during new registration.
2. Metadata persistence must be atomic.
3. If metadata persistence fails after a successful secret write for a new slot, the flow should roll back the newly written Keychain entry when safe to do so.
4. Reauth must preserve the existing usable slot until replacement succeeds.
5. Partial failures must leave the system in a state that `status` can classify clearly.

These rules matter more than implementation style. The user should never need to inspect raw files to determine whether a slot is usable.

## Error Handling

Phase 1 should define explicit error categories with direct recovery guidance.

Required categories include:

- unsupported OS
- missing browser automation dependency
- browser launch failure
- login timeout or user abandonment
- ambiguous authenticated-state detection
- session extraction failure
- Keychain write failure
- metadata validation failure
- metadata persistence failure
- missing or invalid target slot for reauth

Each error should:

- produce a distinct CLI message
- explain whether the slot was changed
- recommend a direct next action when one exists

Silent partial failure is not acceptable.

## Testing Strategy

Phase 1 requires both automated tests and a manual verification path.

### Automated tests

Unit tests should cover:

- config path and environment rules
- slot selection behavior
- metadata schema validation
- user-facing state classification
- rollback behavior for partial registration failures

Integration-style tests should cover:

- `secret_store` behavior behind a mockable boundary
- registration orchestration using mocked browser-state and extraction outcomes
- reauth preservation of the old slot on replacement failure

### Manual verification

Because the phase requires a real browser login flow, Phase 1 should include a manual macOS verification checklist that confirms:

- the visible browser launches
- the user can complete login manually
- authenticated-state detection succeeds after login
- session material is stored without appearing in the metadata file
- `status` reflects the new slot correctly
- reauth updates the slot without corrupting local state

## Exit Criteria

Phase 1 is complete only when all of the following are true:

- a user can register at least one account on macOS through a real browser login flow
- a user can reauthenticate an existing slot through the same browser-driven mechanism
- `status` reports slot state and broken secret references clearly
- no sensitive session material is stored in plaintext metadata files
- partial failures leave local state consistent and diagnosable
- subsystem boundaries remain clean enough for Phase 2 to add switching without redesigning registration

## Deferred To Phase 2

The following concerns are intentionally deferred:

- retrieving stored session material for active switching
- clearing and reinjecting browser session state
- manual switching commands
- switch target selection rules
- switch event history

This deferral is deliberate. Phase 1 proves account acquisition and secure local persistence. Phase 2 will prove session reuse and switching.

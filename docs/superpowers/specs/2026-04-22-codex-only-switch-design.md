# Codex-Only Switch Design

## Goal

Make `switchgpt switch --to <slot>` manage only Codex CLI authentication.

The command should stop depending on ChatGPT browser session cookies, managed browser startup, cookie injection, and browser authentication checks.

## Current Problem

The current implementation stores imported Codex `auth.json` per slot, but `switch` still tries to activate the slot through the managed browser using `session_token` and `csrf_token`.

That creates a mismatch:

- a slot can contain valid imported Codex auth
- `switch` can still fail with `Account slot <n> likely needs reauthentication.`
- the browser can still open even when the user only wants Codex CLI account rotation

This behavior is incorrect for the Codex-only workflow.

## Decision

`switchgpt switch --to <slot>` becomes a Codex-only command.

It will:

- load the target slot record
- load the target slot secret
- require `codex_auth_json` to exist for that slot
- project that payload into the live Codex auth file
- persist runtime state for the active slot
- write switch history

It will not:

- open the managed browser
- inject browser cookies
- validate browser authentication state
- raise browser reauthentication errors

## Command Behavior

### Success

`switch --to <slot>` succeeds when:

- the slot exists
- the slot secret exists
- the slot secret includes imported `codex_auth_json`
- projecting that auth payload to the configured live Codex auth path succeeds

On success, the command prints the switched slot and updates active runtime state and switch history.

### Failure

`switch --to <slot>` fails when:

- the slot does not exist
- the slot secret is missing
- the slot has no imported Codex auth payload
- writing the live Codex auth file fails

If the slot has no imported Codex auth, the repair guidance should tell the user to:

1. run `codex login` with the target account
2. run `switchgpt import-codex-auth --slot <slot>`
3. retry `switchgpt switch --to <slot>`

### Compatibility

Browser-specific logic may remain in the codebase for other commands, but `switch` must not depend on it.

## Implementation Outline

### `switch_service`

- remove the managed-browser switch path from `switch`
- stop calling `ensure_runtime`, `prepare_switch`, and `is_authenticated`
- perform Codex auth projection directly from the stored `codex_auth_json`
- keep runtime-state persistence and history recording

### Error handling

- replace browser reauth failures with direct Codex repair guidance
- preserve distinct handling for missing slot and missing secret
- preserve strict failure if Codex auth projection fails

### Tests

Add or update tests to cover:

- successful Codex-only switch without any browser interaction
- failure when imported Codex auth is missing
- no managed-browser calls during `switch`
- runtime state and history updates still occur on success

## Non-Goals

- redesigning browser-oriented commands such as `open` or `watch`
- deleting the managed browser subsystem
- changing slot import semantics beyond what `switch` requires

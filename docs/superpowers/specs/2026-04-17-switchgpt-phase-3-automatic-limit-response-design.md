# switchgpt Phase 3 Automatic Limit Response Design

Roadmap Phase: Phase 3
Primary Capability Area: automatic limit detection and response
Affected Tracks: reliability, observability and diagnostics, testability
Prerequisites: roadmap approved, Phase 2 manual session switching design approved
Status: in design

## Purpose

This document defines the Phase 3 Automatic Limit Response design for `switchgpt`.

Phase 3 turns `switchgpt` from a deterministic manual switching tool into a bounded automation tool. It adds a foreground monitoring loop that watches the `switchgpt`-managed ChatGPT browser workspace for a supported usage-limit state and immediately rotates to the next eligible registered account when that limit state appears.

This phase is intentionally limited to a user-run foreground command. It does not include a background daemon, broad failure-recovery policy, or multiple detection strategies. The goal is to prove one reliable automation path on top of the Phase 2 switching foundation.

## Scope

Phase 3 covers:

- a new foreground automation command, `switchgpt watch`
- page-level usage-limit detection in the managed browser workspace
- immediate automatic switching when the supported limit state is detected
- deterministic next-account selection for automated rotation
- bounded per-run exclusion of accounts that fail during an automation run
- clear terminal outcomes and event recording for automated actions

Phase 3 does not cover:

- background watcher or daemon lifecycle management
- response to generic submission failures, network failures, or ambiguous UI errors
- durable cooldowns or cross-run account backoff policy
- packaging, installer, or platform-expansion work
- operational hardening beyond what is required for a safe first automation loop

## Phase Outcome

At the end of Phase 3, the project should have a dependable first automation loop on macOS that can:

1. open or reuse the `switchgpt`-managed ChatGPT browser workspace
2. monitor that workspace for a supported page-level usage-limit state
3. immediately switch to the next eligible registered account when that state is detected
4. record both successful and failed automated rotation events
5. stop with a clear outcome when no eligible replacement account remains

The phase outcome is not “all limit-related failures are handled automatically.” The phase outcome is “one narrow, reliable automatic limit-response path exists and is stable enough to use as the base for later hardening.”

## Product Boundary For This Phase

Phase 3 assumes `switchgpt` remains:

- single-user
- local-first
- terminal-oriented
- browser-driven
- dependent on OS-managed secret storage

Automation remains supported only inside the `switchgpt`-managed Playwright browser workspace introduced in Phase 2. Phase 3 does not attempt to detect limits or mutate sessions in arbitrary user-managed browser profiles because that would weaken determinism and make automation state less trustworthy.

## Goals

- add a bounded automation loop without weakening the Phase 2 switching boundaries
- keep limit detection replaceable by isolating it behind a narrow browser-facing interface
- keep account-selection policy simple, deterministic, and easy to inspect
- make automated outcomes visible through explicit CLI and history signals
- stop cleanly when automation cannot proceed instead of retrying ambiguously

## Non-Goals

- adding background process management
- building fairness, cooldown, or quota-balancing policy
- inferring limits from broad classes of request failure
- introducing cross-run exclusion state
- solving broader daily-use hardening concerns that belong in Phase 4

## Architectural Stance

Phase 3 should preserve the roadmap’s architectural stance:

1. Local-first execution
All monitoring and switching behavior runs on the user’s machine without hosted infrastructure.

2. Secret isolation
Session secrets remain in macOS Keychain only. Automation history and runtime state remain non-secret.

3. Small subsystem boundaries
Browser state detection, watch-loop orchestration, account persistence, and switch execution remain separate concerns.

4. Replaceable detection and switching logic
The first supported limit detector should be narrow and localizable so later phases can evolve detection without redesigning switching orchestration.

## Supported Environment

Phase 3 targets:

- macOS only
- local interactive terminal usage
- a Playwright-managed visible browser runtime

Phase 3 assumes:

- Phase 2 registration and manual switching are already working
- at least two registered accounts exist for useful automation
- the user performs ChatGPT work inside the `switchgpt`-managed browser window
- Playwright and its browser dependency are installed and usable

Phase 3 should fail fast with clear guidance when those prerequisites are missing.

## Command Surface

Phase 3 adds one primary user-facing command:

### `switchgpt watch`

Starts a foreground monitoring loop for the managed ChatGPT workspace.

The command should:

- open or reuse the managed browser workspace if needed
- validate that automation can establish a deterministic current account context
- poll for the supported page-level usage-limit state
- immediately rotate to the next eligible account when that state is detected
- continue monitoring after a successful switch
- stop cleanly on exhaustion, unrecoverable runtime failure, or user interrupt

The command should fail before entering the loop when:

- fewer than two registered accounts are available
- the managed browser workspace cannot be opened
- account metadata cannot be loaded
- the current active account cannot be determined from local runtime metadata

Phase 3 does not add user-tunable policy flags for poll interval, retry strategy, or target-selection policy. Those remain internal implementation details in this phase.

## Subsystem Design

Phase 3 should be implemented as a small set of focused subsystems.

### `cli`

Responsibilities:

- parse the new `watch` command
- invoke the watch service
- render user-facing monitoring, switch, and stop outcomes
- return stable exit codes for success, exhaustion, failure, and interrupt

The CLI should not perform browser detection or account selection directly.

### `managed_browser`

Responsibilities:

- continue owning the Playwright persistent profile and managed ChatGPT workspace
- expose narrow workspace access for the watch loop
- provide a limit-detection operation, such as `detect_limit_state(page) -> LimitState`
- keep browser-specific detection details isolated from account and CLI policy

This subsystem should not decide which account to switch to or how long to keep monitoring.

### `switch_service`

Responsibilities:

- continue to own single-target switching execution
- continue coordinating secret retrieval, session mutation, auth verification, metadata updates, and event recording for a single switch attempt
- surface bounded per-account failure outcomes that the watch loop can interpret

Phase 3 should not merge watch-loop logic into `switch_service`.

### `watch_service`

Responsibilities:

- own the foreground automation loop
- load the active runtime context at start
- poll for supported limit state
- compute eligible targets
- invoke `switch_service` for each candidate target
- track per-run account exclusions for failed automated attempts
- stop cleanly with clear terminal outcomes

This subsystem is the Phase 3 orchestration layer for automation and should remain separate from browser implementation details.

### `account_store`

Responsibilities:

- continue exposing registered accounts and active-account runtime metadata
- remain the source of deterministic slot-order information
- avoid absorbing watch-loop policy or per-run transient exclusion state

## Limit Detection Contract

Phase 3 supports exactly one trigger: a positive page-level usage-limit state in the managed browser workspace.

The detector must distinguish between:

- `limit_detected`
- `no_limit_detected`
- `unknown`

Behavior by state:

- `limit_detected`: the watch loop immediately starts automated rotation
- `no_limit_detected`: the watch loop continues monitoring
- `unknown`: the watch loop does nothing beyond continuing to monitor

Phase 3 must not treat generic request failures, network instability, or ambiguous page states as equivalent to a supported usage-limit signal. False positives are more harmful than delayed switching in this phase because they can rotate away from healthy accounts for the wrong reason.

## Automation Loop

`switchgpt watch` should run a single-process foreground loop with a bounded state machine:

- `monitoring`
- `switching`
- `stopped`

### Monitoring

In `monitoring`, the watch service polls the managed browser page at a fixed short interval defined as an internal constant. The interval should be responsive enough for interactive use without becoming a busy loop. Phase 3 does not expose this interval as a user-facing flag.

### Switching

When the detector returns `limit_detected`, the watch service enters `switching`:

1. identify the current active account from runtime metadata
2. compute eligible targets by deterministic slot order
3. skip the current active slot
4. skip any slot already marked unavailable for the current watch run
5. call `switch_service.switch_to(index=...)` for each remaining candidate in order

On successful switch:

- update the active-account runtime state through existing switching behavior
- record the automated success event
- return to `monitoring`

On candidate-specific failure:

- record the failure outcome
- mark that slot unavailable for the current run
- continue to the next eligible target

### Stopped

The watch loop enters `stopped` when:

- no eligible replacement account remains
- an unrecoverable browser or metadata failure occurs
- the user interrupts the process

When the loop stops because no eligible account remains, it must:

- leave the browser on the current limited session
- print a clear exhaustion outcome
- exit non-zero
- record a terminal exhaustion event

When the user interrupts with Ctrl-C, the loop should exit cleanly without mutating account metadata unless a switch had already completed before the interrupt.

## Account Eligibility Policy

Phase 3 uses a simple deterministic eligibility rule for automated rotation:

- iterate registered accounts in ascending slot order
- exclude the current active slot
- exclude any slot already marked unavailable for the current watch run

An account becomes unavailable for the current run when an automated attempt fails because of a bounded per-account failure such as:

- missing secret material
- reauthentication required
- post-switch authentication verification failure

The exclusion list is in-memory only. It resets each time the user starts a new `switchgpt watch` process. Phase 3 does not introduce durable exclusion, account cooldown windows, or fairness policy.

## Data Model And Event Recording

Phase 3 should continue storing only non-secret metadata on disk.

Persistent account metadata remains the source of:

- registered account records
- `active_account_index`
- `last_switch_at`

Phase 3 should not add new durable account fields for automation backoff, retry counts, or cooldown state.

The switch/event history should expand to distinguish automated events from manual ones. The simplest acceptable model is to preserve the existing event structure and add an automated mode such as `watch-auto`.

Automation history should capture:

- timestamp
- from account index or `null`
- to account index or `null` for terminal events with no candidate
- mode, including an automated mode distinct from manual switching
- bounded result category
- short diagnostic message when relevant

Terminal automation events such as “no eligible account remains” should be recorded even when no successful switch occurs, because they are operationally important outcomes.

## Failure Model

Phase 3 should keep its failure vocabulary bounded and explicit.

Recommended result categories:

- `limit-detected`
- `switch-succeeded`
- `needs-reauth`
- `missing-secret`
- `post-switch-auth-failed`
- `account-exhausted-for-run`
- `no-eligible-account`
- `browser-runtime-failure`
- `user-interrupted`

Implementation may map low-level exceptions into these categories internally, but Phase 3 should expose only stable, user-comprehensible outcomes through CLI and event history.

Failure handling rules:

- ambiguous detection does not trigger switching
- candidate-specific failures do not stop the loop if later eligible targets remain
- unrecoverable runtime failures stop the loop immediately
- exhaustion stops the loop immediately with a clear terminal outcome

## CLI Behavior

`switchgpt watch` should make the automation loop observable without becoming noisy.

It should report at minimum:

- that monitoring has started
- when a supported limit state is detected
- which target slot is being attempted
- whether automated switching succeeded
- why the loop stopped, when it stops

The command should avoid streaming every poll iteration to the terminal. The operator should see state transitions and outcomes, not heartbeat spam.

## Testing Strategy

Phase 3 testing should prioritize behavior and boundaries over UI-detail assertions.

Required test coverage areas:

- `watch_service` state transitions between monitoring, switching, and stopped
- positive detection triggering immediate automated switching
- `unknown` and `no_limit_detected` states causing continued monitoring without switch attempts
- deterministic slot-order target selection
- in-run exclusion after bounded per-account failure
- exhaustion behavior when all alternate accounts are unavailable
- clean interrupt handling
- event/history recording for automated success, per-account failure, and terminal exhaustion
- CLI coverage for `switchgpt watch`

Testing should continue to rely heavily on fakes around browser interaction, secret retrieval, and account storage so the automation policy can be verified without depending on live browser behavior.

## Implementation Notes

The cleanest implementation path is to add `watch_service` above the existing Phase 2 switching seam rather than widening `switch_service` to own detection. That keeps “when to switch” separate from “how to switch,” which preserves replaceability and makes later trigger expansion less invasive.

Phase 3 should prefer small, explicit abstractions:

- a bounded `LimitState` model
- a watch-loop orchestrator
- a pure eligibility selector or helper where practical

This keeps the policy surface understandable and helps Phase 4 build on real operational evidence rather than hidden coupling.

## Design Decisions Locked In This Spec

- Foreground command vs daemon: foreground command only in Phase 3
- Trigger scope: page-level usage-limit state only
- Switch timing: immediate switching on positive detection
- Eligibility policy: deterministic slot-order rotation with in-run exclusions
- Exhaustion behavior: stop the loop, leave the browser on the current limited account, print a clear error, and record the terminal event

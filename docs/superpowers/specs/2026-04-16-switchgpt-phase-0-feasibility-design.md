# switchgpt Phase 0 Feasibility Design

Roadmap Phase: Phase 0
Primary Capability Area: session capture and injection
Affected Tracks: security, observability and diagnostics, testability, maintainability and packaging
Prerequisites: roadmap approved
Status: in design

## Purpose

This document defines the Phase 0 feasibility work for `switchgpt`.

Phase 0 exists to determine whether the product's core assumptions are technically viable before the project commits to implementation-oriented specs. This phase does not produce production code, CLI behavior, or automation loops. It produces a decision-grade understanding of what can likely work, what is still uncertain, and what would block Phase 1.

## Scope

Phase 0 is a documentation and research phase.

It covers:

- regular user browser feasibility, before any Codex CLI-specific integration
- cross-platform feasibility across macOS, Linux, and Windows
- session capture and later reinjection assumptions
- login-state detection assumptions
- candidate limit-detection signals
- secure secret storage feasibility by OS
- major failure modes and uncertainty areas

It does not cover:

- implementation of a production CLI
- background watching or automatic switching
- final module APIs
- account rotation policy
- packaging or installer work
- Codex CLI browser-launch integration

## Phase Outcome

At the end of Phase 0, the project should be able to answer:

1. Can a locally run tool likely capture enough session material from a supported browser session to enable later account restoration?
2. Can that session material likely be reinjected in a way that restores an authenticated ChatGPT web session without forcing a full login each time?
3. What are the minimum reliable signals for detecting successful login and account-limit states?
4. What secure storage mechanisms are viable on each target OS?
5. What risks or unknowns are serious enough to constrain or reshape Phase 1?

The intended output is a clear recommendation: proceed, proceed with constraints, or stop.

## Product Boundary For This Phase

Phase 0 assumes `switchgpt` remains:

- single-user
- local-first
- terminal-oriented
- browser-driven
- dependent on OS-managed secret storage

For this phase, the only target surface is the regular user browser experience for ChatGPT web. Codex CLI-specific behavior is intentionally deferred until browser-session assumptions are validated on their own.

## Feasibility Questions

Phase 0 should answer the following questions explicitly.

### 1. Session Capture

Can the system identify and extract the minimum session material required to restore an authenticated ChatGPT web session later?

Key concerns:

- which cookies or browser-held values appear necessary
- whether any additional browser storage layers matter
- whether session material is browser-profile-specific
- whether manual login completion can be treated as a stable prerequisite

### 2. Session Reinjection

Can previously captured session material be restored into a browser context in a way that predictably resumes an authenticated session?

Key concerns:

- whether reinjection requires a clean browser context
- whether cookie domain, path, expiry, and security attributes materially affect success
- whether restored sessions survive page reloads and navigation
- whether reinjection behavior differs across OS or browser engines

### 3. Login-State Detection

Can the system detect, with bounded ambiguity, whether the browser is authenticated, unauthenticated, or expired?

Key concerns:

- URL-based indicators
- DOM-level indicators
- request/response patterns that imply authenticated state
- signals that imply session expiry versus transient loading failures

### 4. Limit Detection

Which signals are plausible candidates for detecting that the active account has hit a usage or availability limit?

Key concerns:

- visible in-page messages
- backend response codes or headers
- distinguishing rate-limit conditions from general outage conditions
- distinguishing account exhaustion from temporary service instability

### 5. Secure Storage

Can the tool rely on OS-managed credential storage across all target platforms without storing sensitive session material in plaintext local metadata files?

Key concerns:

- viability of Keychain on macOS
- viability of Credential Manager on Windows
- viability and dependency assumptions for Linux secret storage
- how to handle environments where Linux secret storage is missing or misconfigured

## Working Assumptions To Validate

Phase 0 starts from the following assumptions, but must treat them as hypotheses rather than facts:

1. An authenticated ChatGPT web session can be resumed later from a limited set of captured browser session artifacts.
2. The required session artifacts can be obtained without needing to automate password or OTP entry.
3. Login success can be detected reliably enough to support later manual account-registration flows.
4. At least one stable limit signal exists that is strong enough to support later automation.
5. Each target OS has a practical secret-storage path that keeps sensitive values out of plaintext local files.
6. A regular user browser flow is enough to validate the core product direction before considering Codex CLI-specific integration.

## Evidence Model

Phase 0 is not complete when it has opinions. It is complete when each core assumption has a decision label backed by evidence.

Each feasibility area must end with one of these outcomes:

- `likely viable`: enough evidence exists to support moving forward
- `uncertain`: plausible, but later specs must preserve a fallback or narrower scope
- `blocked`: evidence suggests the current product assumption is not dependable

Each conclusion must be backed by one or more of:

- observed browser behavior
- platform documentation
- reproducible manual experiment notes
- comparison against alternative explanations

## Research Structure

Phase 0 should be documented using the following sections.

### Environment Assumptions

Document the minimum environment assumptions that later specs may rely on:

- supported browser family assumptions
- whether a dedicated browser profile is required
- Playwright or equivalent automation dependency assumptions
- OS-specific secret-storage dependencies
- filesystem path assumptions for non-secret metadata

### Session Material Inventory

Document candidate session artifacts and classify them as:

- likely required
- possibly required
- likely unnecessary
- unknown

The goal is not to guarantee the final implementation artifact list. The goal is to narrow the later implementation target away from guesswork.

### Login Success Signals

List candidate signals for a completed authenticated state and rank them by confidence:

- strong
- medium
- weak

The same structure should be used for expiry or forced-login signals.

### Limit Signals

List candidate limit indicators and classify each by:

- observability source: DOM, network, navigation, or mixed
- likely specificity: high, medium, or low
- known ambiguity risks

### OS Secure Storage Analysis

For each supported OS, document:

- likely storage mechanism
- dependency assumptions
- usability risks
- fallback posture if the secure mechanism is unavailable

Fallback posture must not violate the product boundary of keeping secrets out of plaintext local metadata files.

### Failure And Uncertainty Register

Track the major risks discovered during Phase 0, including:

- browser state that cannot be restored cleanly
- signals that appear too brittle to automate against
- Linux credential-store availability issues
- account-state transitions that are hard to distinguish
- browser or site changes that would threaten later specs

Each risk entry should describe:

- the failure mode
- likely user impact
- whether the impact affects Phase 1, Phase 2, or both
- the proposed constraint or mitigation

## Cross-Platform Feasibility Criteria

Phase 0 must treat cross-platform support as an explicit evaluation area, not an optimistic assumption.

### macOS

Phase 0 should determine whether the planned secret boundary can rely on Keychain and whether browser automation assumptions appear straightforward enough to support future implementation.

### Linux

Phase 0 should explicitly account for fragmented desktop environments and the possibility that a secure credential store may not be available or configured by default. Linux should not be labeled viable unless the spec identifies a realistic minimum-supported environment or a defensible support constraint.

### Windows

Phase 0 should determine whether Credential Manager provides a practical secret boundary and whether browser automation assumptions materially differ from macOS and Linux.

## Decision Rules

Phase 0 should recommend one of the following outcomes.

### Proceed

Use this only if session capture, reinjection, and secure storage all appear likely viable, and no discovered risk invalidates the product's local-first design.

### Proceed With Constraints

Use this if the product still looks worth building, but later specs must narrow scope. Example constraints include:

- initial browser support narrowed
- initial OS support narrowed
- detection logic treated as provisional
- Linux support requiring a documented secret-storage prerequisite

### Stop Or Reframe

Use this if the core session or storage assumptions appear too brittle to support a dependable product. This outcome should identify whether the project should be abandoned or materially reframed.

## Exit Criteria

Phase 0 is complete only when all of the following are true:

- environment assumptions are documented for macOS, Linux, and Windows
- session capture feasibility is labeled with a decision outcome
- session reinjection feasibility is labeled with a decision outcome
- login-state detection candidates are ranked and scoped
- limit-detection candidates are ranked and scoped
- secure-storage feasibility is documented for each target OS
- major failure modes and open uncertainties are recorded
- a final recommendation is made for whether Phase 1 should proceed
- any Phase 1 constraints are stated explicitly rather than implied

## Deliverables

Phase 0 should produce the following artifacts:

- this design spec
- a feasibility findings document or appendix containing the evidence gathered
- a concise go/no-go recommendation for Phase 1
- a list of constraints that Phase 1 must inherit

No implementation code is required for this phase.

## Downstream Constraint On Phase 1

Phase 1 must not assume any of the following unless Phase 0 findings justify them explicitly:

- that one cookie alone is sufficient for session restoration
- that limit detection is reliable enough for automation
- that Linux secure storage is universally available
- that Codex CLI integration behaves the same as a regular browser session

If Phase 0 ends with `proceed with constraints`, the Phase 1 spec must adopt those constraints directly instead of reopening them informally.

## Suggested Next Spec

If Phase 0 concludes with `proceed` or `proceed with constraints`, the next spec should target `Phase 1: Local Foundation` with focus on:

- CLI entry structure
- non-secret local metadata layout
- secure credential storage boundary
- manual account registration and reauthentication surfaces
- validation and status visibility for persisted local state

That Phase 1 spec should treat session switching and automatic limit response as out of scope.

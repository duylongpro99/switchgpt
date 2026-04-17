# switchgpt Roadmap Design

## Purpose

This document is the master planning artifact for `switchgpt`.

It defines the product roadmap at the phase level so future specs can reference a stable source of truth for:

- delivery phase
- capability area
- cross-cutting concerns
- progress tracking

This document is intentionally not an implementation plan. It defines sequencing, boundaries, and tracking structure without specifying task-level execution.

## Product Boundaries

`switchgpt` is a single-user, local-first CLI tool for rotating between ChatGPT Plus accounts when usage limits are hit.

It is explicitly scoped as:

- a local automation tool
- a terminal-first workflow
- secure storage using OS-managed credential facilities
- browser-driven session management

It is explicitly out of scope as:

- a multi-user service
- a remote orchestration system
- a shared team account manager
- a hosted control plane
- a generalized browser automation platform

## Architectural Stance

The roadmap assumes the following principles remain stable across all future specs:

1. Local-first execution
The system runs on the user's machine and should not require hosted infrastructure for core behavior.

2. Secret isolation
Sensitive session material must be stored only in OS-managed secure storage, never in plaintext local metadata files.

3. Clear subsystem boundaries
CLI orchestration, account persistence, session automation, limit detection, and rotation policy should remain separable concerns.

4. Replaceable detection and switching logic
Detection signals and switching mechanics should be designed so they can evolve without forcing a redesign of unrelated modules.

5. Hardening after proof of core value
The roadmap prioritizes proving the core workflow first, then expanding reliability, diagnostics, and maintainability in later phases.

## Roadmap Structure

The roadmap uses a hybrid structure:

- milestone-based phases are the primary delivery structure
- cross-cutting tracks capture concerns that span multiple phases

Every future spec should map to both dimensions.

## Phase Catalog

### Phase 0: Feasibility and Constraints

**Objective**

Validate that the product's core technical assumptions are viable and narrow the highest-risk unknowns before committing to implementation specs.

**Why this phase exists**

The PRD assumes browser session capture, cookie reinjection, login-state detection, and limit-state detection are workable. These assumptions create the foundation for every later phase. If any of them are unstable, later specs must reflect that reality.

**Included outcomes**

- define local environment assumptions and external dependencies
- validate whether session capture and reinjection are technically viable
- identify minimum reliable signals for successful login detection
- identify candidate signals for limit detection
- document major failure and uncertainty areas

**Non-goals**

- no production-grade CLI
- no automated switching behavior
- no hard commitment to specific module implementations

**Exit criteria**

- the core workflow is confirmed to be worth building
- major technical unknowns are documented
- later phases can be scoped against known constraints instead of assumptions

**Downstream dependency**

All later phases depend on this phase.

### Phase 1: Local Foundation

**Objective**

Build the base local system needed to manage accounts and securely persist the non-volatile state required by the tool.

**Why this phase exists**

The system needs a dependable local foundation before switching behavior or automation can be added. This phase establishes the CLI surface, metadata model, and secure secret handling.

**Included outcomes**

- CLI entry structure
- config and path conventions
- account metadata model
- secure keychain integration
- initial account add and reauthentication flows
- basic status and validation surfaces

**Non-goals**

- no automatic response to limit events
- no background watcher
- no assumption that account switching is already reliable

**Exit criteria**

- accounts can be registered and reauthenticated
- metadata is persisted safely
- secrets are stored through the intended secure boundary
- local state can be inspected and validated through the CLI

**Downstream dependency**

Required by Phases 2 through 5.

### Phase 2: Manual Session Switching

**Objective**

Deliver the first end-to-end user value by allowing reliable on-demand switching between previously registered accounts.

**Why this phase exists**

Manual switching proves the core account rotation path before adding autonomous behavior. It isolates session manipulation from event detection.

**Included outcomes**

- retrieval of stored session material
- browser session clearing and reinjection flow
- deterministic manual switching commands
- account selection rules for manual flows
- switch event recording

**Non-goals**

- no background monitoring
- no automatic trigger response
- no advanced recovery orchestration beyond the switching path

**Exit criteria**

- the user can switch to another valid account without repeating full login
- switching behavior is predictable enough to serve as the base for automation

**Downstream dependency**

Required by Phases 3 through 5.

### Phase 3: Automatic Limit Response

**Objective**

Add the product's core automation loop: detect a limit event and rotate to the next eligible account with clear, bounded behavior.

**Why this phase exists**

This is the phase where the tool becomes meaningfully automatic instead of being only a manual convenience wrapper.

**Included outcomes**

- limit detection strategy
- account eligibility filtering
- automatic switch trigger handling
- failure behavior when candidate accounts are unavailable
- state updates tied to automated switch events

**Non-goals**

- no deep operational hardening beyond what is necessary for a safe first automation loop
- no packaging or install optimization work

**Exit criteria**

- the tool can detect a supported limit condition
- the tool can attempt rotation to the next valid account
- failure cases produce clear outcomes instead of silent ambiguity

**Downstream dependency**

Required by Phases 4 and 5.

### Phase 4: Operational Hardening

**Objective**

Improve trustworthiness for daily use by making failure modes visible, recoverable, and diagnosable.

**Why this phase exists**

The automation loop is not sufficient on its own. Daily-use software must expose failure state clearly and recover without forcing guesswork.

**Included outcomes**

- token expiry handling
- clearer error and recovery paths
- improved status surfaces
- diagnostics and event history improvements
- safer retry and fallback behavior
- broader validation and test coverage

**Non-goals**

- no expansion into multi-user or remote use cases
- no premature platformization

**Exit criteria**

- common operational failures are understandable
- recovery actions are explicit
- daily-use confidence no longer depends on manual inspection of internals

**Downstream dependency**

Required by Phase 5.

### Phase 5: Packaging and Maintainability

**Objective**

Make the system easier to install, evolve, and support over time without redesigning the core architecture.

**Why this phase exists**

Once the tool is functionally solid, the next bottleneck becomes maintenance cost. This phase formalizes developer ergonomics, packaging expectations, and extension boundaries.

**Included outcomes**

- installation and distribution approach
- logging conventions
- module boundary refinement
- configuration ergonomics
- test workflow expectations
- extension points for future internal evolution

**Non-goals**

- no move to hosted services
- no expansion into team or multi-tenant behavior
- no feature growth that changes the core product boundary

**Exit criteria**

- the project is straightforward to install and debug
- architectural boundaries are stable enough for future incremental specs
- long-term evolution does not require revisiting first principles

## Cross-Cutting Tracks

### Security

**Intent**

Protect secret material and make credential handling boundaries explicit.

**Why it matters**

The product is built around session credentials. Security mistakes directly undermine the product.

**Becomes mandatory**

From Phase 0 onward.

**Future specs touching this track must address**

- where sensitive data lives
- what is written to disk
- redaction and logging behavior
- reauthentication and secret refresh boundaries

### Reliability

**Intent**

Ensure switching and automation produce predictable outcomes under normal and degraded conditions.

**Why it matters**

The tool's value depends on deterministic behavior when the user is already interrupted by account limits.

**Becomes mandatory**

From Phase 2 onward, and central in Phases 3 and 4.

**Future specs touching this track must address**

- incomplete or failed switch behavior
- handling unavailable or exhausted accounts
- state consistency after errors
- safe fallback behavior

### Observability and Diagnostics

**Intent**

Expose system state and failures clearly enough for both users and future maintainers to understand what happened.

**Why it matters**

Browser automation and session handling fail in ways that can otherwise be opaque.

**Becomes mandatory**

Starts early, becomes critical by Phase 4.

**Future specs touching this track must address**

- status visibility
- actionable error messages
- logs or event history
- debugging surfaces for automation behavior

### Testability

**Intent**

Preserve testable boundaries around logic that would otherwise be tightly coupled to browsers, external state, and timing-sensitive behavior.

**Why it matters**

This project has multiple risky integration points. Poor early boundaries would make later hardening expensive and brittle.

**Becomes mandatory**

From Phase 1 onward.

**Future specs touching this track must address**

- test seam definition
- isolation of external dependencies
- balance between unit and integration coverage
- how high-risk behavior is verified

### Maintainability and Packaging

**Intent**

Keep the system understandable, installable, and evolvable as it grows.

**Why it matters**

Even as a single-user tool, maintainability determines whether later changes remain incremental or turn into repeated rewrites.

**Becomes mandatory**

Partial concern in early phases, explicit focus in Phase 5.

**Future specs touching this track must address**

- module ownership and boundaries
- configuration ergonomics
- installation expectations
- compatibility with future incremental change

## Capability Areas

Future specs should classify themselves under one primary capability area:

- CLI surface
- account persistence
- secure credential storage
- session capture and injection
- limit detection
- rotation policy
- watch and automation loop
- status and diagnostics
- packaging and developer workflow

These capability areas are not phases. They are a stable classification layer that helps track related specs across multiple phases.

## Spec Linkage Rules

Every future spec derived from this roadmap should include a short metadata header with:

- roadmap phase
- primary capability area
- affected cross-cutting tracks
- prerequisites
- status

Suggested template:

```md
Roadmap Phase: Phase X
Primary Capability Area: session capture and injection
Affected Tracks: security, reliability
Prerequisites: Phase 1 approved
Status: not started | in design | spec approved | in implementation | verified | complete
```

## Progress Model

Roadmap-linked work should use the following status values:

- `not started`
- `in design`
- `spec approved`
- `in implementation`
- `verified`
- `complete`

This status model is intentionally simple so it can be reused across phases, specs, and eventual implementation plans.

## Usage Rules For Later Specs

Later specs should use this roadmap in the following way:

1. Anchor to a single roadmap phase.
2. Declare one primary capability area.
3. List all affected cross-cutting tracks.
4. Reference prerequisite roadmap items or earlier specs.
5. Avoid pulling work from multiple phases unless the roadmap is explicitly revised first.

This keeps the roadmap useful as a control document instead of allowing later specs to blur boundaries.

## Recommended Initial Sequencing

The roadmap implies this sequencing:

1. validate feasibility and constraints
2. establish the secure local foundation
3. prove manual switching
4. automate the limit response
5. harden for daily use
6. formalize packaging and maintainability

This sequence should be treated as the default order unless a later roadmap revision makes a justified change.

## Revision Policy

This roadmap is expected to evolve only when one of the following happens:

- a core technical assumption changes
- a phase boundary is discovered to be incorrect
- a capability area needs to be split or merged
- cross-cutting expectations become materially different

Small implementation discoveries should update later specs, not this roadmap, unless they change roadmap-level boundaries.

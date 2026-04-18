# switchgpt Phase 5 Packaging and Maintainability Design

Roadmap Phase: Phase 5
Primary Capability Area: packaging and developer workflow
Affected Tracks: maintainability and packaging, observability and diagnostics, testability, security
Prerequisites: roadmap approved, Phase 4 operational hardening design approved
Status: in design

## Purpose

This document defines the Phase 5 Packaging and Maintainability design for `switchgpt`.

Phase 5 formalizes the internal operating shape of the project after the core account registration, switching, automation, and hardening phases are functionally established. It does not turn `switchgpt` into a broadly distributed product. Instead, it makes the codebase easier to install in a repeatable local development environment, easier to debug, and safer to evolve through small future changes.

This phase is intentionally limited to internal maintainability and packaging boundaries. It may include modest refactors where earlier phases left rough seams, but it must not become a broad architectural rewrite or a release-channel commitment.

## Scope

Phase 5 covers:

- internal packaging boundaries for running and testing the project consistently
- project-level developer setup expectations for local use
- logging and diagnostic conventions with explicit redaction rules
- configuration ergonomics and clearer separation of config, runtime state, and secrets
- modest module-boundary refactors where earlier phases created avoidable coupling
- stable test workflow expectations for unit, integration, and operational verification
- documentation of extension seams for future internal evolution

Phase 5 does not cover:

- Homebrew, `pipx`, installer, or public release-channel commitments
- hosted services, shared control planes, or team-oriented deployment
- feature expansion that changes the product boundary
- broad rewrites of proven switching or automation behavior
- cross-platform support expansion beyond what earlier phases already established

## Phase Outcome

At the end of Phase 5, the project should have an internal operating shape on macOS that is stable enough for continued incremental development:

1. local setup and execution are predictable without relying on tribal knowledge
2. logging and diagnostics are structured enough to debug operational issues without leaking secrets
3. configuration, runtime state, and secure storage responsibilities are clearly separated
4. rough subsystem seams from earlier phases are tightened where they materially affect maintenance cost
5. test expectations are explicit enough that future changes can be verified consistently
6. future internal specs can extend the tool without revisiting first-principles architecture

The phase outcome is not “the tool is packaged for public distribution.” The phase outcome is “the internal system is installable, diagnosable, and evolvable with bounded ongoing cost.”

## Product Boundary For This Phase

Phase 5 assumes `switchgpt` remains:

- single-user
- local-first
- terminal-oriented
- browser-driven
- dependent on OS-managed secret storage

This phase improves the internal shape of the existing tool. It does not change the product into a service, a GUI application, or a multi-user account-management system.

## Goals

- reduce maintenance cost by clarifying module ownership and interfaces
- make local developer setup and verification repeatable
- standardize diagnostic output so daily-use failures and implementation regressions are easier to understand
- keep security boundaries explicit while improving observability
- document narrow extension seams so future phases can remain incremental

## Non-Goals

- choosing a public distribution channel
- redesigning core automation policy
- adding new account-management features
- collapsing major subsystems into a single orchestration layer
- performing cleanup that is unrelated to maintainability or packaging boundaries

## Architectural Stance

Phase 5 should preserve the roadmap’s architectural stance:

1. Local-first execution
All normal execution and verification remain local. Packaging work should support repeatable local use, not remote orchestration.

2. Secret isolation
Session secrets remain outside normal disk metadata and log outputs. Improved diagnostics must not weaken this boundary.

3. Small subsystem boundaries
CLI, configuration, account persistence, secret storage, browser automation, switching, monitoring, and diagnostics should remain separable concerns with clearer interfaces where needed.

4. Incremental evolution over redesign
Refactors in this phase should remove coupling that blocks maintainability, not reopen settled architectural decisions from Phases 1 through 4.

## Supported Environment

Phase 5 targets:

- macOS only
- local interactive terminal usage
- a Playwright-managed browser runtime
- a repository-driven developer workflow

Phase 5 assumes:

- earlier phases already established working account registration, switching, and automation behavior
- local developers can install the project’s Python and Playwright dependencies
- the repository remains the primary installation surface for this phase

Phase 5 should continue to fail fast with clear guidance when the local environment is incomplete or unsupported.

## Command Surface

Phase 5 should avoid large user-facing CLI expansion. Its command-surface work is primarily about making existing commands more internally consistent and diagnosable.

Phase 5 may add narrow developer-oriented surfaces only when they directly support maintainability, such as:

- a validation-oriented command for checking local environment prerequisites
- a diagnostics-oriented command for surfacing non-secret runtime and configuration state

Any new command in this phase must satisfy all of the following:

- it serves a real maintenance or operational-debugging use case
- it does not expose secret session material
- it does not create a second path for core switching or automation behavior

This phase should prefer improving existing `status` and operational output over adding many new commands.

## Subsystem Design

Phase 5 should preserve the earlier subsystem decomposition while tightening ownership where needed.

### `cli`

Responsibilities:

- keep command parsing, exit-code behavior, and user-facing rendering consistent
- centralize shared output conventions for normal, warning, and failure states
- avoid embedding business logic, filesystem layout decisions, or browser-specific diagnostics directly in command handlers

If earlier phases duplicated formatting or status logic across commands, Phase 5 may extract small shared presentation helpers.

### `config`

Responsibilities:

- define the canonical application paths, filenames, and environment assumptions
- distinguish immutable config inputs from tool-owned runtime state locations
- provide a single source of truth for defaults and validation rules

Phase 5 should tighten this subsystem if path logic or environment checks leaked into unrelated modules in earlier phases.

### `account_store`

Responsibilities:

- remain the owner of non-secret account metadata and event-history persistence
- expose narrow reads and writes that support status, switching, and watch behavior
- avoid absorbing logging, rendering, or secret-resolution concerns

Phase 5 may refine metadata access patterns if earlier phases introduced ambiguous update ownership.

### `secret_store`

Responsibilities:

- remain the only subsystem responsible for secure secret retrieval and persistence
- expose stable failure categories that other layers can log safely without leaking secret contents
- keep Keychain-specific behavior localized

This subsystem must not become responsible for broader diagnostics or runtime-state inspection.

### `managed_browser`

Responsibilities:

- own the Playwright persistent profile and browser-session lifecycle
- expose narrow browser operations used by registration, switching, and watch flows
- encapsulate browser-specific diagnostics that can be surfaced through higher-level logging without leaking implementation details into orchestration layers

Phase 5 may extract smaller helpers inside this subsystem if browser lifecycle, session mutation, and detection concerns became too entangled.

### `switch_service`

Responsibilities:

- continue owning single-target switch orchestration
- expose stable result categories and structured outcomes for CLI and logging layers
- avoid taking on environment validation, persistent diagnostics policy, or broad watch-loop logic

### `watch_service`

Responsibilities:

- continue owning foreground automation orchestration
- emit structured events or result objects instead of ad hoc terminal strings
- remain separate from low-level detection and switching mechanics

### `diagnostics`

Phase 5 may introduce a dedicated diagnostics-oriented subsystem if earlier phases spread event formatting, logging policy, and redaction across multiple modules.

Responsibilities:

- define structured log/event shapes
- apply redaction rules before emission
- centralize formatting of bounded operational result categories

This subsystem should not become a generic dumping ground for unrelated utilities.

## Packaging Boundary

Phase 5 should define an internal packaging posture rather than a public distribution plan.

That posture should include:

- one canonical way to install repository dependencies for development and local operation
- one canonical way to run the CLI from the repository
- one canonical way to run the test suite, with clear separation between fast tests and heavier operational checks
- a repository layout that makes the executable entrypoint and internal modules obvious

Phase 5 should not commit to:

- publishing artifacts to package indexes
- OS package managers
- auto-update behavior
- versioned installer UX for external users

The design intent is “repeatable internal packaging” rather than “user-facing software distribution.”

## Configuration And State Boundary

By Phase 5, configuration ergonomics should be explicit enough that maintainers can answer three questions immediately:

1. what values are user-configurable inputs
2. what files and directories are tool-owned runtime state
3. what information is secret and must stay in secure storage

Phase 5 should enforce a clean separation between:

- configuration inputs such as supported paths, environment toggles, or debug modes
- runtime artifacts such as browser profiles, transient lock files, or event logs
- non-secret persisted metadata such as account records and active-account state
- secret session material held in Keychain

If earlier phases blurred these categories, modest refactors in this phase should make the separation obvious in both code structure and operator-facing documentation.

## Logging And Diagnostics Conventions

Phase 5 should standardize how the project emits operational information.

Required logging properties:

- logs and recorded events use stable, bounded result categories
- diagnostic messages are short, specific, and tied to a clear subsystem
- secret values, session cookies, raw auth headers, and equivalent sensitive payloads are never logged
- high-value operational events use a consistent shape across registration, switching, monitoring, and recovery flows

Recommended diagnostic fields where appropriate:

- timestamp
- subsystem
- command or mode
- account index when relevant
- result category
- short message

Phase 5 should distinguish between:

- user-facing terminal output optimized for actionability
- internal logs or event records optimized for diagnosis

These surfaces may share the same underlying result model, but they should not be treated as identical output channels.

## Module Boundary Refinement Rules

Phase 5 explicitly allows modest refactors to stabilize rough seams from earlier phases.

Allowed refactor scope:

- extracting shared helpers when the same policy logic is duplicated across subsystems
- moving path or environment validation into `config`
- moving result-category shaping or redaction into a diagnostics-oriented seam
- splitting files that have accumulated multiple unrelated responsibilities
- clarifying ownership of metadata writes when more than one subsystem currently mutates the same state ambiguously

Disallowed refactor scope:

- rewriting validated automation flows for stylistic reasons
- replacing established subsystem boundaries with a new architecture without a concrete maintenance need
- moving large amounts of code only to normalize naming or folder structure
- changing product behavior as a side effect of cleanup unless the behavior was already undefined or inconsistent

The standard for inclusion is practical: a refactor belongs in Phase 5 only if it materially lowers maintenance cost, debugging difficulty, or verification friction.

## Test Workflow Expectations

Phase 5 should make the verification model explicit and repeatable.

The project should define at least three testing layers:

- fast unit tests for pure logic and bounded service behavior
- integration-oriented tests using fakes or controlled adapters for account storage, secret access, and browser-facing seams
- heavier operational checks for end-to-end command behavior where justified

Phase 5 should establish:

- canonical commands for running each verification layer
- expectations for which tests must pass before merging routine changes
- where browser-dependent tests belong and how they are isolated from fast default workflows
- stable fixtures or fakes for high-risk boundaries such as account metadata, Keychain adapters, and browser-state detection

This phase should reduce ambiguity around “how do I know this change is safe?” without requiring every change to run the heaviest possible verification path.

## Documentation Expectations

Phase 5 should leave behind maintainability-oriented documentation, not marketing or release documentation.

Expected documentation outcomes:

- a concise developer setup path
- clear commands for running the CLI locally
- test workflow guidance
- explanation of config, runtime state, and secret-storage boundaries
- notes on the intended ownership of the main subsystems

Documentation should be concise and operational. It should help a future maintainer understand how to work on the tool without reverse-engineering the repository layout.

## Extension Seams

This phase should document future-safe internal extension points without implementing major new features.

The most important seams to keep explicit are:

- detection strategies beyond the first supported limit signal
- switching-policy changes that do not require browser-runtime redesign
- additional diagnostics surfaces that still share the same redaction and result-category model
- future packaging or distribution work that should layer on top of the internal packaging boundary rather than replace it

The value of these seams is architectural clarity, not speculative abstraction. Phase 5 should prefer narrow interfaces around real variability points over generic plugin systems.

## Failure Model For This Phase

Phase 5 should improve clarity, not invent new operational behaviors.

The main failure classes this phase should make easier to diagnose are:

- incomplete local setup
- invalid or conflicting configuration inputs
- missing or unreadable runtime state
- secret-store access failures
- browser runtime initialization failures
- internal contract violations between subsystems
- test-environment misconfiguration

The design objective is that these failures become easier to localize and explain through consistent diagnostics, not that every one of them gains automated recovery behavior in this phase.

## Testing Strategy

Phase 5 testing should verify maintainability outcomes through stable behavioral seams.

Required coverage areas:

- config validation and path-resolution behavior
- diagnostics redaction rules
- stable structured result models across core services
- CLI behavior for environment or diagnostics-oriented commands, if added
- metadata and runtime-state boundary behavior
- regression coverage for modest refactors to subsystem ownership

Where refactors occur, tests should emphasize preserved behavior at subsystem boundaries rather than line-for-line implementation details. Phase 5 succeeds when internals become easier to change without broad regression risk.

## Implementation Notes

The cleanest path for Phase 5 is to improve the system around the existing proven flows rather than through them.

That means:

- standardize result categories and diagnostic shaping before widening CLI behavior
- tighten config and state boundaries before adding new environment-facing commands
- extract small focused helpers or modules only where coupling is already causing confusion
- document the canonical developer workflow as part of the phase rather than as an afterthought

Phase 5 should treat “make future small changes cheaper” as the core requirement. If a proposed cleanup does not clearly serve that goal, it does not belong in this phase.

## Design Decisions Locked In This Spec

- Distribution posture: internal packaging boundary only, no public release-channel commitment
- Refactor authority: modest boundary-stabilizing refactors allowed, broad rewrites disallowed
- Packaging goal: repeatable repository-based install, run, and test workflow
- Diagnostic goal: consistent structured outcomes with strict redaction
- Architecture goal: preserve subsystem separation while clarifying ownership and interfaces

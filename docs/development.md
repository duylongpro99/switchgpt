# Development Guide

## Canonical Local Workflow

1. Install the development environment with `uv sync --dev`.
2. Use `uv run sca doctor` to check local readiness.
4. Use `uv run sca paths` to confirm repository-owned runtime locations.
5. Use `uv run sca status` to inspect account state.
6. Run `codex login`, then use `uv run sca add` or `uv run sca add --reauth <slot>` to manage account slots.
7. Use `uv run sca import-codex-auth --slot <slot>` when you need to refresh a slot's stored Codex `auth.json` after another `codex login`.
8. Use `uv run sca codex-sync` to project the active slot's imported Codex auth back to the live Codex auth path.
9. Use `uv run sca switch` for account rotation.
10. Run `uv run pytest` before merging changes.

## Local State Boundaries

- Configuration inputs define supported paths, environment assumptions, and runtime toggles.
- Runtime state covers account metadata and event logs.
- Non-secret metadata covers account records and active-account state.
- Secret session material stays in the OS keychain and never appears in normal disk metadata or logs.
- Imported inactive Codex `auth.json` payloads stay in the OS keychain; only the active projected Codex auth file is written to disk.

## Main Ownership Boundaries

- `cli` owns command parsing, exit codes, and user-facing rendering.
- `config` owns canonical paths, filenames, and environment validation.
- `account_store` owns non-secret account metadata and event-history persistence.
- `secret_store` owns secure secret retrieval and persistence.
- `switch_service` owns single-target switch orchestration.
- `diagnostics` owns structured log and event shaping when diagnostics need to stay bounded and redacted.

## Expected Verification Before Merge

- Run `uv run pytest` for the default verification gate.
- Run targeted CLI commands when the change affects command rendering or workflow behavior.
- For Codex auth changes, verify `import-codex-auth`, `codex-sync`, `status`, and `doctor` behavior together.
- Keep verification local and repeatable; do not require secret material in logs or test output.

## Codex Auth Repair Flow

When Codex auth is missing or drifted, the intended operator flow is:

1. `codex login`
2. `uv run sca import-codex-auth --slot <slot>`
3. `uv run sca codex-sync`

`sca add` and `sca add --reauth <slot>` import the current live Codex auth automatically after slot creation or reauthentication.

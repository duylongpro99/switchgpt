# switchgpt

`switchgpt` is a macOS-only CLI for rotating ChatGPT accounts when usage limits are hit.

This repository is intended for local, repository-driven development. See [docs/development.md](docs/development.md) for the maintainer workflow, ownership boundaries, and merge checks.

## Local Setup

Install the development environment:

```bash
uv sync --dev
```

## Local Commands

- `uv run sca paths`
- `uv run sca doctor`
- `uv run sca status`
- `uv run sca add`
- `uv run sca add --reauth <slot>`
- `uv run sca import-codex-auth --slot <slot>`
- `uv run sca codex-sync`
- `uv run sca switch`

Use `paths` to inspect the repository-owned runtime locations.
Use `doctor` to check local readiness.
Use `status` to inspect registered account slots.
Use `add` after `codex login` to register a new slot and immediately attach the current live Codex CLI `auth.json` to that slot.
Use `add --reauth <slot>` to reauthenticate an existing slot.
Use `import-codex-auth --slot <slot>` after running `codex login` with the target account to store that slot's raw Codex `auth.json` in the secret store.
Use `codex-sync` to project the active slot's previously imported Codex `auth.json` back to the live Codex auth path.
Use `switch` to rotate to another account slot.

## Codex Auth Flow

SwitchGPT no longer tries to recover Codex auth through browser OAuth flows.

The supported flow is:

1. Authenticate the target Codex account manually:

```bash
codex login
```

2. Register a new slot and import the current live Codex auth file:

```bash
uv run sca add
```

3. Import the resulting live Codex auth file into an existing slot when needed:

```bash
uv run sca import-codex-auth --slot <slot>
```

4. When needed, re-project the active slot into the live Codex auth path:

```bash
uv run sca codex-sync
```

`switch`, `status`, and `doctor` now assume this imported-auth flow. If a slot is missing imported Codex auth, repair guidance points to `codex login` plus `sca import-codex-auth`.

## Testing

Run the full test suite with:

```bash
uv run pytest
```

## Maintainer Workflow

The canonical maintainer workflow, local state boundaries, and expected verification before merge are documented in [docs/development.md](docs/development.md).

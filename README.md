# switchgpt

`switchgpt` is a macOS-only CLI for rotating ChatGPT accounts when usage limits are hit.

This repository is intended for local, repository-driven development. See [docs/development.md](docs/development.md) for the maintainer workflow, ownership boundaries, and merge checks.

## Local Setup

Install the development environment and browser runtime:

```bash
uv sync --dev
uv run playwright install chromium
```

## Local Commands

- `uv run switchgpt paths`
- `uv run switchgpt doctor`
- `uv run switchgpt status`
- `uv run switchgpt add`
- `uv run switchgpt add --reauth <slot>`
- `uv run switchgpt switch`
- `uv run switchgpt watch`

Use `paths` to inspect the repository-owned runtime locations.
Use `doctor` to check local readiness before running browser-dependent flows.
Use `status` to inspect registered account slots.
Use `add` to register a new account, or `add --reauth <slot>` to reauthenticate an existing slot.
Use `switch` to rotate to another account slot.
Use `watch` to run the foreground monitoring loop.

## Testing

Run the full test suite with:

```bash
uv run pytest
```

## Maintainer Workflow

The canonical maintainer workflow, local state boundaries, and expected verification before merge are documented in [docs/development.md](docs/development.md).

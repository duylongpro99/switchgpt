# switchgpt

`switchgpt` is a macOS-only CLI for rotating ChatGPT accounts when usage limits are hit.

This repository currently contains the bootstrap CLI and the first smoke test.

## Usage

Use `uv run switchgpt status` to inspect registered account slots.
Use `uv run switchgpt add` to register a new account, or `uv run switchgpt add --reauth <slot>` to reauthenticate an existing slot.

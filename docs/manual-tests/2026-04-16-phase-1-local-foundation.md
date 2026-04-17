# Phase 1 Manual Verification

1. Run `uv run switchgpt add`.
2. Confirm a visible Chromium window opens.
3. Complete ChatGPT login manually.
4. Press Enter in the terminal when login is complete.
5. Run `uv run switchgpt status`.
6. Confirm the slot appears as `registered`.
7. Run `uv run switchgpt add --reauth 0`.
8. Confirm the existing slot remains intact if login is cancelled.

# Phase 2 Manual Session Switching Checks

## Preconditions

- macOS host with Playwright installed
- at least two registered accounts created with `switchgpt add`
- terminal opened in the project root

## Checks

1. Run `switchgpt open` and confirm a managed ChatGPT browser window opens.
2. Run `switchgpt switch --to 1` and confirm the managed window reloads into account slot 1.
3. Run `switchgpt switch` and confirm it selects the first registered account that is not currently active.
4. Close the managed browser window, run `switchgpt switch`, and confirm the workspace reopens automatically.
5. Force one account to use an invalid session token, run `switchgpt switch --to <slot>`, and confirm the CLI reports likely reauthentication needed without updating active-account metadata.
6. Inspect `~/.switchgpt/switch-history.jsonl` and confirm both success and failure events were appended as JSON lines.

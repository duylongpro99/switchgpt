# switchgpt Phase 3 Automatic Limit Response Manual Test

## Preconditions

- macOS environment with Playwright browser dependencies installed
- at least two registered accounts in `switchgpt`
- the active account already loaded in the managed ChatGPT workspace

## Scenario 1: Positive limit detection triggers immediate switch

1. Run `switchgpt watch`.
2. Trigger the supported page-level usage-limit state in the managed browser.
3. Confirm the terminal prints that a limit was detected.
4. Confirm the terminal prints the attempted target slot.
5. Confirm the terminal prints successful rotation to the next eligible slot.

## Scenario 2: All alternate accounts are unavailable

1. Start `switchgpt watch` with one current slot and remaining slots intentionally invalid.
2. Trigger the supported page-level usage-limit state.
3. Confirm the terminal reports each failed candidate.
4. Confirm the process exits after printing that no eligible account remains.

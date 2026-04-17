# switchgpt Phase 3 Automatic Limit Response Manual Test

## Preconditions

- macOS with Playwright browser dependencies installed and `switchgpt open` able to launch the managed browser
- at least two registered accounts in `switchgpt` (`switchgpt status` should show slot 0 as active and one other slot as registered)
- the managed ChatGPT workspace is already open on the active slot before starting `watch`
- a ChatGPT account/session that can reach the usage-limit banner or modal recognized by `watch`

## Scenario 1: Positive limit detection triggers immediate switch

1. Run `switchgpt watch` from the project root.
2. In the managed browser, keep the active chat open and continue until ChatGPT shows the usage-limit state that the watch loop recognizes.
3. Pass if the terminal prints `Watching the managed ChatGPT workspace for usage limits.` followed by `Usage limit detected. Switching immediately.`
4. Pass if the terminal then prints `Trying slot <next-index>.` and `Switched to slot <next-index>.`
5. Fail if the watch loop never prints the limit-detected line, or if it prints `No eligible registered account remains for automatic switching.` instead of switching.

## Scenario 2: All alternate accounts are unavailable

1. Keep the current active slot registered and make every other registered slot unavailable for a watch-time switch. The simplest way is to leave the account record in place and remove the valid browser session for each alternate slot, so switching to it fails with a `SwitchError`.
2. Run `switchgpt watch`.
3. Trigger the same usage-limit state as in Scenario 1.
4. Pass if the terminal prints `Trying slot <index>.` for each alternate slot, then prints each failure reason, and finally prints `No eligible registered account remains for automatic switching.`
5. Pass if the process exits with code `1`.
6. Fail if any alternate slot switches successfully, or if the command exits `0` after reporting exhaustion.

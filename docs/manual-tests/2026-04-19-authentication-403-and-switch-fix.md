# SwitchGPT Auth 403 and Switch Fix (2026-04-19, updated 2026-04-22)

## Context

During account registration and switching, the ChatGPT browser flow failed in Playwright-managed Chrome while normal Chrome login worked.

As of 2026-04-22, this note applies only to ChatGPT browser-session capture and switching. Codex auth repair no longer depends on browser OAuth recovery; it now uses manual `codex login` plus `switchgpt import-codex-auth --slot <n>`.

## Symptoms Observed

- `switchgpt add` login page could not complete reliably in Playwright runtime.
- Network inspection showed `403` responses from `https://chatgpt.com/`.
- Captured request headers indicated Playwright `Chromium` fingerprint (`sec-ch-ua: "Chromium"`).
- After registration, `switchgpt switch --to 0` failed with:
  - `BrowserContext.add_cookies: Cookie should have either url or path`
- CLI command typed across two lines caused:
  - `zsh: command not found: --from-open`

## Root Causes

1. Registration/switch workspace sometimes ran in Playwright Chromium fingerprint instead of real Chrome channel.
2. Cloudflare bot checks returned `403` under automation fingerprint conditions.
3. CSRF cookie payload in switch injection incorrectly included both `url` and `path`.
4. Shell command split across lines executed `--from-open` as a separate command.
5. Email extraction could fail when body text did not expose the address, producing `unknown@example.com` label.

## Fixes Implemented

1. Persistent registration context
- `add` registration now supports persistent profile context.
- Bootstrap wires managed profile path into registration client.

2. Chrome-first launch strategy
- Browser launch now prefers Chrome channel by default.
- Falls back when channel launch is unavailable.

3. Optional stealth mode for bot-fingerprint pressure
- Added opt-in launch flags:
  - `ignore_default_args=["--enable-automation"]`
  - `args=["--disable-blink-features=AutomationControlled"]`
- Added init script override:
  - `navigator.webdriver => undefined`

4. Cookie contract fix for switch path
- Removed `path` from `__Host-next-auth.csrf-token` when using `url` cookie format.
- This resolves Playwright `add_cookies` runtime error.

5. `.env` configuration support
- `SWITCHGPT_BROWSER_CHANNEL` and `SWITCHGPT_BROWSER_STEALTH` now load from `.env`.
- Process environment variables still take precedence over `.env`.

6. Email discovery hardening
- Email extraction now checks `/api/auth/session` first and falls back to body-text regex only when needed.
- This prevents `unknown@example.com` for authenticated sessions where UI text does not contain the email.

## Current Runtime Commands

Use one line:

```bash
uv run switchgpt add --from-open
```

If explicit override is needed:

```bash
SWITCHGPT_BROWSER_CHANNEL=chrome SWITCHGPT_BROWSER_STEALTH=1 uv run switchgpt add --from-open
```

Switching:

```bash
uv run switchgpt switch --to 0
```

Codex auth import for a slot:

```bash
codex login
uv run switchgpt import-codex-auth --slot 0
uv run switchgpt codex-sync
```

## Notes

- `email: "unknown@example.com"` should now be rare and indicates neither session API nor body extraction exposed an email at capture time.
- `active_account_index: null` is expected until a successful `switch` updates active slot state.
- If `status` or `doctor` reports missing or drifted Codex auth, the supported fix is manual `codex login` followed by `switchgpt import-codex-auth --slot <n>`.

## Verification Status

- Full test suite after fixes: `155 passed`.
- Manual registration succeeded with Chrome + stealth configuration.
- Switch cookie injection error fixed by CSRF cookie payload correction.

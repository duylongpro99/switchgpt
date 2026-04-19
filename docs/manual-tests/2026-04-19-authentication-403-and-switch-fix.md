# SwitchGPT Auth 403 and Switch Fix (2026-04-19)

## Context

During account registration and switching, the flow failed in Playwright-managed Chrome while normal Chrome login worked.

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

## Correct Runtime Commands

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

## Notes

- `email: "unknown@example.com"` should now be rare and indicates neither session API nor body extraction exposed an email at capture time.
- `active_account_index: null` is expected until a successful `switch` updates active slot state.

## Verification Status

- Full test suite after fixes: `155 passed`.
- Manual registration succeeded with Chrome + stealth configuration.
- Switch cookie injection error fixed by CSRF cookie payload correction.

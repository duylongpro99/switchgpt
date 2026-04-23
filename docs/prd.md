# switchgpt — Architecture & PRD

> CLI tool for automatic ChatGPT Plus account rotation when usage limits are hit, with slot-scoped Codex auth projection from imported `auth.json`.

---

## Architecture Diagram

```
                          ┌─────────────────┐
                          │  User / Terminal │
                          └────────┬────────┘
                                   │
                          ┌────────▼────────┐
                          │    CLI Core     │
                          │  cmd parser ·   │
                          │  config loader  │
                          └──┬─────┬─────┬──┘
                             │     │     │
               ┌─────────────┘     │     └─────────────┐
               │                   │                   │
    ┌──────────▼──────────┐ ┌──────▼───────┐ ┌────────▼────────┐
    │   Session Manager   │ │ Account Store│ │  Limit Detector │
    │ cookie/token inject │ │  encrypted   │ │  rate · quota   │
    │                     │ │  keychain    │ │  watcher        │
    └──────────┬──────────┘ └──────┬───────┘ └────────┬────────┘
               │                   │    ╔══════════════╝
               │                   │    ║  auto-switch trigger
               │            ┌──────▼────╨──────────┐
               │            │   Persistence Layer   │
               │            │ accounts.json · OS    │
               │            │ keychain              │
               │            └───────────────────────┘
               │
    ┌──────────▼──────────────────────────┐
    │      Browser Automation Layer       │
    │      Playwright · headless          │
    │      Chromium                       │
    └──────────┬──────────────────────────┘
               │
    ┌──────────▼──────────────────────────┐
    │    ChatGPT / Codex (browser)        │
    └─────────────────────────────────────┘


  Legend
  ──────
  ──┬──   data / control flow (solid)
  ══╨══   auto-switch callback (triggered on limit hit)
```

### Component summary

| Component | Responsibility |
|---|---|
| **CLI core** | Entry point — parses subcommands, loads config, orchestrates modules |
| **Account store** | Manages 3 account profiles; credentials referenced via OS keychain |
| **Session manager** | Injects correct browser cookies/tokens for the target account |
| **Limit detector** | Watches for quota signals (HTTP 429, DOM text, API headers) |
| **Browser automation** | Performs the actual session swap via Playwright + headless Chromium |
| **Persistence layer** | Stores account ordering, last-used timestamps, and switch history |

---

## Product Requirements Document

### Problem statement

When one of your 3 ChatGPT Plus accounts hits its Codex usage limit, you are forced to manually log out, re-authenticate, and resume work. This interrupts flow, wastes time, and is entirely automatable.

### Goals

- Zero-friction account rotation when a limit is hit
- Works seamlessly with Codex CLI (which opens ChatGPT in a browser session)
- Credentials stored securely — never in plaintext
- Fully terminal-native — no GUI required

---

### CLI commands

| Command | Description |
|---|---|
| `switchgpt add` | One-time login flow for a new account — opens visible Chromium, user logs in manually (incl. OTP), session token captured and stored in OS keychain |
| `switchgpt add --reauth 1` | Re-run the one-time login for an existing account slot (e.g. when token expires after ~30 days) |
| `switchgpt import-codex-auth --slot 1` | Import the currently active Codex CLI `auth.json` into slot 1 after manual `codex login` |
| `switchgpt codex-sync` | Project the active slot's previously imported Codex `auth.json` back to the live Codex auth path |
| `switchgpt switch` | Manually switch to the next account in rotation (cookie inject only, no login) |
| `switchgpt switch --to 2` | Switch to a specific account by index |
| `switchgpt status` | Show all accounts, which is active, token expiry estimate, and limit reset times |
| `switchgpt watch` | Background daemon mode — monitors for limit hits and auto-switches |
| `switchgpt remove <index>` | Remove an account and its keychain entry from the store |

---

### Authentication & credential persistence

ChatGPT uses a `__Secure-next-auth.session-token` cookie (~30 day TTL) that authenticates the full browser session. SwitchGPT stores that browser session in the OS keychain for ChatGPT switching, and separately stores imported Codex CLI `auth.json` payloads per slot for Codex projection.

#### First-time login (`switchgpt add`) — runs once per account

```
switchgpt add
    │
    ├─ open visible Chromium window
    ├─ user completes login manually
    │     └─ email + password + OTP (if prompted)
    ├─ tool detects successful login (URL or DOM signal)
    ├─ Playwright extracts session token from browser cookie jar
    │     ├─ __Secure-next-auth.session-token   (primary)
    │     └─ __Host-next-auth.csrf-token        (secondary)
    ├─ tokens encrypted and stored → OS keychain
    └─ browser closes

Done. Never repeated for this account unless token expires.
```

OTP handling during `switchgpt add` uses the manual completion approach: Playwright pauses and prints a prompt in the terminal. The user completes the full login (including OTP) in the visible browser window, then presses Enter in the terminal. Playwright then captures the resulting session cookie. This requires zero OTP detection logic and works regardless of whether ChatGPT uses email OTP, SMS, or an authenticator app.

```
[switchgpt] Complete login in the browser window (email, password, OTP if asked).
[switchgpt] Press ENTER here when you are done: _
```

#### Codex auth import — manual, slot-scoped

```
codex login
    │
    ├─ user authenticates in Codex CLI with the target account
    ├─ Codex writes live ~/.codex/auth.json
    ├─ switchgpt import-codex-auth --slot N
    ├─ tool validates and fingerprints live auth.json
    ├─ raw auth.json stored securely → OS keychain
    └─ non-secret fingerprint metadata stored → accounts.json
```

#### Every switch after that — no login, no OTP

```
limit hit detected  (or: switchgpt switch)
    │
    ├─ read next account from rotation queue
    ├─ fetch session token from OS keychain        ← silent, ~10 ms
    ├─ clear current browser cookies
    ├─ inject stored session token
    ├─ reload page
    ├─ project imported Codex auth.json for active slot
    └─ Codex resumes on new account               ← ~2–3 seconds total
```

#### Credential storage layout

```
OS Keychain  (never written to disk as plaintext)
├── switchgpt_account_0   →  session token for account1@example.com
├── switchgpt_account_1   →  session token for account2@example.com
└── switchgpt_account_2   →  session token for account3@example.com

~/.switchgpt/accounts.json  (safe to inspect — contains no secrets)
└── email, keychain_key reference, last_used, limit_hit_at, token_captured_at, Codex import/projection fingerprints
```

#### Token expiry (~30 days)

When a stored browser token expires the page redirects to the login screen instead of loading ChatGPT. The limit detector watches for this redirect and surfaces a warning:

```
[switchgpt] ⚠  Session expired for account2@example.com
[switchgpt]    Run: switchgpt add --reauth 1
```

`--reauth` re-triggers the one-time login flow for that account slot only, refreshes the stored token, and normal rotation resumes.

When Codex auth is missing or drifted, the repair path is:

```bash
codex login
uv run switchgpt import-codex-auth --slot <slot>
uv run switchgpt codex-sync
```

SwitchGPT no longer performs browser-driven Codex OAuth recovery in normal flows.

---

### Auto-switch trigger conditions

The limit detector triggers on any of the following signals:

1. HTTP `429` with `X-RateLimit-Remaining: 0` on `/backend-api/` endpoints
2. Page DOM contains `"You've reached your limit"` or `"GPT-4 is currently unavailable"`
3. Manual trigger via `switchgpt switch`

On trigger, the tool:

1. Reads the next account from the rotation queue
2. Clears current browser cookies
3. Injects the next account's session token
4. Reloads the page (~2–3 seconds total)
5. Logs the switch event with a timestamp to `~/.switchgpt/history.log`

---

### Tech stack

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.10+ | Clean async support, mature ecosystem |
| Browser automation | Playwright | Better cookie API than Puppeteer, official Python bindings |
| Credential storage | `keyring` | OS-native keychain (Keychain / libsecret / Credential Manager) |
| Config | `~/.switchgpt/accounts.json` | Human-readable, gitignore-able |
| Daemon/watch mode | Polling loop (5 s interval) | Avoids OS service complexity in v1 |
| CLI framework | `click` or `typer` | Ergonomic arg parsing with minimal boilerplate |

---

### File structure

```
switchgpt/
├── switchgpt/
│   ├── __init__.py
│   ├── cli.py           # Entry point — click/typer commands
│   ├── account_store.py # Load/save accounts.json + keychain ops
│   ├── session.py       # Cookie capture & injection via Playwright
│   ├── detector.py      # Limit detection logic (DOM + HTTP)
│   └── config.py        # Paths, constants, defaults
├── tests/
├── pyproject.toml
└── README.md
```

---

### Data model — `accounts.json`

```json
{
  "active": 0,
  "accounts": [
    {
      "index": 0,
      "email": "account1@example.com",
      "keychain_key": "switchgpt_account_0",
      "last_used": "2026-04-16T08:30:00Z",
      "limit_hit_at": null,
      "token_captured_at": "2026-04-01T10:00:00Z"
    },
    {
      "index": 1,
      "email": "account2@example.com",
      "keychain_key": "switchgpt_account_1",
      "last_used": "2026-04-15T22:10:00Z",
      "limit_hit_at": "2026-04-16T07:00:00Z",
      "token_captured_at": "2026-04-01T10:05:00Z"
    },
    {
      "index": 2,
      "email": "account3@example.com",
      "keychain_key": "switchgpt_account_2",
      "last_used": "2026-04-14T18:45:00Z",
      "limit_hit_at": null,
      "token_captured_at": "2026-04-01T10:10:00Z"
    }
  ]
}
```

Sensitive values (session tokens) are stored **only** in the OS keychain, referenced by `keychain_key`. The JSON file contains no credentials. `token_captured_at` is used by `switchgpt status` to warn when a token is approaching its ~30 day expiry.

---

### Rotation strategy

Accounts are selected using **least-recently-used + skip-if-limited** logic:

1. Filter out accounts whose `limit_hit_at` is within the last 3 hours
2. From the remaining accounts, pick the one with the oldest `last_used` timestamp
3. If all accounts are limited, report the earliest expected reset time and exit gracefully

---

### Out of scope (v1)

- Proxy / VPN per account (anti-fingerprinting)
- GUI or system tray app
- Firefox support
- Shared account pools across machines
- Automatic token refresh (user re-runs `switchgpt add` when token expires)

---

### Build order (recommended)

1. `switchgpt add` — one-time login + OTP (manual completion) + token capture and keychain storage
2. `switchgpt switch` — silent cookie inject from keychain, no login (immediate value)
3. `switchgpt status` — account states, token age, limit reset times
4. `switchgpt watch` — fully automated daemon mode
5. `switchgpt add --reauth` — token refresh when expiry is detected

---

*Generated by Claude · switchgpt v0.1 spec*

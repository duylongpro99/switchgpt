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
    ┌──────────▼──────────┐ ┌──────▼───────┐
    │ Codex Auth Projector│ │ Account Store│
    │ auth.json sync      │ │ keychain refs│
    └──────────┬──────────┘ └──────┬───────┘
               │                   │
               │            ┌──────▼───────────────┐
               │            │   Persistence Layer   │
               │            │ accounts.json · OS    │
               │            │ keychain              │
               │            └───────────────────────┘
               │
    ┌──────────▼──────────────────────────┐
    │      Codex CLI auth.json            │
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
| **Codex auth projector** | Writes stored slot auth into the live Codex CLI auth file |
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
| `sca add` | Register the current Codex CLI account after manual `codex login` |
| `sca add --reauth 1` | Refresh metadata for an existing account slot after manual `codex login` |
| `sca import-codex-auth --slot 1` | Import the currently active Codex CLI `auth.json` into slot 1 after manual `codex login` |
| `sca codex-sync` | Project the active slot's previously imported Codex `auth.json` back to the live Codex auth path |
| `sca switch` | Manually switch to the next account in rotation by projecting stored Codex auth |
| `sca switch --to 2` | Switch to a specific account by index |
| `sca status` | Show all accounts, which is active, token expiry estimate, and limit reset times |
| `sca remove <index>` | Remove an account and its keychain entry from the store |

---

### Authentication & credential persistence

SwitchGPT stores imported Codex CLI `auth.json` payloads per slot in the OS keychain, then projects the selected slot back to the live Codex auth file during `switch` or `codex-sync`.

#### First-time login (`sca add`) — runs once per account

```
codex login
    │
    ├─ user authenticates through Codex CLI
    ├─ Codex writes live ~/.codex/auth.json
    ├─ sca add
    ├─ tool imports the live auth.json into the new slot
    └─ non-secret fingerprint metadata stored → accounts.json
```

#### Codex auth import — manual, slot-scoped

```
codex login
    │
    ├─ user authenticates in Codex CLI with the target account
    ├─ Codex writes live ~/.codex/auth.json
    ├─ sca import-codex-auth --slot N
    ├─ tool validates and fingerprints live auth.json
    ├─ raw auth.json stored securely → OS keychain
    └─ non-secret fingerprint metadata stored → accounts.json
```

#### Every switch after that — no login, no OTP

```
limit hit detected  (or: sca switch)
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
[switchgpt]    Run: sca add --reauth 1
```

`--reauth` re-triggers the one-time login flow for that account slot only, refreshes the stored token, and normal rotation resumes.

When Codex auth is missing or drifted, the repair path is:

```bash
codex login
uv run sca import-codex-auth --slot <slot>
uv run sca codex-sync
```

SwitchGPT no longer performs browser-driven Codex OAuth recovery in normal flows.

---

### Auto-switch trigger conditions

The limit detector triggers on any of the following signals:

1. HTTP `429` with `X-RateLimit-Remaining: 0` on `/backend-api/` endpoints
2. Page DOM contains `"You've reached your limit"` or `"GPT-4 is currently unavailable"`
3. Manual trigger via `sca switch`

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
| Credential storage | `keyring` | OS-native keychain (Keychain / libsecret / Credential Manager) |
| Config | `~/.switchgpt/accounts.json` | Human-readable, gitignore-able |
| CLI framework | `click` or `typer` | Ergonomic arg parsing with minimal boilerplate |

---

### File structure

```
switchgpt/
├── switchgpt/
│   ├── __init__.py
│   ├── cli.py           # Entry point — click/typer commands
│   ├── account_store.py # Load/save accounts.json + keychain ops
│   ├── codex_auth_sync.py # Codex auth import and projection
│   ├── switch_service.py  # Slot switching
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

Sensitive values (session tokens) are stored **only** in the OS keychain, referenced by `keychain_key`. The JSON file contains no credentials. `token_captured_at` is used by `sca status` to warn when a token is approaching its ~30 day expiry.

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
- Automatic token refresh (user re-runs `sca add` when token expires)

---

### Build order (recommended)

1. `sca add` — slot creation and current Codex auth import
2. `sca switch` — project stored Codex auth into the live auth file
3. `sca status` — account states, token age, limit reset times
4. `sca add --reauth` — refresh slot metadata after manual Codex login

---

*Generated by Claude · switchgpt v0.1 spec*

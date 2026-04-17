# SwitchGPT Phase 2 Manual Session Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 2 manual session switching so `switchgpt` can open a managed Playwright browser workspace, switch it to another registered account using stored Keychain session material, and record switch outcomes without adding automatic limit handling.

**Architecture:** Extend the Phase 1 foundation instead of replacing it. Keep registration isolated in `registration.py`, add a narrow `managed_browser.py` adapter for the persistent Playwright runtime, a `switch_history.py` helper for non-secret event logging, and a `switch_service.py` orchestration layer that selects a target account, injects session cookies, verifies auth state, and updates metadata only after success.

**Tech Stack:** Python 3.12, Typer, Playwright, keyring, pytest

---

## File Structure

### Project files

- Modify: `switchgpt/config.py`
- Modify: `switchgpt/errors.py`
- Modify: `switchgpt/models.py`
- Modify: `switchgpt/account_store.py`
- Modify: `switchgpt/cli.py`
- Create: `switchgpt/managed_browser.py`
- Create: `switchgpt/switch_history.py`
- Create: `switchgpt/switch_service.py`

### Test files

- Modify: `tests/test_config.py`
- Modify: `tests/test_account_store.py`
- Modify: `tests/test_cli.py`
- Create: `tests/test_switch_history.py`
- Create: `tests/test_switch_service.py`
- Create: `tests/test_managed_browser.py`

### Documentation

- Create: `docs/manual-tests/2026-04-16-phase-2-manual-session-switching.md`

### Responsibilities

- `switchgpt/config.py`: add managed browser profile path and switch event log path
- `switchgpt/errors.py`: add bounded switching-specific error types
- `switchgpt/models.py`: extend metadata models with active-account and switch timestamps; define switch-event data
- `switchgpt/account_store.py`: persist and load top-level Phase 2 runtime metadata atomically
- `switchgpt/managed_browser.py`: own the Playwright persistent context and ChatGPT session mutation operations
- `switchgpt/switch_history.py`: append and load non-secret switch event records
- `switchgpt/switch_service.py`: orchestrate target selection, secret retrieval, browser mutation, verification, metadata updates, and event recording
- `switchgpt/cli.py`: add `switch` and `open` commands without embedding browser logic

## Task 1: Extend Settings And Error Types For Phase 2 Runtime Paths

**Files:**
- Modify: `switchgpt/config.py`
- Modify: `switchgpt/errors.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing config and error tests**

```python
from pathlib import Path

from switchgpt.config import Settings
from switchgpt.errors import ManagedBrowserError, SwitchError, SwitchGptError


def test_settings_exposes_phase_2_runtime_paths(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/example-home")

    settings = Settings.from_env()

    assert settings.managed_profile_dir == Path("/tmp/example-home/.switchgpt/playwright-profile")
    assert settings.switch_history_path == Path("/tmp/example-home/.switchgpt/switch-history.jsonl")


def test_phase_2_error_types_inherit_from_switchgpt_error() -> None:
    assert issubclass(ManagedBrowserError, SwitchGptError)
    assert issubclass(SwitchError, SwitchGptError)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with missing `managed_profile_dir`, `switch_history_path`, `ManagedBrowserError`, or `SwitchError`

- [ ] **Step 3: Write the minimal config and error implementation**

```python
from dataclasses import dataclass
from pathlib import Path
import os
import platform

from .errors import UnsupportedPlatformError


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    metadata_path: Path
    keychain_service: str
    slot_count: int
    chatgpt_base_url: str
    managed_profile_dir: Path
    switch_history_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        home = Path(os.environ["HOME"])
        data_dir = home / ".switchgpt"
        return cls(
            data_dir=data_dir,
            metadata_path=data_dir / "accounts.json",
            keychain_service="switchgpt",
            slot_count=3,
            chatgpt_base_url="https://chatgpt.com",
            managed_profile_dir=data_dir / "playwright-profile",
            switch_history_path=data_dir / "switch-history.jsonl",
        )


def ensure_supported_platform() -> None:
    if platform.system() != "Darwin":
        raise UnsupportedPlatformError("switchgpt Phase 1 supports macOS only.")
```

```python
class SwitchGptError(Exception):
    """Base application error."""


class UnsupportedPlatformError(SwitchGptError):
    """Raised when the current OS is not supported."""


class AccountStoreError(SwitchGptError):
    """Raised when account metadata cannot be read or parsed."""


class SecretStoreError(SwitchGptError):
    """Raised when keychain secret data cannot be read or parsed."""


class BrowserRegistrationError(SwitchGptError):
    """Raised when browser-based registration cannot verify or capture state."""


class ManagedBrowserError(SwitchGptError):
    """Raised when the managed Playwright runtime cannot be used."""


class SwitchError(SwitchGptError):
    """Raised when a manual switch cannot be completed."""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add switchgpt/config.py switchgpt/errors.py tests/test_config.py
git commit -m "feat: add phase 2 runtime settings and switch errors"
```

## Task 2: Extend Metadata Models And Account Store For Active Account State

**Files:**
- Modify: `switchgpt/models.py`
- Modify: `switchgpt/account_store.py`
- Modify: `tests/test_account_store.py`

- [ ] **Step 1: Write the failing account store tests**

```python
from datetime import UTC, datetime

from switchgpt.account_store import AccountStore
from switchgpt.models import AccountRecord, AccountSnapshot, AccountState


def test_load_returns_empty_snapshot_with_phase_2_top_level_fields(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts.json", slot_count=3)

    snapshot = store.load()

    assert snapshot.accounts == []
    assert snapshot.active_account_index is None
    assert snapshot.last_switch_at is None


def test_save_active_account_round_trips_with_registered_accounts(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts.json", slot_count=3)
    recorded_at = datetime(2026, 4, 16, 11, 15, tzinfo=UTC)
    store.save_record(
        AccountRecord(
            index=0,
            email="account1@example.com",
            keychain_key="switchgpt_account_0",
            registered_at=recorded_at,
            last_reauth_at=recorded_at,
            last_validated_at=recorded_at,
            status=AccountState.REGISTERED,
            last_error=None,
        )
    )

    store.save_runtime_state(active_account_index=0, switched_at=recorded_at)
    snapshot = store.load()

    assert snapshot.active_account_index == 0
    assert snapshot.last_switch_at == recorded_at
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_account_store.py -v`
Expected: FAIL with missing `active_account_index`, `last_switch_at`, `AccountSnapshot`, or `save_runtime_state`

- [ ] **Step 3: Write the minimal model and store implementation**

```python
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AccountState(StrEnum):
    EMPTY = "empty"
    REGISTERED = "registered"
    MISSING_SECRET = "missing-secret"
    NEEDS_REAUTH = "needs-reauth"
    ERROR = "error"


@dataclass(frozen=True)
class AccountRecord:
    index: int
    email: str
    keychain_key: str
    registered_at: datetime
    last_reauth_at: datetime
    last_validated_at: datetime
    status: AccountState
    last_error: str | None


@dataclass(frozen=True)
class AccountSnapshot:
    accounts: list[AccountRecord]
    active_account_index: int | None
    last_switch_at: datetime | None
```

```python
import json
from dataclasses import asdict
from datetime import datetime

from .models import AccountRecord, AccountSnapshot, AccountState


class AccountStore:
    def load(self) -> AccountSnapshot:
        if not self._metadata_path.exists():
            return AccountSnapshot(accounts=[], active_account_index=None, last_switch_at=None)
        payload = json.loads(self._metadata_path.read_text())
        active_account_index = payload.get("active_account_index")
        last_switch_at = payload.get("last_switch_at")
        return AccountSnapshot(
            accounts=[self._load_record(item) for item in payload["accounts"]],
            active_account_index=active_account_index,
            last_switch_at=datetime.fromisoformat(last_switch_at) if isinstance(last_switch_at, str) else None,
        )

    def _write_snapshot(self, snapshot: AccountSnapshot) -> None:
        payload = {
            "version": 1,
            "active_account_index": snapshot.active_account_index,
            "last_switch_at": snapshot.last_switch_at.isoformat() if snapshot.last_switch_at else None,
            "accounts": [
                {
                    **asdict(account),
                    "registered_at": account.registered_at.isoformat(),
                    "last_reauth_at": account.last_reauth_at.isoformat(),
                    "last_validated_at": account.last_validated_at.isoformat(),
                    "status": account.status.value,
                }
                for account in snapshot.accounts
            ],
        }
        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._metadata_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2))
        temp_path.replace(self._metadata_path)

    def save_runtime_state(self, active_account_index: int | None, switched_at: datetime | None) -> None:
        snapshot = self.load()
        self._write_snapshot(
            AccountSnapshot(
                accounts=snapshot.accounts,
                active_account_index=active_account_index,
                last_switch_at=switched_at,
            )
        )

    def save_record(self, record: AccountRecord) -> None:
        snapshot = self.load()
        accounts = [account for account in snapshot.accounts if account.index != record.index] + [record]
        self._write_snapshot(
            AccountSnapshot(
                accounts=sorted(accounts, key=lambda item: item.index),
                active_account_index=snapshot.active_account_index,
                last_switch_at=snapshot.last_switch_at,
            )
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_account_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add switchgpt/models.py switchgpt/account_store.py tests/test_account_store.py
git commit -m "feat: persist active account runtime metadata"
```

## Task 3: Add Switch Event Recording As A Separate JSONL Log

**Files:**
- Create: `switchgpt/switch_history.py`
- Create: `tests/test_switch_history.py`

- [ ] **Step 1: Write the failing switch history tests**

```python
from datetime import UTC, datetime

from switchgpt.switch_history import SwitchEvent, SwitchHistoryStore


def test_append_writes_single_json_line_event(tmp_path) -> None:
    store = SwitchHistoryStore(tmp_path / "switch-history.jsonl")

    store.append(
        SwitchEvent(
            occurred_at=datetime(2026, 4, 16, 11, 15, tzinfo=UTC),
            from_account_index=0,
            to_account_index=1,
            mode="explicit-target",
            result="success",
            message=None,
        )
    )

    lines = (tmp_path / "switch-history.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert '"to_account_index": 1' in lines[0]


def test_append_creates_parent_directory(tmp_path) -> None:
    history_path = tmp_path / "nested" / "switch-history.jsonl"
    store = SwitchHistoryStore(history_path)

    store.append(
        SwitchEvent(
            occurred_at=datetime(2026, 4, 16, 11, 15, tzinfo=UTC),
            from_account_index=None,
            to_account_index=0,
            mode="auto-target",
            result="success",
            message=None,
        )
    )

    assert history_path.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_switch_history.py -v`
Expected: FAIL with missing `SwitchHistoryStore` or `SwitchEvent`

- [ ] **Step 3: Write the minimal switch history implementation**

```python
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class SwitchEvent:
    occurred_at: datetime
    from_account_index: int | None
    to_account_index: int
    mode: str
    result: str
    message: str | None


class SwitchHistoryStore:
    def __init__(self, history_path: Path) -> None:
        self._history_path = history_path

    def append(self, event: SwitchEvent) -> None:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(event)
        payload["occurred_at"] = event.occurred_at.isoformat()
        with self._history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_switch_history.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add switchgpt/switch_history.py tests/test_switch_history.py
git commit -m "feat: add switch history event store"
```

## Task 4: Add A Managed Browser Adapter For The Playwright Runtime

**Files:**
- Create: `switchgpt/managed_browser.py`
- Create: `tests/test_managed_browser.py`

- [ ] **Step 1: Write the failing managed browser tests**

```python
from switchgpt.managed_browser import ManagedBrowser


class FakeContext:
    def __init__(self) -> None:
        self.cookies_cleared = False
        self.cookies_added = []

    def clear_cookies(self) -> None:
        self.cookies_cleared = True

    def add_cookies(self, cookies) -> None:
        self.cookies_added.extend(cookies)


class FakePage:
    def __init__(self) -> None:
        self.url = "https://chatgpt.com"
        self.visited = []
        self.text = "ChatGPT"

    def goto(self, url: str) -> None:
        self.visited.append(url)
        self.url = url

    def locator(self, selector: str):
        assert selector == "body"
        return self

    def inner_text(self) -> str:
        return self.text


def test_prepare_switch_clears_and_injects_cookies() -> None:
    browser = ManagedBrowser("https://chatgpt.com", profile_dir=None)
    context = FakeContext()
    page = FakePage()

    browser.prepare_switch(
        context,
        page,
        session_token="session-1",
        csrf_token="csrf-1",
    )

    assert context.cookies_cleared is True
    assert context.cookies_added[0]["name"] == "__Secure-next-auth.session-token"
    assert page.visited[-1] == "https://chatgpt.com"


def test_is_authenticated_rejects_login_page() -> None:
    browser = ManagedBrowser("https://chatgpt.com", profile_dir=None)
    page = FakePage()
    page.url = "https://chatgpt.com/auth/login"
    page.text = "Log in"

    assert browser.is_authenticated(page) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_managed_browser.py -v`
Expected: FAIL with missing `ManagedBrowser`

- [ ] **Step 3: Write the minimal managed browser implementation**

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ManagedBrowser:
    base_url: str
    profile_dir: Path | None

    def prepare_switch(
        self,
        context,
        page,
        *,
        session_token: str,
        csrf_token: str | None,
    ) -> None:
        context.clear_cookies()
        cookies = [
            {
                "name": "__Secure-next-auth.session-token",
                "value": session_token,
                "domain": ".chatgpt.com",
                "path": "/",
            }
        ]
        if csrf_token is not None:
            cookies.append(
                {
                    "name": "__Host-next-auth.csrf-token",
                    "value": csrf_token,
                    "domain": "chatgpt.com",
                    "path": "/",
                }
            )
        context.add_cookies(cookies)
        page.goto(self.base_url)

    def is_authenticated(self, page) -> bool:
        lowered_url = getattr(page, "url", "").lower()
        body = page.locator("body").inner_text().lower()
        if any(marker in lowered_url for marker in ("/login", "/signin", "/auth")):
            return False
        return "log in" not in body and "sign in" not in body
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_managed_browser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add switchgpt/managed_browser.py tests/test_managed_browser.py
git commit -m "feat: add managed browser switching adapter"
```

## Task 5: Build The Switch Service And Prove Metadata Safety Rules

**Files:**
- Create: `switchgpt/switch_service.py`
- Create: `tests/test_switch_service.py`

- [ ] **Step 1: Write the failing switch service tests**

```python
from datetime import UTC, datetime

import pytest

from switchgpt.models import AccountRecord, AccountState
from switchgpt.secret_store import SessionSecret
from switchgpt.switch_history import SwitchEvent
from switchgpt.switch_service import SwitchService


class FakeAccountStore:
    def __init__(self, accounts, active_account_index=None) -> None:
        self._snapshot = type(
            "Snapshot",
            (),
            {
                "accounts": accounts,
                "active_account_index": active_account_index,
                "last_switch_at": None,
            },
        )()
        self.saved_runtime_state = None

    def load(self):
        return self._snapshot

    def get_record(self, index: int):
        for account in self._snapshot.accounts:
            if account.index == index:
                return account
        raise ValueError(index)

    def save_runtime_state(self, active_account_index, switched_at):
        self.saved_runtime_state = (active_account_index, switched_at)


class FakeSecretStore:
    def __init__(self, secret):
        self._secret = secret

    def read(self, key: str):
        return self._secret


class FakeManagedBrowser:
    def __init__(self, authenticated=True) -> None:
        self.authenticated = authenticated
        self.prepared = []

    def ensure_runtime(self):
        return "context", "page"

    def prepare_switch(self, context, page, *, session_token: str, csrf_token: str | None) -> None:
        self.prepared.append((session_token, csrf_token))

    def is_authenticated(self, page) -> bool:
        return self.authenticated


class FakeHistoryStore:
    def __init__(self) -> None:
        self.events = []

    def append(self, event: SwitchEvent) -> None:
        self.events.append(event)


def build_account(index: int, email: str) -> AccountRecord:
    now = datetime(2026, 4, 16, 11, 15, tzinfo=UTC)
    return AccountRecord(
        index=index,
        email=email,
        keychain_key=f"switchgpt_account_{index}",
        registered_at=now,
        last_reauth_at=now,
        last_validated_at=now,
        status=AccountState.REGISTERED,
        last_error=None,
    )


def test_switch_to_explicit_account_updates_active_state_and_history() -> None:
    service = SwitchService(
        account_store=FakeAccountStore([build_account(0, "a@example.com"), build_account(1, "b@example.com")], active_account_index=0),
        secret_store=FakeSecretStore(SessionSecret(session_token="session-2", csrf_token="csrf-2")),
        managed_browser=FakeManagedBrowser(authenticated=True),
        history_store=FakeHistoryStore(),
    )

    result = service.switch_to(index=1)

    assert result.account.index == 1
    assert result.mode == "explicit-target"
    assert service._account_store.saved_runtime_state[0] == 1
    assert service._history_store.events[-1].result == "success"


def test_switch_next_uses_first_registered_account_not_current() -> None:
    service = SwitchService(
        account_store=FakeAccountStore([build_account(0, "a@example.com"), build_account(1, "b@example.com")], active_account_index=0),
        secret_store=FakeSecretStore(SessionSecret(session_token="session-2", csrf_token=None)),
        managed_browser=FakeManagedBrowser(authenticated=True),
        history_store=FakeHistoryStore(),
    )

    result = service.switch_next()

    assert result.account.index == 1
    assert result.mode == "auto-target"


def test_failed_auth_verification_does_not_update_active_account() -> None:
    service = SwitchService(
        account_store=FakeAccountStore([build_account(0, "a@example.com"), build_account(1, "b@example.com")], active_account_index=0),
        secret_store=FakeSecretStore(SessionSecret(session_token="session-2", csrf_token=None)),
        managed_browser=FakeManagedBrowser(authenticated=False),
        history_store=FakeHistoryStore(),
    )

    with pytest.raises(Exception):
        service.switch_to(index=1)

    assert service._account_store.saved_runtime_state is None
    assert service._history_store.events[-1].result == "needs-reauth"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_switch_service.py -v`
Expected: FAIL with missing `SwitchService`

- [ ] **Step 3: Write the minimal switch service implementation**

```python
from dataclasses import dataclass
from datetime import UTC, datetime

from .errors import SwitchError
from .switch_history import SwitchEvent


@dataclass(frozen=True)
class SwitchResult:
    account: object
    mode: str


class SwitchService:
    def __init__(self, account_store, secret_store, managed_browser, history_store) -> None:
        self._account_store = account_store
        self._secret_store = secret_store
        self._managed_browser = managed_browser
        self._history_store = history_store

    def switch_next(self) -> SwitchResult:
        snapshot = self._account_store.load()
        candidates = [
            account
            for account in snapshot.accounts
            if account.index != snapshot.active_account_index
        ]
        if not candidates:
            raise SwitchError("No alternative registered account is available for switching.")
        return self._switch_account(candidates[0], mode="auto-target")

    def switch_to(self, index: int) -> SwitchResult:
        account = self._account_store.get_record(index)
        return self._switch_account(account, mode="explicit-target")

    def _switch_account(self, account, *, mode: str) -> SwitchResult:
        previous_active_index = self._account_store.load().active_account_index
        secret = self._secret_store.read(account.keychain_key)
        if secret is None:
            raise SwitchError(f"Stored session secret is missing for slot {account.index}.")
        occurred_at = datetime.now(UTC)
        context, page = self._managed_browser.ensure_runtime()
        self._managed_browser.prepare_switch(
            context,
            page,
            session_token=secret.session_token,
            csrf_token=secret.csrf_token,
        )
        if not self._managed_browser.is_authenticated(page):
            self._history_store.append(
                SwitchEvent(
                    occurred_at=occurred_at,
                    from_account_index=previous_active_index,
                    to_account_index=account.index,
                    mode=mode,
                    result="needs-reauth",
                    message=f"Authenticated state verification failed for slot {account.index}.",
                )
            )
            raise SwitchError(f"Account slot {account.index} likely needs reauthentication.")
        self._account_store.save_runtime_state(account.index, occurred_at)
        self._history_store.append(
            SwitchEvent(
                occurred_at=occurred_at,
                from_account_index=previous_active_index,
                to_account_index=account.index,
                mode=mode,
                result="success",
                message=None,
            )
        )
        return SwitchResult(account=account, mode=mode)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_switch_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add switchgpt/switch_service.py tests/test_switch_service.py
git commit -m "feat: add manual switch orchestration service"
```

## Task 6: Wire The Real CLI Commands For `open` And `switch`

**Files:**
- Modify: `switchgpt/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

```python
from typer.testing import CliRunner

from switchgpt.cli import app


runner = CliRunner()


def test_switch_command_reports_selected_account(monkeypatch) -> None:
    class FakeService:
        def switch_next(self):
            class Result:
                mode = "auto-target"

                class Account:
                    index = 1
                    email = "account2@example.com"

                account = Account()

            return Result()

    monkeypatch.setattr("switchgpt.cli.build_switch_service", lambda: FakeService())

    result = runner.invoke(app, ["switch"])

    assert result.exit_code == 0
    assert "Switched to account2@example.com in slot 1." in result.stdout


def test_open_command_reports_managed_workspace_ready(monkeypatch) -> None:
    class FakeManagedBrowser:
        def open_workspace(self):
            return None

    monkeypatch.setattr("switchgpt.cli.build_managed_browser", lambda: FakeManagedBrowser())

    result = runner.invoke(app, ["open"])

    assert result.exit_code == 0
    assert "Managed ChatGPT workspace is ready." in result.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with missing `switch` or `open` commands, or missing builders

- [ ] **Step 3: Write the minimal CLI wiring**

```python
from .managed_browser import ManagedBrowser
from .switch_history import SwitchHistoryStore
from .switch_service import SwitchService


def build_managed_browser() -> ManagedBrowser:
    settings = Settings.from_env()
    return ManagedBrowser(
        base_url=settings.chatgpt_base_url,
        profile_dir=settings.managed_profile_dir,
    )


def build_switch_service() -> SwitchService:
    settings = Settings.from_env()
    store = AccountStore(settings.metadata_path, settings.slot_count)
    secret_store = KeychainSecretStore(settings.keychain_service)
    managed_browser = build_managed_browser()
    history_store = SwitchHistoryStore(settings.switch_history_path)
    return SwitchService(store, secret_store, managed_browser, history_store)


@app.command()
def open() -> None:
    try:
        ensure_supported_platform()
        build_managed_browser().open_workspace()
        print("Managed ChatGPT workspace is ready.")
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def switch(to: int | None = typer.Option(None, "--to")) -> None:
    try:
        ensure_supported_platform()
        service = build_switch_service()
        result = service.switch_next() if to is None else service.switch_to(to)
        print(f"Switched to {result.account.email} in slot {result.account.index}.")
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add switchgpt/cli.py tests/test_cli.py
git commit -m "feat: add manual switch and open cli commands"
```

## Task 7: Replace The Minimal Browser Stub With The Real Persistent Playwright Runtime

**Files:**
- Modify: `switchgpt/managed_browser.py`
- Modify: `tests/test_managed_browser.py`

- [ ] **Step 1: Write the failing runtime test**

```python
from pathlib import Path

from switchgpt.managed_browser import ManagedBrowser


def test_open_workspace_creates_profile_dir_and_returns_runtime_handles(tmp_path, monkeypatch) -> None:
    launched = {}

    class FakePage:
        def goto(self, url: str) -> None:
            launched["goto"] = url

    class FakeBrowserContext:
        def __init__(self) -> None:
            self.pages = []

        def new_page(self):
            return FakePage()

    class FakeChromium:
        def launch_persistent_context(self, profile_dir: str, headless: bool):
            launched["profile_dir"] = profile_dir
            launched["headless"] = headless
            return FakeBrowserContext()

    class FakePlaywrightHandle:
        chromium = FakeChromium()

    class FakePlaywrightFactory:
        def start(self):
            return FakePlaywrightHandle()

    monkeypatch.setattr("switchgpt.managed_browser.sync_playwright", lambda: FakePlaywrightFactory())

    browser = ManagedBrowser("https://chatgpt.com", profile_dir=tmp_path / "profile")
    context, page = browser.open_workspace()

    assert Path(launched["profile_dir"]) == tmp_path / "profile"
    assert launched["headless"] is False
    assert launched["goto"] == "https://chatgpt.com"
    assert context is not None
    assert page is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_managed_browser.py::test_open_workspace_creates_profile_dir_and_returns_runtime_handles -v`
Expected: FAIL with missing `open_workspace` or missing Playwright launch logic

- [ ] **Step 3: Write the real persistent-context implementation**

```python
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import sync_playwright

from .errors import ManagedBrowserError


@dataclass
class ManagedBrowser:
    base_url: str
    profile_dir: Path
    _playwright: object | None = field(default=None, init=False, repr=False)
    _context: object | None = field(default=None, init=False, repr=False)
    _page: object | None = field(default=None, init=False, repr=False)

    def open_workspace(self):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        if self._context is None:
            self._playwright = sync_playwright().start()
            try:
                self._context = self._playwright.chromium.launch_persistent_context(
                    str(self.profile_dir),
                    headless=False,
                )
            except Exception as exc:
                raise ManagedBrowserError("Unable to launch the managed ChatGPT browser workspace.") from exc
        if self._page is None:
            pages = list(self._context.pages)
            self._page = pages[0] if pages else self._context.new_page()
        self._page.goto(self.base_url)
        return self._context, self._page

    def ensure_runtime(self):
        return self.open_workspace()
```

- [ ] **Step 4: Run the browser adapter tests to verify they pass**

Run: `uv run pytest tests/test_managed_browser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add switchgpt/managed_browser.py tests/test_managed_browser.py
git commit -m "feat: launch managed persistent browser workspace"
```

## Task 8: Add Manual Verification Coverage And Run The Phase 2 Test Suite

**Files:**
- Create: `docs/manual-tests/2026-04-16-phase-2-manual-session-switching.md`

- [ ] **Step 1: Write the manual verification checklist**

```md
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
```

- [ ] **Step 2: Run the automated Phase 2 test suite**

Run: `uv run pytest tests/test_config.py tests/test_account_store.py tests/test_switch_history.py tests/test_managed_browser.py tests/test_switch_service.py tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add docs/manual-tests/2026-04-16-phase-2-manual-session-switching.md
git commit -m "docs: add phase 2 manual switching verification checklist"
```

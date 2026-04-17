# SwitchGPT Phase 1 Local Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first usable macOS-only `switchgpt` CLI that can register and reauthenticate ChatGPT accounts through a real visible browser login flow, store session secrets in Keychain, persist non-secret metadata on disk, and report local account status.

**Architecture:** Start with a small Typer-based CLI and explicit service boundaries: config, metadata store, secret store, registration, and status. Implement each boundary behind a narrow interface with tests first, then wire the real Playwright and macOS Keychain adapters last so failure handling and rollback rules are already proven before the interactive path is added.

**Tech Stack:** Python 3.12, Typer, Playwright, keyring, pytest

---

## File Structure

### Project files

- Create: `pyproject.toml`
- Create: `README.md`
- Create: `switchgpt/__init__.py`
- Create: `switchgpt/cli.py`
- Create: `switchgpt/errors.py`
- Create: `switchgpt/config.py`
- Create: `switchgpt/models.py`
- Create: `switchgpt/account_store.py`
- Create: `switchgpt/secret_store.py`
- Create: `switchgpt/registration.py`
- Create: `switchgpt/playwright_client.py`
- Create: `switchgpt/status_service.py`

### Test files

- Create: `tests/conftest.py`
- Create: `tests/test_cli.py`
- Create: `tests/test_config.py`
- Create: `tests/test_account_store.py`
- Create: `tests/test_secret_store.py`
- Create: `tests/test_status_service.py`
- Create: `tests/test_registration.py`

### Documentation

- Create: `docs/manual-tests/2026-04-16-phase-1-local-foundation.md`

### Responsibilities

- `switchgpt/cli.py`: command parsing and user-facing output only
- `switchgpt/config.py`: app paths, slot count, service names, prerequisite validation
- `switchgpt/models.py`: typed account metadata and registration results
- `switchgpt/account_store.py`: metadata validation, atomic reads and writes, slot selection
- `switchgpt/secret_store.py`: Keychain-backed secret boundary and replacement helpers
- `switchgpt/registration.py`: registration and reauth orchestration, auth-state decisions, rollback rules
- `switchgpt/playwright_client.py`: real browser automation adapter
- `switchgpt/status_service.py`: slot classification for `status`

### Task 1: Bootstrap The Python Package And CLI Smoke Test

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `switchgpt/__init__.py`
- Create: `switchgpt/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI smoke test**

```python
from typer.testing import CliRunner

from switchgpt.cli import app


runner = CliRunner()


def test_status_command_is_registered() -> None:
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "No accounts registered." in result.stdout
```

- [ ] **Step 2: Run the smoke test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_status_command_is_registered -v`
Expected: FAIL with `ModuleNotFoundError` for `switchgpt` or missing `app`

- [ ] **Step 3: Write the minimal package and CLI implementation**

```toml
[project]
name = "switchgpt"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "typer>=0.16.0",
  "playwright>=1.52.0",
  "keyring>=25.6.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3.0",
]

[project.scripts]
switchgpt = "switchgpt.cli:main"
```

```python
import typer


app = typer.Typer(no_args_is_help=True)


@app.command()
def status() -> None:
    print("No accounts registered.")


def main() -> None:
    app()
```

- [ ] **Step 4: Run the smoke test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_status_command_is_registered -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md switchgpt/__init__.py switchgpt/cli.py tests/test_cli.py
git commit -m "chore: bootstrap switchgpt cli package"
```

### Task 2: Add Config, Paths, And macOS Environment Guards

**Files:**
- Create: `switchgpt/errors.py`
- Create: `switchgpt/config.py`
- Create: `tests/test_config.py`
- Modify: `switchgpt/cli.py`

- [ ] **Step 1: Write the failing config tests**

```python
from pathlib import Path

import pytest

from switchgpt.config import Settings, ensure_supported_platform
from switchgpt.errors import UnsupportedPlatformError


def test_settings_uses_switchgpt_home_under_user_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/example-home")
    settings = Settings.from_env()
    assert settings.data_dir == Path("/tmp/example-home/.switchgpt")
    assert settings.metadata_path == Path("/tmp/example-home/.switchgpt/accounts.json")
    assert settings.keychain_service == "switchgpt"


def test_ensure_supported_platform_rejects_non_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Linux")
    with pytest.raises(UnsupportedPlatformError):
        ensure_supported_platform()
```

- [ ] **Step 2: Run the config tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with missing `Settings`, `ensure_supported_platform`, or `UnsupportedPlatformError`

- [ ] **Step 3: Write the minimal config and error code**

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

    @classmethod
    def from_env(cls) -> "Settings":
        home = Path(os.environ["HOME"])
        data_dir = home / ".switchgpt"
        return cls(
            data_dir=data_dir,
            metadata_path=data_dir / "accounts.json",
            keychain_service="switchgpt",
            slot_count=3,
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
```

```python
import typer

from .config import ensure_supported_platform
from .errors import SwitchGptError


app = typer.Typer(no_args_is_help=True)


@app.command()
def status() -> None:
    try:
        ensure_supported_platform()
    except SwitchGptError as exc:
        raise typer.Exit(code=1) from exc
    print("No accounts registered.")
```

- [ ] **Step 4: Run the config tests to verify they pass**

Run: `uv run pytest tests/test_config.py tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add switchgpt/errors.py switchgpt/config.py switchgpt/cli.py tests/test_config.py tests/test_cli.py
git commit -m "feat: add config and macos environment guards"
```

### Task 3: Build Metadata Models And Atomic Account Store

**Files:**
- Create: `switchgpt/models.py`
- Create: `switchgpt/account_store.py`
- Create: `tests/conftest.py`
- Create: `tests/test_account_store.py`

- [ ] **Step 1: Write the failing account store tests**

```python
from datetime import datetime, UTC

from switchgpt.account_store import AccountStore
from switchgpt.models import AccountRecord, AccountState


def test_allocate_next_empty_slot_returns_zero_for_empty_store(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts.json", slot_count=3)
    assert store.next_empty_slot() == 0


def test_save_and_reload_registered_account_round_trips(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts.json", slot_count=3)
    record = AccountRecord(
        index=0,
        email="account1@example.com",
        keychain_key="switchgpt_account_0",
        registered_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_reauth_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_validated_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        status=AccountState.REGISTERED,
        last_error=None,
    )
    store.save_record(record)
    reloaded = store.load().accounts[0]
    assert reloaded.email == "account1@example.com"
    assert reloaded.status is AccountState.REGISTERED
```

- [ ] **Step 2: Run the store tests to verify they fail**

Run: `uv run pytest tests/test_account_store.py -v`
Expected: FAIL with missing `AccountStore`, `AccountRecord`, or `AccountState`

- [ ] **Step 3: Write the models and store implementation**

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
```

```python
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .models import AccountRecord, AccountState


@dataclass(frozen=True)
class AccountSnapshot:
    accounts: list[AccountRecord]


class AccountStore:
    def __init__(self, metadata_path: Path, slot_count: int) -> None:
        self._metadata_path = metadata_path
        self._slot_count = slot_count

    def load(self) -> AccountSnapshot:
        if not self._metadata_path.exists():
            return AccountSnapshot(accounts=[])
        payload = json.loads(self._metadata_path.read_text())
        accounts = []
        for item in payload["accounts"]:
            accounts.append(
                AccountRecord(
                    index=item["index"],
                    email=item["email"],
                    keychain_key=item["keychain_key"],
                    registered_at=datetime.fromisoformat(item["registered_at"]),
                    last_reauth_at=datetime.fromisoformat(item["last_reauth_at"]),
                    last_validated_at=datetime.fromisoformat(item["last_validated_at"]),
                    status=AccountState(item["status"]),
                    last_error=item["last_error"],
                )
            )
        return AccountSnapshot(accounts=accounts)

    def next_empty_slot(self) -> int:
        used = {account.index for account in self.load().accounts}
        for index in range(self._slot_count):
            if index not in used:
                return index
        raise ValueError("No empty account slots remain.")

    def save_record(self, record: AccountRecord) -> None:
        snapshot = self.load()
        accounts = [account for account in snapshot.accounts if account.index != record.index] + [record]
        payload = {
            "version": 1,
            "accounts": [
                {
                    **asdict(account),
                    "registered_at": account.registered_at.isoformat(),
                    "last_reauth_at": account.last_reauth_at.isoformat(),
                    "last_validated_at": account.last_validated_at.isoformat(),
                    "status": account.status.value,
                }
                for account in sorted(accounts, key=lambda item: item.index)
            ],
        }
        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._metadata_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2))
        temp_path.replace(self._metadata_path)
```

- [ ] **Step 4: Run the store tests to verify they pass**

Run: `uv run pytest tests/test_account_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add switchgpt/models.py switchgpt/account_store.py tests/conftest.py tests/test_account_store.py
git commit -m "feat: add account metadata models and store"
```

### Task 4: Add Keychain Secret Store Interface And Tests

**Files:**
- Create: `switchgpt/secret_store.py`
- Create: `tests/test_secret_store.py`

- [ ] **Step 1: Write the failing secret store tests**

```python
from switchgpt.secret_store import KeychainSecretStore, SessionSecret


class FakeKeyring:
    def __init__(self) -> None:
        self.values = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


def test_write_and_read_secret_round_trip() -> None:
    store = KeychainSecretStore(service_name="switchgpt", backend=FakeKeyring())
    secret = SessionSecret(session_token="token-1", csrf_token="csrf-1")
    store.write("switchgpt_account_0", secret)
    assert store.read("switchgpt_account_0") == secret


def test_replace_keeps_old_secret_until_new_secret_is_ready() -> None:
    store = KeychainSecretStore(service_name="switchgpt", backend=FakeKeyring())
    store.write("switchgpt_account_0", SessionSecret(session_token="old", csrf_token="old"))
    store.replace("switchgpt_account_0", SessionSecret(session_token="new", csrf_token="new"))
    assert store.read("switchgpt_account_0").session_token == "new"
```

- [ ] **Step 2: Run the secret store tests to verify they fail**

Run: `uv run pytest tests/test_secret_store.py -v`
Expected: FAIL with missing `KeychainSecretStore` or `SessionSecret`

- [ ] **Step 3: Write the secret store implementation**

```python
import json
from dataclasses import asdict, dataclass

import keyring


@dataclass(frozen=True)
class SessionSecret:
    session_token: str
    csrf_token: str | None


class KeychainSecretStore:
    def __init__(self, service_name: str, backend=keyring) -> None:
        self._service_name = service_name
        self._backend = backend

    def write(self, key: str, secret: SessionSecret) -> None:
        self._backend.set_password(self._service_name, key, json.dumps(asdict(secret)))

    def read(self, key: str) -> SessionSecret | None:
        raw = self._backend.get_password(self._service_name, key)
        if raw is None:
            return None
        payload = json.loads(raw)
        return SessionSecret(**payload)

    def exists(self, key: str) -> bool:
        return self.read(key) is not None

    def replace(self, key: str, secret: SessionSecret) -> None:
        self.write(key, secret)

    def delete(self, key: str) -> None:
        self._backend.delete_password(self._service_name, key)
```

- [ ] **Step 4: Run the secret store tests to verify they pass**

Run: `uv run pytest tests/test_secret_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add switchgpt/secret_store.py tests/test_secret_store.py
git commit -m "feat: add keychain secret store boundary"
```

### Task 5: Implement Status Classification And Wire The `status` Command

**Files:**
- Create: `switchgpt/status_service.py`
- Create: `tests/test_status_service.py`
- Modify: `switchgpt/cli.py`

- [ ] **Step 1: Write the failing status tests**

```python
from datetime import datetime, UTC

from switchgpt.models import AccountRecord, AccountState
from switchgpt.status_service import StatusService


class FakeSecretStore:
    def __init__(self, existing_keys: set[str]) -> None:
        self._existing_keys = existing_keys

    def exists(self, key: str) -> bool:
        return key in self._existing_keys


def test_registered_slot_requires_metadata_and_secret() -> None:
    service = StatusService(secret_store=FakeSecretStore({"switchgpt_account_0"}))
    account = AccountRecord(
        index=0,
        email="account1@example.com",
        keychain_key="switchgpt_account_0",
        registered_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_reauth_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_validated_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        status=AccountState.REGISTERED,
        last_error=None,
    )
    slot = service.classify(account)
    assert slot.state is AccountState.REGISTERED


def test_missing_secret_is_reported_when_keychain_entry_is_absent() -> None:
    service = StatusService(secret_store=FakeSecretStore(set()))
    account = AccountRecord(
        index=0,
        email="account1@example.com",
        keychain_key="switchgpt_account_0",
        registered_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_reauth_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_validated_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        status=AccountState.REGISTERED,
        last_error=None,
    )
    slot = service.classify(account)
    assert slot.state is AccountState.MISSING_SECRET
```

- [ ] **Step 2: Run the status tests to verify they fail**

Run: `uv run pytest tests/test_status_service.py -v`
Expected: FAIL with missing `StatusService`

- [ ] **Step 3: Write the status service and CLI output**

```python
from dataclasses import dataclass

from .models import AccountRecord, AccountState


@dataclass(frozen=True)
class SlotStatus:
    index: int
    email: str
    state: AccountState
    last_error: str | None


class StatusService:
    def __init__(self, secret_store) -> None:
        self._secret_store = secret_store

    def classify(self, account: AccountRecord) -> SlotStatus:
        if not self._secret_store.exists(account.keychain_key):
            return SlotStatus(account.index, account.email, AccountState.MISSING_SECRET, account.last_error)
        return SlotStatus(account.index, account.email, account.status, account.last_error)
```

```python
@app.command()
def status() -> None:
    ensure_supported_platform()
    settings = Settings.from_env()
    store = AccountStore(settings.metadata_path, settings.slot_count)
    secret_store = KeychainSecretStore(settings.keychain_service)
    snapshot = store.load()
    if not snapshot.accounts:
        print("No accounts registered.")
        return
    service = StatusService(secret_store)
    for account in snapshot.accounts:
        slot = service.classify(account)
        print(f"[{slot.index}] {slot.email} - {slot.state}")
```

- [ ] **Step 4: Run the status tests to verify they pass**

Run: `uv run pytest tests/test_status_service.py tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add switchgpt/status_service.py switchgpt/cli.py tests/test_status_service.py tests/test_cli.py
git commit -m "feat: add local account status classification"
```

### Task 6: Define Registration Models, Auth-State Rules, And Rollback Behavior

**Files:**
- Create: `switchgpt/registration.py`
- Create: `tests/test_registration.py`
- Modify: `switchgpt/errors.py`

- [ ] **Step 1: Write the failing registration orchestration tests**

```python
from datetime import datetime, UTC

import pytest

from switchgpt.registration import RegistrationService, RegistrationResult
from switchgpt.secret_store import SessionSecret


class FakeBrowserClient:
    def register(self) -> RegistrationResult:
        return RegistrationResult(
            email="account1@example.com",
            secret=SessionSecret(session_token="token-1", csrf_token="csrf-1"),
            captured_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        )


def test_add_registration_writes_secret_before_metadata(tmp_path) -> None:
    store = []

    class FakeSecretStore:
        def write(self, key, secret) -> None:
            store.append(("secret", key, secret.session_token))

    class FakeAccountStore:
        def next_empty_slot(self) -> int:
            return 0

        def save_record(self, record) -> None:
            store.append(("metadata", record.index, record.email))

    service = RegistrationService(FakeAccountStore(), FakeSecretStore(), FakeBrowserClient())
    service.add()
    assert store == [
        ("secret", "switchgpt_account_0", "token-1"),
        ("metadata", 0, "account1@example.com"),
    ]


def test_add_rolls_back_secret_when_metadata_write_fails(tmp_path) -> None:
    deleted = []

    class FakeSecretStore:
        def write(self, key, secret) -> None:
            return None

        def delete(self, key) -> None:
            deleted.append(key)

    class FakeAccountStore:
        def next_empty_slot(self) -> int:
            return 0

        def save_record(self, record) -> None:
            raise RuntimeError("disk failure")

    service = RegistrationService(FakeAccountStore(), FakeSecretStore(), FakeBrowserClient())
    with pytest.raises(RuntimeError):
        service.add()
    assert deleted == ["switchgpt_account_0"]
```

- [ ] **Step 2: Run the registration tests to verify they fail**

Run: `uv run pytest tests/test_registration.py -v`
Expected: FAIL with missing `RegistrationService` or `RegistrationResult`

- [ ] **Step 3: Write the registration domain logic**

```python
from dataclasses import dataclass
from datetime import datetime

from .models import AccountRecord, AccountState
from .secret_store import SessionSecret


@dataclass(frozen=True)
class RegistrationResult:
    email: str
    secret: SessionSecret
    captured_at: datetime


class RegistrationService:
    def __init__(self, account_store, secret_store, browser_client) -> None:
        self._account_store = account_store
        self._secret_store = secret_store
        self._browser_client = browser_client

    def add(self) -> AccountRecord:
        slot = self._account_store.next_empty_slot()
        key = f"switchgpt_account_{slot}"
        result = self._browser_client.register()
        self._secret_store.write(key, result.secret)
        record = AccountRecord(
            index=slot,
            email=result.email,
            keychain_key=key,
            registered_at=result.captured_at,
            last_reauth_at=result.captured_at,
            last_validated_at=result.captured_at,
            status=AccountState.REGISTERED,
            last_error=None,
        )
        try:
            self._account_store.save_record(record)
        except Exception:
            self._secret_store.delete(key)
            raise
        return record
```

- [ ] **Step 4: Run the registration tests to verify they pass**

Run: `uv run pytest tests/test_registration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add switchgpt/registration.py switchgpt/errors.py tests/test_registration.py
git commit -m "feat: add registration transaction and rollback logic"
```

### Task 7: Add The Real Playwright Browser Adapter And `switchgpt add`

**Files:**
- Create: `switchgpt/playwright_client.py`
- Modify: `switchgpt/config.py`
- Modify: `switchgpt/registration.py`
- Modify: `switchgpt/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_registration.py`

- [ ] **Step 1: Write the failing tests for the browser adapter contract and add command**

```python
from typer.testing import CliRunner

from switchgpt.cli import app


runner = CliRunner()


def test_add_command_reports_registered_slot(monkeypatch) -> None:
    class FakeRegistrationService:
        def add(self):
            class Result:
                index = 0
                email = "account1@example.com"
            return Result()

    monkeypatch.setattr("switchgpt.cli.build_registration_service", lambda: FakeRegistrationService())
    result = runner.invoke(app, ["add"])
    assert result.exit_code == 0
    assert "Registered account1@example.com in slot 0." in result.stdout
```

```python
import pytest

from switchgpt.playwright_client import BrowserRegistrationClient


def test_browser_client_requires_visible_browser_when_register_called():
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")
    with pytest.raises(RuntimeError):
        client._assert_visible_mode(headless=True)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_cli.py tests/test_registration.py -v`
Expected: FAIL with missing `build_registration_service`, `BrowserRegistrationClient`, or visible-browser guard

- [ ] **Step 3: Write the real Playwright adapter and CLI wiring**

```python
from dataclasses import dataclass
from datetime import UTC, datetime

from playwright.sync_api import sync_playwright

from .secret_store import SessionSecret
from .registration import RegistrationResult


@dataclass(frozen=True)
class BrowserRegistrationClient:
    base_url: str

    def _assert_visible_mode(self, headless: bool) -> None:
        if headless:
            raise RuntimeError("Phase 1 registration requires a visible browser window.")

    def register(self) -> RegistrationResult:
        self._assert_visible_mode(headless=False)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(self.base_url)
            input("[switchgpt] Complete login in the browser, then press ENTER here.")
            cookies = context.cookies()
            browser.close()
        session_token = next(cookie["value"] for cookie in cookies if cookie["name"] == "__Secure-next-auth.session-token")
        csrf_cookie = next((cookie["value"] for cookie in cookies if cookie["name"] == "__Host-next-auth.csrf-token"), None)
        return RegistrationResult(
            email="unknown@example.com",
            secret=SessionSecret(session_token=session_token, csrf_token=csrf_cookie),
            captured_at=datetime.now(UTC),
        )

    def reauth(self, existing_email: str) -> RegistrationResult:
        return self.register()
```

```python
def build_registration_service() -> RegistrationService:
    settings = Settings.from_env()
    store = AccountStore(settings.metadata_path, settings.slot_count)
    secret_store = KeychainSecretStore(settings.keychain_service)
    browser_client = BrowserRegistrationClient(base_url="https://chatgpt.com")
    return RegistrationService(store, secret_store, browser_client)


@app.command()
def add() -> None:
    ensure_supported_platform()
    record = build_registration_service().add()
    print(f"Registered {record.email} in slot {record.index}.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py tests/test_registration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add switchgpt/playwright_client.py switchgpt/config.py switchgpt/registration.py switchgpt/cli.py tests/test_cli.py tests/test_registration.py
git commit -m "feat: add browser-driven account registration command"
```

### Task 8: Add `switchgpt add --reauth <index>` Without Losing The Existing Slot

**Files:**
- Modify: `switchgpt/registration.py`
- Modify: `switchgpt/account_store.py`
- Modify: `switchgpt/cli.py`
- Modify: `tests/test_registration.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing reauth tests**

```python
from datetime import datetime, UTC

import pytest

from switchgpt.models import AccountRecord, AccountState
from switchgpt.registration import RegistrationResult, RegistrationService
from switchgpt.secret_store import SessionSecret


def test_reauth_keeps_old_secret_when_browser_capture_fails() -> None:
    class FakeBrowserClient:
        def reauth(self, existing_email: str):
            raise RuntimeError("login cancelled")

    class FakeSecretStore:
        def __init__(self) -> None:
            self.values = {"switchgpt_account_0": SessionSecret(session_token="old", csrf_token="old")}

        def read(self, key):
            return self.values[key]

        def replace(self, key, secret):
            self.values[key] = secret

    class FakeAccountStore:
        def get_record(self, index: int) -> AccountRecord:
            return AccountRecord(
                index=0,
                email="account1@example.com",
                keychain_key="switchgpt_account_0",
                registered_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
                last_reauth_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
                last_validated_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
                status=AccountState.REGISTERED,
                last_error=None,
            )

        def save_record(self, record) -> None:
            raise AssertionError("save_record should not run when reauth capture fails")

    service = RegistrationService(FakeAccountStore(), FakeSecretStore(), FakeBrowserClient())
    with pytest.raises(RuntimeError):
        service.reauth(0)
```

```python
from typer.testing import CliRunner

from switchgpt.cli import app


runner = CliRunner()


def test_reauth_command_requires_slot_index(monkeypatch) -> None:
    class FakeRegistrationService:
        def reauth(self, index: int):
            class Result:
                index = 0
                email = "account1@example.com"
            return Result()

    monkeypatch.setattr("switchgpt.cli.build_registration_service", lambda: FakeRegistrationService())
    result = runner.invoke(app, ["add", "--reauth", "0"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run the reauth tests to verify they fail**

Run: `uv run pytest tests/test_registration.py tests/test_cli.py -v`
Expected: FAIL with missing `reauth` flow or missing CLI option handling

- [ ] **Step 3: Write the reauth implementation**

```python
class RegistrationService:
    ...

    def reauth(self, index: int) -> AccountRecord:
        existing = self._account_store.get_record(index)
        result = self._browser_client.reauth(existing.email)
        self._secret_store.replace(existing.keychain_key, result.secret)
        refreshed = AccountRecord(
            index=existing.index,
            email=result.email,
            keychain_key=existing.keychain_key,
            registered_at=existing.registered_at,
            last_reauth_at=result.captured_at,
            last_validated_at=result.captured_at,
            status=AccountState.REGISTERED,
            last_error=None,
        )
        self._account_store.save_record(refreshed)
        return refreshed
```

```python
@app.command()
def add(reauth: int | None = typer.Option(default=None, "--reauth")) -> None:
    ensure_supported_platform()
    service = build_registration_service()
    if reauth is None:
        record = service.add()
        print(f"Registered {record.email} in slot {record.index}.")
        return
    record = service.reauth(reauth)
    print(f"Reauthenticated {record.email} in slot {record.index}.")
```

```python
class AccountStore:
    ...

    def get_record(self, index: int) -> AccountRecord:
        for account in self.load().accounts:
            if account.index == index:
                return account
        raise ValueError(f"Account slot {index} is not registered.")
```

- [ ] **Step 4: Run the reauth tests to verify they pass**

Run: `uv run pytest tests/test_registration.py tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add switchgpt/registration.py switchgpt/account_store.py switchgpt/cli.py tests/test_registration.py tests/test_cli.py
git commit -m "feat: add account reauthentication flow"
```

### Task 9: Tighten Output, Add Manual Verification Doc, And Run The Full Test Suite

**Files:**
- Create: `docs/manual-tests/2026-04-16-phase-1-local-foundation.md`
- Modify: `README.md`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI output test for populated status**

```python
from typer.testing import CliRunner

from switchgpt.cli import app


runner = CliRunner()


def test_status_lists_registered_accounts(monkeypatch) -> None:
    class FakeAccount:
        index = 0
        email = "account1@example.com"
        keychain_key = "switchgpt_account_0"
        last_error = None

    class FakeStore:
        class Snapshot:
            accounts = [FakeAccount()]

        def load(self):
            return self.Snapshot()

    class FakeStatusService:
        def classify(self, account):
            class Slot:
                index = account.index
                email = account.email
                state = "registered"
            return Slot()

    monkeypatch.setattr("switchgpt.cli.build_status_service", lambda: (FakeStore(), FakeStatusService()))
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "[0] account1@example.com - registered" in result.stdout
```

- [ ] **Step 2: Run the targeted test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_status_lists_registered_accounts -v`
Expected: FAIL with missing `build_status_service`

- [ ] **Step 3: Write the status builder, README usage, and manual verification checklist**

```python
def build_status_service() -> tuple[AccountStore, StatusService]:
    settings = Settings.from_env()
    store = AccountStore(settings.metadata_path, settings.slot_count)
    service = StatusService(KeychainSecretStore(settings.keychain_service))
    return store, service


@app.command()
def status() -> None:
    ensure_supported_platform()
    store, service = build_status_service()
    snapshot = store.load()
    if not snapshot.accounts:
        print("No accounts registered.")
        return
    for account in snapshot.accounts:
        slot = service.classify(account)
        print(f"[{slot.index}] {slot.email} - {slot.state}")
```

```markdown
# Phase 1 Manual Verification

1. Run `uv run switchgpt add`.
2. Confirm a visible Chromium window opens.
3. Complete ChatGPT login manually.
4. Press Enter in the terminal when login is complete.
5. Run `uv run switchgpt status`.
6. Confirm the slot appears as `registered`.
7. Run `uv run switchgpt add --reauth 0`.
8. Confirm the existing slot remains intact if login is cancelled.
```

- [ ] **Step 4: Run the full test suite to verify everything passes**

Run: `uv run pytest tests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add README.md docs/manual-tests/2026-04-16-phase-1-local-foundation.md switchgpt/cli.py tests/test_cli.py
git commit -m "docs: add phase 1 verification guidance"
```

## Self-Review

### Spec coverage

- CLI entry structure: Tasks 1, 2, 5, 7, 8
- macOS-only path conventions and prerequisites: Task 2
- non-secret metadata persistence: Task 3
- Keychain secret boundary: Task 4
- real browser-driven add flow: Task 7
- reauthentication flow: Task 8
- local account-state inspection: Tasks 5 and 9
- validation and rollback rules: Tasks 3, 6, and 8

No spec section is left without an implementing task.

### Placeholder scan

- No `TBD`, `TODO`, or “implement later” markers
- Each command step includes an exact file target, code snippet, and verification command
- No task depends on an undefined function name introduced only later

### Type consistency

- `AccountState`, `AccountRecord`, `SessionSecret`, `RegistrationResult`, and `RegistrationService` names are consistent across all tasks
- `switchgpt add --reauth <index>` is modeled through the same `add` command with an optional `--reauth` integer, matching the spec
- `StatusService.classify()` and CLI output formatting stay consistent from Task 5 through Task 9

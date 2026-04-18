# switchgpt Phase 4 Operational Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 4 foreground hardening so `switchgpt watch` can enter a bounded in-session reauthentication flow, `status` can explain operational readiness from metadata and recent history, and a new `doctor` command can diagnose local prerequisites without mutating account state.

**Architecture:** Preserve the Phase 3 seam. `watch_service` remains the watch-loop orchestrator, `registration` remains responsible for credential refresh and secure secret persistence, and `managed_browser` remains the narrow browser/runtime adapter. Add one new read-oriented `doctor_service`, enrich `status_service` to summarize recent history, and expand `watch_service` with explicit `reauth-required` and `resuming` transitions rather than broad auto-healing.

**Tech Stack:** Python 3, Typer CLI, Playwright sync API, pytest, macOS Keychain-backed secret storage, JSON metadata and JSONL history.

---

## File Structure

- `switchgpt/errors.py`: add specific Phase 4 error types for reauth-required and doctor failures
- `switchgpt/switch_history.py`: keep append-only JSONL history, add a helper for latest event and preserve backward-compatible loading
- `switchgpt/status_service.py`: replace single-slot classification-only logic with snapshot-level readiness summary plus slot classification
- `switchgpt/managed_browser.py`: add bounded runtime smoke-check and reauth-oriented browser helpers without absorbing policy
- `switchgpt/playwright_client.py`: add capture helpers that can reuse an existing managed page for reauthentication
- `switchgpt/registration.py`: add in-managed-workspace reauth flow while preserving secret-store rollback behavior
- `switchgpt/watch_service.py`: add explicit recovery states, typed notifications, and bounded resume behavior
- `switchgpt/doctor_service.py`: new diagnosis-only subsystem for platform, metadata, history, keychain, and runtime readiness checks
- `switchgpt/cli.py`: wire new `doctor` command and richer `status` / `watch` output
- `tests/test_status_service.py`: cover readiness summaries and recent-history guidance
- `tests/test_switch_history.py`: cover latest-event access and new recovery-oriented result categories
- `tests/test_registration.py`: cover reauth-in-managed-workspace success and rollback paths
- `tests/test_watch_service.py`: cover `reauth-required`, resume, and runtime-stop behavior
- `tests/test_cli.py`: cover `doctor`, richer `status`, and reauth/resume watch output
- `tests/test_managed_browser.py`: cover bounded runtime smoke check and reauth helpers
- `tests/test_doctor_service.py`: new service-level diagnostics coverage

### Task 1: Enrich Errors, History Access, And Status Summaries

**Files:**
- Modify: `switchgpt/errors.py`
- Modify: `switchgpt/switch_history.py`
- Modify: `switchgpt/status_service.py`
- Test: `tests/test_status_service.py`
- Test: `tests/test_switch_history.py`

- [ ] **Step 1: Write the failing status and history tests**

```python
from datetime import UTC, datetime

from switchgpt.models import AccountRecord, AccountState
from switchgpt.status_service import StatusService
from switchgpt.switch_history import SwitchEvent, SwitchHistoryStore


class FakeSecretStore:
    def __init__(self, existing_keys: set[str]) -> None:
        self._existing_keys = existing_keys

    def exists(self, key: str) -> bool:
        return key in self._existing_keys


class FakeHistoryStore:
    def __init__(self, events) -> None:
        self._events = list(events)

    def read(self):
        return list(self._events)


def build_account(index: int, state: AccountState = AccountState.REGISTERED) -> AccountRecord:
    now = datetime(2026, 4, 17, 11, 15, tzinfo=UTC)
    return AccountRecord(
        index=index,
        email=f"account{index}@example.com",
        keychain_key=f"switchgpt_account_{index}",
        registered_at=now,
        last_reauth_at=now,
        last_validated_at=now,
        status=state,
        last_error=None,
    )


def test_summarize_reports_recent_failure_and_next_action() -> None:
    service = StatusService(
        secret_store=FakeSecretStore({"switchgpt_account_0"}),
        history_store=FakeHistoryStore(
            [
                SwitchEvent(
                    occurred_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
                    from_account_index=0,
                    to_account_index=1,
                    mode="watch-auto",
                    result="needs-reauth",
                    message="Account slot 1 likely needs reauthentication.",
                )
            ]
        ),
    )

    summary = service.summarize([build_account(0)], active_account_index=0)

    assert summary.readiness == "needs-attention"
    assert summary.latest_result == "needs-reauth"
    assert "Reauthenticate slot 1" in summary.next_action


def test_read_returns_latest_event_or_none(tmp_path) -> None:
    store = SwitchHistoryStore(tmp_path / "switch-history.jsonl")
    assert store.latest() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_status_service.py tests/test_switch_history.py -v`
Expected: FAIL with `TypeError` / `AttributeError` because `StatusService` does not accept `history_store`, `summarize()` does not exist, and `SwitchHistoryStore.latest()` does not exist.

- [ ] **Step 3: Add Phase 4 error types and status/history helpers**

```python
# switchgpt/errors.py
class ReauthRequiredError(SwitchGptError):
    """Raised when an account can continue only after explicit reauthentication."""


class DoctorCheckError(SwitchGptError):
    """Raised when a bounded doctor check cannot complete normally."""
```

```python
# switchgpt/switch_history.py
def latest(self) -> SwitchEvent | None:
    events = self.load()
    if not events:
        return None
    return events[-1]
```

```python
# switchgpt/status_service.py
from dataclasses import dataclass

from .errors import SecretStoreError, SwitchHistoryError
from .models import AccountRecord, AccountState


@dataclass(frozen=True)
class SlotStatus:
    index: int
    email: str
    state: AccountState
    last_error: str | None


@dataclass(frozen=True)
class StatusSummary:
    slots: list[SlotStatus]
    active_account_index: int | None
    readiness: str
    latest_result: str | None
    next_action: str | None


class StatusService:
    def __init__(self, secret_store, history_store=None) -> None:
        self._secret_store = secret_store
        self._history_store = history_store

    def classify(self, account: AccountRecord) -> SlotStatus:
        try:
            exists = self._secret_store.exists(account.keychain_key)
        except SecretStoreError:
            exists = False
        if not exists:
            return SlotStatus(
                account.index,
                account.email,
                AccountState.MISSING_SECRET,
                account.last_error,
            )
        return SlotStatus(
            account.index,
            account.email,
            account.status,
            account.last_error,
        )

    def summarize(self, accounts: list[AccountRecord], *, active_account_index: int | None) -> StatusSummary:
        slots = [self.classify(account) for account in accounts]
        latest = self._latest_event_result()
        readiness = "ready"
        next_action = None
        if any(slot.state is AccountState.NEEDS_REAUTH for slot in slots) or latest == "needs-reauth":
            readiness = "needs-attention"
            next_action = "Reauthenticate slot 1 with `switchgpt add --reauth 1` or let `switchgpt watch` guide the in-session flow."
        elif any(slot.state is AccountState.MISSING_SECRET for slot in slots):
            readiness = "degraded"
            next_action = "Repair the missing Keychain entry or reauthenticate the affected slot."
        return StatusSummary(
            slots=slots,
            active_account_index=active_account_index,
            readiness=readiness,
            latest_result=latest,
            next_action=next_action,
        )

    def _latest_event_result(self) -> str | None:
        if self._history_store is None:
            return None
        try:
            latest = self._history_store.latest()
        except (AttributeError, SwitchHistoryError):
            return "history-invalid"
        return None if latest is None else latest.result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_status_service.py tests/test_switch_history.py -v`
Expected: PASS with new readiness-summary coverage and latest-history access coverage.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/errors.py switchgpt/switch_history.py switchgpt/status_service.py tests/test_status_service.py tests/test_switch_history.py
git commit -m "feat: add phase 4 status and history summaries"
```

### Task 2: Add Managed-Workspace Reauthentication Support

**Files:**
- Modify: `switchgpt/playwright_client.py`
- Modify: `switchgpt/registration.py`
- Modify: `switchgpt/managed_browser.py`
- Test: `tests/test_registration.py`
- Test: `tests/test_managed_browser.py`

- [ ] **Step 1: Write the failing reauth-in-managed-workspace tests**

```python
from datetime import UTC, datetime

from switchgpt.models import AccountRecord, AccountState
from switchgpt.registration import RegistrationResult, RegistrationService
from switchgpt.secret_store import SessionSecret


class FakeBrowserClient:
    def capture_existing_session(self, page, *, existing_email: str) -> RegistrationResult:
        return RegistrationResult(
            email=existing_email,
            secret=SessionSecret(session_token="new-token", csrf_token="csrf"),
            captured_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
        )


def test_reauth_in_managed_workspace_refreshes_secret_and_metadata() -> None:
    page = object()
    existing = AccountRecord(
        index=0,
        email="account0@example.com",
        keychain_key="switchgpt_account_0",
        registered_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_reauth_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_validated_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        status=AccountState.NEEDS_REAUTH,
        last_error="expired session",
    )
    class FakeAccountStore:
        def get_record(self, index: int) -> AccountRecord:
            assert index == 0
            return existing

        def save_record(self, record: AccountRecord) -> None:
            self.saved = record

    class FakeSecretStore:
        def read(self, key: str):
            assert key == "switchgpt_account_0"
            return SessionSecret(session_token="old-token", csrf_token=None)

        def replace(self, key: str, secret: SessionSecret) -> None:
            self.replaced = (key, secret)

    service = RegistrationService(FakeAccountStore(), FakeSecretStore(), FakeBrowserClient())
    record = service.reauth_in_managed_workspace(index=0, page=page)

    assert record.status is AccountState.REGISTERED
    assert record.last_error is None
```

```python
from switchgpt.managed_browser import ManagedBrowser


def test_smoke_check_runtime_opens_workspace_and_returns_true(tmp_path) -> None:
    browser = ManagedBrowser(base_url="https://chatgpt.com", profile_dir=tmp_path / "profile")
    browser._launch_runtime = lambda replace_existing=False: type("Context", (), {"pages": [], "new_page": lambda self: type("Page", (), {"goto": lambda self, url: None})()})()
    assert browser.can_open_workspace() is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_registration.py tests/test_managed_browser.py -v`
Expected: FAIL because `reauth_in_managed_workspace()` and `can_open_workspace()` do not exist.

- [ ] **Step 3: Add capture-from-existing-page and managed-workspace reauth methods**

```python
# switchgpt/playwright_client.py
def capture_existing_session(self, page, *, existing_email: str) -> RegistrationResult:
    self._assert_authenticated_state(page)
    context = page.context
    cookies = context.cookies()
    session_token = self._require_cookie_value(
        cookies, "__Secure-next-auth.session-token"
    )
    csrf_cookie = self._optional_cookie_value(
        cookies, "__Host-next-auth.csrf-token"
    )
    email = self._discover_email(page) or self._normalize_email(existing_email)
    return RegistrationResult(
        email=email,
        secret=SessionSecret(
            session_token=session_token,
            csrf_token=csrf_cookie,
        ),
        captured_at=datetime.now(UTC),
    )
```

```python
# switchgpt/registration.py
def reauth_in_managed_workspace(self, *, index: int, page) -> AccountRecord:
    existing = self._account_store.get_record(index)
    previous_secret = self._secret_store.read(existing.keychain_key)
    result = self._browser_client.capture_existing_session(
        page, existing_email=existing.email
    )
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
    try:
        self._account_store.save_record(refreshed)
    except Exception:
        with suppress(Exception):
            if previous_secret is None:
                self._secret_store.delete(existing.keychain_key)
            else:
                self._secret_store.replace(existing.keychain_key, previous_secret)
        raise
    return refreshed
```

```python
# switchgpt/managed_browser.py
def can_open_workspace(self) -> bool:
    try:
        self.open_workspace()
    except ManagedBrowserError:
        return False
    return True


def wait_for_reauthentication(self, page) -> None:
    input("[switchgpt] Complete reauthentication in the managed browser, then press ENTER here.")
    page.goto(self.base_url)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_registration.py tests/test_managed_browser.py -v`
Expected: PASS with managed-workspace reauth and bounded runtime smoke-check coverage.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/playwright_client.py switchgpt/registration.py switchgpt/managed_browser.py tests/test_registration.py tests/test_managed_browser.py
git commit -m "feat: add managed workspace reauthentication support"
```

### Task 3: Expand Watch Recovery States And Resume Flow

**Files:**
- Modify: `switchgpt/watch_service.py`
- Modify: `switchgpt/errors.py`
- Modify: `switchgpt/switch_service.py`
- Modify: `switchgpt/switch_history.py`
- Test: `tests/test_watch_service.py`

- [ ] **Step 1: Write the failing watch recovery tests**

```python
from datetime import UTC, datetime

from switchgpt.errors import ReauthRequiredError
from switchgpt.models import AccountState, LimitState
from switchgpt.watch_service import WatchService


class FakeRegistrationService:
    def __init__(self) -> None:
        self.calls = []

    def reauth_in_managed_workspace(self, *, index: int, page):
        self.calls.append((index, page))
        return build_account(index, "reauth@example.com")


def test_run_enters_reauth_flow_and_resumes_monitoring() -> None:
    managed_browser = FakeManagedBrowser(detections=[LimitState.LIMIT_DETECTED, LimitState.NO_LIMIT_DETECTED])
    switch_service = FakeSwitchService(
        failures={1: ReauthRequiredError("Account slot 1 likely needs reauthentication.")}
    )
    registration_service = FakeRegistrationService()
    notifications = []
    history_store = FakeHistoryStore()
    service = WatchService(
        account_store=FakeAccountStore([build_account(0, "a@example.com"), build_account(1, "b@example.com")], active_account_index=0),
        managed_browser=managed_browser,
        switch_service=switch_service,
        registration_service=registration_service,
        history_store=history_store,
        poll_interval_seconds=0.0,
    )

    result = service.run(notify=notifications.append, sleep_fn=lambda _: None, stop_after_cycles=2)

    assert result.reason == "cycle-limit"
    assert registration_service.calls == [(1, "page")]
    assert any(event.kind == "reauth-required" for event in notifications)
    assert any(event.kind == "resume-succeeded" for event in notifications)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_watch_service.py -v`
Expected: FAIL because `WatchService` does not accept `registration_service`, does not emit `reauth-required` / `resume-succeeded`, and cannot branch on `ReauthRequiredError`.

- [ ] **Step 3: Implement explicit recovery states and typed reauth branching**

```python
# switchgpt/errors.py
class ReauthRequiredError(SwitchError):
    """Raised when a switch candidate can continue only after explicit reauthentication."""
```

```python
# switchgpt/switch_service.py
from .errors import ReauthRequiredError, SwitchError

if not self._managed_browser.is_authenticated(page):
    self._append_event(
        occurred_at=occurred_at,
        previous_active_index=previous_active_index,
        account_index=account.index,
        mode=mode,
        result="needs-reauth",
        message=f"Account slot {account.index} likely needs reauthentication.",
    )
    event_recorded = True
    raise ReauthRequiredError(
        f"Account slot {account.index} likely needs reauthentication."
    )
```

```python
# switchgpt/watch_service.py
class WatchService:
    def __init__(
        self,
        account_store,
        managed_browser,
        switch_service,
        registration_service,
        history_store,
        *,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self._account_store = account_store
        self._managed_browser = managed_browser
        self._switch_service = switch_service
        self._registration_service = registration_service
        self._history_store = history_store
        self._poll_interval_seconds = poll_interval_seconds

    def _handle_reauth_required(self, notify, *, active_index: int, target_index: int, page):
        self._emit(notify, "reauth-required", f"Slot {target_index} requires reauthentication in the managed browser.")
        self._history_store.append(
            SwitchEvent(
                occurred_at=datetime.now(UTC),
                from_account_index=active_index,
                to_account_index=target_index,
                mode="watch-auto",
                result="reauth-started",
                message=f"Starting in-session reauthentication for slot {target_index}.",
            )
        )
        self._managed_browser.wait_for_reauthentication(page)
        record = self._registration_service.reauth_in_managed_workspace(index=target_index, page=page)
        self._history_store.append(
            SwitchEvent(
                occurred_at=datetime.now(UTC),
                from_account_index=active_index,
                to_account_index=record.index,
                mode="watch-auto",
                result="resume-succeeded",
                message=f"Reauthentication succeeded for slot {record.index}; resuming watch.",
            )
        )
        self._emit(notify, "resume-succeeded", f"Reauthenticated slot {record.index}; resuming watch.")
        return record.index
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_watch_service.py -v`
Expected: PASS with explicit reauth/recovery-path coverage and unchanged stop behavior for true runtime failures.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/errors.py switchgpt/switch_service.py switchgpt/watch_service.py tests/test_watch_service.py
git commit -m "feat: add watch reauthentication recovery flow"
```

### Task 4: Add Doctor Service And Diagnostic Coverage

**Files:**
- Create: `switchgpt/doctor_service.py`
- Modify: `switchgpt/errors.py`
- Test: `tests/test_doctor_service.py`

- [ ] **Step 1: Write the failing doctor-service tests**

```python
from switchgpt.doctor_service import DoctorService


class FakeManagedBrowser:
    def __init__(self, can_open: bool) -> None:
        self._can_open = can_open

    def can_open_workspace(self) -> bool:
        return self._can_open


def test_run_reports_watch_readiness_when_all_checks_pass(tmp_path) -> None:
    service = DoctorService(
        metadata_store=type("Store", (), {"load": lambda self: type("Snapshot", (), {"accounts": [type("Account", (), {"keychain_key": "switchgpt_account_0"})()], "active_account_index": None, "last_switch_at": None})()})(),
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=type("Secrets", (), {"exists": lambda self, key: True})(),
        managed_browser=FakeManagedBrowser(can_open=True),
        platform_name="Darwin",
    )

    report = service.run()

    assert report.readiness == "watch-ready"
    assert all(check.status == "pass" for check in report.checks)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_doctor_service.py -v`
Expected: FAIL because `switchgpt/doctor_service.py` does not exist.

- [ ] **Step 3: Implement bounded doctor checks**

```python
# switchgpt/doctor_service.py
from dataclasses import dataclass

from .errors import AccountStoreError, DoctorCheckError, SwitchHistoryError


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str
    next_action: str | None


@dataclass(frozen=True)
class DoctorReport:
    readiness: str
    checks: list[DoctorCheck]


class DoctorService:
    def __init__(self, metadata_store, history_store, secret_store, managed_browser, *, platform_name: str) -> None:
        self._metadata_store = metadata_store
        self._history_store = history_store
        self._secret_store = secret_store
        self._managed_browser = managed_browser
        self._platform_name = platform_name

    def run(self) -> DoctorReport:
        checks = [
            self._check_platform(),
            self._check_metadata(),
            self._check_history(),
            self._check_keychain_entries(),
            self._check_runtime(),
        ]
        readiness = "watch-ready" if all(check.status == "pass" for check in checks) else "needs-attention"
        return DoctorReport(readiness=readiness, checks=checks)

    def _check_platform(self) -> DoctorCheck:
        if self._platform_name != "Darwin":
            return DoctorCheck("platform", "fail", "switchgpt requires macOS.", "Run switchgpt on macOS.")
        return DoctorCheck("platform", "pass", "macOS detected.", None)

    def _check_metadata(self) -> DoctorCheck:
        try:
            self._metadata_store.load()
        except AccountStoreError as exc:
            return DoctorCheck("metadata", "fail", str(exc), "Repair or remove malformed account metadata.")
        return DoctorCheck("metadata", "pass", "Account metadata is readable.", None)

    def _check_history(self) -> DoctorCheck:
        try:
            self._history_store.load()
        except SwitchHistoryError as exc:
            return DoctorCheck("history", "warn", str(exc), "Repair or archive malformed switch history.")
        return DoctorCheck("history", "pass", "Switch history is readable.", None)

    def _check_keychain_entries(self) -> DoctorCheck:
        snapshot = self._metadata_store.load()
        missing_keys = [
            account.keychain_key
            for account in snapshot.accounts
            if not self._secret_store.exists(account.keychain_key)
        ]
        if missing_keys:
            return DoctorCheck(
                "keychain",
                "fail",
                "One or more registered accounts are missing Keychain secrets.",
                "Reauthenticate the affected slot to refresh its secret.",
            )
        return DoctorCheck("keychain", "pass", "Registered account secrets exist in Keychain.", None)

    def _check_runtime(self) -> DoctorCheck:
        if not self._managed_browser.can_open_workspace():
            return DoctorCheck("managed-browser", "fail", "Managed workspace could not be opened.", "Run `switchgpt open` after repairing Playwright/browser prerequisites.")
        return DoctorCheck("managed-browser", "pass", "Managed workspace can be opened.", None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_doctor_service.py -v`
Expected: PASS with stable diagnosis and readiness coverage.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/doctor_service.py tests/test_doctor_service.py
git commit -m "feat: add doctor diagnostics service"
```

### Task 5: Wire CLI For Rich Status, Doctor, And Recovery-Aware Watch Output

**Files:**
- Modify: `switchgpt/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

```python
def test_doctor_command_prints_check_results(monkeypatch) -> None:
    class FakeDoctorService:
        def run(self):
            return type(
                "Report",
                (),
                {
                    "readiness": "watch-ready",
                    "checks": [
                        type("Check", (), {"name": "platform", "status": "pass", "detail": "macOS detected.", "next_action": None})()
                    ],
                },
            )()

    monkeypatch.setattr("switchgpt.cli.build_doctor_service", lambda: FakeDoctorService())
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "platform: pass" in result.stdout


def test_status_command_prints_readiness_and_next_action(monkeypatch) -> None:
    class FakeStore:
        class Snapshot:
            accounts = []
            active_account_index = 0
            last_switch_at = None

        def load(self):
            return self.Snapshot()

    class FakeStatusService:
        def summarize(self, accounts, *, active_account_index):
            return type(
                "Summary",
                (),
                {
                    "slots": [],
                    "readiness": "needs-attention",
                    "latest_result": "needs-reauth",
                    "next_action": "Reauthenticate slot 1.",
                    "active_account_index": active_account_index,
                },
            )()

    monkeypatch.setattr("switchgpt.cli.build_status_service", lambda: (FakeStore(), FakeStatusService()))
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Readiness: needs-attention" in result.stdout
    assert "Next action: Reauthenticate slot 1." in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL because `doctor` is not registered and `status` still prints only one line per slot.

- [ ] **Step 3: Implement CLI builders and user-facing output changes**

```python
# switchgpt/cli.py
from .doctor_service import DoctorService


def build_status_service() -> tuple[AccountStore, StatusService]:
    settings = Settings.from_env()
    store = AccountStore(settings.metadata_path, settings.slot_count)
    history_store = SwitchHistoryStore(settings.switch_history_path)
    service = StatusService(
        KeychainSecretStore(settings.keychain_service),
        history_store=history_store,
    )
    return store, service


def build_doctor_service() -> DoctorService:
    settings = Settings.from_env()
    return DoctorService(
        metadata_store=AccountStore(settings.metadata_path, settings.slot_count),
        history_store=SwitchHistoryStore(settings.switch_history_path),
        secret_store=KeychainSecretStore(settings.keychain_service),
        managed_browser=build_managed_browser(),
        platform_name=platform.system(),
    )


def build_watch_service() -> WatchService:
    store, secret_store, managed_browser, history_store = _build_switch_components()
    switch_service = SwitchService(store, secret_store, managed_browser, history_store)
    registration_service = build_registration_service()
    return WatchService(
        account_store=store,
        managed_browser=managed_browser,
        switch_service=switch_service,
        registration_service=registration_service,
        history_store=history_store,
    )


@app.command()
def doctor() -> None:
    try:
        service = build_doctor_service()
        report = service.run()
        print(f"Readiness: {report.readiness}")
        for check in report.checks:
            print(f"{check.name}: {check.status} - {check.detail}")
            if check.next_action:
                print(f"  next: {check.next_action}")
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
```

```python
# switchgpt/cli.py
@app.command()
def status() -> None:
    try:
        ensure_supported_platform()
        store, service = build_status_service()
        snapshot = store.load()
        if not snapshot.accounts:
            print("No accounts registered.")
            return
        summary = service.summarize(
            snapshot.accounts,
            active_account_index=snapshot.active_account_index,
        )
        print(f"Readiness: {summary.readiness}")
        if summary.active_account_index is not None:
            print(f"Active slot: {summary.active_account_index}")
        if summary.latest_result is not None:
            print(f"Latest result: {summary.latest_result}")
        if summary.next_action is not None:
            print(f"Next action: {summary.next_action}")
        for slot in summary.slots:
            print(f"[{slot.index}] {slot.email} - {slot.state}")
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS with `doctor` coverage and richer status/watch output coverage.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/cli.py tests/test_cli.py
git commit -m "feat: wire phase 4 status and doctor commands"
```

### Task 6: Run Full Phase 4 Verification And Add Manual Checks

**Files:**
- Modify: `docs/superpowers/plans/2026-04-17-switchgpt-phase-4-operational-hardening.md`

- [ ] **Step 1: Add the manual verification checklist to this plan**

```md
## Phase 4 Manual Verification

1. Register at least two real accounts on macOS.
2. Start `switchgpt watch` in the managed browser workspace.
3. Force or simulate a reauthentication-required path for one account.
4. Complete the reauthentication in the managed browser when prompted.
5. Confirm `watch` prints a resume message and continues monitoring.
6. Break the browser runtime intentionally by closing the managed profile or removing browser access.
7. Confirm `watch` stops with restart / `doctor` guidance instead of silently retrying forever.
8. Run `switchgpt status` and confirm it surfaces readiness, latest result, and next action.
9. Run `switchgpt doctor` and confirm each check prints pass/warn/fail with an actionable next step when needed.
```

- [ ] **Step 2: Run the focused automated suite**

Run: `uv run pytest tests/test_status_service.py tests/test_switch_history.py tests/test_registration.py tests/test_managed_browser.py tests/test_watch_service.py tests/test_doctor_service.py tests/test_cli.py -v`
Expected: PASS with Phase 4 status, doctor, reauth, and watch-recovery coverage.

- [ ] **Step 3: Run the full automated suite**

Run: `uv run pytest -v`
Expected: PASS for the full suite with the new Phase 4 coverage included.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-04-17-switchgpt-phase-4-operational-hardening.md
git commit -m "docs: add phase 4 verification checklist"
```

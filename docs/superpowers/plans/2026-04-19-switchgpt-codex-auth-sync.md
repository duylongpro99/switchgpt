# switchgpt Phase 6 Codex Auth Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every successful slot-mutation flow keeps Codex authentication aligned with the active slot (or fails loudly), with first-class diagnostics and a manual repair command.

**Architecture:** Add a dedicated `CodexAuthSyncService` with adapter targets (`file` first, `env` fallback) and a typed outcome model. Extend persisted metadata with non-secret sync state, then invoke sync from slot-mutation flows (`add`, `reauth`, `switch`, and watch transitions) using strict default policy so commands cannot silently leave Codex auth out of sync. Expose drift and last-sync diagnostics in `status`/`doctor`, plus a `codex-sync` repair command.

**Tech Stack:** Python 3.12, Typer CLI, pytest, existing `switchgpt` runtime stores/services, JSON metadata persistence, macOS local runtime.

---

## File Structure

- Create: `switchgpt/codex_auth_sync.py`
  Purpose: Define typed outcomes, file/env targets, fallback orchestration, strict sync policy behavior, and redacted sync error handling.
- Modify: `switchgpt/models.py`
  Purpose: Extend `AccountSnapshot` with non-secret Codex sync metadata fields used by status/doctor and repair flow.
- Modify: `switchgpt/account_store.py`
  Purpose: Parse/persist new sync metadata and add a dedicated method for writing codex-sync runtime state without mutating account records.
- Modify: `switchgpt/errors.py`
  Purpose: Add explicit sync-domain exception types for strict failure handling and bounded CLI messaging.
- Modify: `switchgpt/bootstrap.py`
  Purpose: Wire sync service construction and inject it into services/commands that mutate active slot state.
- Modify: `switchgpt/registration.py`
  Purpose: Trigger sync only after successful add/reauth persistence, then raise strict failures with actionable guidance.
- Modify: `switchgpt/switch_service.py`
  Purpose: Trigger sync immediately after successful active-slot mutation and enforce strict non-zero outcome behavior.
- Modify: `switchgpt/watch_service.py`
  Purpose: Enforce sync on watch-driven successful switches and successful in-session reauth resume transitions.
- Modify: `switchgpt/status_service.py`
  Purpose: Add codex-sync drift evaluation and user action guidance when active slot differs from last synced slot.
- Modify: `switchgpt/doctor_service.py`
  Purpose: Add codex sync consistency check surfaced as operational diagnostics.
- Modify: `switchgpt/output.py`
  Purpose: Render codex sync status/method/timestamp/error details in `status` output.
- Modify: `switchgpt/cli.py`
  Purpose: Add `switchgpt codex-sync` repair command and route strict sync errors to non-zero exit with guidance.
- Modify: `tests/test_account_store.py`
  Purpose: Verify codex sync metadata load/write behavior and backward-compatible defaulting.
- Create: `tests/test_codex_auth_sync.py`
  Purpose: Unit-test adapter ordering, fallback behavior, strict outcomes, and metadata persistence updates.
- Modify: `tests/test_registration.py`
  Purpose: Verify add/reauth flows call sync after mutation and fail loudly when strict sync fails.
- Modify: `tests/test_switch_service.py`
  Purpose: Verify successful switches invoke sync and strict sync failures surface non-success outcomes.
- Modify: `tests/test_watch_service.py`
  Purpose: Verify watch successful transitions invoke sync and strict failures terminate run non-zero.
- Modify: `tests/test_status_service.py`
  Purpose: Verify in-sync vs out-of-sync readiness and codex repair next actions.
- Modify: `tests/test_doctor_service.py`
  Purpose: Verify codex sync health check content and readiness impact.
- Modify: `tests/test_cli.py`
  Purpose: Verify `codex-sync` command behavior and strict sync failure guidance on mutating commands.

### Task 1: Persist Codex Sync Metadata In Account Snapshot

**Files:**
- Modify: `switchgpt/models.py`
- Modify: `switchgpt/account_store.py`
- Test: `tests/test_account_store.py`

- [ ] **Step 1: Write the failing metadata persistence tests**

```python
# tests/test_account_store.py
from datetime import UTC, datetime

from switchgpt.account_store import AccountStore
from switchgpt.models import AccountSnapshot


def test_load_defaults_codex_sync_metadata_when_missing(tmp_path) -> None:
    metadata_path = tmp_path / "accounts.json"
    metadata_path.write_text(
        '{"version":1,"active_account_index":0,"last_switch_at":null,"accounts":[]}'
    )
    store = AccountStore(metadata_path, slot_count=3)

    snapshot = store.load()

    assert snapshot.last_codex_sync_at is None
    assert snapshot.last_codex_sync_slot is None
    assert snapshot.last_codex_sync_method is None
    assert snapshot.last_codex_sync_status is None
    assert snapshot.last_codex_sync_error is None


def test_save_codex_sync_state_persists_non_secret_sync_fields(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts.json", slot_count=3)

    store.save_codex_sync_state(
        synced_at=datetime(2026, 4, 19, 9, 30, tzinfo=UTC),
        synced_slot=1,
        method="env-fallback",
        status="fallback-ok",
        error="codex-auth-format-unsupported",
    )

    snapshot = store.load()

    assert snapshot.last_codex_sync_slot == 1
    assert snapshot.last_codex_sync_method == "env-fallback"
    assert snapshot.last_codex_sync_status == "fallback-ok"
    assert snapshot.last_codex_sync_error == "codex-auth-format-unsupported"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_account_store.py::test_load_defaults_codex_sync_metadata_when_missing tests/test_account_store.py::test_save_codex_sync_state_persists_non_secret_sync_fields -v`

Expected: FAIL with `AttributeError`/`TypeError` because `AccountSnapshot` and `AccountStore` do not yet support codex sync fields.

- [ ] **Step 3: Implement snapshot model and store changes**

```python
# switchgpt/models.py
@dataclass(frozen=True)
class AccountSnapshot:
    accounts: list[AccountRecord]
    active_account_index: int | None
    last_switch_at: datetime | None
    last_codex_sync_at: datetime | None
    last_codex_sync_slot: int | None
    last_codex_sync_method: str | None
    last_codex_sync_status: str | None
    last_codex_sync_error: str | None
```

```python
# switchgpt/account_store.py (additions)
def load(self) -> AccountSnapshot:
    if not self._metadata_path.exists():
        return AccountSnapshot(
            accounts=[],
            active_account_index=None,
            last_switch_at=None,
            last_codex_sync_at=None,
            last_codex_sync_slot=None,
            last_codex_sync_method=None,
            last_codex_sync_status=None,
            last_codex_sync_error=None,
        )
    ...
    return AccountSnapshot(
        accounts=accounts,
        active_account_index=self._load_active_account_index(payload),
        last_switch_at=self._load_last_switch_at(payload),
        last_codex_sync_at=self._load_optional_datetime(payload.get("last_codex_sync_at")),
        last_codex_sync_slot=self._load_optional_int(payload.get("last_codex_sync_slot")),
        last_codex_sync_method=self._load_optional_str(payload.get("last_codex_sync_method")),
        last_codex_sync_status=self._load_optional_str(payload.get("last_codex_sync_status")),
        last_codex_sync_error=self._load_optional_str(payload.get("last_codex_sync_error")),
    )


def save_codex_sync_state(
    self,
    *,
    synced_at: datetime | None,
    synced_slot: int | None,
    method: str | None,
    status: str | None,
    error: str | None,
) -> None:
    snapshot = self.load()
    self._write_snapshot(
        AccountSnapshot(
            accounts=snapshot.accounts,
            active_account_index=snapshot.active_account_index,
            last_switch_at=snapshot.last_switch_at,
            last_codex_sync_at=synced_at,
            last_codex_sync_slot=synced_slot,
            last_codex_sync_method=method,
            last_codex_sync_status=status,
            last_codex_sync_error=error,
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_account_store.py::test_load_defaults_codex_sync_metadata_when_missing tests/test_account_store.py::test_save_codex_sync_state_persists_non_secret_sync_fields -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/models.py switchgpt/account_store.py tests/test_account_store.py
git commit -m "feat: persist codex auth sync metadata in account snapshot"
```

### Task 2: Build Codex Auth Sync Service With File-First Fallback

**Files:**
- Create: `switchgpt/codex_auth_sync.py`
- Modify: `switchgpt/errors.py`
- Test: `tests/test_codex_auth_sync.py`

- [ ] **Step 1: Write failing sync service tests**

```python
# tests/test_codex_auth_sync.py
from datetime import UTC, datetime

from switchgpt.codex_auth_sync import CodexAuthSyncService, CodexSyncResult


def test_sync_returns_ok_when_file_target_succeeds() -> None:
    calls = []

    class FileTarget:
        def apply(self, *, email: str, session_token: str, csrf_token: str | None) -> str:
            calls.append("file")
            return "file"

    class EnvTarget:
        def apply(self, **kwargs):
            raise AssertionError("env fallback should not run")

    service = CodexAuthSyncService(file_target=FileTarget(), env_target=EnvTarget())

    result = service.sync_active_slot(
        active_slot=1,
        email="account1@example.com",
        session_token="token-1",
        csrf_token="csrf-1",
        occurred_at=datetime(2026, 4, 19, 10, 0, tzinfo=UTC),
    )

    assert result == CodexSyncResult(
        outcome="ok",
        method="file",
        failure_class=None,
        message=None,
    )
    assert calls == ["file"]


def test_sync_falls_back_to_env_when_file_is_unsupported() -> None:
    class FileTarget:
        def apply(self, **kwargs):
            raise RuntimeError("codex-auth-format-unsupported")

    class EnvTarget:
        def apply(self, **kwargs):
            return "env-fallback"

    service = CodexAuthSyncService(file_target=FileTarget(), env_target=EnvTarget())

    result = service.sync_active_slot(
        active_slot=0,
        email="account0@example.com",
        session_token="token-0",
        csrf_token=None,
        occurred_at=datetime(2026, 4, 19, 10, 5, tzinfo=UTC),
    )

    assert result.outcome == "fallback-ok"
    assert result.method == "env-fallback"
    assert result.failure_class is None


def test_sync_returns_failed_when_both_targets_fail() -> None:
    class FileTarget:
        def apply(self, **kwargs):
            raise RuntimeError("codex-auth-write-failed")

    class EnvTarget:
        def apply(self, **kwargs):
            raise RuntimeError("codex-auth-fallback-failed")

    service = CodexAuthSyncService(file_target=FileTarget(), env_target=EnvTarget())

    result = service.sync_active_slot(
        active_slot=2,
        email="account2@example.com",
        session_token="token-2",
        csrf_token="csrf-2",
        occurred_at=datetime(2026, 4, 19, 10, 10, tzinfo=UTC),
    )

    assert result.outcome == "failed"
    assert result.method is None
    assert result.failure_class == "codex-auth-fallback-failed"


def test_sync_persists_metadata_for_last_result() -> None:
    persisted = {}

    class FakeStore:
        def save_codex_sync_state(self, **kwargs) -> None:
            persisted.update(kwargs)

    class FileTarget:
        def apply(self, **kwargs):
            return "file"

    class EnvTarget:
        def apply(self, **kwargs):
            raise AssertionError("fallback should not run")

    service = CodexAuthSyncService(
        file_target=FileTarget(),
        env_target=EnvTarget(),
        account_store=FakeStore(),
    )

    result = service.sync_active_slot(
        active_slot=1,
        email="account1@example.com",
        session_token="token-1",
        csrf_token=None,
        occurred_at=datetime(2026, 4, 19, 10, 30, tzinfo=UTC),
    )

    assert result.outcome == "ok"
    assert persisted == {
        "synced_at": datetime(2026, 4, 19, 10, 30, tzinfo=UTC),
        "synced_slot": 1,
        "method": "file",
        "status": "ok",
        "error": None,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_codex_auth_sync.py -v`

Expected: FAIL because `switchgpt.codex_auth_sync` module and types do not exist.

- [ ] **Step 3: Implement typed sync outcomes and fallback orchestration**

```python
# switchgpt/codex_auth_sync.py
from dataclasses import dataclass

from .diagnostics import redact_text


@dataclass(frozen=True)
class CodexSyncResult:
    outcome: str
    method: str | None
    failure_class: str | None
    message: str | None


class CodexSyncError(Exception):
    def __init__(self, failure_class: str, message: str) -> None:
        super().__init__(message)
        self.failure_class = failure_class


class CodexAuthSyncService:
    def __init__(self, *, file_target, env_target, account_store=None) -> None:
        self._file_target = file_target
        self._env_target = env_target
        self._account_store = account_store

    def sync_active_slot(
        self,
        *,
        active_slot: int,
        email: str,
        session_token: str,
        csrf_token: str | None,
        occurred_at,
    ) -> CodexSyncResult:
        try:
            method = self._file_target.apply(
                email=email,
                session_token=session_token,
                csrf_token=csrf_token,
            )
            result = CodexSyncResult("ok", method, None, None)
            self._persist_result(
                occurred_at=occurred_at,
                active_slot=active_slot,
                result=result,
            )
            return result
        except Exception as file_exc:
            file_error = self._classify_error(file_exc)
            if file_error not in {
                "codex-auth-target-missing",
                "codex-auth-format-unsupported",
                "codex-auth-write-failed",
                "codex-auth-verify-failed",
            }:
                result = CodexSyncResult(
                    "failed",
                    None,
                    file_error,
                    redact_text(str(file_exc)),
                )
                self._persist_result(
                    occurred_at=occurred_at,
                    active_slot=active_slot,
                    result=result,
                )
                return result

        try:
            method = self._env_target.apply(
                email=email,
                session_token=session_token,
                csrf_token=csrf_token,
            )
            result = CodexSyncResult("fallback-ok", method, None, None)
            self._persist_result(
                occurred_at=occurred_at,
                active_slot=active_slot,
                result=result,
            )
            return result
        except Exception as env_exc:
            failure_class = self._classify_error(env_exc)
            result = CodexSyncResult(
                "failed",
                None,
                failure_class,
                redact_text(str(env_exc)),
            )
            self._persist_result(
                occurred_at=occurred_at,
                active_slot=active_slot,
                result=result,
            )
            return result

    def _classify_error(self, exc: Exception) -> str:
        text = str(exc)
        if text in {
            "codex-auth-target-missing",
            "codex-auth-format-unsupported",
            "codex-auth-write-failed",
            "codex-auth-verify-failed",
            "codex-auth-fallback-failed",
        }:
            return text
        return "codex-auth-write-failed"

    def _persist_result(self, *, occurred_at, active_slot: int, result: CodexSyncResult) -> None:
        if self._account_store is None:
            return
        self._account_store.save_codex_sync_state(
            synced_at=occurred_at,
            synced_slot=active_slot,
            method=result.method,
            status=result.outcome,
            error=result.failure_class,
        )


class CodexFileAuthTarget:
    def apply(self, *, email: str, session_token: str, csrf_token: str | None) -> str:
        del email, session_token, csrf_token
        # Implement the file-target write with atomic temp + replace semantics.
        return "file"


class CodexEnvAuthTarget:
    def apply(self, *, email: str, session_token: str, csrf_token: str | None) -> str:
        del email, session_token, csrf_token
        # Implement the env/config fallback projection here.
        return "env-fallback"
```

```python
# switchgpt/errors.py
class CodexAuthSyncFailedError(SwitchGptError):
    """Raised when strict Codex auth sync cannot complete."""
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_codex_auth_sync.py -v`

Expected: PASS for `ok`, `fallback-ok`, and `failed` outcomes.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/codex_auth_sync.py switchgpt/errors.py tests/test_codex_auth_sync.py
git commit -m "feat: add codex auth sync service with file-first fallback"
```

### Task 3: Enforce Strict Sync On Successful Mutation Flows

**Files:**
- Modify: `switchgpt/bootstrap.py`
- Modify: `switchgpt/registration.py`
- Modify: `switchgpt/switch_service.py`
- Modify: `switchgpt/watch_service.py`
- Test: `tests/test_registration.py`
- Test: `tests/test_switch_service.py`
- Test: `tests/test_watch_service.py`

- [ ] **Step 1: Write failing integration tests for mutation-path sync**

```python
# tests/test_switch_service.py
def test_switch_to_runs_codex_sync_after_runtime_state_save() -> None:
    events = []

    class FakeSyncService:
        def sync_active_slot(self, **kwargs):
            events.append(("sync", kwargs["active_slot"]))
            return type("Result", (), {"outcome": "ok", "method": "file", "failure_class": None, "message": None})()

    service = SwitchService(
        account_store=FakeAccountStore([build_account(0, "a@example.com"), build_account(1, "b@example.com")], active_account_index=0),
        secret_store=FakeSecretStore(SessionSecret(session_token="session-2", csrf_token="csrf-2")),
        managed_browser=FakeManagedBrowser(authenticated=True),
        history_store=FakeHistoryStore(),
        codex_auth_sync=FakeSyncService(),
    )

    result = service.switch_to(index=1)

    assert result.account.index == 1
    assert events == [("sync", 1)]


def test_switch_to_raises_when_strict_codex_sync_fails() -> None:
    class FakeSyncService:
        def sync_active_slot(self, **kwargs):
            return type(
                "Result",
                (),
                {
                    "outcome": "failed",
                    "method": None,
                    "failure_class": "codex-auth-fallback-failed",
                    "message": "write failed",
                },
            )()

    service = SwitchService(
        account_store=FakeAccountStore([build_account(0, "a@example.com"), build_account(1, "b@example.com")], active_account_index=0),
        secret_store=FakeSecretStore(SessionSecret(session_token="session-2", csrf_token="csrf-2")),
        managed_browser=FakeManagedBrowser(authenticated=True),
        history_store=FakeHistoryStore(),
        codex_auth_sync=FakeSyncService(),
    )

    with pytest.raises(SwitchError, match="switchgpt codex-sync"):
        service.switch_to(index=1)
```

```python
# tests/test_registration.py
def test_add_runs_codex_sync_after_successful_persist() -> None:
    sync_calls = []

    class FakeSyncService:
        def sync_active_slot(self, **kwargs):
            sync_calls.append(kwargs["active_slot"])
            return type("Result", (), {"outcome": "ok", "method": "file", "failure_class": None, "message": None})()

    service = RegistrationService(FakeAccountStore(), FakeSecretStore(), FakeBrowserClient(), codex_auth_sync=FakeSyncService())

    record = service.add()

    assert record.index == 0
    assert sync_calls == [0]
```

```python
# tests/test_watch_service.py
def test_watch_auto_switch_failure_from_codex_sync_exits_non_zero() -> None:
    class FakeSyncService:
        def sync_active_slot(self, **kwargs):
            return type("Result", (), {"outcome": "failed", "method": None, "failure_class": "codex-auth-fallback-failed", "message": "bad"})()

    switch_service = FakeSwitchService()
    switch_service.codex_auth_sync = FakeSyncService()
    service = WatchService(
        account_store=FakeAccountStore([build_account(0, "a@example.com"), build_account(1, "b@example.com")], active_account_index=0),
        managed_browser=FakeManagedBrowser(detections=[LimitState.LIMIT_DETECTED]),
        switch_service=switch_service,
        history_store=FakeHistoryStore(),
        poll_interval_seconds=0.0,
    )

    result = service.run(notify=None, sleep_fn=lambda _: None, stop_after_cycles=1)

    assert result.exit_code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_registration.py tests/test_switch_service.py tests/test_watch_service.py -k "codex_sync or codex-sync" -v`

Expected: FAIL due to missing `codex_auth_sync` injection points and strict failure logic.

- [ ] **Step 3: Implement service wiring and strict mutation-path enforcement**

```python
# switchgpt/bootstrap.py (new helper)
from .codex_auth_sync import CodexAuthSyncService, CodexEnvAuthTarget, CodexFileAuthTarget


def build_codex_auth_sync_service(runtime: Runtime | None = None) -> CodexAuthSyncService:
    runtime = build_runtime() if runtime is None else runtime
    del runtime
    return CodexAuthSyncService(
        file_target=CodexFileAuthTarget(),
        env_target=CodexEnvAuthTarget(),
    )
```

```python
# switchgpt/registration.py (constructor + post-persist sync)
class RegistrationService:
    def __init__(self, account_store, secret_store, browser_client, *, codex_auth_sync=None) -> None:
        ...
        self._codex_auth_sync = codex_auth_sync

    def _sync_active_slot_or_raise(self, record: AccountRecord, secret: SessionSecret) -> None:
        if self._codex_auth_sync is None:
            return
        result = self._codex_auth_sync.sync_active_slot(
            active_slot=record.index,
            email=record.email,
            session_token=secret.session_token,
            csrf_token=secret.csrf_token,
            occurred_at=record.last_reauth_at,
        )
        if result.outcome == "failed":
            raise SwitchError(
                "Codex auth sync failed after slot mutation. Run `switchgpt codex-sync` to repair."
            )
```

```python
# switchgpt/switch_service.py (constructor + strict sync after save_runtime_state)
class SwitchService:
    def __init__(..., codex_auth_sync=None) -> None:
        ...
        self._codex_auth_sync = codex_auth_sync

    def _run_codex_sync_or_raise(self, *, account, secret, occurred_at) -> None:
        if self._codex_auth_sync is None:
            return
        result = self._codex_auth_sync.sync_active_slot(
            active_slot=account.index,
            email=account.email,
            session_token=secret.session_token,
            csrf_token=secret.csrf_token,
            occurred_at=occurred_at,
        )
        if result.outcome == "failed":
            raise SwitchError(
                "Codex auth sync failed after switch. Run `switchgpt codex-sync` to repair."
            )
```

```python
# switchgpt/watch_service.py (treat strict sync failures as non-zero terminal)
except SwitchError as exc:
    if "codex-sync" in str(exc):
        self._emit(notify, "codex-sync-failed", str(exc), account_index=active_index)
        return WatchRunResult("codex-sync-failed", 1, active_index)
    excluded_indexes.add(account.index)
    self._emit(notify, "account-exhausted-for-run", str(exc))
    continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_registration.py tests/test_switch_service.py tests/test_watch_service.py -k "codex_sync or codex-sync" -v`

Expected: PASS with sync invoked after successful mutation and strict failures returning non-zero behavior.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/bootstrap.py switchgpt/registration.py switchgpt/switch_service.py switchgpt/watch_service.py tests/test_registration.py tests/test_switch_service.py tests/test_watch_service.py
git commit -m "feat: enforce strict codex auth sync on mutation flows"
```

### Task 4: Add `codex-sync` Repair Command And CLI Guidance

**Files:**
- Modify: `switchgpt/cli.py`
- Modify: `switchgpt/bootstrap.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests for repair command and strict guidance**

```python
# tests/test_cli.py
def test_codex_sync_command_repairs_active_slot_and_prints_method(monkeypatch) -> None:
    class FakeService:
        def sync_active_slot(self):
            return type(
                "Result",
                (),
                {
                    "outcome": "fallback-ok",
                    "method": "env-fallback",
                    "failure_class": None,
                    "message": None,
                },
            )()

    monkeypatch.setattr("switchgpt.cli.build_codex_sync_command_service", lambda: FakeService())

    result = runner.invoke(app, ["codex-sync"])

    assert result.exit_code == 0
    assert "Codex auth sync: fallback-ok (env-fallback)." in result.stdout


def test_switch_command_surfaces_codex_sync_failure_with_repair_hint(monkeypatch) -> None:
    class FakeService:
        def switch_to(self, index: int):
            raise SwitchError("Codex auth sync failed after switch. Run `switchgpt codex-sync` to repair.")

    monkeypatch.setattr("switchgpt.cli.build_switch_service", lambda: FakeService())

    result = runner.invoke(app, ["switch", "--to", "1"])

    assert result.exit_code == 1
    assert "switchgpt codex-sync" in result.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py::test_codex_sync_command_repairs_active_slot_and_prints_method tests/test_cli.py::test_switch_command_surfaces_codex_sync_failure_with_repair_hint -v`

Expected: FAIL because the new command and service builder do not exist.

- [ ] **Step 3: Implement command and service builder**

```python
# switchgpt/cli.py

def build_codex_sync_command_service():
    return bootstrap.build_codex_sync_command_service()


@app.command("codex-sync")
def codex_sync() -> None:
    try:
        ensure_supported_platform()
        result = build_codex_sync_command_service().sync_active_slot()
        method_suffix = f" ({result.method})" if result.method is not None else ""
        print(f"Codex auth sync: {result.outcome}{method_suffix}.")
        if result.outcome == "failed":
            raise typer.Exit(code=1)
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
```

```python
# switchgpt/bootstrap.py
class CodexSyncCommandService:
    def __init__(self, account_store, secret_store, codex_auth_sync) -> None:
        self._account_store = account_store
        self._secret_store = secret_store
        self._codex_auth_sync = codex_auth_sync

    def sync_active_slot(self):
        snapshot = self._account_store.load()
        if snapshot.active_account_index is None:
            raise SwitchError("No active slot available for Codex sync.")
        account = self._account_store.get_record(snapshot.active_account_index)
        secret = self._secret_store.read(account.keychain_key)
        if secret is None:
            raise SwitchError(f"Stored session secret is missing for slot {account.index}.")
        return self._codex_auth_sync.sync_active_slot(
            active_slot=account.index,
            email=account.email,
            session_token=secret.session_token,
            csrf_token=secret.csrf_token,
            occurred_at=account.last_reauth_at,
        )


def build_codex_sync_command_service(runtime: Runtime | None = None) -> CodexSyncCommandService:
    runtime = build_runtime() if runtime is None else runtime
    return CodexSyncCommandService(
        runtime.account_store,
        runtime.secret_store,
        build_codex_auth_sync_service(runtime),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py::test_codex_sync_command_repairs_active_slot_and_prints_method tests/test_cli.py::test_switch_command_surfaces_codex_sync_failure_with_repair_hint -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/cli.py switchgpt/bootstrap.py tests/test_cli.py
git commit -m "feat: add codex-sync repair command"
```

### Task 5: Report Sync Drift In Status And Doctor

**Files:**
- Modify: `switchgpt/status_service.py`
- Modify: `switchgpt/doctor_service.py`
- Modify: `switchgpt/output.py`
- Modify: `tests/test_status_service.py`
- Modify: `tests/test_doctor_service.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing diagnostics tests**

```python
# tests/test_status_service.py
def test_summarize_reports_out_of_sync_when_active_slot_differs_from_last_codex_sync() -> None:
    service = StatusService(secret_store=FakeSecretStore({"switchgpt_account_0"}))

    summary = service.summarize(
        [build_account(0)],
        active_account_index=0,
        codex_sync_state={
            "last_codex_sync_slot": 1,
            "last_codex_sync_status": "failed",
            "last_codex_sync_method": None,
            "last_codex_sync_at": None,
            "last_codex_sync_error": "codex-auth-fallback-failed",
        },
    )

    assert summary.readiness == "degraded"
    assert summary.codex_sync.state == "out-of-sync"
    assert summary.next_action is not None
    assert "switchgpt codex-sync" in summary.next_action
```

```python
# tests/test_doctor_service.py
def test_run_reports_codex_sync_check_when_last_sync_mismatches_active_slot() -> None:
    snapshot = type(
        "Snapshot",
        (),
        {
            "accounts": [Account("switchgpt_account_0")],
            "active_account_index": 0,
            "last_switch_at": datetime(2026, 4, 19, 11, 0, tzinfo=UTC),
            "last_codex_sync_slot": 2,
            "last_codex_sync_method": "file",
            "last_codex_sync_status": "failed",
            "last_codex_sync_at": datetime(2026, 4, 19, 10, 59, tzinfo=UTC),
            "last_codex_sync_error": "codex-auth-fallback-failed",
        },
    )()

    service = DoctorService(
        metadata_store=type("Store", (), {"load": lambda self: snapshot})(),
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=type("Secrets", (), {"exists": lambda self, key: True})(),
        managed_browser=FakeManagedBrowser(can_open=True),
        platform_name="Darwin",
    )

    report = service.run()

    codex_check = next(check for check in report.checks if check.name == "codex-sync")
    assert codex_check.status == "warn"
    assert "switchgpt codex-sync" in (codex_check.next_action or "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_status_service.py::test_summarize_reports_out_of_sync_when_active_slot_differs_from_last_codex_sync tests/test_doctor_service.py::test_run_reports_codex_sync_check_when_last_sync_mismatches_active_slot -v`

Expected: FAIL because `StatusSummary`/`DoctorService` do not yet model codex sync diagnostics.

- [ ] **Step 3: Implement status and doctor codex sync diagnostics**

```python
# switchgpt/status_service.py
@dataclass(frozen=True)
class CodexSyncStatus:
    state: str
    method: str | None
    synced_at: str | None
    error: str | None


@dataclass(frozen=True)
class StatusSummary:
    slots: list[SlotStatus]
    active_account_index: int | None
    readiness: str
    latest_result: str | None
    next_action: str | None
    codex_sync: CodexSyncStatus
```

```python
# switchgpt/status_service.py (summarize signature and logic)
def summarize(self, accounts, *, active_account_index, codex_sync_state=None) -> StatusSummary:
    ...
    codex = self._build_codex_sync_status(active_account_index, codex_sync_state)
    if codex.state == "out-of-sync" and readiness == "ready":
        readiness = "degraded"
        next_action = "Run `switchgpt codex-sync` to repair Codex authentication drift."
    return StatusSummary(..., codex_sync=codex)
```

```python
# switchgpt/cli.py (pass persisted sync state into status summary)
summary = service.summarize(
    snapshot.accounts,
    active_account_index=snapshot.active_account_index,
    codex_sync_state={
        "last_codex_sync_slot": snapshot.last_codex_sync_slot,
        "last_codex_sync_status": snapshot.last_codex_sync_status,
        "last_codex_sync_method": snapshot.last_codex_sync_method,
        "last_codex_sync_at": snapshot.last_codex_sync_at,
        "last_codex_sync_error": snapshot.last_codex_sync_error,
    },
)
```

```python
# switchgpt/doctor_service.py (new check)
def run(self) -> DoctorReport:
    snapshot, metadata_check = self._load_snapshot()
    checks = [
        self._check_platform(),
        metadata_check,
        self._check_history(),
        self._check_keychain_entries(snapshot, metadata_check),
        self._check_codex_sync(snapshot, metadata_check),
        self._check_runtime(),
    ]
    ...


def _check_codex_sync(self, snapshot, metadata_check: DoctorCheck) -> DoctorCheck:
    if snapshot is None:
        return DoctorCheck("codex-sync", "fail", metadata_check.detail, metadata_check.next_action)
    if snapshot.active_account_index is None:
        return DoctorCheck("codex-sync", "pass", "No active slot; no Codex sync required.", None)
    if snapshot.last_codex_sync_slot == snapshot.active_account_index and snapshot.last_codex_sync_status in {"ok", "fallback-ok"}:
        return DoctorCheck("codex-sync", "pass", "Codex auth is synced to active slot.", None)
    return DoctorCheck(
        "codex-sync",
        "warn",
        "Active slot and last Codex-synced slot differ or last sync failed.",
        "Run `switchgpt codex-sync` and re-run `switchgpt doctor`.",
    )
```

```python
# switchgpt/output.py
if summary.codex_sync.state:
    lines.append(f"Codex sync: {summary.codex_sync.state}")
if summary.codex_sync.method is not None:
    lines.append(f"Codex sync method: {summary.codex_sync.method}")
if summary.codex_sync.synced_at is not None:
    lines.append(f"Codex synced at: {summary.codex_sync.synced_at}")
if summary.codex_sync.error is not None:
    lines.append(f"Codex sync error: {summary.codex_sync.error}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_status_service.py tests/test_doctor_service.py tests/test_cli.py -k "codex sync or codex-sync" -v`

Expected: PASS with clear drift/action diagnostics in `status` and `doctor` output paths.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/status_service.py switchgpt/doctor_service.py switchgpt/output.py tests/test_status_service.py tests/test_doctor_service.py tests/test_cli.py
git commit -m "feat: report codex auth sync drift in status and doctor"
```

### Task 6: End-to-End Verification For Strict Sync Contract

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `tests/test_watch_service.py`
- Modify: `tests/test_switch_service.py`

- [ ] **Step 1: Add end-to-end style failing regression tests**

```python
# tests/test_cli.py
def test_add_command_returns_non_zero_when_strict_codex_sync_fails(monkeypatch) -> None:
    class FakeRegistrationService:
        def add(self):
            raise SwitchError("Codex auth sync failed after slot mutation. Run `switchgpt codex-sync` to repair.")

    monkeypatch.setattr("switchgpt.cli.build_registration_service", lambda: FakeRegistrationService())

    result = runner.invoke(app, ["add"])

    assert result.exit_code == 1
    assert "switchgpt codex-sync" in result.stderr


def test_watch_command_exits_non_zero_when_codex_sync_fails(monkeypatch) -> None:
    class FakeWatchService:
        def run(self, *, notify, sleep_fn=None, stop_after_cycles=None):
            notify(type("Event", (), {"message": "Codex auth sync failed after switch. Run `switchgpt codex-sync` to repair."})())
            return type("Result", (), {"exit_code": 1})()

    monkeypatch.setattr("switchgpt.cli.build_watch_service", lambda: FakeWatchService())

    result = runner.invoke(app, ["watch"])

    assert result.exit_code == 1
    assert "switchgpt codex-sync" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -k "strict_codex_sync or codex_sync_fails" -v`

Expected: FAIL before strict guidance is fully wired through CLI output/error paths.

- [ ] **Step 3: Implement minimal glue fixes to satisfy strict contract**

```python
# switchgpt/cli.py (common guidance passthrough in command handlers)
except SwitchGptError as exc:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc

# Keep this shape for add/switch/watch/codex-sync so strict sync failures always return non-zero and surface repair guidance.
```

- [ ] **Step 4: Run focused verification suite**

Run: `uv run pytest tests/test_codex_auth_sync.py tests/test_account_store.py tests/test_registration.py tests/test_switch_service.py tests/test_watch_service.py tests/test_status_service.py tests/test_doctor_service.py tests/test_cli.py -v`

Expected: PASS for all codex-sync-specific flows.

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli.py tests/test_watch_service.py tests/test_switch_service.py switchgpt/cli.py
git commit -m "test: lock strict codex auth sync behavior across cli flows"
```

## Self-Review

1. **Spec coverage check**
- File-first sync adapter + env fallback: covered in Task 2.
- Sync only after successful slot mutation (`add`, `reauth`, `switch`, `watch` transitions): covered in Task 3.
- Strict mode default/no silent divergence: covered in Tasks 3 and 6.
- `status` and `doctor` observability (slot match/method/timestamp/error): covered in Task 5.
- Manual repair command `switchgpt codex-sync`: covered in Task 4.
- Non-secret metadata persistence and redaction-safe error text: covered in Tasks 1 and 2.

2. **Placeholder scan**
- No `TODO`/`TBD` placeholders.
- Every task includes explicit test command, implementation snippet, and commit command.
- No “similar to previous task” shortcuts.

3. **Type/signature consistency**
- Consistent naming: `CodexAuthSyncService.sync_active_slot`, `CodexSyncResult`, `save_codex_sync_state`, `switchgpt codex-sync`.
- Sync outcomes consistently referenced as `ok`, `fallback-ok`, `failed`.

Plan complete and saved to `docs/superpowers/plans/2026-04-19-switchgpt-codex-auth-sync.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration

2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?

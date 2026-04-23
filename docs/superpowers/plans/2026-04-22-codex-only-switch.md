# Codex-Only Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `switchgpt switch --to <slot>` update only Codex CLI authentication and never depend on browser session authentication.

**Architecture:** Keep the existing `SwitchService` entrypoints and history/runtime-state behavior, but remove managed-browser interaction from the switch path. The service should validate the target slot secret, project stored `codex_auth_json` through `CodexAuthSyncService`, persist runtime state, and record history. CLI behavior remains the same except that reauthentication errors are replaced by direct Codex import repair guidance.

**Tech Stack:** Python, Typer CLI, pytest, existing `CodexAuthSyncService`, existing account/secret/history stores

---

## File Structure

- Modify: `switchgpt/switch_service.py`
  Responsibility: remove browser-auth switching from `SwitchService` while preserving slot lookup, secret lookup, Codex auth projection, runtime-state persistence, and history recording.
- Modify: `tests/test_switch_service.py`
  Responsibility: prove `SwitchService` no longer uses `managed_browser`, still updates runtime state/history, and fails with Codex-specific repair guidance when imported auth is missing.
- Modify: `tests/test_cli.py`
  Responsibility: prove the `switch` command still renders Codex repair guidance through the CLI when sync fails for the selected slot.

### Task 1: Lock in Codex-Only Switch Tests

**Files:**
- Modify: `tests/test_switch_service.py`
- Test: `tests/test_switch_service.py`

- [ ] **Step 1: Write the failing service tests**

Add these tests to `tests/test_switch_service.py` near the existing `SwitchService` coverage:

```python
def test_switch_to_does_not_touch_managed_browser_for_codex_only_switch() -> None:
    class StrictManagedBrowser:
        def ensure_runtime(self):
            raise AssertionError("managed browser should not be used")

        def prepare_switch(self, *args, **kwargs):
            raise AssertionError("managed browser should not be used")

        def is_authenticated(self, *args, **kwargs):
            raise AssertionError("managed browser should not be used")

    class FakeSyncService:
        def sync_active_slot(self, **kwargs):
            return type(
                "Result",
                (),
                {
                    "outcome": "ok",
                    "method": "file",
                    "failure_class": None,
                    "message": None,
                },
            )()

    service = SwitchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        secret_store=FakeSecretStore(
            SessionSecret(
                session_token="stale-browser-cookie",
                csrf_token="stale-browser-csrf",
                codex_auth_json={
                    "tokens": {
                        "access_token": "access-2",
                        "refresh_token": "refresh-2",
                        "id_token": "id-2",
                        "account_id": "account-2",
                    }
                },
            )
        ),
        managed_browser=StrictManagedBrowser(),
        history_store=FakeHistoryStore(),
        codex_auth_sync=FakeSyncService(),
    )

    result = service.switch_to(index=1)

    assert result.account.index == 1
    assert service._account_store.saved_runtime_state[0] == 1
    assert service._history_store.events[-1].result == "success"


def test_switch_to_missing_imported_codex_auth_raises_repair_guidance() -> None:
    class FakeSyncService:
        def sync_active_slot(self, **kwargs):
            del kwargs
            return type(
                "Result",
                (),
                {
                    "outcome": "failed",
                    "method": None,
                    "failure_class": "codex-auth-source-missing",
                    "message": "codex-auth-source-missing: no imported auth.json stored for this slot",
                },
            )()

    service = SwitchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        secret_store=FakeSecretStore(
            SessionSecret(session_token="", csrf_token=None, codex_auth_json=None)
        ),
        managed_browser=object(),
        history_store=FakeHistoryStore(),
        codex_auth_sync=FakeSyncService(),
    )

    with pytest.raises(
        CodexAuthSyncFailedError,
        match="switchgpt import-codex-auth --slot 1",
    ):
        service.switch_to(index=1)

    assert service._history_store.events[-1].result == "failure"
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `uv run pytest tests/test_switch_service.py -q`

Expected: FAIL because `test_switch_to_does_not_touch_managed_browser_for_codex_only_switch` still triggers the managed-browser path in `SwitchService._switch_account`.

- [ ] **Step 3: Commit the failing-test checkpoint**

```bash
git add tests/test_switch_service.py
git commit -m "test: define codex-only switch behavior"
```

### Task 2: Remove Browser Switching From `SwitchService`

**Files:**
- Modify: `switchgpt/switch_service.py`
- Test: `tests/test_switch_service.py`

- [ ] **Step 1: Replace the service implementation with the Codex-only path**

Update `switchgpt/switch_service.py` as follows:

```python
from dataclasses import dataclass
from datetime import UTC, datetime

from .codex_auth_sync import raise_for_failed_sync
from .diagnostics import redact_text
from .errors import CodexAuthSyncFailedError, SwitchError
from .switch_history import SwitchEvent


@dataclass(frozen=True)
class SwitchResult:
    account: object
    mode: str


class SwitchService:
    def __init__(
        self,
        account_store,
        secret_store,
        managed_browser,
        history_store,
        *,
        codex_auth_sync=None,
    ) -> None:
        self._account_store = account_store
        self._secret_store = secret_store
        self._managed_browser = managed_browser
        self._history_store = history_store
        self._codex_auth_sync = codex_auth_sync

    def switch_next(self, *, mode: str = "auto-target") -> SwitchResult:
        occurred_at = datetime.now(UTC)
        previous_active_index = None
        try:
            snapshot = self._account_store.load()
            previous_active_index = snapshot.active_account_index
            candidates = [
                account
                for account in snapshot.accounts
                if account.index != snapshot.active_account_index
            ]
            if not candidates:
                raise SwitchError(
                    "No alternative registered account is available for switching."
                )
        except Exception as exc:
            self._append_event(
                occurred_at=occurred_at,
                previous_active_index=previous_active_index,
                account_index=None,
                mode=mode,
                result="failure",
                message=str(exc),
            )
            raise
        return self._switch_account(candidates[0], mode=mode)

    def switch_to(self, index: int, *, mode: str = "explicit-target") -> SwitchResult:
        return self._switch_account(
            account=None,
            account_index=index,
            mode=mode,
        )

    def _switch_account(
        self,
        account,
        *,
        mode: str,
        account_index: int | None = None,
    ) -> SwitchResult:
        previous_active_index = None
        occurred_at = datetime.now(UTC)
        failure_result = "failure"
        try:
            previous_active_index = self._account_store.load().active_account_index
            if account is None:
                if account_index is None:
                    raise SwitchError("Switch target is required.")
                account = self._account_store.get_record(account_index)
            else:
                account_index = account.index

            secret = self._secret_store.read(account.keychain_key)
            if secret is None:
                failure_result = "missing-secret"
                raise SwitchError(
                    f"Stored session secret is missing for slot {account.index}."
                )

            self._account_store.save_runtime_state(account.index, occurred_at)
            self._sync_active_slot_or_raise(
                account=account,
                secret=secret,
                occurred_at=occurred_at,
            )
        except Exception as exc:
            if account_index is not None:
                self._append_event(
                    occurred_at=occurred_at,
                    previous_active_index=previous_active_index,
                    account_index=account_index,
                    mode=mode,
                    result=failure_result,
                    message=str(exc),
                )
            raise

        self._append_event(
            occurred_at=occurred_at,
            previous_active_index=previous_active_index,
            account_index=account.index,
            mode=mode,
            result=self._success_result_for_mode(mode),
            message=None,
        )
        return SwitchResult(account=account, mode=mode)

    def _sync_active_slot_or_raise(self, *, account, secret, occurred_at: datetime) -> None:
        if self._codex_auth_sync is None:
            return
        result = self._codex_auth_sync.sync_active_slot(
            active_slot=account.index,
            email=account.email,
            session_token=secret.session_token,
            csrf_token=secret.csrf_token,
            codex_auth_json=getattr(secret, "codex_auth_json", None),
            occurred_at=occurred_at,
        )
        try:
            raise_for_failed_sync(result)
        except CodexAuthSyncFailedError as exc:
            raise CodexAuthSyncFailedError(
                "Codex auth sync failed after switch. Run `codex login` with the target account, then "
                f"`switchgpt import-codex-auth --slot {account.index}` and retry `switchgpt switch --to {account.index}`.",
                failure_class=exc.failure_class,
            ) from exc

    def _success_result_for_mode(self, mode: str) -> str:
        return "switch-succeeded" if mode == "watch-auto" else "success"

    def _append_event(
        self,
        *,
        occurred_at: datetime,
        previous_active_index: int | None,
        account_index: int | None,
        mode: str,
        result: str,
        message: str | None,
    ) -> None:
        self._history_store.append(
            SwitchEvent(
                occurred_at=occurred_at,
                from_account_index=previous_active_index,
                to_account_index=account_index,
                mode=mode,
                result=result,
                message=redact_text(message) if message is not None else None,
            )
        )
```

- [ ] **Step 2: Remove obsolete browser-reauth test coverage**

Delete the old browser-auth failure tests from `tests/test_switch_service.py`, specifically the tests that assert `ReauthRequiredError` or depend on `FakeManagedBrowser(authenticated=False)`. Remove the stale import at the top as well:

```python
from switchgpt.errors import CodexAuthSyncFailedError, SwitchError
```

- [ ] **Step 3: Run the service tests to verify they pass**

Run: `uv run pytest tests/test_switch_service.py -q`

Expected: PASS. The new strict managed-browser test should pass because `SwitchService` never calls browser methods during `switch`.

- [ ] **Step 4: Commit the service refactor**

```bash
git add switchgpt/switch_service.py tests/test_switch_service.py
git commit -m "feat: make switch codex-only"
```

### Task 3: Verify CLI Repair Guidance For Codex-Only Switch

**Files:**
- Modify: `tests/test_cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI regression test**

Add this test to `tests/test_cli.py` near the existing `switch` command tests:

```python
def test_switch_command_surfaces_codex_only_repair_guidance(monkeypatch) -> None:
    class FakeSwitchService:
        def switch_to(self, index: int, mode: str = "explicit-target"):
            assert index == 1
            assert mode == "explicit-target"
            raise CodexAuthSyncFailedError(
                "Codex auth sync failed after switch. Run `codex login` with the target account, then "
                "`switchgpt import-codex-auth --slot 1` and retry `switchgpt switch --to 1`.",
                failure_class="codex-auth-source-missing",
            )

    monkeypatch.setattr("switchgpt.cli.ensure_supported_platform", lambda: None)
    monkeypatch.setattr(
        "switchgpt.cli.bootstrap.build_switch_service",
        lambda: FakeSwitchService(),
    )

    result = runner.invoke(app, ["switch", "--to", "1"])

    assert result.exit_code == 1
    assert "switchgpt import-codex-auth --slot 1" in result.stderr
    assert "switchgpt switch --to 1" in result.stderr
```

- [ ] **Step 2: Run the targeted CLI test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_switch_command_surfaces_codex_only_repair_guidance -q`

Expected: FAIL before the implementation if the CLI still rewrites the repair message to `retry switchgpt codex-sync` instead of preserving the new `retry switchgpt switch --to 1` guidance.

- [ ] **Step 3: Adjust the CLI repair-message helper if needed**

If the test fails because `_render_codex_sync_repair_message()` rewrites the new guidance, update `switchgpt/cli.py` so it preserves messages that already mention `switchgpt switch --to`:

```python
def _render_codex_sync_repair_message(message: str | None) -> str:
    detail = (message or "Codex auth sync failed.").strip()
    if (
        "switchgpt codex-sync" in detail
        or "switchgpt import-codex-auth" in detail
        or "switchgpt switch --to" in detail
    ):
        return detail
    if detail.endswith("."):
        return f"{detail} Run `switchgpt codex-sync` to repair."
    return f"{detail}. Run `switchgpt codex-sync` to repair."
```

- [ ] **Step 4: Run the focused CLI and service tests together**

Run: `uv run pytest tests/test_switch_service.py tests/test_cli.py -q`

Expected: PASS with all switch-related regression coverage green.

- [ ] **Step 5: Commit the CLI regression coverage**

```bash
git add tests/test_cli.py switchgpt/cli.py
git commit -m "test: cover codex-only switch cli guidance"
```

### Task 4: Final Verification

**Files:**
- Test: `tests/test_switch_service.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Run the final verification command**

Run: `uv run pytest tests/test_switch_service.py tests/test_cli.py -q`

Expected: PASS with exit code `0`.

- [ ] **Step 2: Inspect the resulting diff before handing off**

Run: `git diff -- switchgpt/switch_service.py switchgpt/cli.py tests/test_switch_service.py tests/test_cli.py`

Expected: the diff removes managed-browser use from `SwitchService`, preserves runtime/history behavior, and adds Codex-only regression coverage.

- [ ] **Step 3: Commit the final verified state if previous task commits were skipped**

```bash
git add switchgpt/switch_service.py switchgpt/cli.py tests/test_switch_service.py tests/test_cli.py
git commit -m "feat: switch slots using codex auth only"
```

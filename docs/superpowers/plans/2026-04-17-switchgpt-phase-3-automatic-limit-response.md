# switchgpt Phase 3 Automatic Limit Response Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a foreground `switchgpt watch` command that monitors the managed ChatGPT browser for a supported usage-limit state and immediately rotates to the next eligible registered account.

**Architecture:** Keep the Phase 2 seam intact. `managed_browser` owns browser-side limit detection, `switch_service` still executes one switch attempt, and a new `watch_service` owns polling, in-run exclusions, and stop conditions. CLI wiring should stay thin and only translate structured watch events and terminal outcomes into user-visible output and exit codes.

**Tech Stack:** Python 3.12, Typer, Playwright sync API, pytest, uv

---

## File Structure

- Modify: `switchgpt/models.py`
  Purpose: add the bounded `LimitState` enum shared by browser detection and watch orchestration.
- Modify: `switchgpt/managed_browser.py`
  Purpose: expose `detect_limit_state(page)` without mixing browser detection with account policy.
- Modify: `switchgpt/switch_service.py`
  Purpose: allow automation-specific event modes and emit bounded per-account failure categories for watch runs.
- Create: `switchgpt/watch_service.py`
  Purpose: own the foreground watch loop, target selection, per-run exclusions, structured watch notifications, and terminal automation history events.
- Modify: `switchgpt/cli.py`
  Purpose: add `switchgpt watch`, construct `WatchService`, print watch events, and map terminal outcomes to exit codes.
- Modify: `tests/test_managed_browser.py`
  Purpose: verify `detect_limit_state()` behavior for positive, negative, and ambiguous page states.
- Modify: `tests/test_switch_service.py`
  Purpose: verify automation mode support and bounded failure categories used by the watch loop.
- Create: `tests/test_watch_service.py`
  Purpose: verify watch-loop state transitions, target selection, exclusion behavior, exhaustion, and interrupt handling.
- Modify: `tests/test_cli.py`
  Purpose: verify `watch` command output and exit-code behavior.
- Create: `docs/manual-tests/2026-04-17-phase-3-automatic-limit-response.md`
  Purpose: capture the manual validation flow for the new foreground automation command.

### Task 1: Add The Limit Detection Contract

**Files:**
- Modify: `switchgpt/models.py`
- Modify: `switchgpt/managed_browser.py`
- Test: `tests/test_managed_browser.py`

- [ ] **Step 1: Write the failing tests**

```python
from switchgpt.models import LimitState


def test_detect_limit_state_returns_limit_detected_for_usage_cap_banner() -> None:
    browser = ManagedBrowser("https://chatgpt.com", profile_dir=None)
    page = FakePage()
    page.text = "You have reached the limit for GPT-5 messages. Try again later."

    assert browser.detect_limit_state(page) is LimitState.LIMIT_DETECTED


def test_detect_limit_state_returns_no_limit_detected_for_normal_workspace() -> None:
    browser = ManagedBrowser("https://chatgpt.com", profile_dir=None)
    page = FakePage()
    page.text = "ChatGPT Open sidebar"

    assert browser.detect_limit_state(page) is LimitState.NO_LIMIT_DETECTED


def test_detect_limit_state_returns_unknown_when_page_text_cannot_be_read() -> None:
    browser = ManagedBrowser("https://chatgpt.com", profile_dir=None)

    class BrokenPage(FakePage):
        def inner_text(self) -> str:
            raise RuntimeError("DOM unavailable")

    assert browser.detect_limit_state(BrokenPage()) is LimitState.UNKNOWN
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_managed_browser.py -q`

Expected: FAIL with `ImportError` for `LimitState` or `AttributeError` for missing `detect_limit_state`.

- [ ] **Step 3: Write minimal implementation**

```python
# switchgpt/models.py
class LimitState(StrEnum):
    LIMIT_DETECTED = "limit_detected"
    NO_LIMIT_DETECTED = "no_limit_detected"
    UNKNOWN = "unknown"
```

```python
# switchgpt/managed_browser.py
from .models import LimitState


def detect_limit_state(self, page) -> LimitState:
    try:
        body = page.locator("body").inner_text().lower()
    except Exception:
        return LimitState.UNKNOWN

    limit_markers = (
        "you have reached the limit",
        "try again later",
        "usage limit",
    )
    if any(marker in body for marker in limit_markers):
        return LimitState.LIMIT_DETECTED
    return LimitState.NO_LIMIT_DETECTED
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_managed_browser.py -q`

Expected: PASS for the new detection tests and the existing managed-browser tests.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/models.py switchgpt/managed_browser.py tests/test_managed_browser.py
git commit -m "feat: add managed browser limit detection"
```

### Task 2: Refine Switch Outcomes For Automation

**Files:**
- Modify: `switchgpt/switch_service.py`
- Test: `tests/test_switch_service.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_switch_to_records_watch_auto_mode_for_automation_success() -> None:
    service = SwitchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        secret_store=FakeSecretStore(
            SessionSecret(session_token="session-2", csrf_token="csrf-2")
        ),
        managed_browser=FakeManagedBrowser(authenticated=True),
        history_store=FakeHistoryStore(),
    )

    result = service.switch_to(index=1, mode="watch-auto")

    assert result.mode == "watch-auto"
    assert service._history_store.events[-1].mode == "watch-auto"
    assert service._history_store.events[-1].result == "switch-succeeded"


def test_missing_secret_records_bounded_missing_secret_result() -> None:
    service = SwitchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        secret_store=FakeSecretStore(None),
        managed_browser=FakeManagedBrowser(authenticated=True),
        history_store=FakeHistoryStore(),
    )

    with pytest.raises(SwitchError, match="Stored session secret is missing"):
        service.switch_to(index=1, mode="watch-auto")

    assert service._history_store.events[-1].result == "missing-secret"


def test_failed_auth_verification_records_post_switch_auth_failed() -> None:
    service = SwitchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        secret_store=FakeSecretStore(
            SessionSecret(session_token="session-2", csrf_token=None)
        ),
        managed_browser=FakeManagedBrowser(authenticated=False),
        history_store=FakeHistoryStore(),
    )

    with pytest.raises(SwitchError, match="likely needs reauthentication"):
        service.switch_to(index=1, mode="watch-auto")

    assert service._history_store.events[-1].result == "post-switch-auth-failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_switch_service.py -q`

Expected: FAIL because `switch_to()` does not accept a `mode` override and still records generic `failure` / `needs-reauth` results.

- [ ] **Step 3: Write minimal implementation**

```python
# switchgpt/switch_service.py
def switch_next(self, *, mode: str = "auto-target") -> SwitchResult:
    ...
    return self._switch_account(candidates[0], mode=mode)


def switch_to(self, index: int, *, mode: str = "explicit-target") -> SwitchResult:
    return self._switch_account(
        account=None,
        account_index=index,
        mode=mode,
    )


def _result_for_failure(self, exc: Exception) -> str:
    message = str(exc).lower()
    if "stored session secret is missing" in message:
        return "missing-secret"
    if "likely needs reauthentication" in message:
        return "post-switch-auth-failed"
    return "failure"


def _success_result_for_mode(self, mode: str) -> str:
    return "switch-succeeded" if mode == "watch-auto" else "success"
```

```python
# inside _switch_account()
if not self._managed_browser.is_authenticated(page):
    raise SwitchError(
        f"Account slot {account.index} likely needs reauthentication."
    )

...
except Exception as exc:
    if not event_recorded and account_index is not None:
        self._append_event(
            occurred_at=occurred_at,
            previous_active_index=previous_active_index,
            account_index=account_index,
            mode=mode,
            result=self._result_for_failure(exc),
            message=str(exc),
        )
    raise

...
self._append_event(
    occurred_at=occurred_at,
    previous_active_index=previous_active_index,
    account_index=account.index,
    mode=mode,
    result=self._success_result_for_mode(mode),
    message=None,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_switch_service.py -q`

Expected: PASS for the new automation-outcome tests and the existing manual-switch tests.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/switch_service.py tests/test_switch_service.py
git commit -m "feat: add bounded switch outcomes for automation"
```

### Task 3: Add The Foreground Watch Service

**Files:**
- Create: `switchgpt/watch_service.py`
- Test: `tests/test_watch_service.py`

- [ ] **Step 1: Write the failing tests**

```python
from switchgpt.models import LimitState
from switchgpt.watch_service import WatchService


def test_run_switches_immediately_when_limit_is_detected() -> None:
    notifications = []
    managed_browser = FakeManagedBrowser(
        detections=[
            LimitState.NO_LIMIT_DETECTED,
            LimitState.LIMIT_DETECTED,
        ]
    )
    switch_service = FakeSwitchService()
    history_store = FakeHistoryStore()
    service = WatchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        managed_browser=managed_browser,
        switch_service=switch_service,
        history_store=history_store,
        poll_interval_seconds=0.0,
    )

    result = service.run(
        notify=notifications.append,
        sleep_fn=lambda _: None,
        stop_after_cycles=2,
    )

    assert switch_service.calls == [(1, "watch-auto")]
    assert result.reason == "cycle-limit"
    assert any(event.kind == "limit-detected" for event in notifications)
    assert any(event.kind == "switch-succeeded" for event in notifications)


def test_run_marks_failed_slot_unavailable_and_tries_next_candidate() -> None:
    managed_browser = FakeManagedBrowser(detections=[LimitState.LIMIT_DETECTED])
    switch_service = FakeSwitchService(
        failures={
            1: SwitchError("Stored session secret is missing for slot 1."),
        }
    )
    history_store = FakeHistoryStore()
    service = WatchService(
        account_store=FakeAccountStore(
            [
                build_account(0, "a@example.com"),
                build_account(1, "b@example.com"),
                build_account(2, "c@example.com"),
            ],
            active_account_index=0,
        ),
        managed_browser=managed_browser,
        switch_service=switch_service,
        history_store=history_store,
        poll_interval_seconds=0.0,
    )

    result = service.run(
        notify=None,
        sleep_fn=lambda _: None,
        stop_after_cycles=1,
    )

    assert switch_service.calls == [(1, "watch-auto"), (2, "watch-auto")]
    assert result.active_account_index == 2


def test_run_stops_with_no_eligible_account_when_all_candidates_fail() -> None:
    managed_browser = FakeManagedBrowser(detections=[LimitState.LIMIT_DETECTED])
    switch_service = FakeSwitchService(
        failures={
            1: SwitchError("Stored session secret is missing for slot 1."),
            2: SwitchError("Account slot 2 likely needs reauthentication."),
        }
    )
    history_store = FakeHistoryStore()
    service = WatchService(
        account_store=FakeAccountStore(
            [
                build_account(0, "a@example.com"),
                build_account(1, "b@example.com"),
                build_account(2, "c@example.com"),
            ],
            active_account_index=0,
        ),
        managed_browser=managed_browser,
        switch_service=switch_service,
        history_store=history_store,
        poll_interval_seconds=0.0,
    )

    result = service.run(
        notify=None,
        sleep_fn=lambda _: None,
        stop_after_cycles=1,
    )

    assert result.reason == "no-eligible-account"
    assert result.exit_code == 1
    assert history_store.events[-1].mode == "watch-auto"
    assert history_store.events[-1].result == "no-eligible-account"


def test_run_returns_user_interrupted_when_sleep_is_interrupted() -> None:
    history_store = FakeHistoryStore()
    service = WatchService(
        account_store=FakeAccountStore([build_account(0, "a@example.com"), build_account(1, "b@example.com")], active_account_index=0),
        managed_browser=FakeManagedBrowser(detections=[LimitState.NO_LIMIT_DETECTED]),
        switch_service=FakeSwitchService(),
        history_store=history_store,
        poll_interval_seconds=1.0,
    )

    result = service.run(
        notify=None,
        sleep_fn=lambda _: (_ for _ in ()).throw(KeyboardInterrupt()),
        stop_after_cycles=None,
    )

    assert result.reason == "user-interrupted"
    assert result.exit_code == 130
    assert history_store.events[-1].result == "user-interrupted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_watch_service.py -q`

Expected: FAIL because `switchgpt/watch_service.py` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# switchgpt/watch_service.py
from dataclasses import dataclass
from datetime import UTC, datetime
import time

from .errors import ManagedBrowserError, SwitchError
from .models import LimitState
from .switch_history import SwitchEvent


@dataclass(frozen=True)
class WatchNotification:
    kind: str
    message: str


@dataclass(frozen=True)
class WatchRunResult:
    reason: str
    exit_code: int
    active_account_index: int | None


class WatchService:
    def __init__(self, account_store, managed_browser, switch_service, history_store, *, poll_interval_seconds: float = 2.0) -> None:
        self._account_store = account_store
        self._managed_browser = managed_browser
        self._switch_service = switch_service
        self._history_store = history_store
        self._poll_interval_seconds = poll_interval_seconds

    def run(self, *, notify=None, sleep_fn=time.sleep, stop_after_cycles: int | None = None) -> WatchRunResult:
        snapshot = self._account_store.load()
        if len(snapshot.accounts) < 2:
            raise SwitchError("Automatic switching requires at least two registered accounts.")
        if snapshot.active_account_index is None:
            raise SwitchError("Automatic switching requires a known active account.")

        context, page = self._managed_browser.ensure_runtime()
        del context
        excluded_indexes: set[int] = set()
        active_index = snapshot.active_account_index
        cycles = 0
        self._emit(notify, "monitoring-started", "Watching the managed ChatGPT workspace for usage limits.")

        while True:
            try:
                detection = self._managed_browser.detect_limit_state(page)
            except ManagedBrowserError:
                return WatchRunResult("browser-runtime-failure", 1, active_index)

            if detection is LimitState.LIMIT_DETECTED:
                self._emit(notify, "limit-detected", "Usage limit detected. Switching immediately.")
                snapshot = self._account_store.load()
                candidates = [
                    account for account in snapshot.accounts
                    if account.index != active_index and account.index not in excluded_indexes
                ]
                for account in candidates:
                    self._emit(notify, "switch-attempt", f"Trying slot {account.index}.")
                    try:
                        result = self._switch_service.switch_to(account.index, mode="watch-auto")
                    except SwitchError as exc:
                        excluded_indexes.add(account.index)
                        self._emit(notify, "account-exhausted-for-run", str(exc))
                        continue
                    active_index = result.account.index
                    self._emit(notify, "switch-succeeded", f"Switched to slot {active_index}.")
                    break
                else:
                    self._emit(notify, "no-eligible-account", "No eligible registered account remains for automatic switching.")
                    self._history_store.append(
                        SwitchEvent(
                            occurred_at=datetime.now(UTC),
                            from_account_index=active_index,
                            to_account_index=None,
                            mode="watch-auto",
                            result="no-eligible-account",
                            message="No eligible registered account remains for automatic switching.",
                        )
                    )
                    return WatchRunResult("no-eligible-account", 1, active_index)

            cycles += 1
            if stop_after_cycles is not None and cycles >= stop_after_cycles:
                return WatchRunResult("cycle-limit", 0, active_index)

            try:
                sleep_fn(self._poll_interval_seconds)
            except KeyboardInterrupt:
                self._emit(notify, "user-interrupted", "Stopped watching for usage limits.")
                self._history_store.append(
                    SwitchEvent(
                        occurred_at=datetime.now(UTC),
                        from_account_index=active_index,
                        to_account_index=None,
                        mode="watch-auto",
                        result="user-interrupted",
                        message="Stopped watching for usage limits.",
                    )
                )
                return WatchRunResult("user-interrupted", 130, active_index)

    def _emit(self, notify, kind: str, message: str) -> None:
        if notify is not None:
            notify(WatchNotification(kind=kind, message=message))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_watch_service.py -q`

Expected: PASS for the new watch-service tests.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/watch_service.py tests/test_watch_service.py
git commit -m "feat: add foreground watch service"
```

### Task 4: Wire The Watch Command Into The CLI

**Files:**
- Modify: `switchgpt/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_watch_command_prints_notifications_and_exits_zero_for_short_run(monkeypatch) -> None:
    class FakeWatchService:
        def run(self, *, notify, sleep_fn=None, stop_after_cycles=None):
            notify(type("Event", (), {"message": "Watching the managed ChatGPT workspace for usage limits."})())
            notify(type("Event", (), {"message": "Usage limit detected. Switching immediately."})())
            notify(type("Event", (), {"message": "Switched to slot 1."})())
            return type("Result", (), {"exit_code": 0})()

    monkeypatch.setattr("switchgpt.cli.build_watch_service", lambda: FakeWatchService())

    result = runner.invoke(app, ["watch"])

    assert result.exit_code == 0
    assert "Watching the managed ChatGPT workspace for usage limits." in result.stdout
    assert "Switched to slot 1." in result.stdout


def test_watch_command_exits_non_zero_on_exhaustion(monkeypatch) -> None:
    class FakeWatchService:
        def run(self, *, notify, sleep_fn=None, stop_after_cycles=None):
            notify(type("Event", (), {"message": "No eligible registered account remains for automatic switching."})())
            return type("Result", (), {"exit_code": 1})()

    monkeypatch.setattr("switchgpt.cli.build_watch_service", lambda: FakeWatchService())

    result = runner.invoke(app, ["watch"])

    assert result.exit_code == 1
    assert "No eligible registered account remains for automatic switching." in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -q`

Expected: FAIL because `build_watch_service()` and the `watch` command do not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# switchgpt/cli.py
from .watch_service import WatchService


def build_watch_service() -> WatchService:
    settings = Settings.from_env()
    store = AccountStore(settings.metadata_path, settings.slot_count)
    secret_store = KeychainSecretStore(settings.keychain_service)
    managed_browser = ManagedBrowser(
        base_url=settings.chatgpt_base_url,
        profile_dir=settings.managed_profile_dir,
    )
    history_store = SwitchHistoryStore(settings.switch_history_path)
    switch_service = SwitchService(store, secret_store, managed_browser, history_store)
    return WatchService(
        account_store=store,
        managed_browser=managed_browser,
        switch_service=switch_service,
        history_store=history_store,
    )


@app.command()
def watch() -> None:
    try:
        ensure_supported_platform()
        service = build_watch_service()

        def print_event(event) -> None:
            print(event.message)

        result = service.run(notify=print_event)
        if result.exit_code != 0:
            raise typer.Exit(code=result.exit_code)
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -q`

Expected: PASS for the new watch-command tests and the existing CLI coverage.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/cli.py tests/test_cli.py
git commit -m "feat: add watch command"
```

### Task 5: Verify History Coverage And Manual Validation

**Files:**
- Modify: `tests/test_switch_history.py`
- Create: `docs/manual-tests/2026-04-17-phase-3-automatic-limit-response.md`

- [ ] **Step 1: Write the failing test and manual test skeleton**

```python
def test_load_reads_watch_auto_events_from_jsonl(tmp_path) -> None:
    history_path = tmp_path / "switch-history.jsonl"
    history_path.write_text(
        json.dumps(
            {
                "occurred_at": "2026-04-17T11:15:00+00:00",
                "from_account_index": 0,
                "to_account_index": 1,
                "mode": "watch-auto",
                "result": "switch-succeeded",
                "message": None,
            }
        )
        + "\n"
    )

    store = SwitchHistoryStore(history_path)

    assert store.load()[0].mode == "watch-auto"
    assert store.load()[0].result == "switch-succeeded"
```

```markdown
# Phase 3 Automatic Limit Response Manual Test

## Preconditions

- macOS environment
- at least two registered accounts
- working managed ChatGPT workspace

## Scenario 1: Limit detected and automatic switch succeeds

1. Run `switchgpt watch`.
2. Trigger the supported page-level usage-limit state in the managed workspace.
3. Confirm the CLI prints the detection and switch messages.
4. Confirm `switchgpt` rotates to the next eligible account.
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_switch_history.py -q`

Expected: FAIL because the history suite does not yet exercise `watch-auto` and `switch-succeeded`.

- [ ] **Step 3: Write minimal implementation**

```python
# tests/test_switch_history.py
def test_load_reads_watch_auto_events_from_jsonl(tmp_path) -> None:
    history_path = tmp_path / "switch-history.jsonl"
    history_path.write_text(
        json.dumps(
            {
                "occurred_at": "2026-04-17T11:15:00+00:00",
                "from_account_index": 0,
                "to_account_index": 1,
                "mode": "watch-auto",
                "result": "switch-succeeded",
                "message": None,
            }
        )
        + "\n"
    )

    store = SwitchHistoryStore(history_path)
    event = store.load()[0]

    assert event.mode == "watch-auto"
    assert event.result == "switch-succeeded"
```

```markdown
# docs/manual-tests/2026-04-17-phase-3-automatic-limit-response.md
# switchgpt Phase 3 Automatic Limit Response Manual Test

## Preconditions

- macOS environment with Playwright browser dependencies installed
- at least two registered accounts in `switchgpt`
- the active account already loaded in the managed ChatGPT workspace

## Scenario 1: Positive limit detection triggers immediate switch

1. Run `switchgpt watch`.
2. Trigger the supported page-level usage-limit state in the managed browser.
3. Confirm the terminal prints that a limit was detected.
4. Confirm the terminal prints the attempted target slot.
5. Confirm the terminal prints successful rotation to the next eligible slot.

## Scenario 2: All alternate accounts are unavailable

1. Start `switchgpt watch` with one current slot and remaining slots intentionally invalid.
2. Trigger the supported page-level usage-limit state.
3. Confirm the terminal reports each failed candidate.
4. Confirm the process exits after printing that no eligible account remains.
```

- [ ] **Step 4: Run focused and full verification**

Run: `uv run pytest tests/test_managed_browser.py tests/test_switch_service.py tests/test_watch_service.py tests/test_cli.py tests/test_switch_history.py -q`

Expected: PASS

Run: `uv run pytest -q`

Expected: PASS for the full suite with the new Phase 3 coverage included.

- [ ] **Step 5: Commit**

```bash
git add tests/test_switch_history.py docs/manual-tests/2026-04-17-phase-3-automatic-limit-response.md
git commit -m "test: cover watch history and manual validation"
```

## Self-Review

- Spec coverage check:
  `switchgpt watch` command is implemented in Task 4.
  Page-level limit detection is implemented in Task 1.
  Immediate switching, deterministic slot order, and in-run exclusions are implemented in Task 3.
  Distinct automation history and bounded switch outcomes are covered in Tasks 2 and 5.
  Exhaustion and interrupt outcomes are covered in Tasks 3 and 4.
- Placeholder scan:
  No unresolved placeholder language remains in task steps or code blocks.
- Type consistency:
  `LimitState`, `WatchNotification`, `WatchRunResult`, `watch-auto`, and `switch-succeeded` are used consistently across tasks.

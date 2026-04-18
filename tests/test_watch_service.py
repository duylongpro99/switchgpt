from datetime import UTC, datetime

from switchgpt.errors import ManagedBrowserError, ReauthRequiredError, SwitchError
from switchgpt.models import AccountRecord, AccountState, LimitState
from switchgpt.switch_history import SwitchEvent
from switchgpt.watch_service import WatchService


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

    def load(self):
        return self._snapshot


class FakeManagedBrowser:
    def __init__(
        self,
        detections,
        ensure_runtime_error: Exception | None = None,
        detect_limit_state_error: Exception | None = None,
        wait_for_reauthentication_error: Exception | None = None,
    ) -> None:
        self._detections = list(detections)
        self._calls = 0
        self._ensure_runtime_error = ensure_runtime_error
        self._detect_limit_state_error = detect_limit_state_error
        self._wait_for_reauthentication_error = wait_for_reauthentication_error
        self.ensure_runtime_calls = 0
        self.waited_pages = []

    def ensure_runtime(self):
        if self._ensure_runtime_error is not None:
            raise self._ensure_runtime_error
        self.ensure_runtime_calls += 1
        return "context", "page"

    def detect_limit_state(self, page):
        if self._detect_limit_state_error is not None:
            raise self._detect_limit_state_error
        detection = self._detections[min(self._calls, len(self._detections) - 1)]
        self._calls += 1
        return detection

    def wait_for_reauthentication(self, page) -> None:
        if self._wait_for_reauthentication_error is not None:
            raise self._wait_for_reauthentication_error
        self.waited_pages.append(page)


class FakeRotatingManagedBrowser:
    def __init__(self, page_detections) -> None:
        self._page_detections = list(page_detections)
        self._ensure_runtime_calls = 0
        self.detect_calls = []

    def ensure_runtime(self):
        page_number = min(self._ensure_runtime_calls, len(self._page_detections) - 1)
        page = f"page-{page_number}"
        self._ensure_runtime_calls += 1
        return "context", page

    @property
    def ensure_runtime_calls(self) -> int:
        return self._ensure_runtime_calls

    def detect_limit_state(self, page):
        self.detect_calls.append(page)
        page_index = int(page.rsplit("-", 1)[1])
        return self._page_detections[page_index]


class FakeSwitchResult:
    def __init__(self, account, mode: str) -> None:
        self.account = account
        self.mode = mode


class FakeSwitchService:
    def __init__(self, failures=None) -> None:
        self.calls = []
        self._failures = failures or {}

    def switch_to(self, index: int, *, mode: str = "explicit-target"):
        self.calls.append((index, mode))
        if index in self._failures:
            raise self._failures[index]
        return FakeSwitchResult(account=build_account(index, f"{index}@example.com"), mode=mode)


class FakeHistoryStore:
    def __init__(self) -> None:
        self.events = []

    def append(self, event: SwitchEvent) -> None:
        self.events.append(event)


class FakeRegistrationService:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = []
        self._error = error

    def reauth_in_managed_workspace(self, *, index: int, page):
        if self._error is not None:
            raise self._error
        self.calls.append((index, page))
        return build_account(index, f"reauth{index}@example.com")


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


def test_run_refreshes_runtime_on_each_cycle_before_detection() -> None:
    notifications = []
    managed_browser = FakeRotatingManagedBrowser(
        page_detections=[
            LimitState.NO_LIMIT_DETECTED,
            LimitState.LIMIT_DETECTED,
        ]
    )
    switch_service = FakeSwitchService()
    service = WatchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        managed_browser=managed_browser,
        switch_service=switch_service,
        history_store=FakeHistoryStore(),
        poll_interval_seconds=0.0,
    )

    result = service.run(
        notify=notifications.append,
        sleep_fn=lambda _: None,
        stop_after_cycles=2,
    )

    assert result.reason == "cycle-limit"
    assert managed_browser.ensure_runtime_calls == 2
    assert managed_browser.detect_calls == ["page-0", "page-1"]
    assert switch_service.calls == [(1, "watch-auto")]
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


def test_run_enters_reauth_flow_and_resumes_monitoring() -> None:
    notifications = []
    managed_browser = FakeManagedBrowser(
        detections=[LimitState.LIMIT_DETECTED, LimitState.NO_LIMIT_DETECTED]
    )
    switch_service = FakeSwitchService(
        failures={1: ReauthRequiredError("Account slot 1 likely needs reauthentication.")}
    )
    registration_service = FakeRegistrationService()
    history_store = FakeHistoryStore()
    service = WatchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        managed_browser=managed_browser,
        switch_service=switch_service,
        registration_service=registration_service,
        history_store=history_store,
        poll_interval_seconds=0.0,
    )

    result = service.run(
        notify=notifications.append,
        sleep_fn=lambda _: None,
        stop_after_cycles=2,
    )

    assert result.reason == "cycle-limit"
    assert result.active_account_index == 1
    assert registration_service.calls == [(1, "page")]
    assert managed_browser.waited_pages == ["page"]
    assert any(event.kind == "reauth-required" for event in notifications)
    assert any(event.kind == "resume-succeeded" for event in notifications)
    assert history_store.events[-2].result == "reauth-started"
    assert history_store.events[-1].result == "resume-succeeded"


def test_run_records_reauth_failure_and_stops_when_reauth_is_interrupted() -> None:
    managed_browser = FakeManagedBrowser(
        detections=[LimitState.LIMIT_DETECTED],
        wait_for_reauthentication_error=KeyboardInterrupt(),
    )
    switch_service = FakeSwitchService(
        failures={1: ReauthRequiredError("Account slot 1 likely needs reauthentication.")}
    )
    history_store = FakeHistoryStore()
    service = WatchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        managed_browser=managed_browser,
        switch_service=switch_service,
        registration_service=FakeRegistrationService(),
        history_store=history_store,
        poll_interval_seconds=0.0,
    )

    result = service.run(
        notify=None,
        sleep_fn=lambda _: None,
        stop_after_cycles=1,
    )

    assert result.reason == "user-interrupted"
    assert [event.result for event in history_store.events[-3:]] == [
        "reauth-started",
        "reauth-failed",
        "user-interrupted",
    ]


def test_run_records_reauth_failure_and_stops_on_runtime_failure_during_reauth() -> None:
    managed_browser = FakeManagedBrowser(
        detections=[LimitState.LIMIT_DETECTED],
        wait_for_reauthentication_error=ManagedBrowserError("runtime unavailable"),
    )
    switch_service = FakeSwitchService(
        failures={1: ReauthRequiredError("Account slot 1 likely needs reauthentication.")}
    )
    history_store = FakeHistoryStore()
    service = WatchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        managed_browser=managed_browser,
        switch_service=switch_service,
        registration_service=FakeRegistrationService(),
        history_store=history_store,
        poll_interval_seconds=0.0,
    )

    result = service.run(
        notify=None,
        sleep_fn=lambda _: None,
        stop_after_cycles=1,
    )

    assert result.reason == "browser-runtime-failure"
    assert [event.result for event in history_store.events[-3:]] == [
        "reauth-started",
        "reauth-failed",
        "browser-runtime-failure",
    ]


def test_run_records_reauth_failure_and_tries_next_candidate_when_capture_fails() -> None:
    managed_browser = FakeManagedBrowser(detections=[LimitState.LIMIT_DETECTED])
    switch_service = FakeSwitchService(
        failures={1: ReauthRequiredError("Account slot 1 likely needs reauthentication.")}
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
        registration_service=FakeRegistrationService(error=RuntimeError("capture failed")),
        history_store=history_store,
        poll_interval_seconds=0.0,
    )

    result = service.run(
        notify=None,
        sleep_fn=lambda _: None,
        stop_after_cycles=1,
    )

    assert result.active_account_index == 2
    assert any(event.result == "reauth-failed" for event in history_store.events)


def test_run_marks_missing_registration_service_as_reauth_failure() -> None:
    managed_browser = FakeManagedBrowser(detections=[LimitState.LIMIT_DETECTED])
    switch_service = FakeSwitchService(
        failures={1: ReauthRequiredError("Account slot 1 likely needs reauthentication.")}
    )
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
        notify=None,
        sleep_fn=lambda _: None,
        stop_after_cycles=1,
    )

    assert result.reason == "no-eligible-account"
    assert any(event.result == "reauth-failed" for event in history_store.events)


def test_run_returns_user_interrupted_when_sleep_is_interrupted() -> None:
    history_store = FakeHistoryStore()
    service = WatchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
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


def test_run_returns_user_interrupted_when_runtime_poll_is_interrupted() -> None:
    history_store = FakeHistoryStore()
    service = WatchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        managed_browser=FakeManagedBrowser(
            detections=[LimitState.NO_LIMIT_DETECTED],
            detect_limit_state_error=KeyboardInterrupt(),
        ),
        switch_service=FakeSwitchService(),
        history_store=history_store,
        poll_interval_seconds=1.0,
    )

    result = service.run(
        notify=None,
        sleep_fn=lambda _: None,
        stop_after_cycles=None,
    )

    assert result.reason == "user-interrupted"
    assert result.exit_code == 130
    assert history_store.events[-1].result == "user-interrupted"


def test_run_requires_active_index_to_match_registered_account() -> None:
    service = WatchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=7,
        ),
        managed_browser=FakeManagedBrowser(detections=[LimitState.NO_LIMIT_DETECTED]),
        switch_service=FakeSwitchService(),
        history_store=FakeHistoryStore(),
        poll_interval_seconds=0.0,
    )

    try:
        service.run(notify=None, sleep_fn=lambda _: None, stop_after_cycles=1)
    except SwitchError as exc:
        assert str(exc) == "Automatic switching requires a known active account."
    else:
        raise AssertionError("Expected SwitchError for unknown active account.")


def test_run_returns_browser_runtime_failure_when_initial_runtime_setup_fails() -> None:
    notifications = []
    history_store = FakeHistoryStore()
    service = WatchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        managed_browser=FakeManagedBrowser(
            detections=[LimitState.NO_LIMIT_DETECTED],
            ensure_runtime_error=ManagedBrowserError("runtime unavailable"),
        ),
        switch_service=FakeSwitchService(),
        history_store=history_store,
        poll_interval_seconds=0.0,
    )

    result = service.run(
        notify=notifications.append,
        sleep_fn=lambda _: None,
        stop_after_cycles=1,
    )

    assert result.reason == "browser-runtime-failure"
    assert result.exit_code == 1
    assert result.active_account_index == 0
    assert notifications[-1].kind == "browser-runtime-failure"
    assert history_store.events[-1].result == "browser-runtime-failure"

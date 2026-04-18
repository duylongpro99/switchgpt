from datetime import UTC, datetime

from switchgpt.secret_store import KeychainSecretStore
from switchgpt.models import AccountRecord, AccountState
from switchgpt.status_service import StatusService


class FakeSecretStore:
    def __init__(self, existing_keys: set[str]) -> None:
        self._existing_keys = existing_keys

    def exists(self, key: str) -> bool:
        return key in self._existing_keys


class FakeKeyringBackend:
    def __init__(self, payload: str | None) -> None:
        self._payload = payload

    def get_password(self, service_name: str, key: str) -> str | None:
        return self._payload

    def set_password(self, service_name: str, key: str, value: str) -> None:
        raise NotImplementedError

    def delete_password(self, service_name: str, key: str) -> None:
        raise NotImplementedError


class FakeHistoryStore:
    def __init__(self, events) -> None:
        self._events = list(events)

    def latest(self):
        if not self._events:
            return None
        return self._events[-1]


def build_account(
    index: int,
    *,
    state: AccountState = AccountState.REGISTERED,
    last_error: str | None = None,
) -> AccountRecord:
    now = datetime(2026, 4, 17, 11, 15, tzinfo=UTC)
    return AccountRecord(
        index=index,
        email=f"account{index}@example.com",
        keychain_key=f"switchgpt_account_{index}",
        registered_at=now,
        last_reauth_at=now,
        last_validated_at=now,
        status=state,
        last_error=last_error,
    )


def test_registered_slot_requires_metadata_and_secret() -> None:
    service = StatusService(secret_store=FakeSecretStore({"switchgpt_account_0"}))
    account = build_account(0)
    slot = service.classify(account)
    assert slot.state is AccountState.REGISTERED


def test_missing_secret_is_reported_when_keychain_entry_is_absent() -> None:
    service = StatusService(secret_store=FakeSecretStore(set()))
    account = build_account(0)
    slot = service.classify(account)
    assert slot.state is AccountState.MISSING_SECRET


def test_unreadable_secret_payload_is_reported_as_missing_secret() -> None:
    secret_store = KeychainSecretStore(
        service_name="switchgpt",
        backend=FakeKeyringBackend('{"session_token": 1}'),
    )
    service = StatusService(secret_store=secret_store)
    account = build_account(0)

    slot = service.classify(account)

    assert slot.state is AccountState.MISSING_SECRET


def test_summarize_reports_recent_failure_and_next_action() -> None:
    from switchgpt.switch_history import SwitchEvent

    service = StatusService(
        secret_store=FakeSecretStore({"switchgpt_account_0", "switchgpt_account_2"}),
        history_store=FakeHistoryStore(
            [
                SwitchEvent(
                    occurred_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
                    from_account_index=0,
                    to_account_index=2,
                    mode="watch-auto",
                    result="needs-reauth",
                    message="Account slot 2 likely needs reauthentication.",
                )
            ]
        ),
    )

    summary = service.summarize([build_account(0), build_account(2)], active_account_index=0)

    assert summary.readiness == "needs-attention"
    assert summary.latest_result == "needs-reauth"
    assert summary.active_account_index == 0
    assert summary.next_action is not None
    assert "Reauthenticate slot 2" in summary.next_action


def test_summarize_uses_needs_reauth_slot_from_metadata() -> None:
    service = StatusService(secret_store=FakeSecretStore({"switchgpt_account_0", "switchgpt_account_3"}))

    summary = service.summarize(
        [build_account(0), build_account(3, state=AccountState.NEEDS_REAUTH)],
        active_account_index=0,
    )

    assert summary.readiness == "needs-attention"
    assert summary.next_action is not None
    assert "Reauthenticate slot 3" in summary.next_action


def test_summarize_reports_degraded_when_secret_missing() -> None:
    service = StatusService(secret_store=FakeSecretStore(set()))

    summary = service.summarize([build_account(0)], active_account_index=0)

    assert summary.readiness == "degraded"
    assert summary.latest_result is None
    assert summary.next_action == (
        "Repair the missing Keychain entry or reauthenticate the affected slot."
    )


def test_summarize_reports_history_invalid_when_history_store_raises() -> None:
    class BrokenHistoryStore:
        def latest(self):
            raise RuntimeError("boom")

    service = StatusService(
        secret_store=FakeSecretStore({"switchgpt_account_0"}),
        history_store=BrokenHistoryStore(),
    )

    summary = service.summarize([build_account(0)], active_account_index=0)

    assert summary.readiness == "degraded"
    assert summary.latest_result == "history-invalid"
    assert summary.next_action == "Repair or archive malformed switch history."


def test_summarize_ignores_history_slot_not_present_in_snapshot() -> None:
    from switchgpt.switch_history import SwitchEvent

    service = StatusService(
        secret_store=FakeSecretStore({"switchgpt_account_0"}),
        history_store=FakeHistoryStore(
            [
                SwitchEvent(
                    occurred_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
                    from_account_index=0,
                    to_account_index=9,
                    mode="watch-auto",
                    result="needs-reauth",
                    message="Account slot 9 likely needs reauthentication.",
                )
            ]
        ),
    )

    summary = service.summarize([build_account(0)], active_account_index=0)

    assert summary.readiness == "degraded"
    assert summary.latest_result == "needs-reauth"
    assert summary.next_action == "Review switch history against the current registered slots."


def test_summarize_marks_history_invalid_when_store_lacks_latest() -> None:
    service = StatusService(
        secret_store=FakeSecretStore({"switchgpt_account_0"}),
        history_store=object(),
    )

    summary = service.summarize([build_account(0)], active_account_index=0)

    assert summary.readiness == "degraded"
    assert summary.latest_result == "history-invalid"


def test_summarize_marks_history_invalid_when_store_returns_unexpected_object() -> None:
    class UnexpectedHistoryStore:
        def latest(self):
            return object()

    service = StatusService(
        secret_store=FakeSecretStore({"switchgpt_account_0"}),
        history_store=UnexpectedHistoryStore(),
    )

    summary = service.summarize([build_account(0)], active_account_index=0)

    assert summary.readiness == "degraded"
    assert summary.latest_result == "history-invalid"


def test_summarize_prioritizes_history_invalid_guidance_over_missing_secret() -> None:
    class BrokenHistoryStore:
        def latest(self):
            raise RuntimeError("boom")

    service = StatusService(
        secret_store=FakeSecretStore(set()),
        history_store=BrokenHistoryStore(),
    )

    summary = service.summarize([build_account(0)], active_account_index=0)

    assert summary.readiness == "degraded"
    assert summary.latest_result == "history-invalid"
    assert summary.next_action == "Repair or archive malformed switch history."

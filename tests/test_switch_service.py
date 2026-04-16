from datetime import UTC, datetime

import pytest

from switchgpt.errors import SwitchError
from switchgpt.models import AccountRecord, AccountState
from switchgpt.secret_store import SessionSecret
from switchgpt.switch_history import SwitchEvent
from switchgpt.switch_service import SwitchService


class FakeAccountStore:
    def __init__(
        self,
        accounts,
        active_account_index=None,
        save_runtime_state_error: Exception | None = None,
        load_error: Exception | None = None,
        get_record_error: Exception | None = None,
    ) -> None:
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
        self._save_runtime_state_error = save_runtime_state_error
        self._load_error = load_error
        self._get_record_error = get_record_error

    def load(self):
        if self._load_error is not None:
            raise self._load_error
        return self._snapshot

    def get_record(self, index: int):
        if self._get_record_error is not None:
            raise self._get_record_error
        for account in self._snapshot.accounts:
            if account.index == index:
                return account
        raise ValueError(index)

    def save_runtime_state(self, active_account_index, switched_at):
        if self._save_runtime_state_error is not None:
            raise self._save_runtime_state_error
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

    def prepare_switch(
        self,
        context,
        page,
        *,
        session_token: str,
        csrf_token: str | None,
    ) -> None:
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

    result = service.switch_to(index=1)

    assert result.account.index == 1
    assert result.mode == "explicit-target"
    assert service._account_store.saved_runtime_state[0] == 1
    assert service._history_store.events[-1].result == "success"


def test_switch_next_uses_first_registered_account_not_current() -> None:
    service = SwitchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        secret_store=FakeSecretStore(
            SessionSecret(session_token="session-2", csrf_token=None)
        ),
        managed_browser=FakeManagedBrowser(authenticated=True),
        history_store=FakeHistoryStore(),
    )

    result = service.switch_next()

    assert result.account.index == 1
    assert result.mode == "auto-target"


def test_failed_auth_verification_does_not_update_active_account() -> None:
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

    with pytest.raises(SwitchError):
        service.switch_to(index=1)

    assert service._account_store.saved_runtime_state is None
    assert service._history_store.events[-1].result == "needs-reauth"


def test_missing_secret_records_failure_history_before_raising() -> None:
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
        service.switch_to(index=1)

    assert service._account_store.saved_runtime_state is None
    assert service._history_store.events[-1].result == "failure"
    assert "Stored session secret is missing" in service._history_store.events[-1].message


def test_runtime_state_persistence_failure_records_failure_history() -> None:
    service = SwitchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
            save_runtime_state_error=RuntimeError("metadata write failed"),
        ),
        secret_store=FakeSecretStore(
            SessionSecret(session_token="session-2", csrf_token=None)
        ),
        managed_browser=FakeManagedBrowser(authenticated=True),
        history_store=FakeHistoryStore(),
    )

    with pytest.raises(RuntimeError, match="metadata write failed"):
        service.switch_to(index=1)

    assert service._account_store.saved_runtime_state is None
    assert service._history_store.events[-1].result == "failure"
    assert service._history_store.events[-1].message == "metadata write failed"


def test_explicit_target_lookup_failure_records_failure_history() -> None:
    service = SwitchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com")],
            active_account_index=0,
            get_record_error=SwitchError("Account slot 1 is not registered."),
        ),
        secret_store=FakeSecretStore(None),
        managed_browser=FakeManagedBrowser(authenticated=True),
        history_store=FakeHistoryStore(),
    )

    with pytest.raises(SwitchError, match="Account slot 1 is not registered."):
        service.switch_to(index=1)

    assert service._history_store.events[-1].to_account_index == 1
    assert service._history_store.events[-1].result == "failure"
    assert service._history_store.events[-1].message == "Account slot 1 is not registered."


def test_explicit_switch_metadata_load_failure_records_failure_history() -> None:
    service = SwitchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
            load_error=RuntimeError("metadata load failed"),
        ),
        secret_store=FakeSecretStore(None),
        managed_browser=FakeManagedBrowser(authenticated=True),
        history_store=FakeHistoryStore(),
    )

    with pytest.raises(RuntimeError, match="metadata load failed"):
        service.switch_to(index=1)

    assert service._history_store.events[-1].to_account_index == 1
    assert service._history_store.events[-1].result == "failure"
    assert service._history_store.events[-1].message == "metadata load failed"

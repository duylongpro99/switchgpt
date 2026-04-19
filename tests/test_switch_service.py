from datetime import UTC, datetime

import pytest

from switchgpt.errors import CodexAuthSyncFailedError, ReauthRequiredError, SwitchError
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


def test_switch_to_runs_codex_sync_after_runtime_state_save() -> None:
    events = []

    class FakeSyncService:
        def sync_active_slot(self, **kwargs):
            events.append(("sync", kwargs["active_slot"], kwargs["occurred_at"]))
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

    class RecordingAccountStore(FakeAccountStore):
        def save_runtime_state(self, active_account_index, switched_at):
            events.append(("runtime-state", active_account_index, switched_at))
            super().save_runtime_state(active_account_index, switched_at)

    service = SwitchService(
        account_store=RecordingAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        secret_store=FakeSecretStore(
            SessionSecret(session_token="session-2", csrf_token="csrf-2")
        ),
        managed_browser=FakeManagedBrowser(authenticated=True),
        history_store=FakeHistoryStore(),
        codex_auth_sync=FakeSyncService(),
    )

    result = service.switch_to(index=1)

    assert result.account.index == 1
    assert [item[:2] for item in events] == [
        ("runtime-state", 1),
        ("sync", 1),
    ]
    assert events[0][2] == events[1][2]


def test_switch_to_raises_strict_codex_sync_failure_with_repair_guidance() -> None:
    class FakeSyncService:
        def sync_active_slot(self, **kwargs):
            del kwargs
            return type(
                "Result",
                (),
                {
                    "outcome": "failed",
                    "method": None,
                    "failure_class": "codex-auth-fallback-failed",
                    "message": "env projection failed",
                },
            )()

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
        codex_auth_sync=FakeSyncService(),
    )

    with pytest.raises(
        CodexAuthSyncFailedError, match="Run `switchgpt codex-sync` to repair"
    ):
        service.switch_to(index=1)

    assert service._account_store.saved_runtime_state[0] == 1
    assert service._history_store.events[-1].result == "failure"


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


def test_switch_next_records_watch_auto_mode_for_automation_success() -> None:
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

    result = service.switch_next(mode="watch-auto")

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

    with pytest.raises(ReauthRequiredError):
        service.switch_to(index=1)

    assert service._account_store.saved_runtime_state is None
    assert service._history_store.events[-1].result == "needs-reauth"


def test_failed_auth_verification_records_needs_reauth() -> None:
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

    with pytest.raises(ReauthRequiredError, match="likely needs reauthentication"):
        service.switch_to(index=1, mode="watch-auto")

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
    assert service._history_store.events[-1].result == "missing-secret"
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


def test_auto_target_metadata_load_failure_records_failure_history_without_target() -> None:
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
        service.switch_next()

    assert service._history_store.events[-1].to_account_index is None
    assert service._history_store.events[-1].result == "failure"
    assert service._history_store.events[-1].message == "metadata load failed"


def test_failure_history_message_is_redacted_before_persistence() -> None:
    class FailingManagedBrowser(FakeManagedBrowser):
        def prepare_switch(
            self,
            context,
            page,
            *,
            session_token: str,
            csrf_token: str | None,
        ) -> None:
            raise SwitchError(
                "prepare_switch failed with session_token=abc123 csrf_token=def456"
            )

    history_store = FakeHistoryStore()
    service = SwitchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        secret_store=FakeSecretStore(
            SessionSecret(session_token="session-2", csrf_token="csrf-2")
        ),
        managed_browser=FailingManagedBrowser(authenticated=True),
        history_store=history_store,
    )

    with pytest.raises(SwitchError, match="prepare_switch failed"):
        service.switch_to(index=1)

    assert history_store.events[-1].message == (
        "prepare_switch failed with session_token=[redacted] csrf_token=[redacted]"
    )

from datetime import UTC, datetime

import pytest

from switchgpt.errors import CodexAuthSyncFailedError, SwitchError
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
        history_store=FakeHistoryStore(),
        codex_auth_sync=FakeSyncService(),
    )

    with pytest.raises(
        CodexAuthSyncFailedError,
        match="retry `sca switch --to 1`",
    ):
        service.switch_to(index=1)

    assert service._account_store.saved_runtime_state[0] == 1
    assert service._history_store.events[-1].result == "failure"


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
        history_store=FakeHistoryStore(),
        codex_auth_sync=FakeSyncService(),
    )

    with pytest.raises(
        CodexAuthSyncFailedError,
        match="sca import-codex-auth --slot 1",
    ):
        service.switch_to(index=1)

    assert service._history_store.events[-1].result == "failure"


def test_switch_to_projects_codex_auth_without_browser_dependencies() -> None:
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
        history_store=FakeHistoryStore(),
        codex_auth_sync=FakeSyncService(),
    )

    result = service.switch_to(index=1)

    assert result.account.index == 1
    assert service._account_store.saved_runtime_state[0] == 1
    assert service._history_store.events[-1].result == "success"


def test_switch_to_persists_refreshed_codex_auth_after_projection() -> None:
    refreshed_auth = {
        "tokens": {
            "access_token": "access-refreshed",
            "refresh_token": "refresh-refreshed",
            "id_token": "id-refreshed",
            "account_id": "account-2",
        }
    }

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
                    "refreshed_auth_json": refreshed_auth,
                },
            )()

    class RecordingSecretStore(FakeSecretStore):
        def __init__(self, secret):
            super().__init__(secret)
            self.replaced = None

        def replace(self, key, secret) -> None:
            self.replaced = (key, secret)

    secret_store = RecordingSecretStore(
        SessionSecret(
            session_token="session-2",
            csrf_token="csrf-2",
            codex_auth_json={
                "tokens": {
                    "access_token": "access-old",
                    "refresh_token": "refresh-old",
                    "id_token": "id-old",
                    "account_id": "account-2",
                }
            },
        )
    )
    service = SwitchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        secret_store=secret_store,
        history_store=FakeHistoryStore(),
        codex_auth_sync=FakeSyncService(),
    )

    service.switch_to(index=1)

    assert secret_store.replaced[0] == "switchgpt_account_1"
    assert (
        secret_store.replaced[1].codex_auth_json["tokens"]["refresh_token"]
        == "refresh-refreshed"
    )


def test_switch_to_records_watch_auto_mode_for_automation_success() -> None:
    service = SwitchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        secret_store=FakeSecretStore(
            SessionSecret(session_token="session-2", csrf_token="csrf-2")
        ),
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
        history_store=FakeHistoryStore(),
    )

    with pytest.raises(SwitchError, match="Stored session secret is missing"):
        service.switch_to(index=1, mode="watch-auto")

    assert service._history_store.events[-1].result == "missing-secret"


def test_missing_secret_records_failure_history_before_raising() -> None:
    service = SwitchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        secret_store=FakeSecretStore(None),
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
        history_store=FakeHistoryStore(),
    )

    with pytest.raises(RuntimeError, match="metadata load failed"):
        service.switch_next()

    assert service._history_store.events[-1].to_account_index is None
    assert service._history_store.events[-1].result == "failure"
    assert service._history_store.events[-1].message == "metadata load failed"


def test_failure_history_message_is_redacted_before_persistence() -> None:
    class FailingSyncService:
        def sync_active_slot(self, **kwargs):
            del kwargs
            raise SwitchError(
                "sync failed with session_token=abc123 csrf_token=def456"
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
        history_store=history_store,
        codex_auth_sync=FailingSyncService(),
    )

    with pytest.raises(SwitchError, match="sync failed"):
        service.switch_to(index=1)

    assert history_store.events[-1].message == (
        "sync failed with session_token=[redacted] csrf_token=[redacted]"
    )

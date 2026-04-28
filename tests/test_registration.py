from datetime import UTC, datetime

import pytest

from switchgpt.models import AccountRecord, AccountState
from switchgpt.registration import RegistrationService
from switchgpt.secret_store import SessionSecret


def build_record(index: int = 0, email: str = "account1@example.com") -> AccountRecord:
    now = datetime(2026, 4, 16, 8, 30, tzinfo=UTC)
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


def test_add_registration_writes_placeholder_secret_before_metadata() -> None:
    events = []

    class FakeSecretStore:
        def write(self, key, secret) -> None:
            events.append(("secret", key, secret.session_token))

    class FakeAccountStore:
        def next_empty_slot(self) -> int:
            return 0

        def save_record(self, record) -> None:
            events.append(("metadata", record.index, record.email))

        def save_runtime_state(self, active_account_index, switched_at) -> None:
            events.append(("runtime-state", active_account_index, switched_at))

    service = RegistrationService(FakeAccountStore(), FakeSecretStore())

    service.add()

    assert events[0] == ("secret", "switchgpt_account_0", "")
    assert events[1] == ("metadata", 0, "slot-0@codex.local")
    assert events[2][0] == "runtime-state"
    assert events[2][1] == 0
    assert isinstance(events[2][2], datetime)


def test_add_uses_live_codex_auth_email_when_available() -> None:
    class FakeSecretStore:
        def write(self, key, secret) -> None:
            assert key == "switchgpt_account_0"
            assert secret == SessionSecret(session_token="", csrf_token=None)

    class FakeAccountStore:
        def next_empty_slot(self) -> int:
            return 0

        def save_record(self, record) -> None:
            assert record.email == "real.user@example.com"

        def save_runtime_state(self, active_account_index, switched_at) -> None:
            assert active_account_index == 0

    class FakeCodexAuthSync:
        def resolve_auth_email(self, payload):
            assert payload is None
            return "real.user@example.com"

    service = RegistrationService(
        FakeAccountStore(),
        FakeSecretStore(),
        codex_auth_sync=FakeCodexAuthSync(),
    )

    record = service.add()

    assert record.email == "real.user@example.com"


def test_add_rolls_back_secret_when_metadata_write_fails() -> None:
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

    service = RegistrationService(FakeAccountStore(), FakeSecretStore())

    with pytest.raises(RuntimeError):
        service.add()

    assert deleted == ["switchgpt_account_0"]


def test_reauth_keeps_existing_secret_and_updates_metadata() -> None:
    events = []
    old_secret = SessionSecret(
        session_token="old",
        csrf_token="old",
        codex_auth_json={"tokens": {"account_id": "account-1"}},
    )

    class FakeSecretStore:
        def read(self, key):
            assert key == "switchgpt_account_0"
            return old_secret

        def replace(self, key, secret):
            events.append(("secret", key, secret))

    class FakeAccountStore:
        def get_record(self, index: int) -> AccountRecord:
            assert index == 0
            return build_record()

        def save_record(self, record) -> None:
            events.append(("metadata", record.index, record.email, record.last_reauth_at))

        def save_runtime_state(self, active_account_index, switched_at) -> None:
            events.append(("runtime-state", active_account_index, switched_at))

    service = RegistrationService(FakeAccountStore(), FakeSecretStore())

    record = service.reauth(0)

    assert record.index == 0
    assert events[0] == ("secret", "switchgpt_account_0", old_secret)
    assert events[1][0:3] == ("metadata", 0, "account1@example.com")
    assert events[2][0:2] == ("runtime-state", 0)
    assert events[1][3] == events[2][2]


def test_reauth_uses_live_codex_auth_email_when_available() -> None:
    class FakeSecretStore:
        def read(self, key):
            return SessionSecret(session_token="", csrf_token=None)

        def replace(self, key, secret):
            return None

    class FakeAccountStore:
        def get_record(self, index: int) -> AccountRecord:
            return build_record(email="old@example.com")

        def save_record(self, record) -> None:
            assert record.email == "new@example.com"

        def save_runtime_state(self, active_account_index, switched_at) -> None:
            assert active_account_index == 0

    class FakeCodexAuthSync:
        def resolve_auth_email(self, payload):
            assert payload is None
            return "new@example.com"

    service = RegistrationService(
        FakeAccountStore(),
        FakeSecretStore(),
        codex_auth_sync=FakeCodexAuthSync(),
    )

    record = service.reauth(0)

    assert record.email == "new@example.com"


def test_reauth_restores_old_secret_when_metadata_save_fails() -> None:
    old_secret = SessionSecret(session_token="old", csrf_token="old")

    class FakeSecretStore:
        def __init__(self) -> None:
            self.value = old_secret

        def read(self, key):
            return self.value

        def replace(self, key, secret):
            self.value = secret

    class FakeAccountStore:
        def get_record(self, index: int) -> AccountRecord:
            return build_record()

        def save_record(self, record) -> None:
            raise RuntimeError("disk failure")

    secret_store = FakeSecretStore()
    service = RegistrationService(FakeAccountStore(), secret_store)

    with pytest.raises(RuntimeError, match="disk failure"):
        service.reauth(0)

    assert secret_store.value == old_secret

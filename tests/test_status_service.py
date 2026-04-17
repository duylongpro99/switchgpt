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


def test_registered_slot_requires_metadata_and_secret() -> None:
    service = StatusService(secret_store=FakeSecretStore({"switchgpt_account_0"}))
    account = AccountRecord(
        index=0,
        email="account1@example.com",
        keychain_key="switchgpt_account_0",
        registered_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_reauth_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_validated_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        status=AccountState.REGISTERED,
        last_error=None,
    )
    slot = service.classify(account)
    assert slot.state is AccountState.REGISTERED


def test_missing_secret_is_reported_when_keychain_entry_is_absent() -> None:
    service = StatusService(secret_store=FakeSecretStore(set()))
    account = AccountRecord(
        index=0,
        email="account1@example.com",
        keychain_key="switchgpt_account_0",
        registered_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_reauth_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_validated_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        status=AccountState.REGISTERED,
        last_error=None,
    )
    slot = service.classify(account)
    assert slot.state is AccountState.MISSING_SECRET


def test_unreadable_secret_payload_is_reported_as_missing_secret() -> None:
    secret_store = KeychainSecretStore(
        service_name="switchgpt",
        backend=FakeKeyringBackend('{"session_token": 1}'),
    )
    service = StatusService(secret_store=secret_store)
    account = AccountRecord(
        index=0,
        email="account1@example.com",
        keychain_key="switchgpt_account_0",
        registered_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_reauth_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_validated_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        status=AccountState.REGISTERED,
        last_error=None,
    )

    slot = service.classify(account)

    assert slot.state is AccountState.MISSING_SECRET

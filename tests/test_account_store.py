import json
from datetime import UTC, datetime

import pytest

from switchgpt.account_store import AccountStore
from switchgpt.errors import AccountStoreError
from switchgpt.models import AccountRecord, AccountState


def test_allocate_next_empty_slot_returns_zero_for_empty_store(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts.json", slot_count=3)
    assert store.next_empty_slot() == 0


def test_save_and_reload_registered_account_round_trips(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts.json", slot_count=3)
    record = AccountRecord(
        index=0,
        email="account1@example.com",
        keychain_key="switchgpt_account_0",
        registered_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_reauth_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_validated_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        status=AccountState.REGISTERED,
        last_error=None,
    )
    store.save_record(record)
    reloaded = store.load().accounts[0]
    assert reloaded.email == "account1@example.com"
    assert reloaded.status is AccountState.REGISTERED


@pytest.mark.parametrize(
    "payload",
    [
        "{not-json",
        '{"version": 1}',
    ],
)
def test_load_rejects_malformed_metadata_with_explicit_store_error(
    tmp_path, payload: str
) -> None:
    metadata_path = tmp_path / "accounts.json"
    metadata_path.write_text(payload)

    store = AccountStore(metadata_path, slot_count=3)

    with pytest.raises(AccountStoreError):
        store.load()


def test_load_wraps_metadata_read_failures_in_account_store_error(tmp_path, monkeypatch) -> None:
    metadata_path = tmp_path / "accounts.json"
    metadata_path.write_text('{"version": 1, "accounts": []}')

    original_read_text = type(metadata_path).read_text

    def fake_read_text(self, *args, **kwargs) -> str:
        if self == metadata_path:
            raise PermissionError("denied")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(type(metadata_path), "read_text", fake_read_text)

    store = AccountStore(metadata_path, slot_count=3)

    with pytest.raises(AccountStoreError):
        store.load()


@pytest.mark.parametrize(
    "record_override",
    [
        {"index": "0"},
        {"last_error": 123},
    ],
)
def test_load_rejects_wrong_typed_account_fields(
    tmp_path, record_override: dict[str, object]
) -> None:
    record = {
        "index": 0,
        "email": "account1@example.com",
        "keychain_key": "switchgpt_account_0",
        "registered_at": "2026-04-16T08:30:00+00:00",
        "last_reauth_at": "2026-04-16T08:30:00+00:00",
        "last_validated_at": "2026-04-16T08:30:00+00:00",
        "status": "registered",
        "last_error": None,
    }
    record.update(record_override)

    metadata_path = tmp_path / "accounts.json"
    metadata_path.write_text(json.dumps({"version": 1, "accounts": [record]}))

    store = AccountStore(metadata_path, slot_count=3)

    with pytest.raises(AccountStoreError):
        store.load()

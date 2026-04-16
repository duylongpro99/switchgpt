import json
from datetime import UTC, datetime

import pytest

from switchgpt.account_store import AccountStore
from switchgpt.errors import AccountStoreError
from switchgpt.models import AccountRecord, AccountSnapshot, AccountState


def test_load_returns_empty_snapshot_with_phase_2_top_level_fields(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts.json", slot_count=3)

    snapshot = store.load()

    assert snapshot == AccountSnapshot(
        accounts=[], active_account_index=None, last_switch_at=None
    )


def test_save_active_account_round_trips_with_registered_accounts(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts.json", slot_count=3)
    recorded_at = datetime(2026, 4, 16, 11, 15, tzinfo=UTC)
    store.save_record(
        AccountRecord(
            index=0,
            email="account1@example.com",
            keychain_key="switchgpt_account_0",
            registered_at=recorded_at,
            last_reauth_at=recorded_at,
            last_validated_at=recorded_at,
            status=AccountState.REGISTERED,
            last_error=None,
        )
    )

    store.save_runtime_state(active_account_index=0, switched_at=recorded_at)
    snapshot = store.load()

    assert snapshot.active_account_index == 0
    assert snapshot.last_switch_at == recorded_at


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

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .errors import AccountStoreError
from .models import AccountRecord, AccountSnapshot, AccountState


class AccountStore:
    def __init__(self, metadata_path: Path, slot_count: int) -> None:
        self._metadata_path = metadata_path
        self._slot_count = slot_count

    def load(self) -> AccountSnapshot:
        if not self._metadata_path.exists():
            return AccountSnapshot(
                accounts=[], active_account_index=None, last_switch_at=None
            )
        try:
            raw_text = self._metadata_path.read_text()
        except OSError as exc:
            raise AccountStoreError("Malformed account metadata.") from exc
        try:
            payload = json.loads(raw_text)
            if not isinstance(payload, dict):
                raise AccountStoreError("Malformed account metadata.")
            raw_accounts = payload["accounts"]
            if not isinstance(raw_accounts, list):
                raise AccountStoreError("Malformed account metadata.")
            accounts = []
            for item in raw_accounts:
                accounts.append(self._load_record(item))
            return AccountSnapshot(
                accounts=accounts,
                active_account_index=self._load_active_account_index(payload),
                last_switch_at=self._load_last_switch_at(payload),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise AccountStoreError("Malformed account metadata.") from exc

    def _load_record(self, item: object) -> AccountRecord:
        if not isinstance(item, dict):
            raise AccountStoreError("Malformed account metadata.")

        index = self._require_int(item.get("index"))
        email = self._require_str(item.get("email"))
        keychain_key = self._require_str(item.get("keychain_key"))
        registered_at = self._require_str(item.get("registered_at"))
        last_reauth_at = self._require_str(item.get("last_reauth_at"))
        last_validated_at = self._require_str(item.get("last_validated_at"))
        status_value = self._require_str(item.get("status"))
        last_error = item.get("last_error")
        if last_error is not None and not isinstance(last_error, str):
            raise AccountStoreError("Malformed account metadata.")

        return AccountRecord(
            index=index,
            email=email,
            keychain_key=keychain_key,
            registered_at=datetime.fromisoformat(registered_at),
            last_reauth_at=datetime.fromisoformat(last_reauth_at),
            last_validated_at=datetime.fromisoformat(last_validated_at),
            status=AccountState(status_value),
            last_error=last_error,
        )

    def _load_active_account_index(self, payload: dict[str, object]) -> int | None:
        active_account_index = payload.get("active_account_index")
        if active_account_index is None:
            return None
        return self._require_int(active_account_index)

    def _load_last_switch_at(self, payload: dict[str, object]) -> datetime | None:
        last_switch_at = payload.get("last_switch_at")
        if last_switch_at is None:
            return None
        last_switch_at_text = self._require_str(last_switch_at)
        return datetime.fromisoformat(last_switch_at_text)

    @staticmethod
    def _require_int(value: object) -> int:
        if type(value) is not int:
            raise AccountStoreError("Malformed account metadata.")
        return value

    @staticmethod
    def _require_str(value: object) -> str:
        if type(value) is not str:
            raise AccountStoreError("Malformed account metadata.")
        return value

    def next_empty_slot(self) -> int:
        used = {account.index for account in self.load().accounts}
        for index in range(self._slot_count):
            if index not in used:
                return index
        raise AccountStoreError("No empty account slots remain.")

    def get_record(self, index: int) -> AccountRecord:
        for account in self.load().accounts:
            if account.index == index:
                return account
        raise AccountStoreError(f"Account slot {index} is not registered.")

    def save_record(self, record: AccountRecord) -> None:
        snapshot = self.load()
        accounts = [
            account for account in snapshot.accounts if account.index != record.index
        ] + [record]
        self._write_snapshot(
            AccountSnapshot(
                accounts=sorted(accounts, key=lambda item: item.index),
                active_account_index=snapshot.active_account_index,
                last_switch_at=snapshot.last_switch_at,
            )
        )

    def save_runtime_state(
        self, active_account_index: int | None, switched_at: datetime | None
    ) -> None:
        snapshot = self.load()
        self._write_snapshot(
            AccountSnapshot(
                accounts=snapshot.accounts,
                active_account_index=active_account_index,
                last_switch_at=switched_at,
            )
        )

    def _write_snapshot(self, snapshot: AccountSnapshot) -> None:
        payload = {
            "version": 1,
            "active_account_index": snapshot.active_account_index,
            "last_switch_at": (
                snapshot.last_switch_at.isoformat()
                if snapshot.last_switch_at is not None
                else None
            ),
            "accounts": [
                {
                    **asdict(account),
                    "registered_at": account.registered_at.isoformat(),
                    "last_reauth_at": account.last_reauth_at.isoformat(),
                    "last_validated_at": account.last_validated_at.isoformat(),
                    "status": account.status.value,
                }
                for account in snapshot.accounts
            ],
        }
        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._metadata_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2))
        temp_path.replace(self._metadata_path)

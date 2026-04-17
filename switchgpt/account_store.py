import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .errors import AccountStoreError
from .models import AccountRecord, AccountState


@dataclass(frozen=True)
class AccountSnapshot:
    accounts: list[AccountRecord]


class AccountStore:
    def __init__(self, metadata_path: Path, slot_count: int) -> None:
        self._metadata_path = metadata_path
        self._slot_count = slot_count

    def load(self) -> AccountSnapshot:
        if not self._metadata_path.exists():
            return AccountSnapshot(accounts=[])
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
            return AccountSnapshot(accounts=accounts)
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
        payload = {
            "version": 1,
            "accounts": [
                {
                    **asdict(account),
                    "registered_at": account.registered_at.isoformat(),
                    "last_reauth_at": account.last_reauth_at.isoformat(),
                    "last_validated_at": account.last_validated_at.isoformat(),
                    "status": account.status.value,
                }
                for account in sorted(accounts, key=lambda item: item.index)
            ],
        }
        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._metadata_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2))
        temp_path.replace(self._metadata_path)

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime

from .models import AccountRecord, AccountState
from .secret_store import SessionSecret


@dataclass(frozen=True)
class RegistrationResult:
    email: str
    secret: SessionSecret
    captured_at: datetime


class RegistrationService:
    def __init__(self, account_store, secret_store, browser_client) -> None:
        self._account_store = account_store
        self._secret_store = secret_store
        self._browser_client = browser_client

    def add(self) -> AccountRecord:
        slot = self._account_store.next_empty_slot()
        key = f"switchgpt_account_{slot}"
        result = self._browser_client.register()
        self._secret_store.write(key, result.secret)
        record = AccountRecord(
            index=slot,
            email=result.email,
            keychain_key=key,
            registered_at=result.captured_at,
            last_reauth_at=result.captured_at,
            last_validated_at=result.captured_at,
            status=AccountState.REGISTERED,
            last_error=None,
        )
        try:
            self._account_store.save_record(record)
        except Exception:
            with suppress(Exception):
                self._secret_store.delete(key)
            raise
        return record

    def reauth(self, index: int) -> AccountRecord:
        existing = self._account_store.get_record(index)
        previous_secret = self._secret_store.read(existing.keychain_key)
        result = self._browser_client.reauth(existing.email)
        self._secret_store.replace(existing.keychain_key, result.secret)
        refreshed = AccountRecord(
            index=existing.index,
            email=result.email,
            keychain_key=existing.keychain_key,
            registered_at=existing.registered_at,
            last_reauth_at=result.captured_at,
            last_validated_at=result.captured_at,
            status=AccountState.REGISTERED,
            last_error=None,
        )
        try:
            self._account_store.save_record(refreshed)
        except Exception:
            with suppress(Exception):
                if previous_secret is None:
                    self._secret_store.delete(existing.keychain_key)
                else:
                    self._secret_store.replace(existing.keychain_key, previous_secret)
            raise
        return refreshed

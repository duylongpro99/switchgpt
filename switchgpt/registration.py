from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime

from .codex_auth_sync import raise_for_failed_sync
from .errors import CodexAuthSyncFailedError
from .models import AccountRecord, AccountState
from .secret_store import SessionSecret


@dataclass(frozen=True)
class RegistrationResult:
    email: str
    secret: SessionSecret
    captured_at: datetime


class RegistrationService:
    def __init__(
        self,
        account_store,
        secret_store,
        browser_client,
        *,
        codex_auth_sync=None,
    ) -> None:
        self._account_store = account_store
        self._secret_store = secret_store
        self._browser_client = browser_client
        self._codex_auth_sync = codex_auth_sync

    def add(self) -> AccountRecord:
        slot = self._account_store.next_empty_slot()
        key = f"switchgpt_account_{slot}"
        result = self._browser_client.register()
        return self._persist_add_result(
            slot=slot,
            key=key,
            result=result,
        )

    def add_in_managed_workspace(self, *, page) -> AccountRecord:
        slot = self._account_store.next_empty_slot()
        key = f"switchgpt_account_{slot}"
        result = self._browser_client.capture_existing_session(
            page,
            existing_email="unknown@example.com",
        )
        return self._persist_add_result(
            slot=slot,
            key=key,
            result=result,
        )

    def _persist_add_result(
        self,
        *,
        slot: int,
        key: str,
        result: RegistrationResult,
    ) -> AccountRecord:
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
        self._sync_active_slot_or_raise(record=record, secret=result.secret)
        return record

    def reauth(self, index: int) -> AccountRecord:
        existing = self._account_store.get_record(index)
        previous_secret = self._secret_store.read(existing.keychain_key)
        result = self._browser_client.reauth(existing.email)
        return self._persist_reauth_result(
            existing=existing,
            previous_secret=previous_secret,
            result=result,
        )

    def reauth_in_managed_workspace(self, *, index: int, page) -> AccountRecord:
        existing = self._account_store.get_record(index)
        previous_secret = self._secret_store.read(existing.keychain_key)
        result = self._browser_client.capture_existing_session(
            page,
            existing_email=existing.email,
        )
        return self._persist_reauth_result(
            existing=existing,
            previous_secret=previous_secret,
            result=result,
        )

    def _persist_reauth_result(
        self,
        *,
        existing: AccountRecord,
        previous_secret: SessionSecret | None,
        result: RegistrationResult,
    ) -> AccountRecord:
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
        self._sync_active_slot_or_raise(record=refreshed, secret=result.secret)
        return refreshed

    def _sync_active_slot_or_raise(
        self,
        *,
        record: AccountRecord,
        secret: SessionSecret,
    ) -> None:
        if self._codex_auth_sync is None:
            return
        result = self._codex_auth_sync.sync_active_slot(
            active_slot=record.index,
            email=record.email,
            session_token=secret.session_token,
            csrf_token=secret.csrf_token,
            occurred_at=record.last_reauth_at,
        )
        try:
            raise_for_failed_sync(result)
        except CodexAuthSyncFailedError as exc:
            raise CodexAuthSyncFailedError(
                "Codex auth sync failed after registration update. Run `switchgpt codex-sync` to repair.",
                failure_class=exc.failure_class,
            ) from exc

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime

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
        *,
        codex_auth_sync=None,
    ) -> None:
        self._account_store = account_store
        self._secret_store = secret_store
        self._codex_auth_sync = codex_auth_sync

    def add(self) -> AccountRecord:
        slot = self._account_store.next_empty_slot()
        key = f"switchgpt_account_{slot}"
        captured_at = datetime.now(UTC)
        email = f"slot-{slot}@codex.local"
        resolver = getattr(self._codex_auth_sync, "resolve_auth_email", None)
        if callable(resolver):
            resolved_email = resolver(None)
            if type(resolved_email) is str and resolved_email:
                email = resolved_email
        result = RegistrationResult(
            email=email,
            secret=SessionSecret(session_token="", csrf_token=None),
            captured_at=captured_at,
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
        self._account_store.save_runtime_state(
            active_account_index=record.index,
            switched_at=record.last_reauth_at,
        )
        return record

    def reauth(self, index: int) -> AccountRecord:
        existing = self._account_store.get_record(index)
        previous_secret = self._secret_store.read(existing.keychain_key)
        captured_at = datetime.now(UTC)
        email = existing.email
        resolver = getattr(self._codex_auth_sync, "resolve_auth_email", None)
        if callable(resolver):
            resolved_email = resolver(None)
            if type(resolved_email) is str and resolved_email:
                email = resolved_email
        result = RegistrationResult(
            email=email,
            secret=previous_secret
            or SessionSecret(session_token="", csrf_token=None),
            captured_at=captured_at,
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
        self._account_store.save_runtime_state(
            active_account_index=refreshed.index,
            switched_at=refreshed.last_reauth_at,
        )
        return refreshed

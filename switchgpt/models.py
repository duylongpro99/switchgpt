from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AccountState(StrEnum):
    EMPTY = "empty"
    REGISTERED = "registered"
    MISSING_SECRET = "missing-secret"
    NEEDS_REAUTH = "needs-reauth"
    ERROR = "error"


class LimitState(StrEnum):
    LIMIT_DETECTED = "limit_detected"
    NO_LIMIT_DETECTED = "no_limit_detected"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AccountRecord:
    index: int
    email: str
    keychain_key: str
    registered_at: datetime
    last_reauth_at: datetime
    last_validated_at: datetime
    status: AccountState
    last_error: str | None


@dataclass(frozen=True)
class AccountSnapshot:
    accounts: list[AccountRecord]
    active_account_index: int | None
    last_switch_at: datetime | None
    last_codex_sync_at: datetime | None
    last_codex_sync_slot: int | None
    last_codex_sync_method: str | None
    last_codex_sync_status: str | None
    last_codex_sync_error: str | None
    last_codex_sync_fingerprint: str | None
    codex_import_fingerprints: dict[int, str]

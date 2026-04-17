from dataclasses import dataclass

from .errors import SecretStoreError
from .models import AccountRecord, AccountState


@dataclass(frozen=True)
class SlotStatus:
    index: int
    email: str
    state: AccountState
    last_error: str | None


class StatusService:
    def __init__(self, secret_store) -> None:
        self._secret_store = secret_store

    def classify(self, account: AccountRecord) -> SlotStatus:
        try:
            exists = self._secret_store.exists(account.keychain_key)
        except SecretStoreError:
            exists = False
        if not exists:
            return SlotStatus(
                account.index,
                account.email,
                AccountState.MISSING_SECRET,
                account.last_error,
            )
        return SlotStatus(
            account.index,
            account.email,
            account.status,
            account.last_error,
        )

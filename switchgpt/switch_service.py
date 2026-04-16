from dataclasses import dataclass
from datetime import UTC, datetime

from .errors import SwitchError
from .switch_history import SwitchEvent


@dataclass(frozen=True)
class SwitchResult:
    account: object
    mode: str


class SwitchService:
    def __init__(self, account_store, secret_store, managed_browser, history_store) -> None:
        self._account_store = account_store
        self._secret_store = secret_store
        self._managed_browser = managed_browser
        self._history_store = history_store

    def switch_next(self) -> SwitchResult:
        snapshot = self._account_store.load()
        candidates = [
            account
            for account in snapshot.accounts
            if account.index != snapshot.active_account_index
        ]
        if not candidates:
            raise SwitchError("No alternative registered account is available for switching.")
        return self._switch_account(candidates[0], mode="auto-target")

    def switch_to(self, index: int) -> SwitchResult:
        account = self._account_store.get_record(index)
        return self._switch_account(account, mode="explicit-target")

    def _switch_account(self, account, *, mode: str) -> SwitchResult:
        previous_active_index = self._account_store.load().active_account_index
        secret = self._secret_store.read(account.keychain_key)
        if secret is None:
            raise SwitchError(f"Stored session secret is missing for slot {account.index}.")

        occurred_at = datetime.now(UTC)
        context, page = self._managed_browser.ensure_runtime()
        self._managed_browser.prepare_switch(
            context,
            page,
            session_token=secret.session_token,
            csrf_token=secret.csrf_token,
        )
        if not self._managed_browser.is_authenticated(page):
            self._history_store.append(
                SwitchEvent(
                    occurred_at=occurred_at,
                    from_account_index=previous_active_index,
                    to_account_index=account.index,
                    mode=mode,
                    result="needs-reauth",
                    message=f"Authenticated state verification failed for slot {account.index}.",
                )
            )
            raise SwitchError(f"Account slot {account.index} likely needs reauthentication.")

        self._account_store.save_runtime_state(account.index, occurred_at)
        self._history_store.append(
            SwitchEvent(
                occurred_at=occurred_at,
                from_account_index=previous_active_index,
                to_account_index=account.index,
                mode=mode,
                result="success",
                message=None,
            )
        )
        return SwitchResult(account=account, mode=mode)

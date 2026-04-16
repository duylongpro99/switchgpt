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
        return self._switch_account(
            account=None,
            account_index=index,
            mode="explicit-target",
        )

    def _switch_account(
        self,
        account,
        *,
        mode: str,
        account_index: int | None = None,
    ) -> SwitchResult:
        previous_active_index = None
        occurred_at = datetime.now(UTC)
        event_recorded = False
        try:
            previous_active_index = self._account_store.load().active_account_index
            if account is None:
                if account_index is None:
                    raise SwitchError("Switch target is required.")
                account = self._account_store.get_record(account_index)
            else:
                account_index = account.index

            secret = self._secret_store.read(account.keychain_key)
            if secret is None:
                raise SwitchError(
                    f"Stored session secret is missing for slot {account.index}."
                )

            context, page = self._managed_browser.ensure_runtime()
            self._managed_browser.prepare_switch(
                context,
                page,
                session_token=secret.session_token,
                csrf_token=secret.csrf_token,
            )
            if not self._managed_browser.is_authenticated(page):
                self._append_event(
                    occurred_at=occurred_at,
                    previous_active_index=previous_active_index,
                    account_index=account.index,
                    mode=mode,
                    result="needs-reauth",
                    message=f"Authenticated state verification failed for slot {account.index}.",
                )
                event_recorded = True
                raise SwitchError(
                    f"Account slot {account.index} likely needs reauthentication."
                )

            self._account_store.save_runtime_state(account.index, occurred_at)
        except Exception as exc:
            if not event_recorded and account_index is not None:
                self._append_event(
                    occurred_at=occurred_at,
                    previous_active_index=previous_active_index,
                    account_index=account_index,
                    mode=mode,
                    result="failure",
                    message=str(exc),
                )
            raise

        self._append_event(
            occurred_at=occurred_at,
            previous_active_index=previous_active_index,
            account_index=account.index,
            mode=mode,
            result="success",
            message=None,
        )
        return SwitchResult(account=account, mode=mode)

    def _append_event(
        self,
        *,
        occurred_at: datetime,
        previous_active_index: int | None,
        account_index: int,
        mode: str,
        result: str,
        message: str | None,
    ) -> None:
        self._history_store.append(
            SwitchEvent(
                occurred_at=occurred_at,
                from_account_index=previous_active_index,
                to_account_index=account_index,
                mode=mode,
                result=result,
                message=message,
            )
        )

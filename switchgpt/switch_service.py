from dataclasses import dataclass
from datetime import UTC, datetime

from .codex_auth_sync import raise_for_failed_sync
from .diagnostics import redact_text
from .errors import CodexAuthSyncFailedError, SwitchError
from .switch_history import SwitchEvent


@dataclass(frozen=True)
class SwitchResult:
    account: object
    mode: str


class SwitchService:
    def __init__(
        self,
        account_store,
        secret_store,
        managed_browser,
        history_store,
        *,
        codex_auth_sync=None,
    ) -> None:
        self._account_store = account_store
        self._secret_store = secret_store
        self._managed_browser = managed_browser
        self._history_store = history_store
        self._codex_auth_sync = codex_auth_sync

    def switch_next(self, *, mode: str = "auto-target") -> SwitchResult:
        occurred_at = datetime.now(UTC)
        previous_active_index = None
        try:
            snapshot = self._account_store.load()
            previous_active_index = snapshot.active_account_index
            candidates = [
                account
                for account in snapshot.accounts
                if account.index != snapshot.active_account_index
            ]
            if not candidates:
                raise SwitchError(
                    "No alternative registered account is available for switching."
                )
        except Exception as exc:
            self._append_event(
                occurred_at=occurred_at,
                previous_active_index=previous_active_index,
                account_index=None,
                mode=mode,
                result="failure",
                message=str(exc),
            )
            raise
        return self._switch_account(candidates[0], mode=mode)

    def switch_to(self, index: int, *, mode: str = "explicit-target") -> SwitchResult:
        return self._switch_account(
            account=None,
            account_index=index,
            mode=mode,
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
        failure_result = "failure"
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
                failure_result = "missing-secret"
                raise SwitchError(
                    f"Stored session secret is missing for slot {account.index}."
                )

            self._account_store.save_runtime_state(account.index, occurred_at)
            self._sync_active_slot_or_raise(
                account=account,
                secret=secret,
                occurred_at=occurred_at,
            )
        except Exception as exc:
            if account_index is not None:
                self._append_event(
                    occurred_at=occurred_at,
                    previous_active_index=previous_active_index,
                    account_index=account_index,
                    mode=mode,
                    result=failure_result,
                    message=str(exc),
                )
            raise

        self._append_event(
            occurred_at=occurred_at,
            previous_active_index=previous_active_index,
            account_index=account.index,
            mode=mode,
            result=self._success_result_for_mode(mode),
            message=None,
        )
        return SwitchResult(account=account, mode=mode)

    def _sync_active_slot_or_raise(self, *, account, secret, occurred_at: datetime) -> None:
        if self._codex_auth_sync is None:
            return
        result = self._codex_auth_sync.sync_active_slot(
            active_slot=account.index,
            email=account.email,
            session_token=secret.session_token,
            csrf_token=secret.csrf_token,
            codex_auth_json=getattr(secret, "codex_auth_json", None),
            occurred_at=occurred_at,
        )
        try:
            raise_for_failed_sync(result)
        except CodexAuthSyncFailedError as exc:
            raise CodexAuthSyncFailedError(
                "Codex auth sync failed after switch. Run `codex login` with the target account, then "
                f"`switchgpt import-codex-auth --slot {account.index}` and retry `switchgpt switch --to {account.index}`.",
                failure_class=exc.failure_class,
            ) from exc

    def _success_result_for_mode(self, mode: str) -> str:
        return "switch-succeeded" if mode == "watch-auto" else "success"

    def _append_event(
        self,
        *,
        occurred_at: datetime,
        previous_active_index: int | None,
        account_index: int | None,
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
                message=redact_text(message) if message is not None else None,
            )
        )

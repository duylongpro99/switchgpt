from dataclasses import dataclass
from datetime import UTC, datetime
import time

from .errors import ManagedBrowserError, SwitchError
from .models import LimitState
from .switch_history import SwitchEvent


@dataclass(frozen=True)
class WatchNotification:
    kind: str
    message: str


@dataclass(frozen=True)
class WatchRunResult:
    reason: str
    exit_code: int
    active_account_index: int | None


class WatchService:
    def __init__(
        self,
        account_store,
        managed_browser,
        switch_service,
        history_store,
        *,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self._account_store = account_store
        self._managed_browser = managed_browser
        self._switch_service = switch_service
        self._history_store = history_store
        self._poll_interval_seconds = poll_interval_seconds

    def run(
        self,
        *,
        notify=None,
        sleep_fn=time.sleep,
        stop_after_cycles: int | None = None,
    ) -> WatchRunResult:
        snapshot = self._account_store.load()
        if len(snapshot.accounts) < 2:
            raise SwitchError(
                "Automatic switching requires at least two registered accounts."
            )
        if snapshot.active_account_index is None:
            raise SwitchError(
                "Automatic switching requires a known active account."
            )

        context, page = self._managed_browser.ensure_runtime()
        del context
        excluded_indexes: set[int] = set()
        active_index = snapshot.active_account_index
        cycles = 0
        self._emit(
            notify,
            "monitoring-started",
            "Watching the managed ChatGPT workspace for usage limits.",
        )

        while True:
            try:
                detection = self._managed_browser.detect_limit_state(page)
            except ManagedBrowserError:
                return WatchRunResult("browser-runtime-failure", 1, active_index)

            if detection is LimitState.LIMIT_DETECTED:
                self._emit(
                    notify,
                    "limit-detected",
                    "Usage limit detected. Switching immediately.",
                )
                snapshot = self._account_store.load()
                candidates = [
                    account
                    for account in snapshot.accounts
                    if account.index != active_index
                    and account.index not in excluded_indexes
                ]
                for account in candidates:
                    self._emit(notify, "switch-attempt", f"Trying slot {account.index}.")
                    try:
                        result = self._switch_service.switch_to(
                            account.index, mode="watch-auto"
                        )
                    except SwitchError as exc:
                        excluded_indexes.add(account.index)
                        self._emit(notify, "account-exhausted-for-run", str(exc))
                        continue
                    active_index = result.account.index
                    self._emit(
                        notify,
                        "switch-succeeded",
                        f"Switched to slot {active_index}.",
                    )
                    break
                else:
                    message = (
                        "No eligible registered account remains for automatic switching."
                    )
                    self._emit(notify, "no-eligible-account", message)
                    self._history_store.append(
                        SwitchEvent(
                            occurred_at=datetime.now(UTC),
                            from_account_index=active_index,
                            to_account_index=None,
                            mode="watch-auto",
                            result="no-eligible-account",
                            message=message,
                        )
                    )
                    return WatchRunResult("no-eligible-account", 1, active_index)

            cycles += 1
            if stop_after_cycles is not None and cycles >= stop_after_cycles:
                return WatchRunResult("cycle-limit", 0, active_index)

            try:
                sleep_fn(self._poll_interval_seconds)
            except KeyboardInterrupt:
                message = "Stopped watching for usage limits."
                self._emit(notify, "user-interrupted", message)
                self._history_store.append(
                    SwitchEvent(
                        occurred_at=datetime.now(UTC),
                        from_account_index=active_index,
                        to_account_index=None,
                        mode="watch-auto",
                        result="user-interrupted",
                        message=message,
                    )
                )
                return WatchRunResult("user-interrupted", 130, active_index)

    def _emit(self, notify, kind: str, message: str) -> None:
        if notify is not None:
            notify(WatchNotification(kind=kind, message=message))

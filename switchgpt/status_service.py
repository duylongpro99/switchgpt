from dataclasses import dataclass
from datetime import datetime

from .errors import SecretStoreError
from .models import AccountRecord, AccountState


@dataclass(frozen=True)
class SlotStatus:
    index: int
    email: str
    state: AccountState
    last_error: str | None


@dataclass(frozen=True)
class StatusSummary:
    slots: list[SlotStatus]
    active_account_index: int | None
    readiness: str
    latest_result: str | None
    next_action: str | None
    codex_sync: "CodexSyncStatus | None"


@dataclass(frozen=True)
class HistoryStatus:
    result: str | None
    to_account_index: int | None


@dataclass(frozen=True)
class PersistedCodexSyncState:
    synced_slot: int | None
    status: str | None
    method: str | None
    synced_at: datetime | None
    error: str | None


@dataclass(frozen=True)
class CodexSyncStatus:
    state: str
    method: str | None
    synced_at: datetime | None
    error: str | None


class StatusService:
    def __init__(self, secret_store, history_store=None) -> None:
        self._secret_store = secret_store
        self._history_store = history_store

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

    def summarize(
        self,
        accounts: list[AccountRecord],
        *,
        active_account_index: int | None,
        codex_sync_state: PersistedCodexSyncState | None = None,
    ) -> StatusSummary:
        slots = [self.classify(account) for account in accounts]
        history_status = self._history_status()
        codex_sync = self._codex_sync_status(
            active_account_index=active_account_index,
            codex_sync_state=codex_sync_state,
        )
        latest_result = history_status.result
        readiness = "ready"
        next_action = None

        if latest_result == "history-invalid":
            readiness = "degraded"
            next_action = "Repair or archive malformed switch history."
        elif any(slot.state is AccountState.MISSING_SECRET for slot in slots):
            readiness = "degraded"
            next_action = (
                "Repair the missing Keychain entry or reauthenticate the affected slot."
            )
        else:
            needs_reauth_slot = self._needs_reauth_slot_index(slots, history_status)
            if latest_result == "needs-reauth" and needs_reauth_slot is None:
                readiness = "degraded"
                next_action = "Review switch history against the current registered slots."
            elif needs_reauth_slot is not None:
                readiness = "needs-attention"
                next_action = (
                    f"Reauthenticate slot {needs_reauth_slot} with `switchgpt add --reauth "
                    f"{needs_reauth_slot}` or let `switchgpt watch` guide the in-session flow."
                )

        if readiness == "ready" and codex_sync.state == "out-of-sync":
            readiness = "degraded"
            next_action = (
                "Run `switchgpt codex-sync` to resync Codex auth to the active slot."
            )

        return StatusSummary(
            slots=slots,
            active_account_index=active_account_index,
            readiness=readiness,
            latest_result=latest_result,
            next_action=next_action,
            codex_sync=codex_sync,
        )

    def _history_status(self) -> HistoryStatus:
        if self._history_store is None:
            return HistoryStatus(result=None, to_account_index=None)
        latest = getattr(self._history_store, "latest", None)
        if not callable(latest):
            return HistoryStatus(result="history-invalid", to_account_index=None)
        try:
            latest_event = latest()
        except Exception:
            return HistoryStatus(result="history-invalid", to_account_index=None)
        if latest_event is None:
            return HistoryStatus(result=None, to_account_index=None)
        try:
            return HistoryStatus(
                result=latest_event.result,
                to_account_index=latest_event.to_account_index,
            )
        except Exception:
            return HistoryStatus(result="history-invalid", to_account_index=None)

    def _needs_reauth_slot_index(
        self,
        slots: list[SlotStatus],
        history_status: HistoryStatus,
    ) -> int | None:
        for slot in slots:
            if slot.state is AccountState.NEEDS_REAUTH:
                return slot.index
        if history_status.result != "needs-reauth":
            return None
        slot_index = history_status.to_account_index
        if not isinstance(slot_index, int):
            return None
        return slot_index if any(slot.index == slot_index for slot in slots) else None

    def _codex_sync_status(
        self,
        *,
        active_account_index: int | None,
        codex_sync_state: PersistedCodexSyncState | None,
    ) -> CodexSyncStatus:
        if active_account_index is None:
            return CodexSyncStatus(
                state="no-data",
                method=(None if codex_sync_state is None else codex_sync_state.method),
                synced_at=(
                    None if codex_sync_state is None else codex_sync_state.synced_at
                ),
                error=(None if codex_sync_state is None else codex_sync_state.error),
            )
        if codex_sync_state is None:
            return CodexSyncStatus(
                state="no-data",
                method=None,
                synced_at=None,
                error=None,
            )
        if (
            codex_sync_state.status in {"ok", "fallback-ok"}
            and codex_sync_state.synced_slot == active_account_index
        ):
            state = "in-sync"
        else:
            state = "out-of-sync"
        return CodexSyncStatus(
            state=state,
            method=codex_sync_state.method,
            synced_at=codex_sync_state.synced_at,
            error=codex_sync_state.error,
        )

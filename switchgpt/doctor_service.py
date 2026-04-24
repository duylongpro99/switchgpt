from dataclasses import dataclass
from tempfile import TemporaryDirectory

from .diagnostics import redact_text
from .errors import AccountStoreError, SecretStoreError, SwitchHistoryError


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str
    next_action: str | None


@dataclass(frozen=True)
class DoctorReport:
    readiness: str
    checks: list[DoctorCheck]


class DoctorService:
    def __init__(
        self,
        metadata_store,
        history_store,
        secret_store,
        managed_browser,
        *,
        platform_name: str,
    ) -> None:
        self._metadata_store = metadata_store
        self._history_store = history_store
        self._secret_store = secret_store
        self._managed_browser = managed_browser
        self._platform_name = platform_name

    def run(self) -> DoctorReport:
        snapshot, metadata_check = self._load_snapshot()
        checks = [
            self._check_platform(),
            metadata_check,
            self._check_history(),
            self._check_codex_sync(snapshot, metadata_check),
            self._check_keychain_entries(snapshot, metadata_check),
            self._check_runtime(),
        ]
        readiness = (
            "watch-ready"
            if all(check.status == "pass" for check in checks)
            else "needs-attention"
        )
        return DoctorReport(readiness=readiness, checks=checks)

    def _check_platform(self) -> DoctorCheck:
        if self._platform_name != "Darwin":
            return DoctorCheck(
                "platform",
                "fail",
                "switchgpt requires macOS.",
                "Run switchgpt on macOS.",
            )
        return DoctorCheck("platform", "pass", "macOS detected.", None)

    def _load_snapshot(self):
        try:
            snapshot = self._metadata_store.load()
        except AccountStoreError as exc:
            return None, DoctorCheck(
                "metadata",
                "fail",
                str(exc),
                "Repair or remove malformed account metadata.",
            )
        return snapshot, DoctorCheck("metadata", "pass", "Account metadata is readable.", None)

    def _check_history(self) -> DoctorCheck:
        try:
            self._history_store.load()
        except SwitchHistoryError as exc:
            return DoctorCheck(
                "history",
                "warn",
                str(exc),
                "Repair or archive malformed switch history.",
            )
        except Exception as exc:
            return DoctorCheck(
                "history",
                "warn",
                str(exc),
                "Repair or archive malformed switch history.",
            )
        return DoctorCheck("history", "pass", "Switch history is readable.", None)

    def _check_codex_sync(self, snapshot, metadata_check: DoctorCheck) -> DoctorCheck:
        if snapshot is None:
            return DoctorCheck(
                "codex-sync",
                "fail",
                metadata_check.detail,
                metadata_check.next_action,
            )

        active_slot = getattr(snapshot, "active_account_index", None)
        if active_slot is None:
            return DoctorCheck(
                "codex-sync",
                "pass",
                "No active slot; Codex sync drift is not applicable.",
                None,
            )

        sync_slot = getattr(snapshot, "last_codex_sync_slot", None)
        sync_status = getattr(snapshot, "last_codex_sync_status", None)
        sync_method = getattr(snapshot, "last_codex_sync_method", None)
        sync_at = getattr(snapshot, "last_codex_sync_at", None)
        sync_error = redact_text(getattr(snapshot, "last_codex_sync_error", None) or "")
        sync_fingerprint = getattr(snapshot, "last_codex_sync_fingerprint", None)
        import_fingerprints = getattr(snapshot, "codex_import_fingerprints", {}) or {}
        imported_fingerprint = import_fingerprints.get(active_slot)
        import_action = (
            f"Run `codex login` with the target account, then `switchgpt import-codex-auth --slot {active_slot}`, then rerun `switchgpt doctor`."
        )
        repair_action = (
            "Run `switchgpt codex-sync` for the active slot, then rerun `switchgpt doctor`."
        )

        if imported_fingerprint is None:
            return DoctorCheck(
                "codex-sync",
                "warn",
                f"No imported Codex auth recorded for active slot {active_slot}.",
                import_action,
            )

        if (
            sync_status == "ok"
            and sync_slot == active_slot
            and sync_fingerprint is not None
            and sync_fingerprint == imported_fingerprint
        ):
            method_suffix = f" via {sync_method}" if sync_method is not None else ""
            time_suffix = f" at {sync_at.isoformat()}" if sync_at is not None else ""
            return DoctorCheck(
                "codex-sync",
                "pass",
                f"Active slot matches the last successful local Codex auth projection{method_suffix}{time_suffix}.",
                None,
            )

        if sync_status == "failed":
            if sync_slot == active_slot:
                detail = f"Last Codex sync failed for active slot {active_slot}."
            elif sync_slot is None:
                detail = (
                    f"Last Codex sync failed, but no synced slot was recorded for active slot "
                    f"{active_slot}."
                )
            else:
                detail = (
                    f"Last Codex sync failed for slot {sync_slot}; active slot is "
                    f"{active_slot}."
                )
            if sync_error:
                detail = f"{detail} Error: {sync_error}"
            return DoctorCheck("codex-sync", "warn", detail, repair_action)

        if sync_slot is None or sync_status is None:
            return DoctorCheck(
                "codex-sync",
                "warn",
                f"No successful Codex sync recorded for active slot {active_slot} after import.",
                repair_action,
            )

        return DoctorCheck(
            "codex-sync",
            "warn",
            f"Active slot {active_slot} has imported Codex auth, but the projected live auth is out of sync.",
            repair_action,
        )

    def _check_keychain_entries(self, snapshot, metadata_check: DoctorCheck) -> DoctorCheck:
        if snapshot is None:
            return DoctorCheck(
                "keychain",
                "fail",
                metadata_check.detail,
                metadata_check.next_action,
            )

        try:
            missing_keys = [
                account.keychain_key
                for account in snapshot.accounts
                if not self._secret_store.exists(account.keychain_key)
            ]
        except SecretStoreError as exc:
            return DoctorCheck(
                "keychain",
                "fail",
                str(exc),
                "Repair the Keychain backend or reauthenticate the affected slot.",
            )
        if missing_keys:
            return DoctorCheck(
                "keychain",
                "fail",
                "One or more registered accounts are missing Keychain secrets.",
                "Reauthenticate the affected slot to refresh its secret.",
            )
        return DoctorCheck(
            "keychain",
            "pass",
            "Registered account secrets exist in Keychain.",
            None,
        )

    def _check_runtime(self) -> DoctorCheck:
        try:
            with TemporaryDirectory(prefix="switchgpt-doctor-") as probe_dir:
                can_open = self._managed_browser.can_open_workspace(
                    probe_profile_dir=probe_dir,
                    headless=True,
                )
        except Exception as exc:
            detail = redact_text(str(exc))
            if not detail:
                detail = "Managed browser probe failed."
            return DoctorCheck(
                "managed-browser",
                "fail",
                detail,
                "Run `switchgpt open` after repairing Playwright/browser prerequisites.",
            )
        if not can_open:
            return DoctorCheck(
                "managed-browser",
                "fail",
                "Managed workspace could not be opened.",
                "Run `switchgpt open` after repairing Playwright/browser prerequisites.",
            )
        return DoctorCheck(
            "managed-browser",
            "pass",
            "Managed workspace can be opened.",
            None,
        )

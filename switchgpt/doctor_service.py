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

from dataclasses import dataclass
from datetime import UTC, datetime
import platform
from pathlib import Path
from contextlib import suppress

from .account_store import AccountStore
from .codex_auth_sync import (
    CodexAuthSyncService,
    CodexEnvAuthTarget,
    CodexFileAuthTarget,
)
from .config import Settings
from .doctor_service import DoctorService
from .errors import SwitchError
from .managed_browser import ManagedBrowser
from .models import AccountRecord, AccountState
from .playwright_client import BrowserRegistrationClient
from .registration import RegistrationService
from .secret_store import KeychainSecretStore
from .secret_store import SessionSecret
from .status_service import StatusService
from .switch_history import SwitchHistoryStore
from .switch_service import SwitchService
from .watch_service import WatchService


@dataclass(frozen=True)
class Runtime:
    settings: Settings
    account_store: AccountStore
    secret_store: KeychainSecretStore
    managed_browser: ManagedBrowser
    history_store: SwitchHistoryStore


@dataclass(frozen=True)
class RemoveCommandResult:
    removed_count: int


class CodexSyncCommandService:
    def __init__(self, account_store, secret_store, codex_auth_sync) -> None:
        self._account_store = account_store
        self._secret_store = secret_store
        self._codex_auth_sync = codex_auth_sync

    def run(self):
        snapshot = self._account_store.load()
        active_slot = snapshot.active_account_index
        if active_slot is None:
            raise SwitchError("No active slot available for Codex sync.")
        account = self._account_store.get_record(active_slot)
        secret = self._secret_store.read(account.keychain_key)
        if secret is None:
            raise SwitchError(
                f"Stored session secret is missing for slot {account.index}."
            )
        result = self._codex_auth_sync.sync_active_slot(
            active_slot=account.index,
            email=account.email,
            session_token=secret.session_token,
            csrf_token=secret.csrf_token,
            codex_auth_json=getattr(secret, "codex_auth_json", None),
            occurred_at=datetime.now(UTC),
        )
        return result

class CodexImportCommandService:
    def __init__(self, account_store, secret_store, codex_auth_sync) -> None:
        self._account_store = account_store
        self._secret_store = secret_store
        self._codex_auth_sync = codex_auth_sync

    def run(self, *, slot: int):
        auth_json = self._codex_auth_sync.read_live_auth_json()
        occurred_at = datetime.now(UTC)
        account = self._get_or_create_account(
            slot=slot,
            auth_json=auth_json,
            occurred_at=occurred_at,
        )
        secret = self._secret_store.read(account.keychain_key)
        if secret is None:
            raise SwitchError(f"Stored session secret is missing for slot {slot}.")
        result = self._codex_auth_sync.import_auth_json(
            slot=slot,
            occurred_at=occurred_at,
        )
        resolved_email = self._resolve_auth_email(auth_json) or account.email
        if resolved_email != account.email:
            self._account_store.save_record(
                AccountRecord(
                    index=account.index,
                    email=resolved_email,
                    keychain_key=account.keychain_key,
                    registered_at=account.registered_at,
                    last_reauth_at=account.last_reauth_at,
                    last_validated_at=account.last_validated_at,
                    status=account.status,
                    last_error=account.last_error,
                )
            )
        self._secret_store.replace(
            account.keychain_key,
            SessionSecret(
                session_token=secret.session_token,
                csrf_token=secret.csrf_token,
                codex_auth_json=auth_json,
            ),
        )
        if getattr(result, "fingerprint", None):
            saver = getattr(self._account_store, "save_codex_import_state", None)
            if callable(saver):
                saver(slot=slot, fingerprint=result.fingerprint)
        return result

    def _get_or_create_account(self, *, slot: int, auth_json, occurred_at: datetime):
        try:
            return self._account_store.get_record(slot)
        except SwitchError as exc:
            if str(exc) != f"Account slot {slot} is not registered.":
                raise

        keychain_key = f"switchgpt_account_{slot}"
        self._secret_store.write(
            keychain_key,
            SessionSecret(session_token="", csrf_token=None),
        )
        record = AccountRecord(
            index=slot,
            email=self._resolve_auth_email(auth_json) or f"slot-{slot}@codex.local",
            keychain_key=keychain_key,
            registered_at=occurred_at,
            last_reauth_at=occurred_at,
            last_validated_at=occurred_at,
            status=AccountState.REGISTERED,
            last_error=None,
        )
        try:
            self._account_store.save_record(record)
        except Exception:
            with suppress(Exception):
                self._secret_store.delete(keychain_key)
            raise
        self._account_store.save_runtime_state(
            active_account_index=slot,
            switched_at=occurred_at,
        )
        return record

    def _resolve_auth_email(self, auth_json) -> str | None:
        resolver = getattr(self._codex_auth_sync, "resolve_auth_email", None)
        if not callable(resolver):
            return None
        resolved = resolver(auth_json)
        if type(resolved) is not str or not resolved:
            return None
        return resolved


class RemoveCommandService:
    def __init__(self, account_store, secret_store) -> None:
        self._account_store = account_store
        self._secret_store = secret_store

    def remove_slot(self, index: int) -> RemoveCommandResult:
        account = self._account_store.get_record(index)
        with suppress(Exception):
            self._secret_store.delete(account.keychain_key)
        self._account_store.remove_record(index)
        return RemoveCommandResult(removed_count=1)

    def remove_all(self) -> RemoveCommandResult:
        snapshot = self._account_store.load()
        for account in snapshot.accounts:
            with suppress(Exception):
                self._secret_store.delete(account.keychain_key)
        self._account_store.clear()
        return RemoveCommandResult(removed_count=len(snapshot.accounts))


def build_runtime() -> Runtime:
    settings = Settings.from_env()
    return Runtime(
        settings=settings,
        account_store=AccountStore(settings.metadata_path, settings.slot_count),
        secret_store=KeychainSecretStore(settings.keychain_service),
        managed_browser=ManagedBrowser(
            base_url=settings.chatgpt_base_url,
            profile_dir=settings.managed_profile_dir,
        ),
        history_store=SwitchHistoryStore(settings.switch_history_path),
    )


def build_registration_service(runtime: Runtime | None = None) -> RegistrationService:
    runtime = build_runtime() if runtime is None else runtime
    browser_client = BrowserRegistrationClient(
        base_url=runtime.settings.chatgpt_base_url,
        profile_dir=runtime.settings.managed_profile_dir,
        codex_auth_file_path=runtime.settings.codex_auth_file_path,
    )
    return RegistrationService(
        runtime.account_store,
        runtime.secret_store,
        browser_client,
        codex_auth_sync=build_codex_auth_sync_service(runtime),
    )


def build_codex_auth_sync_service(
    runtime: Runtime | None = None,
) -> CodexAuthSyncService:
    runtime = build_runtime() if runtime is None else runtime
    return CodexAuthSyncService(
        file_target=CodexFileAuthTarget(
            auth_file_path=runtime.settings.codex_auth_file_path,
        ),
        account_store=runtime.account_store,
    )


def build_status_service(
    runtime: Runtime | None = None,
) -> tuple[AccountStore, StatusService]:
    runtime = build_runtime() if runtime is None else runtime
    return (
        runtime.account_store,
        StatusService(runtime.secret_store, history_store=runtime.history_store),
    )


def build_doctor_service(runtime: Runtime | None = None) -> DoctorService:
    runtime = build_runtime() if runtime is None else runtime
    return DoctorService(
        metadata_store=runtime.account_store,
        history_store=runtime.history_store,
        secret_store=runtime.secret_store,
        managed_browser=runtime.managed_browser,
        platform_name=platform.system(),
    )


def build_managed_browser(runtime: Runtime | None = None) -> ManagedBrowser:
    runtime = build_runtime() if runtime is None else runtime
    return runtime.managed_browser


def build_switch_service(runtime: Runtime | None = None) -> SwitchService:
    runtime = build_runtime() if runtime is None else runtime
    return SwitchService(
        runtime.account_store,
        runtime.secret_store,
        runtime.managed_browser,
        runtime.history_store,
        codex_auth_sync=build_codex_auth_sync_service(runtime),
    )


def build_codex_sync_command_service(
    runtime: Runtime | None = None,
) -> CodexSyncCommandService:
    runtime = build_runtime() if runtime is None else runtime
    return CodexSyncCommandService(
        runtime.account_store,
        runtime.secret_store,
        build_codex_auth_sync_service(runtime),
    )


def build_codex_import_service(
    runtime: Runtime | None = None,
) -> CodexImportCommandService:
    runtime = build_runtime() if runtime is None else runtime
    return CodexImportCommandService(
        runtime.account_store,
        runtime.secret_store,
        build_codex_auth_sync_service(runtime),
    )


def build_remove_command_service(
    runtime: Runtime | None = None,
) -> RemoveCommandService:
    runtime = build_runtime() if runtime is None else runtime
    return RemoveCommandService(
        runtime.account_store,
        runtime.secret_store,
    )


def build_watch_service(
    runtime: Runtime | None = None,
    *,
    registration_service: RegistrationService | None = None,
) -> WatchService:
    runtime = build_runtime() if runtime is None else runtime
    switch_service = build_switch_service(runtime)
    if registration_service is None:
        registration_service = build_registration_service(runtime)
    return WatchService(
        account_store=runtime.account_store,
        managed_browser=runtime.managed_browser,
        switch_service=switch_service,
        registration_service=registration_service,
        history_store=runtime.history_store,
    )

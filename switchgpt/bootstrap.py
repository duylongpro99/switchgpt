from dataclasses import dataclass
import platform

from .account_store import AccountStore
from .config import Settings
from .doctor_service import DoctorService
from .managed_browser import ManagedBrowser
from .playwright_client import BrowserRegistrationClient
from .registration import RegistrationService
from .secret_store import KeychainSecretStore
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
    browser_client = BrowserRegistrationClient(base_url=runtime.settings.chatgpt_base_url)
    return RegistrationService(runtime.account_store, runtime.secret_store, browser_client)


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
    )


def build_watch_service(
    runtime: Runtime | None = None,
    *,
    registration_service: RegistrationService | None = None,
) -> WatchService:
    runtime = build_runtime() if runtime is None else runtime
    switch_service = SwitchService(
        runtime.account_store,
        runtime.secret_store,
        runtime.managed_browser,
        runtime.history_store,
    )
    if registration_service is None:
        registration_service = build_registration_service(runtime)
    return WatchService(
        account_store=runtime.account_store,
        managed_browser=runtime.managed_browser,
        switch_service=switch_service,
        registration_service=registration_service,
        history_store=runtime.history_store,
    )

import platform

import typer

from .account_store import AccountStore
from .config import Settings, ensure_supported_platform
from .errors import SwitchGptError
from .doctor_service import DoctorService
from .managed_browser import ManagedBrowser
from .playwright_client import BrowserRegistrationClient
from .registration import RegistrationService
from .secret_store import KeychainSecretStore
from .status_service import StatusService
from .switch_history import SwitchHistoryStore
from .switch_service import SwitchService
from .watch_service import WatchService


app = typer.Typer(no_args_is_help=True)


@app.callback()
def main_command() -> None:
    pass


def build_registration_service() -> RegistrationService:
    settings = Settings.from_env()
    store = AccountStore(settings.metadata_path, settings.slot_count)
    secret_store = KeychainSecretStore(settings.keychain_service)
    browser_client = BrowserRegistrationClient(base_url=settings.chatgpt_base_url)
    return RegistrationService(store, secret_store, browser_client)


def build_status_service() -> tuple[AccountStore, StatusService]:
    settings = Settings.from_env()
    store = AccountStore(settings.metadata_path, settings.slot_count)
    history_store = SwitchHistoryStore(settings.switch_history_path)
    service = StatusService(
        KeychainSecretStore(settings.keychain_service),
        history_store=history_store,
    )
    return store, service


def build_doctor_service() -> DoctorService:
    settings = Settings.from_env()
    return DoctorService(
        metadata_store=AccountStore(settings.metadata_path, settings.slot_count),
        history_store=SwitchHistoryStore(settings.switch_history_path),
        secret_store=KeychainSecretStore(settings.keychain_service),
        managed_browser=build_managed_browser(),
        platform_name=platform.system(),
    )


def build_managed_browser() -> ManagedBrowser:
    settings = Settings.from_env()
    return ManagedBrowser(
        base_url=settings.chatgpt_base_url,
        profile_dir=settings.managed_profile_dir,
    )


def _build_switch_components() -> tuple[AccountStore, KeychainSecretStore, ManagedBrowser, SwitchHistoryStore]:
    settings = Settings.from_env()
    store = AccountStore(settings.metadata_path, settings.slot_count)
    secret_store = KeychainSecretStore(settings.keychain_service)
    managed_browser = build_managed_browser()
    history_store = SwitchHistoryStore(settings.switch_history_path)
    return store, secret_store, managed_browser, history_store


def build_switch_service() -> SwitchService:
    store, secret_store, managed_browser, history_store = _build_switch_components()
    return SwitchService(store, secret_store, managed_browser, history_store)


def build_watch_service() -> WatchService:
    store, secret_store, managed_browser, history_store = _build_switch_components()
    switch_service = SwitchService(store, secret_store, managed_browser, history_store)
    registration_service = build_registration_service()
    return WatchService(
        account_store=store,
        managed_browser=managed_browser,
        switch_service=switch_service,
        registration_service=registration_service,
        history_store=history_store,
    )

@app.command()
def status() -> None:
    try:
        ensure_supported_platform()
        store, service = build_status_service()
        snapshot = store.load()
        if not snapshot.accounts:
            print("No accounts registered.")
            return
        summary = service.summarize(
            snapshot.accounts,
            active_account_index=snapshot.active_account_index,
        )
        print(f"Readiness: {summary.readiness}")
        if summary.active_account_index is not None:
            print(f"Active slot: {summary.active_account_index}")
        if summary.latest_result is not None:
            print(f"Latest result: {summary.latest_result}")
        if summary.next_action is not None:
            print(f"Next action: {summary.next_action}")
        for slot in summary.slots:
            print(f"[{slot.index}] {slot.email} - {slot.state}")
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def doctor() -> None:
    try:
        service = build_doctor_service()
        report = service.run()
        print(f"Readiness: {report.readiness}")
        for check in report.checks:
            print(f"{check.name}: {check.status} - {check.detail}")
            if check.next_action:
                print(f"next: {check.next_action}")
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def add(reauth: int | None = typer.Option(None, "--reauth")) -> None:
    try:
        ensure_supported_platform()
        service = build_registration_service()
        if reauth is None:
            record = service.add()
            print(f"Registered {record.email} in slot {record.index}.")
            return
        record = service.reauth(reauth)
        print(f"Reauthenticated {record.email} in slot {record.index}.")
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def open() -> None:
    try:
        ensure_supported_platform()
        build_managed_browser().open_workspace()
        print("Managed ChatGPT workspace is ready.")
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def switch(to: int | None = typer.Option(None, "--to")) -> None:
    try:
        ensure_supported_platform()
        service = build_switch_service()
        result = service.switch_next() if to is None else service.switch_to(to)
        print(f"Switched to {result.account.email} in slot {result.account.index}.")
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def watch() -> None:
    try:
        ensure_supported_platform()
        service = build_watch_service()

        def print_event(event) -> None:
            print(event.message)

        result = service.run(notify=print_event)
        if result.exit_code != 0:
            raise typer.Exit(code=result.exit_code)
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def main() -> None:
    app()

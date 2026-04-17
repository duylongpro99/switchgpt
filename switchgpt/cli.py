import typer

from .account_store import AccountStore
from .config import Settings, ensure_supported_platform
from .errors import SwitchGptError
from .playwright_client import BrowserRegistrationClient
from .registration import RegistrationService
from .secret_store import KeychainSecretStore
from .status_service import StatusService


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
    service = StatusService(KeychainSecretStore(settings.keychain_service))
    return store, service


@app.command()
def status() -> None:
    try:
        ensure_supported_platform()
        store, service = build_status_service()
        snapshot = store.load()
        if not snapshot.accounts:
            print("No accounts registered.")
            return
        for account in snapshot.accounts:
            slot = service.classify(account)
            print(f"[{slot.index}] {slot.email} - {slot.state}")
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


def main() -> None:
    app()

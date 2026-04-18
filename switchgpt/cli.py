import typer

from . import bootstrap
from .config import ensure_supported_platform
from .errors import SwitchGptError
from .output import render_doctor_report, render_settings_items, render_status_summary
from .registration import RegistrationService
from .switch_service import SwitchService
from .watch_service import WatchService


app = typer.Typer(no_args_is_help=True)


@app.callback()
def main_command() -> None:
    pass


def build_registration_service() -> RegistrationService:
    return bootstrap.build_registration_service()


def build_status_service():
    return bootstrap.build_status_service()


def build_doctor_service():
    return bootstrap.build_doctor_service()


def build_managed_browser():
    return bootstrap.build_managed_browser()


def _build_switch_components():
    runtime = bootstrap.build_runtime()
    return (
        runtime.account_store,
        runtime.secret_store,
        runtime.managed_browser,
        runtime.history_store,
    )


def build_switch_service():
    store, secret_store, managed_browser, history_store = _build_switch_components()
    return SwitchService(store, secret_store, managed_browser, history_store)


def build_watch_service():
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
def paths() -> None:
    try:
        ensure_supported_platform()
        runtime = bootstrap.build_runtime()
        for line in render_settings_items(runtime.settings.describe_items()):
            print(line)
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


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
        for line in render_status_summary(summary):
            print(line)
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def doctor() -> None:
    try:
        report = build_doctor_service().run()
        for line in render_doctor_report(report):
            print(line)
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

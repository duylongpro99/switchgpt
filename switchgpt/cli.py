import typer

from . import bootstrap
from .config import ensure_supported_platform
from .errors import SwitchGptError
from .output import render_doctor_report, render_settings_items, render_status_summary
from .registration import RegistrationService
from .status_service import PersistedCodexSyncState
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


def build_switch_service():
    return bootstrap.build_switch_service()


def build_codex_sync_command_service():
    return bootstrap.build_codex_sync_command_service()


def build_watch_service():
    return bootstrap.build_watch_service()


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
            codex_sync_state=PersistedCodexSyncState(
                synced_slot=getattr(snapshot, "last_codex_sync_slot", None),
                status=getattr(snapshot, "last_codex_sync_status", None),
                method=getattr(snapshot, "last_codex_sync_method", None),
                synced_at=getattr(snapshot, "last_codex_sync_at", None),
                error=getattr(snapshot, "last_codex_sync_error", None),
            ),
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
def add(
    reauth: int | None = typer.Option(None, "--reauth"),
    from_open: bool = typer.Option(False, "--from-open"),
) -> None:
    try:
        ensure_supported_platform()
        if from_open and reauth is not None:
            raise SwitchGptError("--from-open cannot be combined with --reauth.")
        service = build_registration_service()
        if from_open:
            _, page = build_managed_browser().open_workspace()
            input(
                "[switchgpt] Complete login in the managed browser, then press ENTER here."
            )
            record = service.add_in_managed_workspace(page=page)
            print(f"Registered {record.email} in slot {record.index}.")
            return
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


@app.command("codex-sync")
def codex_sync() -> None:
    try:
        ensure_supported_platform()
        result = build_codex_sync_command_service().run()
        method_suffix = f" ({result.method})" if result.method is not None else ""
        print(f"Codex auth sync: {result.outcome}{method_suffix}.")
        if result.outcome == "failed":
            detail = result.message or result.failure_class or "Codex auth sync failed."
            typer.echo(detail, err=True)
            raise typer.Exit(code=1)
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

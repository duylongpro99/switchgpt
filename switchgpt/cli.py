import typer

from . import bootstrap
from .config import ensure_supported_platform
from .errors import CodexAuthSyncFailedError, SwitchGptError
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


def build_codex_import_service():
    return bootstrap.build_codex_import_service()


def build_remove_command_service():
    return bootstrap.build_remove_command_service()


def build_watch_service():
    return bootstrap.build_watch_service()


def _persisted_codex_sync_state_from_snapshot(snapshot):
    synced_slot = getattr(snapshot, "last_codex_sync_slot", None)
    status = getattr(snapshot, "last_codex_sync_status", None)
    method = getattr(snapshot, "last_codex_sync_method", None)
    synced_at = getattr(snapshot, "last_codex_sync_at", None)
    error = getattr(snapshot, "last_codex_sync_error", None)
    fingerprint = getattr(snapshot, "last_codex_sync_fingerprint", None)
    import_fingerprints = getattr(snapshot, "codex_import_fingerprints", {}) or {}
    active_account_index = getattr(snapshot, "active_account_index", None)
    imported_fingerprint = (
        None
        if active_account_index is None
        else import_fingerprints.get(active_account_index)
    )
    if all(
        value is None
        for value in (synced_slot, status, method, synced_at, error, fingerprint)
    ) and imported_fingerprint is None:
        return None
    return PersistedCodexSyncState(
        synced_slot=synced_slot,
        status=status,
        method=method,
        synced_at=synced_at,
        error=error,
        fingerprint=fingerprint,
        imported=imported_fingerprint is not None,
        imported_fingerprint=imported_fingerprint,
    )


def _render_codex_sync_repair_message(message: str | None) -> str:
    detail = (message or "Codex auth sync failed.").strip()
    if "switchgpt codex-sync" in detail or "switchgpt import-codex-auth" in detail:
        return detail
    if detail.endswith("."):
        return f"{detail} Run `switchgpt codex-sync` to repair."
    return f"{detail}. Run `switchgpt codex-sync` to repair."


def _import_codex_auth_for_slot(slot: int) -> None:
    result = build_codex_import_service().run(slot=slot)
    print(f"Imported Codex auth for slot {slot}.")
    if getattr(result, "fingerprint", None):
        print("Codex auth fingerprint stored.")


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
            codex_sync_state=_persisted_codex_sync_state_from_snapshot(snapshot),
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
    import_codex_auth: bool = typer.Option(False, "--import-codex-auth"),
) -> None:
    try:
        ensure_supported_platform()
        if from_open:
            raise SwitchGptError(
                "--from-open is no longer supported. Run `codex login`, then `switchgpt add`."
            )
        service = build_registration_service()
        if reauth is None:
            record = service.add()
            print(f"Registered {record.email} in slot {record.index}.")
            _import_codex_auth_for_slot(record.index)
            return
        record = service.reauth(reauth)
        print(f"Reauthenticated {record.email} in slot {record.index}.")
        if import_codex_auth:
            _import_codex_auth_for_slot(record.index)
    except CodexAuthSyncFailedError as exc:
        typer.echo(_render_codex_sync_repair_message(str(exc)), err=True)
        raise typer.Exit(code=1) from exc
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
            detail = _render_codex_sync_repair_message(
                result.message or result.failure_class
            )
            typer.echo(detail, err=True)
            raise typer.Exit(code=1)
    except CodexAuthSyncFailedError as exc:
        typer.echo(_render_codex_sync_repair_message(str(exc)), err=True)
        raise typer.Exit(code=1) from exc
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command("import-codex-auth")
def import_codex_auth(slot: int = typer.Option(..., "--slot")) -> None:
    try:
        ensure_supported_platform()
        result = build_codex_import_service().run(slot=slot)
        print(f"Imported Codex auth for slot {slot}.")
        if getattr(result, "fingerprint", None):
            print("Codex auth fingerprint stored.")
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def remove(
    slot: int | None = typer.Option(None, "--slot"),
    all: bool = typer.Option(False, "--all"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    try:
        ensure_supported_platform()
        if slot is None and not all:
            raise SwitchGptError("Specify either --slot or --all.")
        if slot is not None and all:
            raise SwitchGptError("--slot cannot be combined with --all.")
        if not yes:
            prompt = (
                f"Remove registered slot {slot}?"
                if slot is not None
                else "Remove all registered accounts?"
            )
            if not typer.confirm(prompt):
                typer.echo("Aborted.", err=True)
                raise typer.Exit(code=1)
        service = build_remove_command_service()
        if slot is not None:
            service.remove_slot(slot)
            print(f"Removed slot {slot}.")
            return
        result = service.remove_all()
        print(f"Removed {result.removed_count} registered accounts.")
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
    except CodexAuthSyncFailedError as exc:
        typer.echo(_render_codex_sync_repair_message(str(exc)), err=True)
        raise typer.Exit(code=1) from exc
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def watch() -> None:
    try:
        ensure_supported_platform()
        service = build_watch_service()
        last_notification_message: str | None = None

        def print_event(event) -> None:
            nonlocal last_notification_message
            last_notification_message = getattr(event, "message", None)
            print(event.message)

        result = service.run(notify=print_event)
        if (
            result.exit_code != 0
            and getattr(result, "reason", None) == "codex-sync-failed"
        ):
            typer.echo(
                _render_codex_sync_repair_message(last_notification_message),
                err=True,
            )
        if result.exit_code != 0:
            raise typer.Exit(code=result.exit_code)
    except CodexAuthSyncFailedError as exc:
        typer.echo(_render_codex_sync_repair_message(str(exc)), err=True)
        raise typer.Exit(code=1) from exc
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def main() -> None:
    app()

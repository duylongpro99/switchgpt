from typer.testing import CliRunner

from switchgpt.account_store import AccountStore
from switchgpt.cli import app
from switchgpt.errors import SwitchError
from switchgpt.models import AccountRecord, AccountState
from switchgpt.registration import RegistrationService

from datetime import UTC, datetime


runner = CliRunner()


def test_paths_command_prints_config_runtime_and_secret_boundaries(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Darwin")

    result = runner.invoke(app, ["paths"])

    assert result.exit_code == 0
    assert "data_dir:" in result.stdout
    assert "[runtime-state]" in result.stdout
    assert "keychain_service: switchgpt [secret-store]" in result.stdout
    assert "chatgpt_base_url: https://chatgpt.com [config]" in result.stdout


def test_status_command_is_registered() -> None:
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "No accounts registered." in result.stdout


def test_status_command_shows_unsupported_platform_error(monkeypatch) -> None:
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Linux")

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "switchgpt Phase 1 supports macOS only." in result.stderr


def test_status_lists_registered_accounts(monkeypatch) -> None:
    class FakeAccount:
        index = 0
        email = "account1@example.com"
        keychain_key = "switchgpt_account_0"
        last_error = None

    class FakeStore:
        class Snapshot:
            accounts = [FakeAccount()]
            active_account_index = 0
            last_switch_at = None

        def load(self):
            return self.Snapshot()

    class FakeStatusService:
        def summarize(self, accounts, *, active_account_index):
            return type(
                "Summary",
                (),
                {
                    "slots": [
                        type(
                            "Slot",
                            (),
                            {
                                "index": 0,
                                "email": "account1@example.com",
                                "state": "registered",
                            },
                        )()
                    ],
                    "readiness": "needs-attention",
                    "latest_result": "needs-reauth",
                    "next_action": "Reauthenticate slot 0.",
                    "active_account_index": active_account_index,
                },
            )()

    monkeypatch.setattr(
        "switchgpt.cli.build_status_service",
        lambda: (FakeStore(), FakeStatusService()),
    )
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Readiness: needs-attention" in result.stdout
    assert "Active slot: 0" in result.stdout
    assert "Latest result: needs-reauth" in result.stdout
    assert "Next action: Reauthenticate slot 0." in result.stdout
    assert "[0] account1@example.com - registered" in result.stdout


def test_status_command_shows_account_store_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Darwin")
    metadata_dir = tmp_path / ".switchgpt"
    metadata_dir.mkdir()
    (metadata_dir / "accounts.json").write_text("{")

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "Malformed account metadata." in result.stderr


def test_add_command_reports_registered_slot(monkeypatch) -> None:
    class FakeRegistrationService:
        def add(self):
            class Result:
                index = 0
                email = "account1@example.com"

            return Result()

    monkeypatch.setattr("switchgpt.cli.build_registration_service", lambda: FakeRegistrationService())
    result = runner.invoke(app, ["add"])
    assert result.exit_code == 0
    assert "Registered account1@example.com in slot 0." in result.stdout


def test_reauth_command_requires_slot_index(monkeypatch) -> None:
    class FakeRegistrationService:
        def reauth(self, index: int):
            class Result:
                index = 0
                email = "account1@example.com"

            return Result()

    monkeypatch.setattr("switchgpt.cli.build_registration_service", lambda: FakeRegistrationService())
    result = runner.invoke(app, ["add", "--reauth", "0"])
    assert result.exit_code == 0


def test_add_command_reports_missing_reauth_slot_cleanly(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Darwin")
    metadata_path = tmp_path / ".switchgpt" / "accounts.json"
    store = AccountStore(metadata_path, slot_count=3)
    store.save_record(
        AccountRecord(
            index=0,
            email="account1@example.com",
            keychain_key="switchgpt_account_0",
            registered_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
            last_reauth_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
            last_validated_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
            status=AccountState.REGISTERED,
            last_error=None,
        )
    )

    class FakeSecretStore:
        def replace(self, key, secret) -> None:
            raise AssertionError("should not be called")

    class FakeBrowserClient:
        def reauth(self, existing_email: str):
            raise AssertionError("should not be called")

    monkeypatch.setattr(
        "switchgpt.cli.build_registration_service",
        lambda: RegistrationService(store, FakeSecretStore(), FakeBrowserClient()),
    )

    result = runner.invoke(app, ["add", "--reauth", "99"])

    assert result.exit_code == 1
    assert "Account slot 99 is not registered." in result.stderr
    assert "Traceback" not in result.stderr


def test_add_command_reports_slot_exhaustion_cleanly(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Darwin")
    metadata_path = tmp_path / ".switchgpt" / "accounts.json"
    store = AccountStore(metadata_path, slot_count=3)

    for index in range(3):
        store.save_record(
            AccountRecord(
                index=index,
                email=f"account{index + 1}@example.com",
                keychain_key=f"switchgpt_account_{index}",
                registered_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
                last_reauth_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
                last_validated_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
                status=AccountState.REGISTERED,
                last_error=None,
            )
        )

    class FakeSecretStore:
        def write(self, key, secret) -> None:
            raise AssertionError("should not be called")

    class FakeBrowserClient:
        def register(self):
            raise AssertionError("should not be called")

    monkeypatch.setattr(
        "switchgpt.cli.build_registration_service",
        lambda: RegistrationService(store, FakeSecretStore(), FakeBrowserClient()),
    )

    result = runner.invoke(app, ["add"])

    assert result.exit_code == 1
    assert "No empty account slots remain." in result.stderr
    assert "Traceback" not in result.stderr


def test_switch_command_reports_selected_account(monkeypatch) -> None:
    class FakeService:
        def switch_to(self, index: int):
            account = type(
                "Account",
                (),
                {
                    "index": index,
                    "email": "account2@example.com" if index == 1 else "account1@example.com",
                },
            )()
            return type("Result", (), {"mode": "explicit-target", "account": account})()

    monkeypatch.setattr("switchgpt.cli.build_switch_service", lambda: FakeService())

    result = runner.invoke(app, ["switch", "--to", "1"])

    assert result.exit_code == 0
    assert "Switched to account2@example.com in slot 1." in result.stdout


def test_switch_command_reports_selected_account_for_default_path(monkeypatch) -> None:
    class FakeService:
        def switch_next(self):
            account = type(
                "Account",
                (),
                {
                    "index": 1,
                    "email": "account2@example.com",
                },
            )()
            return type("Result", (), {"mode": "auto-target", "account": account})()

    monkeypatch.setattr("switchgpt.cli.build_switch_service", lambda: FakeService())

    result = runner.invoke(app, ["switch"])

    assert result.exit_code == 0
    assert "Switched to account2@example.com in slot 1." in result.stdout


def test_switch_command_surfaces_switch_error_cleanly(monkeypatch) -> None:
    class FakeService:
        def switch_to(self, index: int):
            raise SwitchError(f"Account slot {index} is not registered.")

    monkeypatch.setattr("switchgpt.cli.build_switch_service", lambda: FakeService())

    result = runner.invoke(app, ["switch", "--to", "2"])

    assert result.exit_code == 1
    assert "Account slot 2 is not registered." in result.stderr
    assert "Traceback" not in result.stderr


def test_open_command_reports_managed_workspace_ready(monkeypatch) -> None:
    class FakeManagedBrowser:
        def open_workspace(self):
            return None

    monkeypatch.setattr("switchgpt.cli.build_managed_browser", lambda: FakeManagedBrowser())

    result = runner.invoke(app, ["open"])

    assert result.exit_code == 0
    assert "Managed ChatGPT workspace is ready." in result.stdout


def test_doctor_command_prints_check_results(monkeypatch) -> None:
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Darwin")

    class FakeDoctorService:
        def run(self):
            return type(
                "Report",
                (),
                {
                    "readiness": "watch-ready",
                    "checks": [
                        type(
                            "Check",
                            (),
                            {
                                "name": "platform",
                                "status": "pass",
                                "detail": "macOS detected.",
                                "next_action": None,
                            },
                        )()
                    ],
                },
            )()

    monkeypatch.setattr("switchgpt.cli.build_doctor_service", lambda: FakeDoctorService())

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Readiness: watch-ready" in result.stdout
    assert "platform: pass - macOS detected." in result.stdout


def test_doctor_command_reports_platform_failure_from_service(monkeypatch) -> None:
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Linux")

    class FakeDoctorService:
        def run(self):
            return type(
                "Report",
                (),
                {
                    "readiness": "needs-attention",
                    "checks": [
                        type(
                            "Check",
                            (),
                            {
                                "name": "platform",
                                "status": "fail",
                                "detail": "switchgpt requires macOS.",
                                "next_action": "Run switchgpt on macOS.",
                            },
                        )()
                    ],
                },
            )()

    monkeypatch.setattr("switchgpt.cli.build_doctor_service", lambda: FakeDoctorService())

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Readiness: needs-attention" in result.stdout
    assert "platform: fail - switchgpt requires macOS." in result.stdout


def test_watch_command_prints_notifications_and_exits_zero_for_short_run(monkeypatch) -> None:
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Darwin")

    class FakeWatchService:
        def run(self, *, notify, sleep_fn=None, stop_after_cycles=None):
            notify(
                type(
                    "Event",
                    (),
                    {"message": "Watching the managed ChatGPT workspace for usage limits."},
                )()
            )
            notify(
                type(
                    "Event",
                    (),
                    {"message": "Usage limit detected. Switching immediately."},
                )()
            )
            notify(type("Event", (), {"message": "Switched to slot 1."})())
            return type("Result", (), {"exit_code": 0})()

    monkeypatch.setattr("switchgpt.cli.build_watch_service", lambda: FakeWatchService())

    result = runner.invoke(app, ["watch"])

    assert result.exit_code == 0
    assert "Watching the managed ChatGPT workspace for usage limits." in result.stdout
    assert "Switched to slot 1." in result.stdout


def test_build_watch_service_wires_registration_service(monkeypatch) -> None:
    store = object()
    secret_store = object()
    managed_browser = object()
    history_store = object()
    registration_service = object()
    captured = {}

    monkeypatch.setattr(
        "switchgpt.cli._build_switch_components",
        lambda: (store, secret_store, managed_browser, history_store),
    )
    monkeypatch.setattr(
        "switchgpt.cli.build_registration_service",
        lambda: registration_service,
    )

    class FakeSwitchService:
        def __init__(self, account_store, secret_store_arg, managed_browser_arg, history_store_arg):
            captured["switch_args"] = (
                account_store,
                secret_store_arg,
                managed_browser_arg,
                history_store_arg,
            )

    class FakeWatchService:
        def __init__(
            self,
            *,
            account_store,
            managed_browser,
            switch_service,
            registration_service,
            history_store,
        ) -> None:
            captured["watch_args"] = {
                "account_store": account_store,
                "managed_browser": managed_browser,
                "switch_service": switch_service,
                "registration_service": registration_service,
                "history_store": history_store,
            }

    monkeypatch.setattr("switchgpt.cli.SwitchService", FakeSwitchService)
    monkeypatch.setattr("switchgpt.cli.WatchService", FakeWatchService)

    from switchgpt.cli import build_watch_service

    build_watch_service()

    assert captured["switch_args"] == (
        store,
        secret_store,
        managed_browser,
        history_store,
    )
    assert captured["watch_args"]["account_store"] is store
    assert captured["watch_args"]["managed_browser"] is managed_browser
    assert captured["watch_args"]["registration_service"] is registration_service
    assert captured["watch_args"]["history_store"] is history_store


def test_watch_command_exits_non_zero_on_exhaustion(monkeypatch) -> None:
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Darwin")

    class FakeWatchService:
        def run(self, *, notify, sleep_fn=None, stop_after_cycles=None):
            notify(
                type(
                    "Event",
                    (),
                    {
                        "message": "No eligible registered account remains for automatic switching."
                    },
                )()
            )
            return type("Result", (), {"exit_code": 1})()

    monkeypatch.setattr("switchgpt.cli.build_watch_service", lambda: FakeWatchService())

    result = runner.invoke(app, ["watch"])

    assert result.exit_code == 1
    assert "No eligible registered account remains for automatic switching." in result.stdout


def test_watch_command_prints_reauth_and_resume_messages(monkeypatch) -> None:
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Darwin")

    class FakeWatchService:
        def run(self, *, notify, sleep_fn=None, stop_after_cycles=None):
            notify(type("Event", (), {"message": "Slot 1 requires reauthentication in the managed browser."})())
            notify(type("Event", (), {"message": "Reauthenticated slot 1; resuming watch."})())
            return type("Result", (), {"exit_code": 0})()

    monkeypatch.setattr("switchgpt.cli.build_watch_service", lambda: FakeWatchService())

    result = runner.invoke(app, ["watch"])

    assert result.exit_code == 0
    assert "Slot 1 requires reauthentication in the managed browser." in result.stdout
    assert "Reauthenticated slot 1; resuming watch." in result.stdout


def test_watch_command_prints_runtime_failure_message_before_exit(monkeypatch) -> None:
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Darwin")

    class FakeWatchService:
        def run(self, *, notify, sleep_fn=None, stop_after_cycles=None):
            notify(
                type(
                    "Event",
                    (),
                    {
                        "message": "Managed ChatGPT workspace became unavailable during watch."
                    },
                )()
            )
            return type("Result", (), {"exit_code": 1})()

    monkeypatch.setattr("switchgpt.cli.build_watch_service", lambda: FakeWatchService())

    result = runner.invoke(app, ["watch"])

    assert result.exit_code == 1
    assert "Managed ChatGPT workspace became unavailable during watch." in result.stdout

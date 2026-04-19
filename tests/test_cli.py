import pytest
from typer.testing import CliRunner

from switchgpt.account_store import AccountStore
from switchgpt.cli import app
from switchgpt.errors import CodexAuthSyncFailedError, SwitchError
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


def test_build_runtime_container_reuses_single_settings_snapshot(monkeypatch) -> None:
    captured = {"calls": 0}

    class FakeSettings:
        metadata_path = "meta"
        slot_count = 3
        keychain_service = "switchgpt"
        chatgpt_base_url = "https://chatgpt.com"
        managed_profile_dir = "profile"
        switch_history_path = "history"

        def describe_items(self):
            return []

    def fake_from_env():
        captured["calls"] += 1
        return FakeSettings()

    monkeypatch.setattr("switchgpt.bootstrap.Settings.from_env", fake_from_env)

    from switchgpt.bootstrap import build_runtime

    runtime = build_runtime()

    assert captured["calls"] == 1
    assert runtime.settings.chatgpt_base_url == "https://chatgpt.com"


def test_build_registration_service_passes_managed_profile_dir_to_browser_client(monkeypatch) -> None:
    captured: dict[str, object] = {}
    runtime = type(
        "Runtime",
        (),
        {
            "settings": type(
                "Settings",
                (),
                {
                    "chatgpt_base_url": "https://chatgpt.com",
                    "managed_profile_dir": "profile-dir",
                },
            )(),
            "account_store": object(),
            "secret_store": object(),
        },
    )()

    class FakeBrowserRegistrationClient:
        def __init__(self, *, base_url, profile_dir):
            captured["base_url"] = base_url
            captured["profile_dir"] = profile_dir

    class FakeRegistrationService:
        def __init__(
            self,
            account_store,
            secret_store,
            browser_client,
            *,
            codex_auth_sync=None,
        ) -> None:
            captured["service_args"] = (account_store, secret_store, browser_client)
            captured["codex_auth_sync"] = codex_auth_sync

    sentinel_sync = object()

    monkeypatch.setattr(
        "switchgpt.bootstrap.BrowserRegistrationClient",
        FakeBrowserRegistrationClient,
    )
    monkeypatch.setattr(
        "switchgpt.bootstrap.RegistrationService",
        FakeRegistrationService,
    )
    monkeypatch.setattr(
        "switchgpt.bootstrap.build_codex_auth_sync_service",
        lambda runtime_arg=None: sentinel_sync if runtime_arg is runtime else None,
    )

    from switchgpt.bootstrap import build_registration_service

    build_registration_service(runtime=runtime)

    assert captured["base_url"] == "https://chatgpt.com"
    assert captured["profile_dir"] == "profile-dir"
    assert captured["service_args"][0] is runtime.account_store
    assert captured["service_args"][1] is runtime.secret_store
    assert captured["codex_auth_sync"] is sentinel_sync


def test_build_switch_service_uses_bootstrap_wiring(monkeypatch) -> None:
    sentinel_service = object()
    monkeypatch.setattr(
        "switchgpt.cli.bootstrap.build_switch_service",
        lambda: sentinel_service,
    )

    from switchgpt.cli import build_switch_service

    assert build_switch_service() is sentinel_service


def test_build_codex_sync_command_service_uses_bootstrap_wiring(monkeypatch) -> None:
    sentinel_service = object()
    monkeypatch.setattr(
        "switchgpt.cli.bootstrap.build_codex_sync_command_service",
        lambda: sentinel_service,
    )

    from switchgpt.cli import build_codex_sync_command_service

    assert build_codex_sync_command_service() is sentinel_service


def test_codex_sync_command_service_syncs_active_slot_from_runtime_state() -> None:
    sync_call: dict[str, object] = {}
    sentinel_result = object()

    class FakeAccountStore:
        class Snapshot:
            active_account_index = 1

        def load(self):
            return self.Snapshot()

        def get_record(self, index: int):
            assert index == 1
            return type(
                "Account",
                (),
                {
                    "index": 1,
                    "email": "account2@example.com",
                    "keychain_key": "switchgpt_account_1",
                },
            )()

    class FakeSecretStore:
        def read(self, key: str):
            assert key == "switchgpt_account_1"
            return type(
                "Secret",
                (),
                {
                    "session_token": "session-2",
                    "csrf_token": "csrf-2",
                },
            )()

    class FakeSyncService:
        def sync_active_slot(self, **kwargs):
            sync_call.update(kwargs)
            return sentinel_result

    from switchgpt.bootstrap import CodexSyncCommandService

    result = CodexSyncCommandService(
        FakeAccountStore(),
        FakeSecretStore(),
        FakeSyncService(),
    ).run()

    assert result is sentinel_result
    assert sync_call["active_slot"] == 1
    assert sync_call["email"] == "account2@example.com"
    assert sync_call["session_token"] == "session-2"
    assert sync_call["csrf_token"] == "csrf-2"
    assert isinstance(sync_call["occurred_at"], datetime)


def test_codex_sync_command_service_requires_active_slot() -> None:
    class FakeAccountStore:
        class Snapshot:
            active_account_index = None

        def load(self):
            return self.Snapshot()

    from switchgpt.bootstrap import CodexSyncCommandService

    with pytest.raises(SwitchError, match="No active slot available for Codex sync."):
        CodexSyncCommandService(
            FakeAccountStore(),
            object(),
            object(),
        ).run()


def test_status_command_is_registered(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Darwin")
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


def test_status_command_uses_rendered_output_lines(monkeypatch) -> None:
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Darwin")

    class FakeStore:
        class Snapshot:
            accounts = [
                type(
                    "Account",
                    (),
                    {
                        "index": 0,
                        "email": "account1@example.com",
                        "keychain_key": "switchgpt_account_0",
                        "last_error": None,
                    },
                )()
            ]
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
                    "slots": [],
                    "readiness": "ready",
                    "latest_result": None,
                    "next_action": None,
                    "active_account_index": active_account_index,
                },
            )()

    monkeypatch.setattr(
        "switchgpt.cli.build_status_service",
        lambda: (FakeStore(), FakeStatusService()),
    )
    monkeypatch.setattr(
        "switchgpt.cli.render_status_summary",
        lambda summary: ["Readiness: ready", "rendered-summary"],
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Readiness: ready" in result.stdout
    assert "rendered-summary" in result.stdout


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


def test_add_command_from_open_captures_managed_workspace_session(monkeypatch) -> None:
    page = object()
    events: list[str] = []

    class FakeRegistrationService:
        def add_in_managed_workspace(self, *, page):
            events.append("capture")
            assert page is not None

            class Result:
                index = 1
                email = "account2@example.com"

            return Result()

    class FakeManagedBrowser:
        def open_workspace(self):
            events.append("open-workspace")
            return object(), page

    monkeypatch.setattr("builtins.input", lambda prompt="": events.append("input"))
    monkeypatch.setattr("switchgpt.cli.build_registration_service", lambda: FakeRegistrationService())
    monkeypatch.setattr("switchgpt.cli.build_managed_browser", lambda: FakeManagedBrowser())

    result = runner.invoke(app, ["add", "--from-open"])

    assert result.exit_code == 0
    assert "Registered account2@example.com in slot 1." in result.stdout
    assert events == ["open-workspace", "input", "capture"]


def test_add_command_rejects_from_open_with_reauth(monkeypatch) -> None:
    class FakeRegistrationService:
        def add(self):
            raise AssertionError("should not be called")

    monkeypatch.setattr("switchgpt.cli.build_registration_service", lambda: FakeRegistrationService())

    result = runner.invoke(app, ["add", "--from-open", "--reauth", "0"])

    assert result.exit_code == 1
    assert "cannot be combined with --reauth" in result.stderr


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


def test_codex_sync_command_repairs_active_slot_and_prints_method(monkeypatch) -> None:
    class FakeService:
        def run(self):
            return type(
                "Result",
                (),
                {
                    "outcome": "fallback-ok",
                    "method": "env-fallback",
                },
            )()

    monkeypatch.setattr(
        "switchgpt.cli.build_codex_sync_command_service",
        lambda: FakeService(),
    )

    result = runner.invoke(app, ["codex-sync"])

    assert result.exit_code == 0
    assert "Codex auth sync: fallback-ok (env-fallback)." in result.stdout


def test_codex_sync_command_exits_non_zero_when_sync_result_failed(monkeypatch) -> None:
    class FakeService:
        def run(self):
            return type(
                "Result",
                (),
                {
                    "outcome": "failed",
                    "method": None,
                },
            )()

    monkeypatch.setattr(
        "switchgpt.cli.build_codex_sync_command_service",
        lambda: FakeService(),
    )

    result = runner.invoke(app, ["codex-sync"])

    assert result.exit_code == 1
    assert "Codex auth sync: failed." in result.stdout


def test_codex_sync_command_reports_domain_errors_cleanly(monkeypatch) -> None:
    class FakeService:
        def run(self):
            raise SwitchError("No active slot available for Codex sync.")

    monkeypatch.setattr(
        "switchgpt.cli.build_codex_sync_command_service",
        lambda: FakeService(),
    )

    result = runner.invoke(app, ["codex-sync"])

    assert result.exit_code == 1
    assert "No active slot available for Codex sync." in result.stderr
    assert "Traceback" not in result.stderr


def test_switch_command_surfaces_codex_sync_failure_with_repair_hint(monkeypatch) -> None:
    class FakeService:
        def switch_to(self, index: int):
            raise CodexAuthSyncFailedError(
                "Codex auth sync failed after switch. Run `switchgpt codex-sync` to repair.",
                failure_class="codex-auth-fallback-failed",
            )

    monkeypatch.setattr("switchgpt.cli.build_switch_service", lambda: FakeService())

    result = runner.invoke(app, ["switch", "--to", "1"])

    assert result.exit_code == 1
    assert "Codex auth sync failed after switch." in result.stderr
    assert "switchgpt codex-sync" in result.stderr
    assert "Traceback" not in result.stderr


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
    runtime = type(
        "Runtime",
        (),
        {
            "account_store": store,
            "secret_store": secret_store,
            "managed_browser": managed_browser,
            "history_store": history_store,
        },
    )()
    registration_service = object()
    codex_auth_sync = object()
    captured = {}

    monkeypatch.setattr(
        "switchgpt.bootstrap.build_runtime",
        lambda: runtime,
    )
    def fake_build_registration_service(runtime_arg=None):
        captured["registration_runtime"] = runtime_arg
        return registration_service

    monkeypatch.setattr(
        "switchgpt.bootstrap.build_registration_service",
        fake_build_registration_service,
    )

    monkeypatch.setattr(
        "switchgpt.bootstrap.build_codex_auth_sync_service",
        lambda runtime_arg=None: codex_auth_sync if runtime_arg is runtime else None,
    )

    class FakeSwitchService:
        def __init__(
            self,
            account_store,
            secret_store_arg,
            managed_browser_arg,
            history_store_arg,
            *,
            codex_auth_sync=None,
        ):
            captured["switch_args"] = (
                account_store,
                secret_store_arg,
                managed_browser_arg,
                history_store_arg,
            )
            captured["switch_codex_auth_sync"] = codex_auth_sync

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

    monkeypatch.setattr("switchgpt.bootstrap.SwitchService", FakeSwitchService)
    monkeypatch.setattr("switchgpt.bootstrap.WatchService", FakeWatchService)

    from switchgpt.bootstrap import build_watch_service

    build_watch_service()

    assert captured["switch_args"] == (
        store,
        secret_store,
        managed_browser,
        history_store,
    )
    assert captured["switch_codex_auth_sync"] is codex_auth_sync
    assert captured["registration_runtime"] is runtime
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

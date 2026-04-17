from typer.testing import CliRunner

from switchgpt.account_store import AccountStore
from switchgpt.cli import app
from switchgpt.models import AccountRecord, AccountState
from switchgpt.registration import RegistrationService

from datetime import UTC, datetime


runner = CliRunner()


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

        def load(self):
            return self.Snapshot()

    class FakeStatusService:
        def classify(self, account):
            class Slot:
                index = account.index
                email = account.email
                state = "registered"

            return Slot()

    monkeypatch.setattr(
        "switchgpt.cli.build_status_service",
        lambda: (FakeStore(), FakeStatusService()),
    )
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
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

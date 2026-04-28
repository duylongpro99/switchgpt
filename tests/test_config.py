from pathlib import Path

import pytest

from switchgpt.config import Settings, SettingsItem, ensure_supported_platform, get_env
from switchgpt.errors import SwitchError, SwitchGptError, UnsupportedPlatformError


def test_settings_uses_switchgpt_home_under_user_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/example-home")
    settings = Settings.from_env()
    assert settings.data_dir == Path("/tmp/example-home/.switchgpt")
    assert settings.metadata_path == Path("/tmp/example-home/.switchgpt/accounts.json")
    assert settings.keychain_service == "switchgpt"


def test_ensure_supported_platform_rejects_non_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Linux")
    with pytest.raises(UnsupportedPlatformError):
        ensure_supported_platform()


def test_settings_exposes_runtime_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/example-home")

    settings = Settings.from_env()

    assert settings.switch_history_path == Path("/tmp/example-home/.switchgpt/switch-history.jsonl")


def test_settings_support_env_overrides_and_describe_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/tmp/example-home")
    monkeypatch.setenv("SWITCHGPT_HOME", "/tmp/custom-switchgpt")
    monkeypatch.setenv("SWITCHGPT_SLOT_COUNT", "5")
    monkeypatch.setenv("SWITCHGPT_KEYCHAIN_SERVICE", "switchgpt-dev")
    monkeypatch.setenv("SWITCHGPT_CODEX_AUTH_PATH", "/tmp/codex-auth.json")

    settings = Settings.from_env()
    items = {item.name: item for item in settings.describe_items()}

    assert settings.data_dir == Path("/tmp/custom-switchgpt")
    assert settings.slot_count == 5
    assert settings.keychain_service == "switchgpt-dev"
    assert settings.codex_auth_file_path == Path("/tmp/codex-auth.json")
    assert "chatgpt_base_url" not in items
    assert "managed_profile_dir" not in items
    assert items["metadata_path"] == SettingsItem(
        name="metadata_path",
        value="/tmp/custom-switchgpt/accounts.json",
        category="runtime-state",
        secret=False,
        description="Non-secret account metadata persisted on disk.",
    )
    assert items["keychain_service"].category == "secret-store"
    assert items["keychain_service"].secret is True


def test_error_types_inherit_from_switchgpt_error() -> None:
    assert issubclass(SwitchError, SwitchGptError)


def test_get_env_reads_from_dotenv_when_process_env_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SWITCHGPT_TEST_VALUE", raising=False)
    (tmp_path / ".env").write_text("SWITCHGPT_TEST_VALUE=from-dotenv\n", encoding="utf-8")

    assert get_env("SWITCHGPT_TEST_VALUE") == "from-dotenv"


def test_get_env_prefers_process_env_over_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SWITCHGPT_TEST_VALUE", "from-env")
    (tmp_path / ".env").write_text("SWITCHGPT_TEST_VALUE=from-dotenv\n", encoding="utf-8")

    assert get_env("SWITCHGPT_TEST_VALUE") == "from-env"

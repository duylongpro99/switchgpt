from pathlib import Path

import pytest

from switchgpt.config import Settings, ensure_supported_platform
from switchgpt.errors import ManagedBrowserError, SwitchError, SwitchGptError, UnsupportedPlatformError


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


def test_settings_exposes_phase_2_runtime_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/tmp/example-home")

    settings = Settings.from_env()

    assert settings.managed_profile_dir == Path("/tmp/example-home/.switchgpt/playwright-profile")
    assert settings.switch_history_path == Path("/tmp/example-home/.switchgpt/switch-history.jsonl")


def test_phase_2_error_types_inherit_from_switchgpt_error() -> None:
    assert issubclass(ManagedBrowserError, SwitchGptError)
    assert issubclass(SwitchError, SwitchGptError)

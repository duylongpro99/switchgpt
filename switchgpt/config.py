from dataclasses import dataclass
import os
import platform
from pathlib import Path

from .errors import UnsupportedPlatformError


@dataclass(frozen=True)
class SettingsItem:
    name: str
    value: str
    category: str
    secret: bool
    description: str


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    metadata_path: Path
    keychain_service: str
    slot_count: int
    chatgpt_base_url: str
    managed_profile_dir: Path
    switch_history_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        home = Path(os.environ["HOME"])
        data_dir = Path(os.environ.get("SWITCHGPT_HOME", home / ".switchgpt"))
        slot_count = int(os.environ.get("SWITCHGPT_SLOT_COUNT", "3"))
        keychain_service = os.environ.get("SWITCHGPT_KEYCHAIN_SERVICE", "switchgpt")
        chatgpt_base_url = os.environ.get("SWITCHGPT_BASE_URL", "https://chatgpt.com")
        return cls(
            data_dir=data_dir,
            metadata_path=data_dir / "accounts.json",
            keychain_service=keychain_service,
            slot_count=slot_count,
            chatgpt_base_url=chatgpt_base_url,
            managed_profile_dir=data_dir / "playwright-profile",
            switch_history_path=data_dir / "switch-history.jsonl",
        )

    def describe_items(self) -> list[SettingsItem]:
        return [
            SettingsItem(
                name="data_dir",
                value=str(self.data_dir),
                category="runtime-state",
                secret=False,
                description="Base directory that stores SwitchGPT runtime files.",
            ),
            SettingsItem(
                name="metadata_path",
                value=str(self.metadata_path),
                category="runtime-state",
                secret=False,
                description="Non-secret account metadata persisted on disk.",
            ),
            SettingsItem(
                name="keychain_service",
                value=self.keychain_service,
                category="secret-store",
                secret=True,
                description="Keychain service name used to store account secrets.",
            ),
            SettingsItem(
                name="slot_count",
                value=str(self.slot_count),
                category="config",
                secret=False,
                description="Maximum number of account slots supported by the store.",
            ),
            SettingsItem(
                name="chatgpt_base_url",
                value=self.chatgpt_base_url,
                category="config",
                secret=False,
                description="Base URL used by the managed ChatGPT browser.",
            ),
            SettingsItem(
                name="managed_profile_dir",
                value=str(self.managed_profile_dir),
                category="runtime-state",
                secret=False,
                description="Playwright profile directory for the managed browser.",
            ),
            SettingsItem(
                name="switch_history_path",
                value=str(self.switch_history_path),
                category="runtime-state",
                secret=False,
                description="JSONL history of account switches on disk.",
            ),
        ]


def ensure_supported_platform() -> None:
    if platform.system() != "Darwin":
        raise UnsupportedPlatformError("switchgpt Phase 1 supports macOS only.")

from dataclasses import dataclass
import os
import platform
from pathlib import Path

from .errors import UnsupportedPlatformError


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
        data_dir = home / ".switchgpt"
        return cls(
            data_dir=data_dir,
            metadata_path=data_dir / "accounts.json",
            keychain_service="switchgpt",
            slot_count=3,
            chatgpt_base_url="https://chatgpt.com",
            managed_profile_dir=data_dir / "playwright-profile",
            switch_history_path=data_dir / "switch-history.jsonl",
        )


def ensure_supported_platform() -> None:
    if platform.system() != "Darwin":
        raise UnsupportedPlatformError("switchgpt Phase 1 supports macOS only.")

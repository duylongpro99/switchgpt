from dataclasses import dataclass
from pathlib import Path
import os
import platform

from .errors import UnsupportedPlatformError


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    metadata_path: Path
    keychain_service: str
    slot_count: int
    chatgpt_base_url: str

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
        )


def ensure_supported_platform() -> None:
    if platform.system() != "Darwin":
        raise UnsupportedPlatformError("switchgpt Phase 1 supports macOS only.")

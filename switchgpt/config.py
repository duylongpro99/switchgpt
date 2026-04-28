from dataclasses import dataclass
import os
import platform
from pathlib import Path

from .errors import UnsupportedPlatformError


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def get_env(name: str, default: str | None = None) -> str | None:
    if name in os.environ:
        return os.environ[name]
    dotenv_values = _read_dotenv(Path.cwd() / ".env")
    return dotenv_values.get(name, default)


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
    switch_history_path: Path
    codex_auth_file_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        home = Path(os.environ["HOME"])
        data_dir = Path(get_env("SWITCHGPT_HOME", str(home / ".switchgpt")) or str(home / ".switchgpt"))
        slot_count = int(get_env("SWITCHGPT_SLOT_COUNT", "3") or "3")
        keychain_service = get_env("SWITCHGPT_KEYCHAIN_SERVICE", "switchgpt") or "switchgpt"
        return cls(
            data_dir=data_dir,
            metadata_path=data_dir / "accounts.json",
            keychain_service=keychain_service,
            slot_count=slot_count,
            switch_history_path=data_dir / "switch-history.jsonl",
            codex_auth_file_path=Path(
                get_env("SWITCHGPT_CODEX_AUTH_PATH", str(home / ".codex" / "auth.json"))
                or str(home / ".codex" / "auth.json")
            ),
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
                name="switch_history_path",
                value=str(self.switch_history_path),
                category="runtime-state",
                secret=False,
                description="JSONL history of account switches on disk.",
            ),
            SettingsItem(
                name="codex_auth_file_path",
                value=str(self.codex_auth_file_path),
                category="runtime-state",
                secret=False,
                description="Codex auth JSON file used for file-backed session sync.",
            ),
        ]


def ensure_supported_platform() -> None:
    if platform.system() != "Darwin":
        raise UnsupportedPlatformError("switchgpt Phase 1 supports macOS only.")

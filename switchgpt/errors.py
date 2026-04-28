class SwitchGptError(Exception):
    """Base application error."""


class UnsupportedPlatformError(SwitchGptError):
    """Raised when the current OS is not supported."""


class AccountStoreError(SwitchGptError):
    """Raised when account metadata cannot be read or parsed."""


class SecretStoreError(SwitchGptError):
    """Raised when keychain secret data cannot be read or parsed."""


class SwitchError(SwitchGptError):
    """Raised when a manual switch cannot be completed."""


class SwitchHistoryError(SwitchGptError):
    """Raised when switch history cannot be parsed or read."""


class DoctorCheckError(SwitchGptError):
    """Raised when a bounded doctor check cannot complete normally."""


class CodexAuthSyncFailedError(SwitchGptError):
    """Raised when strict Codex auth sync cannot complete."""

    def __init__(self, message: str, *, failure_class: str | None = None) -> None:
        super().__init__(message)
        self.failure_class = failure_class

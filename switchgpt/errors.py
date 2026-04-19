class SwitchGptError(Exception):
    """Base application error."""


class UnsupportedPlatformError(SwitchGptError):
    """Raised when the current OS is not supported."""


class AccountStoreError(SwitchGptError):
    """Raised when account metadata cannot be read or parsed."""


class SecretStoreError(SwitchGptError):
    """Raised when keychain secret data cannot be read or parsed."""


class BrowserRegistrationError(SwitchGptError):
    """Raised when browser-based registration cannot verify or capture state."""


class ManagedBrowserError(SwitchGptError):
    """Raised when the managed Playwright runtime cannot be used."""


class SwitchError(SwitchGptError):
    """Raised when a manual switch cannot be completed."""


class SwitchHistoryError(SwitchGptError):
    """Raised when switch history cannot be parsed or read."""


class ReauthRequiredError(SwitchError):
    """Raised when an account can continue only after explicit reauthentication."""


class DoctorCheckError(SwitchGptError):
    """Raised when a bounded doctor check cannot complete normally."""


class CodexAuthSyncFailedError(SwitchGptError):
    """Raised when strict Codex auth sync cannot complete."""

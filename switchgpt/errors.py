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

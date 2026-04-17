from datetime import UTC, datetime

import pytest

from switchgpt.models import AccountRecord, AccountState
from switchgpt.errors import BrowserRegistrationError
from switchgpt.playwright_client import BrowserRegistrationClient
from switchgpt.registration import RegistrationResult, RegistrationService
from switchgpt.secret_store import SessionSecret


class FakeBrowserClient:
    def register(self) -> RegistrationResult:
        return RegistrationResult(
            email="account1@example.com",
            secret=SessionSecret(session_token="token-1", csrf_token="csrf-1"),
            captured_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        )


def test_add_registration_writes_secret_before_metadata(tmp_path) -> None:
    store = []

    class FakeSecretStore:
        def write(self, key, secret) -> None:
            store.append(("secret", key, secret.session_token))

    class FakeAccountStore:
        def next_empty_slot(self) -> int:
            return 0

        def save_record(self, record) -> None:
            store.append(("metadata", record.index, record.email))

    service = RegistrationService(FakeAccountStore(), FakeSecretStore(), FakeBrowserClient())
    service.add()
    assert store == [
        ("secret", "switchgpt_account_0", "token-1"),
        ("metadata", 0, "account1@example.com"),
    ]


def test_add_rolls_back_secret_when_metadata_write_fails(tmp_path) -> None:
    deleted = []

    class FakeSecretStore:
        def write(self, key, secret) -> None:
            return None

        def delete(self, key) -> None:
            deleted.append(key)

    class FakeAccountStore:
        def next_empty_slot(self) -> int:
            return 0

        def save_record(self, record) -> None:
            raise RuntimeError("disk failure")

    service = RegistrationService(FakeAccountStore(), FakeSecretStore(), FakeBrowserClient())
    with pytest.raises(RuntimeError):
        service.add()
    assert deleted == ["switchgpt_account_0"]


def test_add_keeps_metadata_error_when_cleanup_also_fails(tmp_path) -> None:
    deleted = []

    class FakeSecretStore:
        def write(self, key, secret) -> None:
            return None

        def delete(self, key) -> None:
            deleted.append(key)
            raise RuntimeError("cleanup failure")

    class FakeAccountStore:
        def next_empty_slot(self) -> int:
            return 0

        def save_record(self, record) -> None:
            raise RuntimeError("disk failure")

    service = RegistrationService(FakeAccountStore(), FakeSecretStore(), FakeBrowserClient())
    with pytest.raises(RuntimeError, match="disk failure"):
        service.add()
    assert deleted == ["switchgpt_account_0"]


def test_reauth_keeps_old_secret_when_browser_capture_fails() -> None:
    class FakeBrowserClient:
        def reauth(self, existing_email: str):
            raise RuntimeError("login cancelled")

    class FakeSecretStore:
        def __init__(self) -> None:
            self.values = {
                "switchgpt_account_0": SessionSecret(session_token="old", csrf_token="old")
            }

        def read(self, key):
            return self.values[key]

        def replace(self, key, secret):
            self.values[key] = secret

    class FakeAccountStore:
        def get_record(self, index: int) -> AccountRecord:
            return AccountRecord(
                index=0,
                email="account1@example.com",
                keychain_key="switchgpt_account_0",
                registered_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
                last_reauth_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
                last_validated_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
                status=AccountState.REGISTERED,
                last_error=None,
            )

        def save_record(self, record) -> None:
            raise AssertionError("save_record should not run when reauth capture fails")

    service = RegistrationService(FakeAccountStore(), FakeSecretStore(), FakeBrowserClient())
    with pytest.raises(RuntimeError):
        service.reauth(0)


def test_reauth_restores_old_secret_when_metadata_save_fails() -> None:
    class FakeBrowserClient:
        def reauth(self, existing_email: str) -> RegistrationResult:
            return RegistrationResult(
                email="account1@example.com",
                secret=SessionSecret(session_token="new", csrf_token="new"),
                captured_at=datetime(2026, 4, 16, 8, 45, tzinfo=UTC),
            )

    class FakeSecretStore:
        def __init__(self) -> None:
            self.values = {
                "switchgpt_account_0": SessionSecret(session_token="old", csrf_token="old")
            }

        def read(self, key):
            return self.values[key]

        def replace(self, key, secret):
            self.values[key] = secret

    class FakeAccountStore:
        def get_record(self, index: int) -> AccountRecord:
            return AccountRecord(
                index=0,
                email="account1@example.com",
                keychain_key="switchgpt_account_0",
                registered_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
                last_reauth_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
                last_validated_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
                status=AccountState.REGISTERED,
                last_error=None,
            )

        def save_record(self, record) -> None:
            raise RuntimeError("disk failure")

    service = RegistrationService(FakeAccountStore(), FakeSecretStore(), FakeBrowserClient())
    with pytest.raises(RuntimeError, match="disk failure"):
        service.reauth(0)
    assert service._secret_store.values["switchgpt_account_0"] == SessionSecret(
        session_token="old",
        csrf_token="old",
    )


def test_browser_client_requires_visible_browser_when_register_called() -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")
    with pytest.raises(RuntimeError):
        client._assert_visible_mode(headless=True)


def test_browser_client_rejects_ambiguous_authenticated_state() -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")

    class FakeBody:
        def inner_text(self) -> str:
            return "Please log in"

    class FakePage:
        url = "https://chatgpt.com/login"

        def locator(self, selector: str):
            assert selector == "body"
            return FakeBody()

    with pytest.raises(BrowserRegistrationError, match="Could not verify authenticated state"):
        client._assert_authenticated_state(FakePage())


def test_browser_client_raises_controlled_error_when_session_cookie_is_missing() -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")

    with pytest.raises(BrowserRegistrationError, match="__Secure-next-auth.session-token"):
        client._require_cookie_value([], "__Secure-next-auth.session-token")


def test_browser_client_uses_discovered_email_when_available(monkeypatch) -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")

    class FakeBody:
        def inner_text(self) -> str:
            return "ChatGPT signed in as ACCOUNT1@EXAMPLE.COM"

    class FakePage:
        url = "https://chatgpt.com/"

        def goto(self, url: str) -> None:
            self.url = url

        def locator(self, selector: str):
            assert selector == "body"
            return FakeBody()

    class FakeContext:
        def __init__(self) -> None:
            self._page = FakePage()

        def new_page(self):
            return self._page

        def cookies(self):
            return [
                {"name": "__Secure-next-auth.session-token", "value": "token-1"},
                {"name": "__Host-next-auth.csrf-token", "value": "csrf-1"},
            ]

    class FakeBrowser:
        def __init__(self) -> None:
            self.context = FakeContext()

        def new_context(self):
            return self.context

        def close(self) -> None:
            return None

    class FakeChromium:
        def __init__(self) -> None:
            self.browser = FakeBrowser()

        def launch(self, headless: bool):
            assert headless is False
            return self.browser

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("builtins.input", lambda prompt="": None)
    monkeypatch.setattr("switchgpt.playwright_client.sync_playwright", lambda: FakePlaywright())

    result = client.register()

    assert result.email == "account1@example.com"


def test_browser_client_registers_and_closes_browser_after_email_capture(monkeypatch) -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")
    events: list[str] = []

    class FakeBody:
        def inner_text(self) -> str:
            events.append("body_text")
            return "ChatGPT signed in as ACCOUNT1@EXAMPLE.COM"

    class FakePage:
        url = "https://chatgpt.com/"

        def goto(self, url: str) -> None:
            events.append(f"goto:{url}")

        def locator(self, selector: str):
            assert selector == "body"
            return FakeBody()

    class FakeContext:
        def __init__(self) -> None:
            self._page = FakePage()

        def new_page(self):
            events.append("new_page")
            return self._page

        def cookies(self):
            events.append("cookies")
            return [
                {"name": "__Secure-next-auth.session-token", "value": "token-1"},
                {"name": "__Host-next-auth.csrf-token", "value": "csrf-1"},
            ]

    class FakeBrowser:
        def __init__(self) -> None:
            self.context = FakeContext()

        def new_context(self):
            events.append("new_context")
            return self.context

        def close(self) -> None:
            events.append("close")

    class FakeChromium:
        def __init__(self) -> None:
            self.browser = FakeBrowser()

        def launch(self, headless: bool):
            assert headless is False
            events.append("launch")
            return self.browser

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = FakeChromium()

        def __enter__(self):
            events.append("enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            events.append("exit")
            return False

    monkeypatch.setattr("builtins.input", lambda prompt="": events.append("input"))
    monkeypatch.setattr("switchgpt.playwright_client.sync_playwright", lambda: FakePlaywright())

    result = client.register()

    assert result.email == "account1@example.com"
    assert events == [
        "enter",
        "launch",
        "new_context",
        "new_page",
        "goto:https://chatgpt.com",
        "input",
        "body_text",
        "cookies",
        "body_text",
        "close",
        "exit",
    ]


def test_browser_client_closes_browser_when_registration_fails(monkeypatch) -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")
    events: list[str] = []

    class FakePage:
        url = "https://chatgpt.com/login"

        def goto(self, url: str) -> None:
            events.append(f"goto:{url}")

        def locator(self, selector: str):
            events.append(f"locator:{selector}")

            class FakeBody:
                def inner_text(self) -> str:
                    return "Please log in"

            return FakeBody()

    class FakeContext:
        def new_page(self):
            events.append("new_page")
            return FakePage()

        def cookies(self):
            events.append("cookies")
            return []

    class FakeBrowser:
        def new_context(self):
            events.append("new_context")
            return FakeContext()

        def close(self) -> None:
            events.append("close")

    class FakeChromium:
        def launch(self, headless: bool):
            assert headless is False
            events.append("launch")
            return FakeBrowser()

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = FakeChromium()

        def __enter__(self):
            events.append("enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            events.append("exit")
            return False

    monkeypatch.setattr("builtins.input", lambda prompt="": events.append("input"))
    monkeypatch.setattr("switchgpt.playwright_client.sync_playwright", lambda: FakePlaywright())

    with pytest.raises(BrowserRegistrationError, match="Could not verify authenticated state"):
        client.register()

    assert "close" in events
    assert events.index("close") < events.index("exit")

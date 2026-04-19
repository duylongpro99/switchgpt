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


def test_reauth_in_managed_workspace_refreshes_secret_and_metadata() -> None:
    page = object()
    existing = AccountRecord(
        index=0,
        email="account0@example.com",
        keychain_key="switchgpt_account_0",
        registered_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_reauth_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        last_validated_at=datetime(2026, 4, 16, 8, 30, tzinfo=UTC),
        status=AccountState.NEEDS_REAUTH,
        last_error="expired session",
    )

    class FakeBrowserClient:
        def capture_existing_session(self, page_arg, *, existing_email: str) -> RegistrationResult:
            assert page_arg is page
            assert existing_email == "account0@example.com"
            return RegistrationResult(
                email=existing_email,
                secret=SessionSecret(session_token="new-token", csrf_token="csrf"),
                captured_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
            )

    class FakeAccountStore:
        def __init__(self) -> None:
            self.saved = None

        def get_record(self, index: int) -> AccountRecord:
            assert index == 0
            return existing

        def save_record(self, record) -> None:
            self.saved = record

    class FakeSecretStore:
        def __init__(self) -> None:
            self.replaced = None

        def read(self, key: str):
            assert key == "switchgpt_account_0"
            return SessionSecret(session_token="old-token", csrf_token=None)

        def replace(self, key: str, secret: SessionSecret) -> None:
            self.replaced = (key, secret)

    account_store = FakeAccountStore()
    secret_store = FakeSecretStore()
    service = RegistrationService(account_store, secret_store, FakeBrowserClient())

    record = service.reauth_in_managed_workspace(index=0, page=page)

    assert secret_store.replaced == (
        "switchgpt_account_0",
        SessionSecret(session_token="new-token", csrf_token="csrf"),
    )
    assert account_store.saved == record
    assert record.status is AccountState.REGISTERED
    assert record.last_error is None
    assert record.last_reauth_at == datetime(2026, 4, 17, 12, 0, tzinfo=UTC)


def test_reauth_in_managed_workspace_restores_old_secret_when_metadata_save_fails() -> None:
    page = object()

    class FakeBrowserClient:
        def capture_existing_session(self, page_arg, *, existing_email: str) -> RegistrationResult:
            assert page_arg is page
            return RegistrationResult(
                email=existing_email,
                secret=SessionSecret(session_token="new", csrf_token="new"),
                captured_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
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
                status=AccountState.NEEDS_REAUTH,
                last_error="expired session",
            )

        def save_record(self, record) -> None:
            raise RuntimeError("disk failure")

    service = RegistrationService(FakeAccountStore(), FakeSecretStore(), FakeBrowserClient())

    with pytest.raises(RuntimeError, match="disk failure"):
        service.reauth_in_managed_workspace(index=0, page=page)

    assert service._secret_store.values["switchgpt_account_0"] == SessionSecret(
        session_token="old",
        csrf_token="old",
    )


def test_add_in_managed_workspace_writes_secret_and_metadata() -> None:
    page = object()

    class FakeBrowserClient:
        def capture_existing_session(self, page_arg, *, existing_email: str) -> RegistrationResult:
            assert page_arg is page
            assert existing_email == "unknown@example.com"
            return RegistrationResult(
                email="account1@example.com",
                secret=SessionSecret(session_token="token-1", csrf_token="csrf-1"),
                captured_at=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
            )

    class FakeSecretStore:
        def __init__(self) -> None:
            self.writes = []

        def write(self, key, secret) -> None:
            self.writes.append((key, secret))

    class FakeAccountStore:
        def __init__(self) -> None:
            self.saved = None

        def next_empty_slot(self) -> int:
            return 1

        def save_record(self, record) -> None:
            self.saved = record

    account_store = FakeAccountStore()
    secret_store = FakeSecretStore()
    service = RegistrationService(account_store, secret_store, FakeBrowserClient())

    record = service.add_in_managed_workspace(page=page)

    assert record.index == 1
    assert record.email == "account1@example.com"
    assert secret_store.writes == [
        ("switchgpt_account_1", SessionSecret(session_token="token-1", csrf_token="csrf-1"))
    ]
    assert account_store.saved == record


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
        "cookies",
        "body_text",
        "body_text",
        "close",
        "exit",
    ]


def test_browser_client_register_rejects_auth_error_route_without_verified_session(
    monkeypatch,
) -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")

    class FakeBody:
        def inner_text(self) -> str:
            return "Please log in"

    class FakePage:
        url = "https://chatgpt.com/auth/error"

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

    with pytest.raises(BrowserRegistrationError, match="Could not verify authenticated state"):
        client.register()


def test_browser_client_capture_existing_session_uses_session_api_email_when_body_has_none() -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")

    class FakeBody:
        def inner_text(self) -> str:
            return "Welcome back"

    class FakePage:
        url = "https://chatgpt.com/"

        def locator(self, selector: str):
            assert selector == "body"
            return FakeBody()

        def evaluate(self, script: str):
            assert "/api/auth/session" in script
            return {"user": {"email": "Account1@Example.com"}}

    class FakeContext:
        def cookies(self):
            return [
                {"name": "__Secure-next-auth.session-token", "value": "token-1"},
                {"name": "__Host-next-auth.csrf-token", "value": "csrf-1"},
            ]

    page = FakePage()
    page.context = FakeContext()

    result = client.capture_existing_session(page, existing_email="unknown@example.com")

    assert result.email == "account1@example.com"


def test_browser_client_register_retries_capture_when_auth_error_route_persists(monkeypatch) -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")
    events: list[str] = []

    class FakeBody:
        def inner_text(self) -> str:
            events.append("body_text")
            return "Please log in"

    class FakePage:
        url = "https://chatgpt.com/api/auth/error"
        _goto_calls = 0

        def goto(self, url: str) -> None:
            events.append(f"goto:{url}")
            self._goto_calls += 1
            if url == "https://chatgpt.com":
                if self._goto_calls == 1:
                    # First navigation still lands in auth error.
                    self.url = "https://chatgpt.com/api/auth/error"
                else:
                    # Recovery navigation succeeds.
                    self.url = "https://chatgpt.com/"

        def wait_for_timeout(self, ms: int) -> None:
            events.append(f"wait:{ms}")

        def evaluate(self, script: str):
            assert "/api/auth/session" in script
            if self.url == "https://chatgpt.com/":
                return {"user": {"email": "account1@example.com"}}
            return None

        def locator(self, selector: str):
            assert selector == "body"
            return FakeBody()

    class FakeContext:
        def __init__(self) -> None:
            self._page = FakePage()
            self._cookies_calls = 0

        def new_page(self):
            return self._page

        def cookies(self):
            self._cookies_calls += 1
            events.append(f"cookies:{self._cookies_calls}")
            if self._cookies_calls == 1:
                return []
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
            events.append("close")

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

    monkeypatch.setattr("builtins.input", lambda prompt="": events.append("input"))
    monkeypatch.setattr("switchgpt.playwright_client.sync_playwright", lambda: FakePlaywright())

    result = client.register()

    assert result.secret.session_token == "token-1"
    assert events == [
        "goto:https://chatgpt.com",
        "input",
        "cookies:1",
        "goto:https://chatgpt.com",
        "wait:1000",
        "cookies:2",
        "close",
    ]


def test_browser_client_register_prompts_again_when_auth_error_persists_after_retries(
    monkeypatch,
) -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")
    events: list[str] = []

    class FakeBody:
        def inner_text(self) -> str:
            events.append("body_text")
            return "ChatGPT signed in as account1@example.com"

    class FakePage:
        url = "https://chatgpt.com/api/auth/error"

        def goto(self, url: str) -> None:
            events.append(f"goto:{url}")
            if url == "https://chatgpt.com":
                self.url = "https://chatgpt.com/api/auth/error"

        def wait_for_timeout(self, ms: int) -> None:
            events.append(f"wait:{ms}")

        def locator(self, selector: str):
            assert selector == "body"
            return FakeBody()

    class FakeContext:
        def __init__(self) -> None:
            self._page = FakePage()
            self._cookies_calls = 0

        def new_page(self):
            return self._page

        def cookies(self):
            self._cookies_calls += 1
            events.append(f"cookies:{self._cookies_calls}")
            # The first capture round fails entirely, then a second manual attempt succeeds.
            if self._cookies_calls <= 3:
                return []
            self._page.url = "https://chatgpt.com/"
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
            events.append("close")

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

    monkeypatch.setattr("builtins.input", lambda prompt="": events.append("input"))
    monkeypatch.setattr("switchgpt.playwright_client.sync_playwright", lambda: FakePlaywright())

    result = client.register()

    assert result.secret.session_token == "token-1"
    assert events.count("input") == 2


def test_browser_client_register_prompts_again_when_first_round_has_no_session_cookie(
    monkeypatch,
) -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")
    events: list[str] = []

    class FakeBody:
        def inner_text(self) -> str:
            events.append("body_text")
            return "ChatGPT signed in as account1@example.com"

    class FakePage:
        url = "https://chatgpt.com/"

        def goto(self, url: str) -> None:
            events.append(f"goto:{url}")
            self.url = "https://chatgpt.com/"

        def wait_for_timeout(self, ms: int) -> None:
            events.append(f"wait:{ms}")

        def locator(self, selector: str):
            assert selector == "body"
            return FakeBody()

    class FakeContext:
        def __init__(self) -> None:
            self._page = FakePage()
            self._cookies_calls = 0

        def new_page(self):
            return self._page

        def cookies(self):
            self._cookies_calls += 1
            events.append(f"cookies:{self._cookies_calls}")
            # Round 1 (3 tries): no session cookie; round 2: session cookie appears.
            if self._cookies_calls <= 3:
                return [{"name": "__Host-next-auth.csrf-token", "value": "csrf-1"}]
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
            events.append("close")

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

    monkeypatch.setattr("builtins.input", lambda prompt="": events.append("input"))
    monkeypatch.setattr("switchgpt.playwright_client.sync_playwright", lambda: FakePlaywright())

    result = client.register()

    assert result.secret.session_token == "token-1"
    assert events.count("input") == 2


def test_browser_client_register_recreates_context_after_auth_error_round(monkeypatch) -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")
    events: list[str] = []

    class FakeBody:
        def __init__(self, text: str, events: list[str]) -> None:
            self._text = text
            self._events = events

        def inner_text(self) -> str:
            self._events.append("body_text")
            return self._text

    class FakePage:
        def __init__(self, context_id: int, events: list[str], auth_error: bool) -> None:
            self._context_id = context_id
            self._events = events
            self.url = "https://chatgpt.com/api/auth/error" if auth_error else "https://chatgpt.com/"
            self._auth_error = auth_error

        def goto(self, url: str) -> None:
            self._events.append(f"goto:ctx{self._context_id}:{url}")
            if url == "https://chatgpt.com" and self._auth_error:
                self.url = "https://chatgpt.com/api/auth/error"
            elif url == "https://chatgpt.com":
                self.url = "https://chatgpt.com/"

        def wait_for_timeout(self, ms: int) -> None:
            self._events.append(f"wait:ctx{self._context_id}:{ms}")

        def locator(self, selector: str):
            assert selector == "body"
            text = "Please log in" if self._auth_error else "ChatGPT signed in as account1@example.com"
            return FakeBody(text, self._events)

    class FakeContext:
        def __init__(self, context_id: int, events: list[str], auth_error: bool) -> None:
            self._context_id = context_id
            self._events = events
            self._page = FakePage(context_id, events, auth_error)
            self._auth_error = auth_error
            self.closed = False

        def new_page(self):
            self._events.append(f"new_page:ctx{self._context_id}")
            return self._page

        def cookies(self):
            self._events.append(f"cookies:ctx{self._context_id}")
            if self._auth_error:
                return []
            return [
                {"name": "__Secure-next-auth.session-token", "value": "token-1"},
                {"name": "__Host-next-auth.csrf-token", "value": "csrf-1"},
            ]

        def close(self) -> None:
            self.closed = True
            self._events.append(f"close_context:ctx{self._context_id}")

    class FakeBrowser:
        def __init__(self) -> None:
            self._context_count = 0

        def new_context(self):
            self._context_count += 1
            events.append(f"new_context:ctx{self._context_count}")
            # First context is stuck on auth error; second context succeeds.
            return FakeContext(
                context_id=self._context_count,
                events=events,
                auth_error=self._context_count == 1,
            )

        def close(self) -> None:
            events.append("close_browser")

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

    monkeypatch.setattr("builtins.input", lambda prompt="": events.append("input"))
    monkeypatch.setattr("switchgpt.playwright_client.sync_playwright", lambda: FakePlaywright())

    result = client.register()

    assert result.secret.session_token == "token-1"
    assert "new_context:ctx1" in events
    assert "close_context:ctx1" in events
    assert "new_context:ctx2" in events


def test_browser_client_register_uses_configured_browser_channel(monkeypatch) -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")
    launch_kwargs: dict[str, object] = {}

    class FakeBody:
        def inner_text(self) -> str:
            return "ChatGPT signed in as account1@example.com"

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
        def new_context(self):
            return FakeContext()

        def close(self) -> None:
            return None

    class FakeChromium:
        def launch(self, **kwargs):
            launch_kwargs.update(kwargs)
            return FakeBrowser()

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setenv("SWITCHGPT_BROWSER_CHANNEL", "chrome")
    monkeypatch.setattr("builtins.input", lambda prompt="": None)
    monkeypatch.setattr("switchgpt.playwright_client.sync_playwright", lambda: FakePlaywright())

    result = client.register()

    assert result.secret.session_token == "token-1"
    assert launch_kwargs == {"headless": False, "channel": "chrome"}


def test_browser_client_register_falls_back_to_default_launch_when_channel_unavailable(
    monkeypatch,
) -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")
    launch_attempts: list[dict[str, object]] = []

    class FakeBody:
        def inner_text(self) -> str:
            return "ChatGPT signed in as account1@example.com"

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
        def new_context(self):
            return FakeContext()

        def close(self) -> None:
            return None

    class FakeChromium:
        def launch(self, **kwargs):
            launch_attempts.append(kwargs.copy())
            if kwargs.get("channel") == "chrome":
                raise RuntimeError("channel unavailable")
            return FakeBrowser()

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setenv("SWITCHGPT_BROWSER_CHANNEL", "chrome")
    monkeypatch.setattr("builtins.input", lambda prompt="": None)
    monkeypatch.setattr("switchgpt.playwright_client.sync_playwright", lambda: FakePlaywright())

    result = client.register()

    assert result.secret.session_token == "token-1"
    assert launch_attempts == [
        {"headless": False, "channel": "chrome"},
        {"headless": False},
    ]


def test_browser_client_register_uses_persistent_context_when_profile_dir_is_configured(
    monkeypatch,
    tmp_path,
) -> None:
    profile_dir = tmp_path / "managed-profile"
    client = BrowserRegistrationClient(
        base_url="https://chatgpt.com",
        profile_dir=profile_dir,
    )
    events: list[str] = []
    launch_args: dict[str, object] = {}

    class FakeBody:
        def inner_text(self) -> str:
            return "ChatGPT signed in as account1@example.com"

    class FakePage:
        url = "https://chatgpt.com/"

        def goto(self, url: str) -> None:
            events.append(f"goto:{url}")
            self.url = url

        def locator(self, selector: str):
            assert selector == "body"
            return FakeBody()

    class FakePersistentContext:
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

        def close(self) -> None:
            events.append("close_context")

    class FakeChromium:
        def launch(self, **kwargs):
            raise AssertionError("register() should use launch_persistent_context when profile_dir is set")

        def launch_persistent_context(self, user_data_dir: str, **kwargs):
            events.append("launch_persistent_context")
            launch_args["user_data_dir"] = user_data_dir
            launch_args.update(kwargs)
            return FakePersistentContext()

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("builtins.input", lambda prompt="": events.append("input"))
    monkeypatch.setattr("switchgpt.playwright_client.sync_playwright", lambda: FakePlaywright())

    result = client.register()

    assert result.secret.session_token == "token-1"
    assert profile_dir.exists()
    assert launch_args == {
        "user_data_dir": str(profile_dir),
        "headless": False,
        "channel": "chrome",
    }
    assert events == [
        "launch_persistent_context",
        "new_page",
        "goto:https://chatgpt.com",
        "input",
        "cookies",
        "close_context",
    ]


def test_browser_client_register_applies_stealth_launch_flags_when_enabled(monkeypatch) -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")
    launch_kwargs: dict[str, object] = {}

    class FakeBody:
        def inner_text(self) -> str:
            return "ChatGPT signed in as account1@example.com"

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
            self.scripts: list[str] = []

        def new_page(self):
            return self._page

        def cookies(self):
            return [
                {"name": "__Secure-next-auth.session-token", "value": "token-1"},
            ]

        def add_init_script(self, script: str) -> None:
            self.scripts.append(script)

    class FakeBrowser:
        def __init__(self) -> None:
            self.context = FakeContext()

        def new_context(self):
            return self.context

        def close(self) -> None:
            return None

    class FakeChromium:
        def launch(self, **kwargs):
            launch_kwargs.update(kwargs)
            return FakeBrowser()

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setenv("SWITCHGPT_BROWSER_STEALTH", "1")
    monkeypatch.setattr("builtins.input", lambda prompt="": None)
    monkeypatch.setattr("switchgpt.playwright_client.sync_playwright", lambda: FakePlaywright())

    result = client.register()

    assert result.secret.session_token == "token-1"
    assert launch_kwargs["ignore_default_args"] == ["--enable-automation"]
    assert launch_kwargs["args"] == ["--disable-blink-features=AutomationControlled"]


def test_browser_client_candidate_channels_reads_from_dotenv(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SWITCHGPT_BROWSER_CHANNEL", raising=False)
    (tmp_path / ".env").write_text("SWITCHGPT_BROWSER_CHANNEL=msedge\n", encoding="utf-8")
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")

    assert client._candidate_channels() == ["msedge", "chrome", None]


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


def test_browser_client_closes_browser_when_opening_context_fails(monkeypatch) -> None:
    client = BrowserRegistrationClient(base_url="https://chatgpt.com")
    events: list[str] = []

    class FakeBrowser:
        def new_context(self):
            events.append("new_context")
            raise RuntimeError("context failed")

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

    monkeypatch.setattr("switchgpt.playwright_client.sync_playwright", lambda: FakePlaywright())

    with pytest.raises(RuntimeError, match="context failed"):
        client.register()

    assert "close" in events
    assert events.index("close") < events.index("exit")

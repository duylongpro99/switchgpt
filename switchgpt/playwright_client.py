from dataclasses import dataclass
from datetime import UTC, datetime
import re

from playwright.sync_api import sync_playwright

from .errors import BrowserRegistrationError
from .registration import RegistrationResult
from .secret_store import SessionSecret


_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


@dataclass(frozen=True)
class BrowserRegistrationClient:
    base_url: str

    def _assert_visible_mode(self, headless: bool) -> None:
        if headless:
            raise RuntimeError("Phase 1 registration requires a visible browser window.")

    def _assert_authenticated_state(self, page) -> None:
        url = getattr(page, "url", "")
        if self._looks_like_login_url(url):
            raise BrowserRegistrationError(
                "Could not verify authenticated state after login."
            )

        body_text = self._page_body_text(page).lower()
        if "sign in" in body_text or "log in" in body_text or "login" in body_text:
            raise BrowserRegistrationError(
                "Could not verify authenticated state after login."
            )

        if "chatgpt" not in body_text and "open sidebar" not in body_text:
            raise BrowserRegistrationError(
                "Could not verify authenticated state after login."
            )

    def _require_cookie_value(self, cookies, cookie_name: str) -> str:
        for cookie in cookies:
            if cookie.get("name") == cookie_name:
                value = cookie.get("value")
                if type(value) is str:
                    return value
                break
        raise BrowserRegistrationError(f"Required session cookie {cookie_name!r} was not found.")

    def _optional_cookie_value(self, cookies, cookie_name: str) -> str | None:
        for cookie in cookies:
            if cookie.get("name") == cookie_name:
                value = cookie.get("value")
                return value if type(value) is str else None
        return None

    def _discover_email(self, page) -> str | None:
        body_text = self._page_body_text(page)
        match = _EMAIL_PATTERN.search(body_text)
        if match is None:
            return None
        return self._normalize_email(match.group(0))

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()

    def _page_body_text(self, page) -> str:
        locator = page.locator("body")
        return locator.inner_text()

    def _looks_like_login_url(self, url: str) -> bool:
        lowered = url.lower()
        return any(marker in lowered for marker in ("/login", "/signin", "/auth"))

    def register(self) -> RegistrationResult:
        self._assert_visible_mode(headless=False)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=False)
            try:
                context = browser.new_context()
                page = context.new_page()
                page.goto(self.base_url)
                input("[switchgpt] Complete login in the browser, then press ENTER here.")
                self._assert_authenticated_state(page)
                cookies = context.cookies()
                session_token = self._require_cookie_value(
                    cookies, "__Secure-next-auth.session-token"
                )
                csrf_cookie = self._optional_cookie_value(
                    cookies, "__Host-next-auth.csrf-token"
                )
                email = self._discover_email(page) or "unknown@example.com"
                return RegistrationResult(
                    email=email,
                    secret=SessionSecret(
                        session_token=session_token,
                        csrf_token=csrf_cookie,
                    ),
                    captured_at=datetime.now(UTC),
                )
            finally:
                browser.close()

    def reauth(self, existing_email: str) -> RegistrationResult:
        return self.register()

    def capture_existing_session(self, page, *, existing_email: str) -> RegistrationResult:
        self._assert_authenticated_state(page)
        context = page.context
        cookies = context.cookies()
        session_token = self._require_cookie_value(
            cookies, "__Secure-next-auth.session-token"
        )
        csrf_cookie = self._optional_cookie_value(
            cookies, "__Host-next-auth.csrf-token"
        )
        email = self._discover_email(page) or self._normalize_email(existing_email)
        return RegistrationResult(
            email=email,
            secret=SessionSecret(
                session_token=session_token,
                csrf_token=csrf_cookie,
            ),
            captured_at=datetime.now(UTC),
        )

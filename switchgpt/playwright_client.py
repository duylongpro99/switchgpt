from dataclasses import dataclass
from datetime import UTC, datetime
import json
import sys
import re
from pathlib import Path
import base64

from playwright.sync_api import sync_playwright

from .config import get_env
from .errors import BrowserRegistrationError
from .registration import RegistrationResult
from .secret_store import SessionSecret


_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MAX_REGISTRATION_CAPTURE_ATTEMPTS = 3
CAPTURE_RETRY_WAIT_MS = 1000
MAX_MANUAL_LOGIN_ATTEMPTS = 2
INITIAL_LOGIN_PROMPT = "[switchgpt] Complete login in the browser, then press ENTER here."
AUTH_ERROR_RETRY_PROMPT = (
    "[switchgpt] Login reached an authentication error page. "
    "Retry login in the browser (including any human verification), then press ENTER here."
)
DEFAULT_BROWSER_CHANNEL = "chrome"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_UNKNOWN_EMAIL = "unknown@example.com"


@dataclass(frozen=True)
class BrowserRegistrationClient:
    base_url: str
    profile_dir: Path | None = None
    codex_auth_file_path: Path | None = None

    def _candidate_channels(self) -> list[str | None]:
        configured = (get_env("SWITCHGPT_BROWSER_CHANNEL", "") or "").strip()
        if configured:
            channels: list[str | None] = [configured]
            if configured != DEFAULT_BROWSER_CHANNEL:
                channels.append(DEFAULT_BROWSER_CHANNEL)
            channels.append(None)
            return channels
        return [DEFAULT_BROWSER_CHANNEL, None]

    def _is_stealth_enabled(self) -> bool:
        value = get_env("SWITCHGPT_BROWSER_STEALTH", "") or ""
        normalized = value.strip().lower()
        if not normalized:
            return True
        if normalized in _FALSE_VALUES:
            return False
        return normalized in _TRUE_VALUES

    def _stealth_launch_kwargs(self) -> dict[str, object]:
        if not self._is_stealth_enabled():
            return {}
        return {
            "ignore_default_args": ["--enable-automation"],
            "args": ["--disable-blink-features=AutomationControlled"],
        }

    def _apply_stealth_context_overrides(self, context) -> None:
        if not self._is_stealth_enabled():
            return
        adder = getattr(context, "add_init_script", None)
        if callable(adder):
            try:
                adder(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
            except Exception:
                pass

    def _launch_browser(self, playwright):
        last_exc = None
        for channel in self._candidate_channels():
            launch_kwargs = {"headless": False}
            launch_kwargs.update(self._stealth_launch_kwargs())
            if channel is not None:
                launch_kwargs["channel"] = channel
            try:
                return playwright.chromium.launch(**launch_kwargs)
            except Exception as exc:
                last_exc = exc
        raise BrowserRegistrationError("Unable to launch browser registration context.") from last_exc

    def _launch_persistent_context(self, playwright):
        if self.profile_dir is None:
            raise BrowserRegistrationError("Managed profile directory is required for persistent registration.")

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        last_exc = None
        for channel in self._candidate_channels():
            launch_kwargs = {"headless": False}
            launch_kwargs.update(self._stealth_launch_kwargs())
            if channel is not None:
                launch_kwargs["channel"] = channel
            try:
                return playwright.chromium.launch_persistent_context(
                    str(self.profile_dir),
                    **launch_kwargs,
                )
            except Exception as exc:
                last_exc = exc
        raise BrowserRegistrationError("Unable to launch browser registration context.") from last_exc

    def _open_registration_context(self, playwright, browser):
        if self.profile_dir is not None:
            return self._launch_persistent_context(playwright)
        if browser is None:
            raise BrowserRegistrationError("Unable to launch browser registration context.")
        return browser.new_context()

    def _is_debug_auth_enabled(self) -> bool:
        value = get_env("SWITCHGPT_DEBUG_AUTH", "") or ""
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _emit_auth_debug(
        self,
        *,
        stage: str,
        manual_attempt: int,
        capture_attempt: int | None,
        page,
        cookies,
    ) -> None:
        if not self._is_debug_auth_enabled():
            return
        url = getattr(page, "url", "")
        has_session_cookie = self._has_session_cookie(cookies)
        cookie_names = sorted(
            cookie.get("name")
            for cookie in cookies
            if type(cookie.get("name")) is str
        )
        capture_label = "-" if capture_attempt is None else str(capture_attempt)
        print(
            "[switchgpt][debug-auth] "
            f"stage={stage} "
            f"manual_attempt={manual_attempt}/{MAX_MANUAL_LOGIN_ATTEMPTS} "
            f"capture_attempt={capture_label}/{MAX_REGISTRATION_CAPTURE_ATTEMPTS} "
            f"url={url!r} "
            f"auth_error={self._looks_like_auth_error_url(url)} "
            f"has_session_cookie={has_session_cookie} "
            f"cookies={cookie_names}",
            file=sys.stderr,
            flush=True,
        )

    def _assert_visible_mode(self, headless: bool) -> None:
        if headless:
            raise RuntimeError("Phase 1 registration requires a visible browser window.")

    def _has_session_cookie(self, cookies) -> bool:
        for cookie in cookies:
            if cookie.get("name") == "__Secure-next-auth.session-token":
                value = cookie.get("value")
                if type(value) is str and value:
                    return True
                break
        return False

    def _assert_authenticated_state(self, page, *, cookies=None) -> None:
        if (
            cookies is not None
            and self._has_session_cookie(cookies)
            and self._has_verified_session(page)
        ):
            return

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
        session_email = self._session_email(page)
        if session_email is not None:
            return session_email
        body_text = self._page_body_text(page)
        match = _EMAIL_PATTERN.search(body_text)
        if match is None:
            return None
        return self._normalize_email(match.group(0))

    def _session_payload(self, page) -> dict | None:
        evaluator = getattr(page, "evaluate", None)
        if not callable(evaluator):
            return None
        try:
            payload = evaluator(
                """
                async () => {
                    try {
                        const response = await fetch("/api/auth/session", {
                            credentials: "include",
                        });
                        if (!response.ok) return null;
                        return await response.json();
                    } catch {
                        return null;
                    }
                }
                """
            )
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _has_verified_session(self, page) -> bool:
        payload = self._session_payload(page)
        if payload is None:
            return False
        user = payload.get("user")
        return isinstance(user, dict)

    def _session_email(self, page) -> str | None:
        payload = self._session_payload(page)
        if payload is None:
            return None
        user = payload.get("user")
        if not isinstance(user, dict):
            return None
        email = user.get("email")
        if type(email) is not str or not email.strip():
            return None
        return self._normalize_email(email)

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()

    def _is_unknown_email(self, email: str | None) -> bool:
        if type(email) is not str:
            return True
        return self._normalize_email(email) == _UNKNOWN_EMAIL

    def _load_codex_auth_identity(self) -> tuple[str, dict[str, object]] | None:
        auth_file_path = self.codex_auth_file_path
        if auth_file_path is None or not auth_file_path.exists():
            return None
        try:
            payload = json.loads(auth_file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        tokens = payload.get("tokens")
        if not isinstance(tokens, dict):
            return None
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        id_token = tokens.get("id_token")
        account_id = tokens.get("account_id")
        if not all(
            type(value) is str and value
            for value in (access_token, refresh_token, id_token, account_id)
        ):
            return None
        token_email = self._email_from_id_token(id_token)
        if token_email is None:
            return None
        return (
            token_email,
            payload,
        )

    def _resolve_registration_email(self, *, page, existing_email: str) -> str:
        discovered_email = self._discover_email(page)
        if discovered_email is not None:
            return discovered_email
        if not self._is_unknown_email(existing_email):
            return self._normalize_email(existing_email)
        resolved = self._load_codex_auth_identity()
        if resolved is not None:
            return resolved[0]
        return self._normalize_email(existing_email)

    def _email_from_id_token(self, id_token: str) -> str | None:
        if "." not in id_token:
            return None
        try:
            payload_segment = id_token.split(".")[1]
            payload_segment += "=" * (-len(payload_segment) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_segment))
        except (ValueError, json.JSONDecodeError):
            return None
        email = payload.get("email")
        if type(email) is not str or not email.strip():
            return None
        return self._normalize_email(email)

    def _page_body_text(self, page) -> str:
        locator = page.locator("body")
        return locator.inner_text()

    def _looks_like_login_url(self, url: str) -> bool:
        lowered = url.lower()
        return any(marker in lowered for marker in ("/login", "/signin", "/auth"))

    def _looks_like_auth_error_url(self, url: str) -> bool:
        lowered = url.lower()
        return "/auth/error" in lowered or "/api/auth/error" in lowered

    def _recover_from_auth_error(self, page) -> None:
        if not self._looks_like_auth_error_url(getattr(page, "url", "")):
            return
        try:
            page.goto(self.base_url)
        except Exception:
            return

    def register(self) -> RegistrationResult:
        self._assert_visible_mode(headless=False)
        with sync_playwright() as playwright:
            browser = None
            context = None
            try:
                browser = None if self.profile_dir is not None else self._launch_browser(playwright)
                context = self._open_registration_context(playwright, browser)
                self._apply_stealth_context_overrides(context)
                page = context.new_page()
                page.goto(self.base_url)
                last_error = None
                for manual_attempt in range(MAX_MANUAL_LOGIN_ATTEMPTS):
                    self._emit_auth_debug(
                        stage="manual-round-start",
                        manual_attempt=manual_attempt + 1,
                        capture_attempt=None,
                        page=page,
                        cookies=[],
                    )
                    if manual_attempt > 0 and self._looks_like_auth_error_url(getattr(page, "url", "")):
                        self._emit_auth_debug(
                            stage="reset-context",
                            manual_attempt=manual_attempt + 1,
                            capture_attempt=None,
                            page=page,
                            cookies=[],
                        )
                        try:
                            context.close()
                        except Exception:
                            pass
                        context = self._open_registration_context(playwright, browser)
                        self._apply_stealth_context_overrides(context)
                        page = context.new_page()
                        page.goto(self.base_url)
                    prompt = INITIAL_LOGIN_PROMPT if manual_attempt == 0 else AUTH_ERROR_RETRY_PROMPT
                    input(prompt)
                    for _ in range(MAX_REGISTRATION_CAPTURE_ATTEMPTS):
                        capture_attempt = _ + 1
                        self._emit_auth_debug(
                            stage="capture-attempt-start",
                            manual_attempt=manual_attempt + 1,
                            capture_attempt=capture_attempt,
                            page=page,
                            cookies=[],
                        )
                        cookies = context.cookies()
                        self._emit_auth_debug(
                            stage="capture-check",
                            manual_attempt=manual_attempt + 1,
                            capture_attempt=capture_attempt,
                            page=page,
                            cookies=cookies,
                        )
                        try:
                            self._assert_authenticated_state(page, cookies=cookies)
                            session_token = self._require_cookie_value(
                                cookies, "__Secure-next-auth.session-token"
                            )
                        except BrowserRegistrationError as exc:
                            last_error = exc
                            self._emit_auth_debug(
                                stage="capture-failed",
                                manual_attempt=manual_attempt + 1,
                                capture_attempt=capture_attempt,
                                page=page,
                                cookies=cookies,
                            )
                            self._recover_from_auth_error(page)
                            try:
                                page.wait_for_timeout(CAPTURE_RETRY_WAIT_MS)
                            except Exception:
                                pass
                            continue

                        csrf_cookie = self._optional_cookie_value(
                            cookies, "__Host-next-auth.csrf-token"
                        )
                        email = self._resolve_registration_email(
                            page=page,
                            existing_email=_UNKNOWN_EMAIL,
                        )
                        return RegistrationResult(
                            email=email,
                            secret=SessionSecret(
                                session_token=session_token,
                                csrf_token=csrf_cookie,
                                codex_auth_json=None,
                            ),
                            captured_at=datetime.now(UTC),
                        )
                if last_error is not None:
                    self._emit_auth_debug(
                        stage="final-failure",
                        manual_attempt=MAX_MANUAL_LOGIN_ATTEMPTS,
                        capture_attempt=MAX_REGISTRATION_CAPTURE_ATTEMPTS,
                        page=page,
                        cookies=[],
                    )
                    raise last_error
                raise BrowserRegistrationError(
                    "Could not verify authenticated state after login."
                )
            finally:
                if context is not None:
                    try:
                        context.close()
                    except Exception:
                        pass
                if browser is not None:
                    browser.close()

    def reauth(self, existing_email: str) -> RegistrationResult:
        return self.register()

    def capture_existing_session(self, page, *, existing_email: str) -> RegistrationResult:
        context = page.context
        cookies = context.cookies()
        self._assert_authenticated_state(page, cookies=cookies)
        session_token = self._require_cookie_value(
            cookies, "__Secure-next-auth.session-token"
        )
        csrf_cookie = self._optional_cookie_value(
            cookies, "__Host-next-auth.csrf-token"
        )
        email = self._resolve_registration_email(page=page, existing_email=existing_email)
        return RegistrationResult(
            email=email,
            secret=SessionSecret(
                session_token=session_token,
                csrf_token=csrf_cookie,
                codex_auth_json=None,
            ),
            captured_at=datetime.now(UTC),
        )

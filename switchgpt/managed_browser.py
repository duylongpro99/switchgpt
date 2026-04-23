from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import sync_playwright

from .config import get_env
from .errors import ManagedBrowserError
from .models import LimitState

LIMIT_DETECTION_MARKERS = (
    "you have reached the limit",
    "try again later",
    "usage limit",
)
RUNTIME_PROBE_TIMEOUT_MS = 5000
DEFAULT_BROWSER_CHANNEL = "chrome"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


@dataclass
class ManagedBrowser:
    base_url: str
    profile_dir: Path | None
    _playwright: object | None = field(default=None, init=False, repr=False)
    _context: object | None = field(default=None, init=False, repr=False)
    _page: object | None = field(default=None, init=False, repr=False)

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

    def _launch_persistent_context(self, playwright, profile_dir: Path, *, headless: bool):
        last_exc = None
        for channel in self._candidate_channels():
            launch_kwargs = {"headless": headless}
            launch_kwargs.update(self._stealth_launch_kwargs())
            if channel is not None:
                launch_kwargs["channel"] = channel
            try:
                return playwright.chromium.launch_persistent_context(
                    str(profile_dir),
                    **launch_kwargs,
                )
            except Exception as exc:
                last_exc = exc
        raise ManagedBrowserError("Unable to launch the managed ChatGPT browser workspace.") from last_exc

    def open_workspace(self):
        if self.profile_dir is None:
            raise ManagedBrowserError("Unable to launch the managed ChatGPT browser workspace.")

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        context = self._context
        page = self._page

        if not self._is_live_context(context):
            context = self._launch_runtime(replace_existing=True)
            page = None

        try:
            page = self._resolve_live_page(context, page)
            page.goto(self.base_url)
        except Exception:
            try:
                context = self._launch_runtime(replace_existing=True)
                page = self._resolve_live_page(context, None)
                page.goto(self.base_url)
            except Exception as exc:
                self._discard_runtime(stop_playwright=True)
                raise ManagedBrowserError("Unable to launch the managed ChatGPT browser workspace.") from exc

        self._context = context
        self._page = page
        return context, page

    def ensure_runtime(self):
        return self.open_workspace()

    def can_open_workspace(
        self,
        *,
        probe_profile_dir=None,
        headless: bool = False,
    ) -> bool:
        if probe_profile_dir is None and self._is_live_context(self._context):
            return True
        profile_dir = self.profile_dir if probe_profile_dir is None else Path(probe_profile_dir)
        if profile_dir is None:
            return False

        profile_dir.mkdir(parents=True, exist_ok=True)
        playwright = None
        context = None
        try:
            playwright = sync_playwright().start()
            context = self._launch_persistent_context(
                playwright,
                profile_dir,
                headless=headless,
            )
            page = self._resolve_live_page(context, None)
            page.goto(self.base_url, timeout=RUNTIME_PROBE_TIMEOUT_MS)
        except Exception:
            return False
        finally:
            self._close_context(context)
            self._stop_playwright(playwright)
        return True

    def _launch_runtime(self, *, replace_existing: bool = False):
        if replace_existing:
            self._discard_runtime(stop_playwright=True)
        self._playwright = sync_playwright().start()
        try:
            context = self._launch_persistent_context(
                self._playwright,
                self.profile_dir,
                headless=False,
            )
        except Exception as exc:
            self._stop_playwright(self._playwright)
            self._playwright = None
            self._context = None
            self._page = None
            raise ManagedBrowserError("Unable to launch the managed ChatGPT browser workspace.") from exc
        self._apply_stealth_context_overrides(context)
        self._context = context
        self._page = None
        return context

    def _resolve_live_page(self, context, page):
        if self._is_live_page(page):
            return page

        try:
            pages = list(context.pages)
        except Exception:
            pages = []

        for candidate in pages:
            if self._is_live_page(candidate):
                return candidate

        try:
            return context.new_page()
        except Exception as exc:
            raise ManagedBrowserError("Unable to launch the managed ChatGPT browser workspace.") from exc

    def _is_live_context(self, context) -> bool:
        if context is None:
            return False
        if self._read_closed_state(context):
            return False
        try:
            list(context.pages)
        except Exception:
            return False
        return True

    def _is_live_page(self, page) -> bool:
        if page is None:
            return False
        return not self._read_closed_state(page)

    def _read_closed_state(self, handle) -> bool:
        probe = getattr(handle, "is_closed", None)
        if probe is None:
            return False
        try:
            return probe() if callable(probe) else bool(probe)
        except Exception:
            return True

    def _discard_runtime(self, *, stop_playwright: bool = False) -> None:
        if stop_playwright:
            self._stop_playwright(self._playwright)
            self._playwright = None
        self._context = None
        self._page = None

    def _stop_playwright(self, playwright) -> None:
        if playwright is None:
            return
        stopper = getattr(playwright, "stop", None)
        if callable(stopper):
            try:
                stopper()
            except Exception:
                pass

    def _close_context(self, context) -> None:
        if context is None:
            return
        closer = getattr(context, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass

    def prepare_switch(
        self,
        context,
        page,
        *,
        session_token: str,
        csrf_token: str | None,
    ) -> None:
        context.clear_cookies()
        cookies = [
            {
                "name": "__Secure-next-auth.session-token",
                "value": session_token,
                "domain": ".chatgpt.com",
                "path": "/",
                "secure": True,
            }
        ]
        if csrf_token is not None:
            cookies.append(
                {
                    "name": "__Host-next-auth.csrf-token",
                    "value": csrf_token,
                    "url": self.base_url,
                    "secure": True,
                }
            )
        context.add_cookies(cookies)
        page.goto(self.base_url)

    def is_authenticated(self, page) -> bool:
        lowered_url = getattr(page, "url", "").lower()
        body = page.locator("body").inner_text().lower()
        if any(marker in lowered_url for marker in ("/login", "/signin", "/auth")):
            return False
        if "sign in" in body or "log in" in body or "login" in body:
            return False
        return "chatgpt" in body or "open sidebar" in body

    def detect_limit_state(self, page) -> LimitState:
        try:
            body = page.locator("body").inner_text().lower()
        except Exception:
            return LimitState.UNKNOWN

        if any(marker in body for marker in LIMIT_DETECTION_MARKERS):
            return LimitState.LIMIT_DETECTED
        return LimitState.NO_LIMIT_DETECTED

    def wait_for_reauthentication(self, page) -> None:
        input(
            "[switchgpt] Complete reauthentication in the managed browser, then press ENTER here."
        )
        try:
            page.goto(self.base_url)
        except Exception as exc:
            raise ManagedBrowserError(
                "Unable to launch the managed ChatGPT browser workspace."
            ) from exc

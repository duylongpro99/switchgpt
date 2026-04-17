from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import sync_playwright

from .errors import ManagedBrowserError
from .models import LimitState

LIMIT_DETECTION_MARKERS = (
    "you have reached the limit",
    "try again later",
    "usage limit",
)


@dataclass
class ManagedBrowser:
    base_url: str
    profile_dir: Path | None
    _playwright: object | None = field(default=None, init=False, repr=False)
    _context: object | None = field(default=None, init=False, repr=False)
    _page: object | None = field(default=None, init=False, repr=False)

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
                self._discard_runtime()
                raise ManagedBrowserError("Unable to launch the managed ChatGPT browser workspace.") from exc

        self._context = context
        self._page = page
        return context, page

    def ensure_runtime(self):
        return self.open_workspace()

    def _launch_runtime(self, *, replace_existing: bool = False):
        if replace_existing:
            self._discard_runtime(stop_playwright=True)
        self._playwright = sync_playwright().start()
        try:
            context = self._playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=False,
            )
        except Exception as exc:
            self._stop_playwright(self._playwright)
            self._playwright = None
            self._context = None
            self._page = None
            raise ManagedBrowserError("Unable to launch the managed ChatGPT browser workspace.") from exc
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
                    "path": "/",
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

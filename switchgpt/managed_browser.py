from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import sync_playwright

from .errors import ManagedBrowserError


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
        if self._context is None:
            self._playwright = sync_playwright().start()
            try:
                self._context = self._playwright.chromium.launch_persistent_context(
                    str(self.profile_dir),
                    headless=False,
                )
            except Exception as exc:
                raise ManagedBrowserError("Unable to launch the managed ChatGPT browser workspace.") from exc

        if self._page is None:
            pages = list(self._context.pages)
            self._page = pages[0] if pages else self._context.new_page()

        self._page.goto(self.base_url)
        return self._context, self._page

    def ensure_runtime(self):
        return self.open_workspace()

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
            }
        ]
        if csrf_token is not None:
            cookies.append(
                {
                    "name": "__Host-next-auth.csrf-token",
                    "value": csrf_token,
                    "domain": "chatgpt.com",
                    "path": "/",
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

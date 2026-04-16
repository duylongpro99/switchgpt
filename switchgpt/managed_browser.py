from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ManagedBrowser:
    base_url: str
    profile_dir: Path | None

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

from pathlib import Path

from switchgpt.managed_browser import ManagedBrowser


class FakeContext:
    def __init__(self) -> None:
        self.cookies_cleared = False
        self.cookies_added = []

    def clear_cookies(self) -> None:
        self.cookies_cleared = True

    def add_cookies(self, cookies) -> None:
        self.cookies_added.extend(cookies)


class FakePage:
    def __init__(self) -> None:
        self.url = "https://chatgpt.com"
        self.visited = []
        self.text = "ChatGPT"

    def goto(self, url: str) -> None:
        self.visited.append(url)
        self.url = url

    def locator(self, selector: str):
        assert selector == "body"
        return self

    def inner_text(self) -> str:
        return self.text


def test_prepare_switch_clears_and_injects_cookies() -> None:
    browser = ManagedBrowser("https://chatgpt.com", profile_dir=None)
    context = FakeContext()
    page = FakePage()

    browser.prepare_switch(
        context,
        page,
        session_token="session-1",
        csrf_token="csrf-1",
    )

    assert context.cookies_cleared is True
    assert len(context.cookies_added) == 2
    assert context.cookies_added[0]["name"] == "__Secure-next-auth.session-token"
    assert context.cookies_added[1]["name"] == "__Host-next-auth.csrf-token"
    assert page.visited[-1] == "https://chatgpt.com"


def test_is_authenticated_accepts_authenticated_page() -> None:
    browser = ManagedBrowser("https://chatgpt.com", profile_dir=None)
    page = FakePage()
    page.text = "ChatGPT Open sidebar"

    assert browser.is_authenticated(page) is True


def test_is_authenticated_rejects_login_page() -> None:
    browser = ManagedBrowser("https://chatgpt.com", profile_dir=None)
    page = FakePage()
    page.url = "https://chatgpt.com/auth/login"
    page.text = "Log in"

    assert browser.is_authenticated(page) is False


def test_open_workspace_creates_profile_dir_and_returns_runtime_handles(tmp_path, monkeypatch) -> None:
    launched = {}

    class FakePage:
        def goto(self, url: str) -> None:
            launched["goto"] = url

    class FakeBrowserContext:
        def __init__(self) -> None:
            self.pages = []

        def new_page(self):
            return FakePage()

    class FakeChromium:
        def launch_persistent_context(self, profile_dir: str, headless: bool):
            launched["profile_dir"] = profile_dir
            launched["headless"] = headless
            return FakeBrowserContext()

    class FakePlaywrightHandle:
        chromium = FakeChromium()

    class FakePlaywrightFactory:
        def start(self):
            return FakePlaywrightHandle()

    monkeypatch.setattr("switchgpt.managed_browser.sync_playwright", lambda: FakePlaywrightFactory())

    browser = ManagedBrowser("https://chatgpt.com", profile_dir=tmp_path / "profile")
    context, page = browser.open_workspace()

    assert Path(launched["profile_dir"]) == tmp_path / "profile"
    assert launched["headless"] is False
    assert launched["goto"] == "https://chatgpt.com"
    assert context is not None
    assert page is not None

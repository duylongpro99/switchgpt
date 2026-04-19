from pathlib import Path

import pytest

from switchgpt.models import LimitState
from switchgpt.managed_browser import ManagedBrowser
from switchgpt.errors import ManagedBrowserError


class FakeContext:
    def __init__(self, pages=None, *, closed: bool = False, fail_pages: bool = False, fail_new_page: bool = False) -> None:
        self.cookies_cleared = False
        self.cookies_added = []
        self._pages = list(pages or [])
        self.closed = closed
        self.close_called = False
        self.fail_pages = fail_pages
        self.fail_new_page = fail_new_page

    def clear_cookies(self) -> None:
        self.cookies_cleared = True

    def add_cookies(self, cookies) -> None:
        for cookie in cookies:
            has_url = "url" in cookie
            has_domain_and_path = "domain" in cookie and "path" in cookie
            assert has_url or has_domain_and_path
        self.cookies_added.extend(cookies)

    def is_closed(self) -> bool:
        return self.closed

    @property
    def pages(self):
        if self.fail_pages:
            raise RuntimeError("stale context")
        return self._pages

    def new_page(self):
        if self.fail_new_page:
            raise RuntimeError("unable to create page")
        page = FakePage()
        self._pages.append(page)
        return page

    def close(self) -> None:
        self.close_called = True
        self.closed = True


class FakePage:
    def __init__(self, *, closed: bool = False) -> None:
        self.url = "https://chatgpt.com"
        self.visited = []
        self.text = "ChatGPT"
        self.closed = closed

    def goto(self, url: str, timeout: int | None = None) -> None:
        if self.closed:
            raise RuntimeError("page closed")
        self.visited.append(url)
        self.url = url

    def locator(self, selector: str):
        assert selector == "body"
        return self

    def inner_text(self) -> str:
        return self.text

    def is_closed(self) -> bool:
        return self.closed


@pytest.mark.parametrize(
    ("page_text", "expected_state"),
    [
        ("You have reached the limit for GPT-5 messages.", LimitState.LIMIT_DETECTED),
        ("Your usage limit has been reached. Try again later.", LimitState.LIMIT_DETECTED),
        ("Please try again later after the current window resets.", LimitState.LIMIT_DETECTED),
    ],
)
def test_detect_limit_state_returns_limit_detected_for_banner_variants(
    page_text: str,
    expected_state: LimitState,
) -> None:
    browser = ManagedBrowser("https://chatgpt.com", profile_dir=None)
    page = FakePage()
    page.text = page_text

    assert browser.detect_limit_state(page) is expected_state


@pytest.mark.parametrize(
    "page_text",
    [
        "ChatGPT Open sidebar",
        "Conversation history",
        "Welcome back to ChatGPT",
    ],
)
def test_detect_limit_state_returns_no_limit_detected_for_normal_workspace_variants(
    page_text: str,
) -> None:
    browser = ManagedBrowser("https://chatgpt.com", profile_dir=None)
    page = FakePage()
    page.text = page_text

    assert browser.detect_limit_state(page) is LimitState.NO_LIMIT_DETECTED


def test_detect_limit_state_returns_unknown_when_page_text_cannot_be_read() -> None:
    browser = ManagedBrowser("https://chatgpt.com", profile_dir=None)

    class BrokenPage(FakePage):
        def inner_text(self) -> str:
            raise RuntimeError("DOM unavailable")

    assert browser.detect_limit_state(BrokenPage()) is LimitState.UNKNOWN


class FakePlaywrightHandle:
    def __init__(self, context) -> None:
        self.chromium = self
        self.context = context
        self.stopped = False
        self.launches = []

    def launch_persistent_context(self, profile_dir: str, headless: bool):
        self.launches.append((profile_dir, headless))
        return self.context

    def stop(self) -> None:
        self.stopped = True


class FakePlaywrightFactory:
    def __init__(self, handle) -> None:
        self.handle = handle
        self.started = 0

    def start(self):
        self.started += 1
        return self.handle


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
    session_cookie = context.cookies_added[0]
    csrf_cookie = context.cookies_added[1]
    assert session_cookie["name"] == "__Secure-next-auth.session-token"
    assert session_cookie["secure"] is True
    assert session_cookie["domain"] == ".chatgpt.com"
    assert csrf_cookie["name"] == "__Host-next-auth.csrf-token"
    assert csrf_cookie["secure"] is True
    assert csrf_cookie["url"] == "https://chatgpt.com"
    assert "domain" not in csrf_cookie
    assert "path" not in csrf_cookie
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

    assert (tmp_path / "profile").exists()
    assert Path(launched["profile_dir"]) == tmp_path / "profile"
    assert launched["headless"] is False
    assert launched["goto"] == "https://chatgpt.com"
    assert context is not None
    assert page is not None


def test_open_workspace_applies_stealth_launch_flags_when_enabled(tmp_path, monkeypatch) -> None:
    launched = {}

    class FakePage:
        def goto(self, url: str) -> None:
            launched["goto"] = url

    class FakeBrowserContext:
        def __init__(self) -> None:
            self.pages = []
            self.scripts = []

        def add_init_script(self, script: str) -> None:
            self.scripts.append(script)

        def new_page(self):
            return FakePage()

    class FakeChromium:
        def launch_persistent_context(self, profile_dir: str, **kwargs):
            launched["profile_dir"] = profile_dir
            launched["kwargs"] = kwargs
            return FakeBrowserContext()

    class FakePlaywrightHandle:
        chromium = FakeChromium()

    class FakePlaywrightFactory:
        def start(self):
            return FakePlaywrightHandle()

    monkeypatch.setenv("SWITCHGPT_BROWSER_STEALTH", "true")
    monkeypatch.setattr("switchgpt.managed_browser.sync_playwright", lambda: FakePlaywrightFactory())

    browser = ManagedBrowser("https://chatgpt.com", profile_dir=tmp_path / "profile")
    browser.open_workspace()

    assert launched["kwargs"]["headless"] is False
    assert launched["kwargs"]["ignore_default_args"] == ["--enable-automation"]
    assert launched["kwargs"]["args"] == ["--disable-blink-features=AutomationControlled"]


def test_managed_browser_stealth_flag_reads_from_dotenv(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SWITCHGPT_BROWSER_STEALTH", raising=False)
    (tmp_path / ".env").write_text("SWITCHGPT_BROWSER_STEALTH=yes\n", encoding="utf-8")
    browser = ManagedBrowser("https://chatgpt.com", profile_dir=tmp_path / "profile")

    assert browser._is_stealth_enabled() is True


def test_open_workspace_recovers_from_closed_cached_page(tmp_path, monkeypatch) -> None:
    live_page = FakePage()
    closed_page = FakePage(closed=True)
    context = FakeContext(pages=[closed_page, live_page])
    playwright = FakePlaywrightHandle(context)
    factory = FakePlaywrightFactory(playwright)

    monkeypatch.setattr("switchgpt.managed_browser.sync_playwright", lambda: factory)

    browser = ManagedBrowser("https://chatgpt.com", profile_dir=tmp_path / "profile")
    browser._playwright = playwright
    browser._context = context
    browser._page = closed_page

    returned_context, returned_page = browser.ensure_runtime()

    assert returned_context is context
    assert returned_page is live_page
    assert live_page.visited[-1] == "https://chatgpt.com"
    assert closed_page.visited == []
    assert factory.started == 0
    assert playwright.stopped is False


def test_open_workspace_relaunches_stale_context(tmp_path, monkeypatch) -> None:
    stale_page = FakePage(closed=True)
    stale_context = FakeContext(pages=[stale_page], closed=True)
    old_playwright = FakePlaywrightHandle(stale_context)

    fresh_page = FakePage()
    fresh_context = FakeContext(pages=[fresh_page])
    fresh_playwright = FakePlaywrightHandle(fresh_context)
    factory = FakePlaywrightFactory(fresh_playwright)

    monkeypatch.setattr("switchgpt.managed_browser.sync_playwright", lambda: factory)

    browser = ManagedBrowser("https://chatgpt.com", profile_dir=tmp_path / "profile")
    browser._playwright = old_playwright
    browser._context = stale_context
    browser._page = stale_page

    returned_context, returned_page = browser.ensure_runtime()

    assert returned_context is fresh_context
    assert returned_page is fresh_page
    assert fresh_page.visited[-1] == "https://chatgpt.com"
    assert old_playwright.stopped is True
    assert factory.started == 1


def test_open_workspace_relaunches_when_cached_context_is_broken(tmp_path, monkeypatch) -> None:
    cached_page = FakePage()
    stale_context = FakeContext(pages=[cached_page], fail_pages=True)
    old_playwright = FakePlaywrightHandle(stale_context)

    fresh_page = FakePage()
    fresh_context = FakeContext(pages=[fresh_page])
    fresh_playwright = FakePlaywrightHandle(fresh_context)
    factory = FakePlaywrightFactory(fresh_playwright)

    monkeypatch.setattr("switchgpt.managed_browser.sync_playwright", lambda: factory)

    browser = ManagedBrowser("https://chatgpt.com", profile_dir=tmp_path / "profile")
    browser._playwright = old_playwright
    browser._context = stale_context
    browser._page = cached_page

    returned_context, returned_page = browser.ensure_runtime()

    assert returned_context is fresh_context
    assert returned_page is fresh_page
    assert cached_page.visited == []
    assert fresh_page.visited[-1] == "https://chatgpt.com"
    assert old_playwright.stopped is True
    assert factory.started == 1


def test_open_workspace_stops_new_playwright_when_launch_fails(tmp_path, monkeypatch) -> None:
    class FailingChromium:
        def launch_persistent_context(self, profile_dir: str, headless: bool):
            raise RuntimeError("launch failed")

    class FailingPlaywrightHandle:
        def __init__(self) -> None:
            self.chromium = FailingChromium()
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    failing_handle = FailingPlaywrightHandle()

    class FailingFactory:
        def start(self):
            return failing_handle

    monkeypatch.setattr("switchgpt.managed_browser.sync_playwright", lambda: FailingFactory())

    browser = ManagedBrowser("https://chatgpt.com", profile_dir=tmp_path / "profile")

    try:
        browser.ensure_runtime()
    except ManagedBrowserError as exc:
        assert "Unable to launch the managed ChatGPT browser workspace." in str(exc)
    else:
        raise AssertionError("expected ManagedBrowserError")

    assert failing_handle.stopped is True
    assert browser._playwright is None
    assert browser._context is None
    assert browser._page is None


def test_open_workspace_stops_relaunched_playwright_when_retry_goto_fails(
    tmp_path, monkeypatch
) -> None:
    stale_page = FakePage(closed=True)
    stale_context = FakeContext(pages=[stale_page], closed=True)
    old_playwright = FakePlaywrightHandle(stale_context)

    class FailingPage(FakePage):
        def goto(self, url: str, timeout: int | None = None) -> None:
            raise RuntimeError("retry goto failed")

    fresh_context = FakeContext(pages=[FailingPage()])
    fresh_playwright = FakePlaywrightHandle(fresh_context)
    factory = FakePlaywrightFactory(fresh_playwright)

    monkeypatch.setattr("switchgpt.managed_browser.sync_playwright", lambda: factory)

    browser = ManagedBrowser("https://chatgpt.com", profile_dir=tmp_path / "profile")
    browser._playwright = old_playwright
    browser._context = stale_context
    browser._page = stale_page

    with pytest.raises(ManagedBrowserError):
        browser.open_workspace()

    assert old_playwright.stopped is True
    assert fresh_playwright.stopped is True
    assert browser._playwright is None
    assert browser._context is None
    assert browser._page is None


def test_can_open_workspace_returns_true_when_workspace_probe_succeeds(tmp_path, monkeypatch) -> None:
    page = FakePage()
    context = FakeContext(pages=[page])
    playwright = FakePlaywrightHandle(context)
    factory = FakePlaywrightFactory(playwright)

    monkeypatch.setattr("switchgpt.managed_browser.sync_playwright", lambda: factory)

    browser = ManagedBrowser("https://chatgpt.com", profile_dir=tmp_path / "profile")

    assert browser.can_open_workspace() is True
    assert page.visited[-1] == "https://chatgpt.com"
    assert context.close_called is True
    assert playwright.stopped is True
    assert browser._context is None
    assert browser._page is None


def test_can_open_workspace_returns_false_when_workspace_probe_fails(tmp_path, monkeypatch) -> None:
    class FailingChromium:
        def launch_persistent_context(self, profile_dir: str, headless: bool):
            raise RuntimeError("runtime unavailable")

    class FailingPlaywrightHandle:
        def __init__(self) -> None:
            self.chromium = FailingChromium()
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    failing = FailingPlaywrightHandle()

    class FailingFactory:
        def start(self):
            return failing

    monkeypatch.setattr("switchgpt.managed_browser.sync_playwright", lambda: FailingFactory())

    browser = ManagedBrowser("https://chatgpt.com", profile_dir=tmp_path / "profile")

    assert browser.can_open_workspace() is False
    assert failing.stopped is True


def test_can_open_workspace_returns_true_without_relaunching_live_runtime(tmp_path, monkeypatch) -> None:
    page = FakePage()
    context = FakeContext(pages=[page])
    browser = ManagedBrowser("https://chatgpt.com", profile_dir=tmp_path / "profile")
    browser._context = context
    browser._page = page

    class UnexpectedFactory:
        def start(self):
            raise AssertionError("probe should not relaunch when runtime is already live")

    monkeypatch.setattr("switchgpt.managed_browser.sync_playwright", lambda: UnexpectedFactory())

    assert browser.can_open_workspace() is True
    assert context.close_called is False
    assert browser._context is context
    assert browser._page is page


def test_can_open_workspace_returns_false_when_navigation_times_out(tmp_path, monkeypatch) -> None:
    class TimeoutPage(FakePage):
        def goto(self, url: str, timeout: int | None = None) -> None:
            raise RuntimeError(f"timed out after {timeout}")

    page = TimeoutPage()
    context = FakeContext(pages=[page])
    playwright = FakePlaywrightHandle(context)
    factory = FakePlaywrightFactory(playwright)

    monkeypatch.setattr("switchgpt.managed_browser.sync_playwright", lambda: factory)

    browser = ManagedBrowser("https://chatgpt.com", profile_dir=tmp_path / "profile")

    assert browser.can_open_workspace() is False
    assert context.close_called is True
    assert playwright.stopped is True


def test_wait_for_reauthentication_returns_to_workspace(monkeypatch) -> None:
    prompts = []
    page = FakePage()

    monkeypatch.setattr(
        "builtins.input",
        lambda prompt="": prompts.append(prompt),
    )

    browser = ManagedBrowser("https://chatgpt.com", profile_dir=None)
    browser.wait_for_reauthentication(page)

    assert prompts == [
        "[switchgpt] Complete reauthentication in the managed browser, then press ENTER here."
    ]
    assert page.visited[-1] == "https://chatgpt.com"


def test_wait_for_reauthentication_raises_managed_browser_error_when_return_fails(
    monkeypatch,
) -> None:
    class BrokenPage(FakePage):
        def goto(self, url: str, timeout: int | None = None) -> None:
            raise RuntimeError("page closed")

    monkeypatch.setattr("builtins.input", lambda prompt="": None)

    browser = ManagedBrowser("https://chatgpt.com", profile_dir=None)

    with pytest.raises(ManagedBrowserError):
        browser.wait_for_reauthentication(BrokenPage())

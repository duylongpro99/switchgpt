# switchgpt Phase 5 Packaging and Maintainability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `switchgpt` easier to run, diagnose, and evolve locally by clarifying settings and state boundaries, standardizing structured diagnostics, extracting CLI construction/output seams, and documenting the canonical repository-based developer workflow.

**Architecture:** Preserve the existing Phase 1-4 service seams. Add a small settings-inventory surface in `config`, a dedicated `diagnostics` module for redaction and structured event payloads, and a thin `bootstrap`/`output` layer so `cli` stops owning object construction and rendering details. Keep the tool repository-driven: improve `README.md`, add a maintainers’ workflow document, and formalize pytest defaults in `pyproject.toml` without committing to any public distribution channel.

**Tech Stack:** Python 3.12, Typer CLI, Playwright sync API, pytest, uv, macOS Keychain-backed secret storage, JSON/JSONL local state.

---

## File Structure

- Create: `switchgpt/diagnostics.py`
  Purpose: centralize message redaction and structured diagnostic event types used by services and CLI renderers.
- Create: `switchgpt/bootstrap.py`
  Purpose: centralize repository-local service construction so `cli.py` stops repeating `Settings.from_env()` and object wiring.
- Create: `switchgpt/output.py`
  Purpose: render status, doctor, watch, and settings inventory consistently without embedding formatting logic in command handlers.
- Create: `docs/development.md`
  Purpose: document canonical local setup, run, test, and subsystem ownership expectations for maintainers.
- Modify: `switchgpt/config.py`
  Purpose: support explicit environment overrides and expose a non-secret inventory of config/runtime/secret boundaries.
- Modify: `switchgpt/cli.py`
  Purpose: add a narrow `paths` diagnostics command, delegate service wiring to `bootstrap`, and delegate printing to `output`.
- Modify: `switchgpt/switch_service.py`
  Purpose: redact failure text before it reaches persistent history and keep structured result categories stable.
- Modify: `switchgpt/watch_service.py`
  Purpose: emit structured watch notifications alongside user-facing text.
- Modify: `switchgpt/doctor_service.py`
  Purpose: emit redacted check details so operational diagnostics stay safe to print and persist.
- Modify: `pyproject.toml`
  Purpose: formalize pytest defaults for the repository workflow.
- Modify: `README.md`
  Purpose: document the canonical repository-based install/run/test workflow at a high level and point maintainers to the deeper guide.
- Modify: `tests/test_config.py`
  Purpose: cover environment overrides and the settings inventory surface.
- Modify: `tests/test_cli.py`
  Purpose: cover the new `paths` command and preserve status/doctor/watch output expectations after the CLI refactor.
- Modify: `tests/test_switch_service.py`
  Purpose: verify history messages are redacted before persistence.
- Modify: `tests/test_watch_service.py`
  Purpose: verify structured watch notifications preserve kind/message while carrying a diagnostic payload.
- Modify: `tests/test_doctor_service.py`
  Purpose: verify unsafe diagnostic detail is redacted before it is returned to the CLI.
- Create: `tests/test_diagnostics.py`
  Purpose: unit-test message redaction and structured diagnostic formatting.

### Task 1: Clarify Settings And Runtime Boundaries

**Files:**
- Modify: `switchgpt/config.py`
- Modify: `switchgpt/cli.py`
- Test: `tests/test_config.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing settings and `paths` command tests**

```python
# tests/test_config.py
from pathlib import Path

import pytest

from switchgpt.config import Settings, SettingsItem


def test_settings_support_env_overrides_and_describe_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/tmp/example-home")
    monkeypatch.setenv("SWITCHGPT_HOME", "/tmp/custom-switchgpt")
    monkeypatch.setenv("SWITCHGPT_SLOT_COUNT", "5")
    monkeypatch.setenv("SWITCHGPT_KEYCHAIN_SERVICE", "switchgpt-dev")
    monkeypatch.setenv("SWITCHGPT_BASE_URL", "https://example.invalid")

    settings = Settings.from_env()
    items = {item.name: item for item in settings.describe_items()}

    assert settings.data_dir == Path("/tmp/custom-switchgpt")
    assert settings.slot_count == 5
    assert settings.keychain_service == "switchgpt-dev"
    assert settings.chatgpt_base_url == "https://example.invalid"
    assert items["metadata_path"] == SettingsItem(
        name="metadata_path",
        value="/tmp/custom-switchgpt/accounts.json",
        category="runtime-state",
        secret=False,
        description="Non-secret account metadata persisted on disk.",
    )
    assert items["keychain_service"].category == "secret-store"
    assert items["keychain_service"].secret is True
```

```python
# tests/test_cli.py
def test_paths_command_prints_config_runtime_and_secret_boundaries(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Darwin")

    result = runner.invoke(app, ["paths"])

    assert result.exit_code == 0
    assert "data_dir:" in result.stdout
    assert "[runtime-state]" in result.stdout
    assert "keychain_service: switchgpt [secret-store]" in result.stdout
    assert "chatgpt_base_url: https://chatgpt.com [config]" in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py tests/test_cli.py -q`

Expected: FAIL with `ImportError` / `AttributeError` because `SettingsItem`, `describe_items()`, and the `paths` command do not exist.

- [ ] **Step 3: Implement environment overrides and the settings inventory surface**

```python
# switchgpt/config.py
from dataclasses import dataclass
import os
import platform
from pathlib import Path

from .errors import UnsupportedPlatformError


@dataclass(frozen=True)
class SettingsItem:
    name: str
    value: str
    category: str
    secret: bool
    description: str


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    metadata_path: Path
    keychain_service: str
    slot_count: int
    chatgpt_base_url: str
    managed_profile_dir: Path
    switch_history_path: Path

    @classmethod
    def from_env(cls) -> "Settings":
        home = Path(os.environ["HOME"])
        data_dir = _env_path("SWITCHGPT_HOME", home / ".switchgpt")
        keychain_service = os.environ.get("SWITCHGPT_KEYCHAIN_SERVICE", "switchgpt")
        slot_count = _env_int("SWITCHGPT_SLOT_COUNT", 3)
        chatgpt_base_url = os.environ.get(
            "SWITCHGPT_BASE_URL",
            "https://chatgpt.com",
        )
        return cls(
            data_dir=data_dir,
            metadata_path=data_dir / "accounts.json",
            keychain_service=keychain_service,
            slot_count=slot_count,
            chatgpt_base_url=chatgpt_base_url,
            managed_profile_dir=data_dir / "playwright-profile",
            switch_history_path=data_dir / "switch-history.jsonl",
        )

    def describe_items(self) -> list[SettingsItem]:
        return [
            SettingsItem(
                name="data_dir",
                value=str(self.data_dir),
                category="runtime-state",
                secret=False,
                description="Root directory for switchgpt-managed local state.",
            ),
            SettingsItem(
                name="metadata_path",
                value=str(self.metadata_path),
                category="runtime-state",
                secret=False,
                description="Non-secret account metadata persisted on disk.",
            ),
            SettingsItem(
                name="managed_profile_dir",
                value=str(self.managed_profile_dir),
                category="runtime-state",
                secret=False,
                description="Tool-owned Playwright profile used for ChatGPT automation.",
            ),
            SettingsItem(
                name="switch_history_path",
                value=str(self.switch_history_path),
                category="runtime-state",
                secret=False,
                description="Append-only non-secret switch history log.",
            ),
            SettingsItem(
                name="keychain_service",
                value=self.keychain_service,
                category="secret-store",
                secret=True,
                description="macOS Keychain service name for stored session secrets.",
            ),
            SettingsItem(
                name="chatgpt_base_url",
                value=self.chatgpt_base_url,
                category="config",
                secret=False,
                description="Base URL used by registration and managed browser flows.",
            ),
            SettingsItem(
                name="slot_count",
                value=str(self.slot_count),
                category="config",
                secret=False,
                description="Configured number of local account slots.",
            ),
        ]


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return default if value is None else Path(value).expanduser()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    parsed = int(raw)
    if parsed < 1:
        raise ValueError(f"{name} must be a positive integer.")
    return parsed


def ensure_supported_platform() -> None:
    if platform.system() != "Darwin":
        raise UnsupportedPlatformError("switchgpt Phase 1 supports macOS only.")
```

```python
# switchgpt/cli.py
@app.command()
def paths() -> None:
    try:
        ensure_supported_platform()
        settings = Settings.from_env()
        for item in settings.describe_items():
            print(f"{item.name}: {item.value} [{item.category}]")
            print(f"  {item.description}")
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py tests/test_cli.py -q`

Expected: PASS with coverage for `Settings.from_env()` overrides, `describe_items()`, and the new `paths` command.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/config.py switchgpt/cli.py tests/test_config.py tests/test_cli.py
git commit -m "feat: add settings inventory and paths diagnostics"
```

### Task 2: Standardize Structured Diagnostics And Redaction

**Files:**
- Create: `switchgpt/diagnostics.py`
- Modify: `switchgpt/switch_service.py`
- Modify: `switchgpt/watch_service.py`
- Modify: `switchgpt/doctor_service.py`
- Test: `tests/test_diagnostics.py`
- Test: `tests/test_switch_service.py`
- Test: `tests/test_watch_service.py`
- Test: `tests/test_doctor_service.py`

- [ ] **Step 1: Write the failing diagnostics and redaction tests**

```python
# tests/test_diagnostics.py
from switchgpt.diagnostics import DiagnosticEvent, format_event, redact_text


def test_redact_text_masks_token_and_cookie_values() -> None:
    message = (
        "prepare_switch failed with session_token=abc123 "
        "csrf_token=def456 cookie=ghi789"
    )

    assert redact_text(message) == (
        "prepare_switch failed with session_token=[redacted] "
        "csrf_token=[redacted] cookie=[redacted]"
    )


def test_format_event_includes_subsystem_result_and_slot() -> None:
    event = DiagnosticEvent(
        subsystem="watch",
        result="switch-succeeded",
        message="Switched to slot 1.",
        account_index=1,
    )

    assert format_event(event) == "[watch] switch-succeeded slot=1: Switched to slot 1."
```

```python
# tests/test_switch_service.py
def test_failure_history_message_is_redacted_before_persistence() -> None:
    class FailingManagedBrowser(FakeManagedBrowser):
        def prepare_switch(
            self,
            context,
            page,
            *,
            session_token: str,
            csrf_token: str | None,
        ) -> None:
            raise SwitchError(
                "prepare_switch failed with session_token=abc123 csrf_token=def456"
            )

    history_store = FakeHistoryStore()
    service = SwitchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        secret_store=FakeSecretStore(
            SessionSecret(session_token="session-2", csrf_token="csrf-2")
        ),
        managed_browser=FailingManagedBrowser(authenticated=True),
        history_store=history_store,
    )

    with pytest.raises(SwitchError, match="prepare_switch failed"):
        service.switch_to(index=1)

    assert history_store.events[-1].message == (
        "prepare_switch failed with session_token=[redacted] csrf_token=[redacted]"
    )
```

```python
# tests/test_watch_service.py
def test_notifications_include_structured_diagnostic_event_payload() -> None:
    notifications = []
    service = WatchService(
        account_store=FakeAccountStore(
            [build_account(0, "a@example.com"), build_account(1, "b@example.com")],
            active_account_index=0,
        ),
        managed_browser=FakeManagedBrowser(detections=[LimitState.LIMIT_DETECTED]),
        switch_service=FakeSwitchService(),
        history_store=FakeHistoryStore(),
        poll_interval_seconds=0.0,
    )

    service.run(notify=notifications.append, sleep_fn=lambda _: None, stop_after_cycles=1)

    first_limit_event = next(item for item in notifications if item.kind == "limit-detected")
    assert first_limit_event.event.subsystem == "watch"
    assert first_limit_event.event.result == "limit-detected"
    assert first_limit_event.message == "Usage limit detected. Switching immediately."
```

```python
# tests/test_doctor_service.py
def test_run_redacts_sensitive_runtime_failure_detail() -> None:
    class BrokenManagedBrowser:
        def can_open_workspace(self, **kwargs) -> bool:
            raise RuntimeError("cookie=abc123 blocked browser startup")

    service = DoctorService(
        metadata_store=type("Store", (), {"load": lambda self: Snapshot([])})(),
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=type("Secrets", (), {"exists": lambda self, key: True})(),
        managed_browser=BrokenManagedBrowser(),
        platform_name="Darwin",
    )

    report = service.run()

    runtime_check = next(check for check in report.checks if check.name == "managed-browser")
    assert runtime_check.detail == "cookie=[redacted] blocked browser startup"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_diagnostics.py tests/test_switch_service.py tests/test_watch_service.py tests/test_doctor_service.py -q`

Expected: FAIL because `switchgpt.diagnostics` does not exist, `WatchNotification` has no structured payload, and services persist or return raw failure text.

- [ ] **Step 3: Add the diagnostics module and thread it through services**

```python
# switchgpt/diagnostics.py
from dataclasses import dataclass
import re


_SENSITIVE_PATTERNS = (
    re.compile(r"(session_token=)[^\\s]+", re.IGNORECASE),
    re.compile(r"(csrf_token=)[^\\s]+", re.IGNORECASE),
    re.compile(r"(cookie=)[^\\s]+", re.IGNORECASE),
    re.compile(r"(authorization=)[^\\s]+", re.IGNORECASE),
)


@dataclass(frozen=True)
class DiagnosticEvent:
    subsystem: str
    result: str
    message: str
    account_index: int | None = None


def redact_text(text: str | None) -> str | None:
    if text is None:
        return None
    redacted = text
    for pattern in _SENSITIVE_PATTERNS:
        redacted = pattern.sub(r"\\1[redacted]", redacted)
    return redacted


def format_event(event: DiagnosticEvent) -> str:
    slot_suffix = "" if event.account_index is None else f" slot={event.account_index}"
    return f"[{event.subsystem}] {event.result}{slot_suffix}: {event.message}"
```

```python
# switchgpt/switch_service.py
from .diagnostics import redact_text


def _append_event(
    self,
    *,
    occurred_at: datetime,
    previous_active_index: int | None,
    account_index: int | None,
    mode: str,
    result: str,
    message: str | None,
) -> None:
    self._history_store.append(
        SwitchEvent(
            occurred_at=occurred_at,
            from_account_index=previous_active_index,
            to_account_index=account_index,
            mode=mode,
            result=result,
            message=redact_text(message),
        )
    )
```

```python
# switchgpt/watch_service.py
from .diagnostics import DiagnosticEvent


@dataclass(frozen=True)
class WatchNotification:
    kind: str
    message: str
    event: DiagnosticEvent


def _emit(
    self,
    notify,
    kind: str,
    message: str,
    *,
    account_index: int | None = None,
) -> None:
    if notify is None:
        return
    event = DiagnosticEvent(
        subsystem="watch",
        result=kind,
        message=message,
        account_index=account_index,
    )
    notify(WatchNotification(kind=kind, message=message, event=event))
```

```python
# switchgpt/doctor_service.py
from .diagnostics import redact_text


def _check_runtime(self) -> DoctorCheck:
    try:
        with TemporaryDirectory(prefix="switchgpt-doctor-") as probe_dir:
            can_open = self._managed_browser.can_open_workspace(
                probe_profile_dir=probe_dir,
                headless=True,
            )
    except Exception as exc:
        return DoctorCheck(
            "managed-browser",
            "fail",
            redact_text(str(exc)) or "Managed browser probe failed.",
            "Run `switchgpt open` after repairing Playwright/browser prerequisites.",
        )
    if not can_open:
        return DoctorCheck(
            "managed-browser",
            "fail",
            "Managed workspace could not be opened.",
            "Run `switchgpt open` after repairing Playwright/browser prerequisites.",
        )
    return DoctorCheck(
        "managed-browser",
        "pass",
        "Managed workspace can be opened.",
        None,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_diagnostics.py tests/test_switch_service.py tests/test_watch_service.py tests/test_doctor_service.py -q`

Expected: PASS with coverage for redaction, structured watch notifications, and sanitized diagnostic detail.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/diagnostics.py switchgpt/switch_service.py switchgpt/watch_service.py switchgpt/doctor_service.py tests/test_diagnostics.py tests/test_switch_service.py tests/test_watch_service.py tests/test_doctor_service.py
git commit -m "feat: standardize diagnostics and redact sensitive messages"
```

### Task 3: Extract CLI Bootstrap And Output Seams

**Files:**
- Create: `switchgpt/bootstrap.py`
- Create: `switchgpt/output.py`
- Modify: `switchgpt/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI bootstrap/output tests**

```python
# tests/test_cli.py
def test_build_runtime_container_reuses_single_settings_snapshot(monkeypatch) -> None:
    captured = {"calls": 0}

    class FakeSettings:
        metadata_path = "meta"
        slot_count = 3
        keychain_service = "switchgpt"
        chatgpt_base_url = "https://chatgpt.com"
        managed_profile_dir = "profile"
        switch_history_path = "history"

        def describe_items(self):
            return []

    def fake_from_env():
        captured["calls"] += 1
        return FakeSettings()

    monkeypatch.setattr("switchgpt.bootstrap.Settings.from_env", fake_from_env)

    from switchgpt.bootstrap import build_runtime

    runtime = build_runtime()

    assert captured["calls"] == 1
    assert runtime.settings.chatgpt_base_url == "https://chatgpt.com"


def test_status_command_uses_rendered_output_lines(monkeypatch) -> None:
    monkeypatch.setattr("switchgpt.config.platform.system", lambda: "Darwin")

    class FakeStore:
        class Snapshot:
            accounts = []
            active_account_index = None
            last_switch_at = None

        def load(self):
            return self.Snapshot()

    class FakeStatusService:
        def summarize(self, accounts, *, active_account_index):
            return type(
                "Summary",
                (),
                {
                    "slots": [],
                    "readiness": "ready",
                    "latest_result": None,
                    "next_action": None,
                    "active_account_index": active_account_index,
                },
            )()

    monkeypatch.setattr(
        "switchgpt.cli.build_status_service",
        lambda: (FakeStore(), FakeStatusService()),
    )
    monkeypatch.setattr(
        "switchgpt.cli.render_status_summary",
        lambda summary: ["Readiness: ready", "No registered slots."],
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Readiness: ready" in result.stdout
    assert "No registered slots." in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -q`

Expected: FAIL because `switchgpt.bootstrap` and `render_status_summary()` do not exist, and `cli.py` still builds services and prints output inline.

- [ ] **Step 3: Extract service construction and rendering helpers**

```python
# switchgpt/bootstrap.py
from dataclasses import dataclass

from .account_store import AccountStore
from .config import Settings
from .doctor_service import DoctorService
from .managed_browser import ManagedBrowser
from .playwright_client import BrowserRegistrationClient
from .registration import RegistrationService
from .secret_store import KeychainSecretStore
from .status_service import StatusService
from .switch_history import SwitchHistoryStore
from .switch_service import SwitchService
from .watch_service import WatchService


@dataclass(frozen=True)
class Runtime:
    settings: Settings
    account_store: AccountStore
    secret_store: KeychainSecretStore
    managed_browser: ManagedBrowser
    history_store: SwitchHistoryStore


def build_runtime() -> Runtime:
    settings = Settings.from_env()
    return Runtime(
        settings=settings,
        account_store=AccountStore(settings.metadata_path, settings.slot_count),
        secret_store=KeychainSecretStore(settings.keychain_service),
        managed_browser=ManagedBrowser(
            base_url=settings.chatgpt_base_url,
            profile_dir=settings.managed_profile_dir,
        ),
        history_store=SwitchHistoryStore(settings.switch_history_path),
    )


def build_registration_service() -> RegistrationService:
    runtime = build_runtime()
    browser_client = BrowserRegistrationClient(
        base_url=runtime.settings.chatgpt_base_url,
    )
    return RegistrationService(runtime.account_store, runtime.secret_store, browser_client)


def build_status_service() -> tuple[AccountStore, StatusService]:
    runtime = build_runtime()
    return runtime.account_store, StatusService(
        runtime.secret_store,
        history_store=runtime.history_store,
    )


def build_doctor_service() -> DoctorService:
    runtime = build_runtime()
    return DoctorService(
        metadata_store=runtime.account_store,
        history_store=runtime.history_store,
        secret_store=runtime.secret_store,
        managed_browser=runtime.managed_browser,
        platform_name=platform.system(),
    )


def build_switch_service() -> SwitchService:
    runtime = build_runtime()
    return SwitchService(
        runtime.account_store,
        runtime.secret_store,
        runtime.managed_browser,
        runtime.history_store,
    )


def build_watch_service() -> WatchService:
    runtime = build_runtime()
    return WatchService(
        account_store=runtime.account_store,
        managed_browser=runtime.managed_browser,
        switch_service=SwitchService(
            runtime.account_store,
            runtime.secret_store,
            runtime.managed_browser,
            runtime.history_store,
        ),
        registration_service=build_registration_service(),
        history_store=runtime.history_store,
    )
```

```python
# switchgpt/output.py
def render_status_summary(summary) -> list[str]:
    lines = [f"Readiness: {summary.readiness}"]
    if summary.active_account_index is not None:
        lines.append(f"Active slot: {summary.active_account_index}")
    if summary.latest_result is not None:
        lines.append(f"Latest result: {summary.latest_result}")
    if summary.next_action is not None:
        lines.append(f"Next action: {summary.next_action}")
    if not summary.slots:
        lines.append("No registered slots.")
        return lines
    for slot in summary.slots:
        lines.append(f"[{slot.index}] {slot.email} - {slot.state}")
    return lines


def render_doctor_report(report) -> list[str]:
    lines = [f"Readiness: {report.readiness}"]
    for check in report.checks:
        lines.append(f"{check.name}: {check.status} - {check.detail}")
        if check.next_action:
            lines.append(f"next: {check.next_action}")
    return lines


def render_settings_items(items) -> list[str]:
    lines: list[str] = []
    for item in items:
        lines.append(f"{item.name}: {item.value} [{item.category}]")
        lines.append(f"  {item.description}")
    return lines
```

```python
# switchgpt/cli.py
from .bootstrap import (
    build_doctor_service,
    build_registration_service,
    build_status_service,
    build_switch_service,
    build_watch_service,
)
from .output import render_doctor_report, render_settings_items, render_status_summary


@app.command()
def status() -> None:
    try:
        ensure_supported_platform()
        store, service = build_status_service()
        snapshot = store.load()
        if not snapshot.accounts:
            print("No accounts registered.")
            return
        summary = service.summarize(
            snapshot.accounts,
            active_account_index=snapshot.active_account_index,
        )
        for line in render_status_summary(summary):
            print(line)
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def doctor() -> None:
    try:
        report = build_doctor_service().run()
        for line in render_doctor_report(report):
            print(line)
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def paths() -> None:
    try:
        ensure_supported_platform()
        for line in render_settings_items(Settings.from_env().describe_items()):
            print(line)
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -q`

Expected: PASS with coverage for the new runtime bootstrap seam, renderer delegation, and unchanged user-facing command behavior.

- [ ] **Step 5: Commit**

```bash
git add switchgpt/bootstrap.py switchgpt/output.py switchgpt/cli.py tests/test_cli.py
git commit -m "refactor: extract cli bootstrap and output helpers"
```

### Task 4: Formalize The Repository Workflow And Maintainer Docs

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Create: `docs/development.md`

- [ ] **Step 1: Write the failing workflow verification check**

```python
# No new Python test file is needed for this docs/config task.
# Verification will use the existing test suite plus direct file inspection commands.
```

- [ ] **Step 2: Run the current verification commands to capture the baseline**

Run: `uv run pytest tests/test_config.py tests/test_cli.py tests/test_doctor_service.py tests/test_switch_service.py tests/test_watch_service.py -q`

Expected: PASS before the docs-only updates, confirming the repository workflow still uses the same canonical command surface.

- [ ] **Step 3: Add pytest defaults and maintainer workflow docs**

```toml
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

```markdown
# README.md
# switchgpt

`switchgpt` is a macOS-only CLI for rotating ChatGPT accounts when usage limits are hit.

## Local Setup

Install repository dependencies with:

```bash
uv sync --dev
uv run playwright install chromium
```

## Local Commands

- `uv run switchgpt paths` shows config, runtime, and secret-store boundaries.
- `uv run switchgpt doctor` checks local readiness without mutating account state.
- `uv run switchgpt status` inspects registered account slots and recent readiness signals.
- `uv run switchgpt add` registers a new account.
- `uv run switchgpt add --reauth <slot>` refreshes an existing account.
- `uv run switchgpt switch [--to <slot>]` changes the managed ChatGPT session.
- `uv run switchgpt watch` monitors the managed workspace and rotates accounts on supported usage-limit events.

## Testing

Run the default repository test workflow with:

```bash
uv run pytest
```

For maintainer-oriented setup details and subsystem ownership notes, see [docs/development.md](docs/development.md).
```

```markdown
# docs/development.md
# switchgpt Development Workflow

## Canonical Local Workflow

1. Install dependencies: `uv sync --dev`
2. Install the browser runtime: `uv run playwright install chromium`
3. Validate the environment: `uv run switchgpt doctor`
4. Run the test suite: `uv run pytest`

## Local State Boundaries

- `switchgpt paths` prints the repository’s current config/runtime/secret-store inventory.
- `accounts.json` and `switch-history.jsonl` are non-secret runtime state.
- macOS Keychain holds session secrets and must never be mirrored into JSON metadata or logs.
- `playwright-profile/` is tool-owned browser runtime state.

## Main Ownership Boundaries

- `config.py`: settings, environment overrides, and path conventions
- `bootstrap.py`: service construction
- `output.py`: CLI rendering only
- `diagnostics.py`: redaction and structured diagnostics
- `managed_browser.py`: browser runtime and page interactions
- `switch_service.py`: single-target switch orchestration
- `watch_service.py`: foreground automation orchestration

## Expected Verification Before Merge

- Run `uv run pytest`
- If browser behavior changed, also run the relevant manual test document in `docs/manual-tests/`
- Keep changes inside existing subsystem seams unless the spec explicitly authorizes a boundary refinement
```

- [ ] **Step 4: Re-run verification after the workflow updates**

Run: `uv run pytest tests/test_config.py tests/test_cli.py tests/test_doctor_service.py tests/test_switch_service.py tests/test_watch_service.py -q`

Expected: PASS with the same command surface intact, while `README.md`, `docs/development.md`, and `pyproject.toml` now define the canonical repository workflow.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md docs/development.md
git commit -m "docs: formalize repository workflow and maintainer guide"
```

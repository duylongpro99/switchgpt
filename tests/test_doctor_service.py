from datetime import UTC, datetime

from switchgpt.doctor_service import DoctorService
from switchgpt.errors import AccountStoreError, SecretStoreError, SwitchHistoryError


class FakeManagedBrowser:
    def __init__(self, can_open: bool) -> None:
        self._can_open = can_open
        self.calls = []

    def can_open_workspace(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return self._can_open


class Snapshot:
    def __init__(
        self,
        accounts,
        *,
        active_account_index=None,
        last_codex_sync_slot=None,
        last_codex_sync_status=None,
        last_codex_sync_method=None,
        last_codex_sync_at=None,
        last_codex_sync_error=None,
    ) -> None:
        self.accounts = accounts
        self.active_account_index = active_account_index
        self.last_switch_at = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)
        self.last_codex_sync_slot = last_codex_sync_slot
        self.last_codex_sync_status = last_codex_sync_status
        self.last_codex_sync_method = last_codex_sync_method
        self.last_codex_sync_at = last_codex_sync_at
        self.last_codex_sync_error = last_codex_sync_error


class Account:
    def __init__(self, keychain_key: str) -> None:
        self.keychain_key = keychain_key


def test_run_reports_watch_readiness_when_all_checks_pass() -> None:
    managed_browser = FakeManagedBrowser(can_open=True)
    service = DoctorService(
        metadata_store=type(
            "Store",
            (),
            {"load": lambda self: Snapshot([Account("switchgpt_account_0")])},
        )(),
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=type(
            "Secrets", (), {"exists": lambda self, key: key == "switchgpt_account_0"}
        )(),
        managed_browser=managed_browser,
        platform_name="Darwin",
    )

    report = service.run()

    assert report.readiness == "watch-ready"
    assert all(check.status == "pass" for check in report.checks)
    assert managed_browser.calls[0]["headless"] is True


def test_run_reports_needs_attention_when_keychain_secret_is_missing() -> None:
    service = DoctorService(
        metadata_store=type(
            "Store",
            (),
            {"load": lambda self: Snapshot([Account("switchgpt_account_0")])},
        )(),
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=type("Secrets", (), {"exists": lambda self, key: False})(),
        managed_browser=FakeManagedBrowser(can_open=True),
        platform_name="Darwin",
    )

    report = service.run()

    assert report.readiness == "needs-attention"
    keychain_check = next(check for check in report.checks if check.name == "keychain")
    assert keychain_check.status == "fail"
    assert keychain_check.next_action is not None


def test_run_reports_metadata_failure_cleanly() -> None:
    class BrokenStore:
        def load(self):
            raise AccountStoreError("Malformed account metadata.")

    service = DoctorService(
        metadata_store=BrokenStore(),
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=type("Secrets", (), {"exists": lambda self, key: True})(),
        managed_browser=FakeManagedBrowser(can_open=True),
        platform_name="Darwin",
    )

    report = service.run()

    assert report.readiness == "needs-attention"
    metadata_check = next(check for check in report.checks if check.name == "metadata")
    assert metadata_check.status == "fail"


def test_run_reports_history_warning_cleanly() -> None:
    service = DoctorService(
        metadata_store=type("Store", (), {"load": lambda self: Snapshot([])})(),
        history_store=type(
            "History",
            (),
            {"load": lambda self: (_ for _ in ()).throw(SwitchHistoryError("bad history"))},
        )(),
        secret_store=type("Secrets", (), {"exists": lambda self, key: True})(),
        managed_browser=FakeManagedBrowser(can_open=True),
        platform_name="Darwin",
    )

    report = service.run()

    history_check = next(check for check in report.checks if check.name == "history")
    assert history_check.status == "warn"
    assert report.readiness == "needs-attention"


def test_run_reports_platform_failure_cleanly() -> None:
    service = DoctorService(
        metadata_store=type("Store", (), {"load": lambda self: Snapshot([])})(),
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=type("Secrets", (), {"exists": lambda self, key: True})(),
        managed_browser=FakeManagedBrowser(can_open=True),
        platform_name="Linux",
    )

    report = service.run()

    platform_check = next(check for check in report.checks if check.name == "platform")
    assert platform_check.status == "fail"
    assert report.readiness == "needs-attention"


def test_run_loads_metadata_once_for_stable_diagnosis() -> None:
    class CountingStore:
        def __init__(self) -> None:
            self.calls = 0

        def load(self):
            self.calls += 1
            return Snapshot([Account("switchgpt_account_0")])

    store = CountingStore()
    service = DoctorService(
        metadata_store=store,
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=type(
            "Secrets", (), {"exists": lambda self, key: key == "switchgpt_account_0"}
        )(),
        managed_browser=FakeManagedBrowser(can_open=True),
        platform_name="Darwin",
    )

    report = service.run()

    assert report.readiness == "watch-ready"
    assert store.calls == 1


def test_run_reports_keychain_backend_failure_cleanly() -> None:
    class BrokenSecrets:
        def exists(self, key: str) -> bool:
            raise SecretStoreError("Secret backend read failed.")

    service = DoctorService(
        metadata_store=type(
            "Store",
            (),
            {"load": lambda self: Snapshot([Account("switchgpt_account_0")])},
        )(),
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=BrokenSecrets(),
        managed_browser=FakeManagedBrowser(can_open=True),
        platform_name="Darwin",
    )

    report = service.run()

    keychain_check = next(check for check in report.checks if check.name == "keychain")
    assert keychain_check.status == "fail"
    assert report.readiness == "needs-attention"


def test_run_reports_managed_browser_failure_cleanly() -> None:
    service = DoctorService(
        metadata_store=type("Store", (), {"load": lambda self: Snapshot([])})(),
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=type("Secrets", (), {"exists": lambda self, key: True})(),
        managed_browser=FakeManagedBrowser(can_open=False),
        platform_name="Darwin",
    )

    report = service.run()

    runtime_check = next(check for check in report.checks if check.name == "managed-browser")
    assert runtime_check.status == "fail"
    assert report.readiness == "needs-attention"


def test_run_uses_fallback_detail_when_runtime_exception_is_empty() -> None:
    class BrokenManagedBrowser:
        def can_open_workspace(self, **kwargs) -> bool:
            raise RuntimeError("")

    service = DoctorService(
        metadata_store=type("Store", (), {"load": lambda self: Snapshot([])})(),
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=type("Secrets", (), {"exists": lambda self, key: True})(),
        managed_browser=BrokenManagedBrowser(),
        platform_name="Darwin",
    )

    report = service.run()

    runtime_check = next(check for check in report.checks if check.name == "managed-browser")
    assert runtime_check.detail == "Managed browser probe failed."


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


def test_run_includes_codex_sync_pass_when_no_active_slot() -> None:
    service = DoctorService(
        metadata_store=type("Store", (), {"load": lambda self: Snapshot([])})(),
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=type("Secrets", (), {"exists": lambda self, key: True})(),
        managed_browser=FakeManagedBrowser(can_open=True),
        platform_name="Darwin",
    )

    report = service.run()

    codex_sync_check = next(check for check in report.checks if check.name == "codex-sync")
    assert codex_sync_check.status == "pass"
    assert codex_sync_check.detail == "No active slot; Codex sync drift is not applicable."


def test_run_warns_when_last_codex_sync_does_not_match_active_slot() -> None:
    service = DoctorService(
        metadata_store=type(
            "Store",
            (),
            {
                "load": lambda self: Snapshot(
                    [Account("switchgpt_account_0")],
                    active_account_index=0,
                    last_codex_sync_slot=1,
                    last_codex_sync_status="ok",
                    last_codex_sync_method="file",
                    last_codex_sync_at=datetime(2026, 4, 19, 9, 30, tzinfo=UTC),
                )
            },
        )(),
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=type(
            "Secrets", (), {"exists": lambda self, key: key == "switchgpt_account_0"}
        )(),
        managed_browser=FakeManagedBrowser(can_open=True),
        platform_name="Darwin",
    )

    report = service.run()

    codex_sync_check = next(check for check in report.checks if check.name == "codex-sync")
    assert codex_sync_check.status == "warn"
    assert "switchgpt codex-sync" in codex_sync_check.next_action
    assert "doctor" in codex_sync_check.next_action
    assert report.readiness == "needs-attention"


def test_run_warns_when_last_codex_sync_failed_for_active_slot() -> None:
    service = DoctorService(
        metadata_store=type(
            "Store",
            (),
            {
                "load": lambda self: Snapshot(
                    [Account("switchgpt_account_0")],
                    active_account_index=0,
                    last_codex_sync_slot=0,
                    last_codex_sync_status="failed",
                    last_codex_sync_method="env-fallback",
                    last_codex_sync_at=datetime(2026, 4, 19, 9, 45, tzinfo=UTC),
                    last_codex_sync_error="codex-auth-write-failed",
                )
            },
        )(),
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=type(
            "Secrets", (), {"exists": lambda self, key: key == "switchgpt_account_0"}
        )(),
        managed_browser=FakeManagedBrowser(can_open=True),
        platform_name="Darwin",
    )

    report = service.run()

    codex_sync_check = next(check for check in report.checks if check.name == "codex-sync")
    assert codex_sync_check.status == "warn"
    assert "failed" in codex_sync_check.detail
    assert "switchgpt codex-sync" in codex_sync_check.next_action


def test_run_warns_when_last_codex_sync_failed_for_different_slot_than_active() -> None:
    service = DoctorService(
        metadata_store=type(
            "Store",
            (),
            {
                "load": lambda self: Snapshot(
                    [Account("switchgpt_account_0"), Account("switchgpt_account_1")],
                    active_account_index=0,
                    last_codex_sync_slot=1,
                    last_codex_sync_status="failed",
                    last_codex_sync_method="env-fallback",
                    last_codex_sync_at=datetime(2026, 4, 19, 9, 45, tzinfo=UTC),
                    last_codex_sync_error="codex-auth-write-failed",
                )
            },
        )(),
        history_store=type("History", (), {"load": lambda self: []})(),
        secret_store=type(
            "Secrets",
            (),
            {"exists": lambda self, key: key in {"switchgpt_account_0", "switchgpt_account_1"}},
        )(),
        managed_browser=FakeManagedBrowser(can_open=True),
        platform_name="Darwin",
    )

    report = service.run()

    codex_sync_check = next(check for check in report.checks if check.name == "codex-sync")
    assert codex_sync_check.status == "warn"
    assert "slot 1" in codex_sync_check.detail
    assert "active slot is 0" in codex_sync_check.detail
    assert "failed for active slot 0" not in codex_sync_check.detail
    assert "switchgpt codex-sync" in codex_sync_check.next_action

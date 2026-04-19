from datetime import UTC, datetime

import pytest

from switchgpt.codex_auth_sync import (
    CodexAuthSyncService,
    CodexSyncResult,
    raise_for_failed_sync,
)
from switchgpt.errors import CodexAuthSyncFailedError


def test_sync_returns_ok_when_file_target_succeeds() -> None:
    calls = []

    class FileTarget:
        def apply(self, *, email: str, session_token: str, csrf_token: str | None) -> str:
            del email, session_token, csrf_token
            calls.append("file")
            return "file"

    class EnvTarget:
        def apply(self, **kwargs):
            del kwargs
            raise AssertionError("env fallback should not run")

    service = CodexAuthSyncService(file_target=FileTarget(), env_target=EnvTarget())

    result = service.sync_active_slot(
        active_slot=1,
        email="account1@example.com",
        session_token="token-1",
        csrf_token="csrf-1",
        occurred_at=datetime(2026, 4, 19, 10, 0, tzinfo=UTC),
    )

    assert result == CodexSyncResult(
        outcome="ok",
        method="file",
        failure_class=None,
        message=None,
    )
    assert calls == ["file"]


def test_sync_falls_back_to_env_when_file_is_unsupported() -> None:
    class FileTarget:
        def apply(self, **kwargs):
            del kwargs
            raise RuntimeError("codex-auth-format-unsupported")

    class EnvTarget:
        def apply(self, **kwargs):
            del kwargs
            return "env-fallback"

    service = CodexAuthSyncService(file_target=FileTarget(), env_target=EnvTarget())

    result = service.sync_active_slot(
        active_slot=0,
        email="account0@example.com",
        session_token="token-0",
        csrf_token=None,
        occurred_at=datetime(2026, 4, 19, 10, 5, tzinfo=UTC),
    )

    assert result.outcome == "fallback-ok"
    assert result.method == "env-fallback"
    assert result.failure_class is None


def test_sync_returns_failed_when_both_targets_fail() -> None:
    class FileTarget:
        def apply(self, **kwargs):
            del kwargs
            raise RuntimeError("codex-auth-write-failed")

    class EnvTarget:
        def apply(self, **kwargs):
            del kwargs
            raise RuntimeError("codex-auth-fallback-failed")

    service = CodexAuthSyncService(file_target=FileTarget(), env_target=EnvTarget())

    result = service.sync_active_slot(
        active_slot=2,
        email="account2@example.com",
        session_token="token-2",
        csrf_token="csrf-2",
        occurred_at=datetime(2026, 4, 19, 10, 10, tzinfo=UTC),
    )

    assert result.outcome == "failed"
    assert result.method is None
    assert result.failure_class == "codex-auth-fallback-failed"


def test_sync_does_not_fallback_for_unknown_file_target_exceptions() -> None:
    calls = []

    class FileTarget:
        def apply(self, **kwargs):
            del kwargs
            raise TypeError("unexpected bug with session_token=secret-value")

    class EnvTarget:
        def apply(self, **kwargs):
            del kwargs
            calls.append("env")
            return "env-fallback"

    service = CodexAuthSyncService(file_target=FileTarget(), env_target=EnvTarget())

    result = service.sync_active_slot(
        active_slot=1,
        email="account1@example.com",
        session_token="token-1",
        csrf_token=None,
        occurred_at=datetime(2026, 4, 19, 10, 15, tzinfo=UTC),
    )

    assert result == CodexSyncResult(
        outcome="failed",
        method=None,
        failure_class="codex-auth-write-failed",
        message="unexpected bug with session_token=[redacted]",
    )
    assert calls == []


def test_sync_persists_metadata_for_last_result() -> None:
    persisted = {}

    class FakeStore:
        def save_codex_sync_state(self, **kwargs) -> None:
            persisted.update(kwargs)

    class FileTarget:
        def apply(self, **kwargs):
            del kwargs
            return "file"

    class EnvTarget:
        def apply(self, **kwargs):
            del kwargs
            raise AssertionError("fallback should not run")

    service = CodexAuthSyncService(
        file_target=FileTarget(),
        env_target=EnvTarget(),
        account_store=FakeStore(),
    )

    result = service.sync_active_slot(
        active_slot=1,
        email="account1@example.com",
        session_token="token-1",
        csrf_token=None,
        occurred_at=datetime(2026, 4, 19, 10, 30, tzinfo=UTC),
    )

    assert result.outcome == "ok"
    assert persisted == {
        "synced_at": datetime(2026, 4, 19, 10, 30, tzinfo=UTC),
        "synced_slot": 1,
        "method": "file",
        "status": "ok",
        "error": None,
    }


def test_sync_returns_result_when_persistence_fails_after_file_success() -> None:
    class FailingStore:
        def save_codex_sync_state(self, **kwargs) -> None:
            del kwargs
            raise RuntimeError("metadata write failed with cookie=secret-cookie")

    class FileTarget:
        def apply(self, **kwargs):
            del kwargs
            return "file"

    class EnvTarget:
        def apply(self, **kwargs):
            del kwargs
            raise AssertionError("fallback should not run")

    service = CodexAuthSyncService(
        file_target=FileTarget(),
        env_target=EnvTarget(),
        account_store=FailingStore(),
    )

    result = service.sync_active_slot(
        active_slot=1,
        email="account1@example.com",
        session_token="token-1",
        csrf_token=None,
        occurred_at=datetime(2026, 4, 19, 10, 35, tzinfo=UTC),
    )

    assert result == CodexSyncResult(
        outcome="ok",
        method="file",
        failure_class=None,
        message=None,
    )


def test_raise_for_failed_sync_wraps_failed_result_in_domain_error() -> None:
    result = CodexSyncResult(
        outcome="failed",
        method=None,
        failure_class="codex-auth-fallback-failed",
        message="env projection failed",
    )

    with pytest.raises(
        CodexAuthSyncFailedError, match="env projection failed"
    ) as exc_info:
        raise_for_failed_sync(result)

    assert exc_info.value.failure_class == "codex-auth-fallback-failed"


def test_raise_for_failed_sync_ignores_non_failed_result() -> None:
    raise_for_failed_sync(
        CodexSyncResult(
            outcome="fallback-ok",
            method="env-fallback",
            failure_class=None,
            message=None,
        )
    )

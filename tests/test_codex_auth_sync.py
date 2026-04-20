from datetime import UTC, datetime
import pytest

from switchgpt.codex_auth_sync import (
    CodexEnvAuthTarget,
    CodexFileAuthTarget,
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


def test_sync_with_default_targets_fails_loudly_when_no_projection_backend_exists() -> None:
    service = CodexAuthSyncService(
        file_target=CodexFileAuthTarget(),
        env_target=CodexEnvAuthTarget(),
    )

    result = service.sync_active_slot(
        active_slot=2,
        email="account2@example.com",
        session_token="token-2",
        csrf_token="csrf-2",
        occurred_at=datetime(2026, 4, 19, 10, 12, tzinfo=UTC),
    )

    assert result == CodexSyncResult(
        outcome="failed",
        method=None,
        failure_class="codex-auth-target-missing",
        message="codex-auth-target-missing",
    )


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


def test_file_target_writes_codex_auth_file_from_oauth_tokens(tmp_path) -> None:
    auth_path = tmp_path / "auth.json"

    class FakeManagedBrowser:
        def __init__(self) -> None:
            self.prepare_calls = []

        def ensure_runtime(self):
            return "context", "page"

        def prepare_switch(self, context, page, *, session_token: str, csrf_token: str | None):
            self.prepare_calls.append((context, page, session_token, csrf_token))

    target = CodexFileAuthTarget(
        managed_browser=FakeManagedBrowser(),
        auth_file_path=auth_path,
    )

    target._run_oauth_code_flow = lambda page, email: {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "id_token": _build_id_token(chatgpt_account_id="account-id-123"),
    }

    method = target.apply(
        email="account1@example.com",
        session_token="session-token",
        csrf_token="csrf-token",
    )

    payload = auth_path.read_text()
    assert method == "file"
    assert '"auth_mode": "chatgpt"' in payload
    assert '"account_id": "account-id-123"' in payload
    assert '"access_token": "access-token"' in payload
    assert '"refresh_token": "refresh-token"' in payload


def test_file_target_rejects_id_token_without_chatgpt_account_id(tmp_path) -> None:
    target = CodexFileAuthTarget(
        managed_browser=type(
            "FakeManagedBrowser",
            (),
            {
                "ensure_runtime": lambda self: ("context", "page"),
                "prepare_switch": lambda self, context, page, *, session_token, csrf_token: None,
            },
        )(),
        auth_file_path=tmp_path / "auth.json",
    )

    target._run_oauth_code_flow = lambda page, email: {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "id_token": _build_id_token(chatgpt_account_id=None),
    }

    with pytest.raises(RuntimeError, match="codex-auth-verify-failed"):
        target.apply(
            email="account1@example.com",
            session_token="session-token",
            csrf_token=None,
        )


def _build_id_token(*, chatgpt_account_id: str | None) -> str:
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = {
        "iss": "https://auth0.openai.com/",
        "sub": "subject-123",
        "email": "account1@example.com",
        "https://api.openai.com/auth": {},
    }
    if chatgpt_account_id is not None:
        payload["https://api.openai.com/auth"]["chatgpt_account_id"] = chatgpt_account_id
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}.signature"

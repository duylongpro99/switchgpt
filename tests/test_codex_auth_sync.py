from datetime import UTC, datetime
import json
import pytest

from switchgpt.codex_auth_sync import (
    CodexAuthSyncService,
    CodexEnvAuthTarget,
    CodexFileAuthTarget,
    CodexSyncResult,
    raise_for_failed_sync,
)
from switchgpt.errors import CodexAuthSyncFailedError


def build_auth_json(account_id: str = "account-1") -> dict[str, object]:
    return {
        "auth_mode": "chatgpt",
        "last_refresh": "2026-04-21T10:00:00Z",
        "tokens": {
            "access_token": f"access-{account_id}",
            "refresh_token": f"refresh-{account_id}",
            "id_token": f"id-{account_id}",
            "account_id": account_id,
        },
    }


def test_import_auth_json_returns_imported_result_with_fingerprint(tmp_path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps(build_auth_json()), encoding="utf-8")
    service = CodexAuthSyncService(
        file_target=CodexFileAuthTarget(auth_file_path=auth_path),
        env_target=CodexEnvAuthTarget(),
    )

    result = service.import_auth_json(
        slot=1,
        occurred_at=datetime(2026, 4, 21, 10, 0, tzinfo=UTC),
    )

    assert result.outcome == "imported"
    assert result.method == "file"
    assert result.failure_class is None
    assert result.fingerprint is not None


def test_import_auth_json_fails_for_invalid_shape(tmp_path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps({"auth_mode": "chatgpt"}), encoding="utf-8")
    service = CodexAuthSyncService(
        file_target=CodexFileAuthTarget(auth_file_path=auth_path),
        env_target=CodexEnvAuthTarget(),
    )

    result = service.import_auth_json(
        slot=1,
        occurred_at=datetime(2026, 4, 21, 10, 1, tzinfo=UTC),
    )

    assert result.outcome == "failed"
    assert result.failure_class == "codex-auth-format-invalid"
    assert "tokens object" in result.message


def test_sync_active_slot_writes_stored_auth_json_atomically(tmp_path) -> None:
    auth_path = tmp_path / "auth.json"
    target = CodexFileAuthTarget(auth_file_path=auth_path)
    service = CodexAuthSyncService(file_target=target, env_target=CodexEnvAuthTarget())

    result = service.sync_active_slot(
        active_slot=2,
        email="account2@example.com",
        session_token="session-2",
        csrf_token="csrf-2",
        codex_auth_json=build_auth_json("account-2"),
        occurred_at=datetime(2026, 4, 21, 10, 5, tzinfo=UTC),
    )

    assert result.outcome == "ok"
    assert result.method == "file"
    assert result.fingerprint is not None
    written = json.loads(auth_path.read_text(encoding="utf-8"))
    assert written["OPENAI_API_KEY"] is None
    assert written["auth_mode"] == "chatgpt"
    assert written["tokens"]["account_id"] == "account-2"
    assert written["last_refresh"] == "2026-04-21T10:00:00Z"
    assert not auth_path.with_name("auth.json.tmp").exists()


def test_sync_active_slot_fails_when_slot_has_no_imported_auth_json(tmp_path) -> None:
    service = CodexAuthSyncService(
        file_target=CodexFileAuthTarget(auth_file_path=tmp_path / "auth.json"),
        env_target=CodexEnvAuthTarget(),
    )

    result = service.sync_active_slot(
        active_slot=2,
        email="account2@example.com",
        session_token="session-2",
        csrf_token="csrf-2",
        codex_auth_json=None,
        occurred_at=datetime(2026, 4, 21, 10, 5, tzinfo=UTC),
    )

    assert result.failure_class == "codex-auth-source-missing"
    assert "no imported auth.json stored" in result.message


def test_sync_active_slot_redacts_secret_values_in_failures() -> None:
    class FailingTarget:
        def read_source_auth_json(self):
            raise AssertionError("not used")

        def apply_auth_json(self, payload, *, occurred_at):
            del payload, occurred_at
            raise RuntimeError("codex-auth-write-failed: access_token=secret-token")

    service = CodexAuthSyncService(
        file_target=FailingTarget(),
        env_target=CodexEnvAuthTarget(),
    )

    result = service.sync_active_slot(
        active_slot=1,
        email="account1@example.com",
        session_token="session-1",
        csrf_token=None,
        codex_auth_json=build_auth_json(),
        occurred_at=datetime(2026, 4, 21, 10, 6, tzinfo=UTC),
    )

    assert result.outcome == "failed"
    assert result.failure_class == "codex-auth-write-failed"
    assert result.message == "codex-auth-write-failed: access_token=[redacted]"


def test_sync_persists_metadata_for_last_result(tmp_path) -> None:
    persisted = {}

    class FakeStore:
        def save_codex_sync_state(self, **kwargs) -> None:
            persisted.update(kwargs)

    service = CodexAuthSyncService(
        file_target=CodexFileAuthTarget(auth_file_path=tmp_path / "auth.json"),
        env_target=CodexEnvAuthTarget(),
        account_store=FakeStore(),
    )

    result = service.sync_active_slot(
        active_slot=4,
        email="account4@example.com",
        session_token="session-4",
        csrf_token=None,
        codex_auth_json=build_auth_json("account-4"),
        occurred_at=datetime(2026, 4, 21, 10, 7, tzinfo=UTC),
    )

    assert result.outcome == "ok"
    assert persisted["synced_slot"] == 4
    assert persisted["status"] == "ok"
    assert persisted["error"] is None
    assert persisted["fingerprint"] == result.fingerprint


def test_fingerprint_and_drift_detection_use_normalized_payloads(tmp_path) -> None:
    auth_path = tmp_path / "auth.json"
    target = CodexFileAuthTarget(auth_file_path=auth_path)
    service = CodexAuthSyncService(file_target=target, env_target=CodexEnvAuthTarget())
    stored = build_auth_json("account-1")
    target.apply_auth_json(stored, occurred_at=datetime(2026, 4, 21, 10, 8, tzinfo=UTC))

    live_fingerprint = service.read_live_fingerprint()

    assert live_fingerprint == service.fingerprint_auth_json(stored)
    assert service.has_drift(stored_auth_json=stored, live_fingerprint=live_fingerprint) is False
    assert (
        service.has_drift(
            stored_auth_json=build_auth_json("account-2"),
            live_fingerprint=live_fingerprint,
        )
        is True
    )


def test_raise_for_failed_sync_wraps_failed_result_in_domain_error() -> None:
    result = CodexSyncResult(
        outcome="failed",
        method=None,
        failure_class="codex-auth-write-failed",
        message="codex-auth-write-failed: access_token=[redacted]",
    )

    with pytest.raises(
        CodexAuthSyncFailedError,
        match="codex-auth-write-failed: access_token=\\[redacted\\]",
    ):
        raise_for_failed_sync(result)


def test_raise_for_failed_sync_ignores_non_failed_result() -> None:
    raise_for_failed_sync(
        CodexSyncResult(
            outcome="ok",
            method="file",
            failure_class=None,
            message=None,
            fingerprint="fingerprint-1",
        )
    )

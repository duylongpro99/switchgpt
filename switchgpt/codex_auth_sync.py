from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .diagnostics import redact_text
from .errors import CodexAuthSyncFailedError


KNOWN_FAILURE_CLASSES = {
    "codex-auth-target-missing",
    "codex-auth-format-unsupported",
    "codex-auth-write-failed",
    "codex-auth-verify-failed",
    "codex-auth-fallback-failed",
}
FALLBACK_ELIGIBLE_FAILURE_CLASSES = {
    "codex-auth-target-missing",
    "codex-auth-format-unsupported",
    "codex-auth-write-failed",
    "codex-auth-verify-failed",
}


class CodexAuthTarget(Protocol):
    def apply(self, *, email: str, session_token: str, csrf_token: str | None) -> str: ...


@dataclass(frozen=True)
class CodexSyncResult:
    outcome: str
    method: str | None
    failure_class: str | None
    message: str | None


class CodexAuthSyncService:
    def __init__(
        self,
        *,
        file_target: CodexAuthTarget,
        env_target: CodexAuthTarget,
        account_store=None,
    ) -> None:
        self._file_target = file_target
        self._env_target = env_target
        self._account_store = account_store

    def sync_active_slot(
        self,
        *,
        active_slot: int,
        email: str,
        session_token: str,
        csrf_token: str | None,
        occurred_at: datetime,
    ) -> CodexSyncResult:
        try:
            method = self._file_target.apply(
                email=email,
                session_token=session_token,
                csrf_token=csrf_token,
            )
        except Exception as exc:
            failure_class = self._known_failure_class(exc)
            if failure_class not in FALLBACK_ELIGIBLE_FAILURE_CLASSES:
                return self._finalize_result(
                    occurred_at=occurred_at,
                    active_slot=active_slot,
                    result=CodexSyncResult(
                        outcome="failed",
                        method=None,
                        failure_class=self._classify_error(exc),
                        message=redact_text(str(exc)),
                    ),
                )
        else:
            return self._finalize_result(
                occurred_at=occurred_at,
                active_slot=active_slot,
                result=CodexSyncResult(
                    outcome="ok",
                    method=method,
                    failure_class=None,
                    message=None,
                ),
            )

        try:
            method = self._env_target.apply(
                email=email,
                session_token=session_token,
                csrf_token=csrf_token,
            )
        except Exception as exc:
            return self._finalize_result(
                occurred_at=occurred_at,
                active_slot=active_slot,
                result=CodexSyncResult(
                    outcome="failed",
                    method=None,
                    failure_class=self._classify_error(exc),
                    message=redact_text(str(exc)),
                ),
            )

        return self._finalize_result(
            occurred_at=occurred_at,
            active_slot=active_slot,
            result=CodexSyncResult(
                outcome="fallback-ok",
                method=method,
                failure_class=None,
                message=None,
            ),
        )

    def _known_failure_class(self, exc: Exception) -> str | None:
        message = str(exc)
        if message in KNOWN_FAILURE_CLASSES:
            return message
        return None

    def _classify_error(self, exc: Exception) -> str:
        failure_class = self._known_failure_class(exc)
        if failure_class is not None:
            return failure_class
        return "codex-auth-write-failed"

    def _finalize_result(
        self,
        *,
        occurred_at: datetime,
        active_slot: int,
        result: CodexSyncResult,
    ) -> CodexSyncResult:
        if self._account_store is not None:
            try:
                self._account_store.save_codex_sync_state(
                    synced_at=occurred_at,
                    synced_slot=active_slot,
                    method=result.method,
                    status=result.outcome,
                    error=result.failure_class,
                )
            except Exception:
                pass
        return result


class CodexFileAuthTarget:
    def apply(self, *, email: str, session_token: str, csrf_token: str | None) -> str:
        del email, session_token, csrf_token
        return "file"


class CodexEnvAuthTarget:
    def apply(self, *, email: str, session_token: str, csrf_token: str | None) -> str:
        del email, session_token, csrf_token
        return "env-fallback"


def raise_for_failed_sync(result: CodexSyncResult) -> None:
    if result.outcome != "failed":
        return
    raise CodexAuthSyncFailedError(
        result.message or result.failure_class or "Codex auth sync failed.",
        failure_class=result.failure_class,
    )

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import base64
from typing import Protocol

from .diagnostics import redact_text
from .errors import CodexAuthSyncFailedError


_REQUIRED_TOKEN_KEYS = ("access_token", "refresh_token", "id_token", "account_id")
_KNOWN_FAILURE_PREFIXES = {
    "codex-auth-source-missing",
    "codex-auth-format-invalid",
    "codex-auth-write-failed",
    "codex-auth-verify-failed",
}
_TOKEN_REDACTION_PATTERN = re.compile(
    r"\b(?P<key>access_token|refresh_token|id_token|account_id)=(?P<value>[^\s,;]+)"
)


def _normalize_email(value: object) -> str | None:
    if type(value) is not str:
        return None
    email = value.strip().lower()
    if not email:
        return None
    return email


def _decode_jwt_payload(token: object) -> dict[str, object] | None:
    if type(token) is not str or token.count(".") < 2:
        return None
    try:
        payload_segment = token.split(".")[1]
        payload_segment += "=" * (-len(payload_segment) % 4)
        decoded = base64.urlsafe_b64decode(payload_segment.encode("utf-8"))
        payload = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _resolve_email_from_tokens(tokens: dict[str, object]) -> str | None:
    access_payload = _decode_jwt_payload(tokens.get("access_token"))
    if access_payload is not None:
        profile = access_payload.get("https://api.openai.com/profile")
        if isinstance(profile, dict):
            profile_email = _normalize_email(profile.get("email"))
            if profile_email is not None:
                return profile_email
        access_email = _normalize_email(access_payload.get("email"))
        if access_email is not None:
            return access_email

    id_payload = _decode_jwt_payload(tokens.get("id_token"))
    if id_payload is not None:
        id_email = _normalize_email(id_payload.get("email"))
        if id_email is not None:
            return id_email

    return None


class CodexAuthTarget(Protocol):
    def read_source_auth_json(self) -> dict[str, object]: ...

    def apply_auth_json(
        self,
        payload: dict[str, object],
        *,
        occurred_at: datetime,
    ) -> None: ...

def _normalize_auth_json_payload(
    payload: object,
    *,
    occurred_at: datetime | None,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise RuntimeError("codex-auth-format-invalid: auth.json must be a JSON object")

    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        raise RuntimeError("codex-auth-format-invalid: auth.json missing tokens object")

    normalized_tokens: dict[str, str] = {}
    for key in _REQUIRED_TOKEN_KEYS:
        value = tokens.get(key)
        if type(value) is not str or not value:
            raise RuntimeError(
                f"codex-auth-format-invalid: auth.json missing tokens.{key}"
            )
        normalized_tokens[key] = value

    normalized: dict[str, object] = dict(payload)
    normalized["OPENAI_API_KEY"] = None
    normalized["auth_mode"] = "chatgpt"
    normalized["tokens"] = normalized_tokens

    last_refresh = payload.get("last_refresh")
    if type(last_refresh) is str and last_refresh:
        normalized["last_refresh"] = last_refresh
    elif occurred_at is not None:
        normalized["last_refresh"] = (
            occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        )
    else:
        normalized.pop("last_refresh", None)

    return normalized


def _fingerprint_auth_json_payload(payload: dict[str, object]) -> str:
    fingerprint_payload = {
        "auth_mode": payload.get("auth_mode"),
        "tokens": payload.get("tokens"),
    }
    encoded = json.dumps(
        fingerprint_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CodexSyncResult:
    outcome: str
    method: str | None
    failure_class: str | None
    message: str | None
    fingerprint: str | None = None


class CodexAuthSyncService:
    def __init__(
        self,
        *,
        file_target: CodexAuthTarget,
        env_target=None,
        account_store=None,
    ) -> None:
        del env_target
        self._file_target = file_target
        self._account_store = account_store

    def import_auth_json(self, *, slot: int, occurred_at: datetime) -> CodexSyncResult:
        try:
            payload = self._file_target.read_source_auth_json()
            normalized = self._normalize_auth_json(payload)
            fingerprint = self._fingerprint_auth_json(normalized)
        except Exception as exc:
            return self._finalize_result(
                occurred_at=occurred_at,
                active_slot=slot,
                result=self._failure_result(exc),
            )

        return self._finalize_result(
            occurred_at=occurred_at,
            active_slot=slot,
            result=CodexSyncResult(
                outcome="imported",
                method="file",
                failure_class=None,
                message=None,
                fingerprint=fingerprint,
            ),
        )

    def sync_active_slot(
        self,
        *,
        active_slot: int,
        email: str,
        session_token: str,
        csrf_token: str | None,
        codex_auth_json: dict[str, object] | None = None,
        occurred_at: datetime,
    ) -> CodexSyncResult:
        if codex_auth_json is None:
            return self._finalize_result(
                occurred_at=occurred_at,
                active_slot=active_slot,
                result=CodexSyncResult(
                    outcome="failed",
                    method=None,
                    failure_class="codex-auth-source-missing",
                    message=(
                        "codex-auth-source-missing: no imported auth.json stored for this slot"
                    ),
                ),
            )

        try:
            normalized = self._normalize_auth_json(codex_auth_json)
            self._file_target.apply_auth_json(normalized, occurred_at=occurred_at)
        except Exception as exc:
            return self._finalize_result(
                occurred_at=occurred_at,
                active_slot=active_slot,
                result=self._failure_result(exc),
            )

        return self._finalize_result(
            occurred_at=occurred_at,
            active_slot=active_slot,
            result=CodexSyncResult(
                outcome="ok",
                method="file",
                failure_class=None,
                message=None,
                fingerprint=self._fingerprint_auth_json(normalized),
            ),
        )

    def fingerprint_auth_json(self, payload: dict[str, object]) -> str:
        return self._fingerprint_auth_json(self._normalize_auth_json(payload))

    def has_drift(
        self,
        *,
        stored_auth_json: dict[str, object] | None,
        live_fingerprint: str | None,
    ) -> bool:
        if stored_auth_json is None or live_fingerprint is None:
            return False
        return self.fingerprint_auth_json(stored_auth_json) != live_fingerprint

    def read_live_fingerprint(self) -> str | None:
        try:
            payload = self._file_target.read_source_auth_json()
            return self._fingerprint_auth_json(self._normalize_auth_json(payload))
        except Exception:
            return None

    def read_live_auth_json(self) -> dict[str, object]:
        return self._normalize_auth_json(self._file_target.read_source_auth_json())

    def resolve_auth_email(self, payload: dict[str, object] | None = None) -> str | None:
        try:
            normalized = (
                self.read_live_auth_json()
                if payload is None
                else self._normalize_auth_json(payload)
            )
        except Exception:
            return None
        tokens = normalized.get("tokens")
        if not isinstance(tokens, dict):
            return None
        return _resolve_email_from_tokens(tokens)

    def _normalize_auth_json(self, payload: object) -> dict[str, object]:
        return _normalize_auth_json_payload(payload, occurred_at=None)

    def _fingerprint_auth_json(self, payload: dict[str, object]) -> str:
        return _fingerprint_auth_json_payload(payload)

    def _failure_result(self, exc: Exception) -> CodexSyncResult:
        message = self._redact_failure_message(str(exc)) or "Codex auth sync failed."
        failure_class = self._classify_error(message)
        return CodexSyncResult(
            outcome="failed",
            method=None,
            failure_class=failure_class,
            message=message,
        )

    def _redact_failure_message(self, message: str) -> str:
        redacted = redact_text(message) or ""
        return _TOKEN_REDACTION_PATTERN.sub(
            lambda match: f"{match.group('key')}=[redacted]",
            redacted,
        )

    def _classify_error(self, message: str) -> str:
        for failure_class in _KNOWN_FAILURE_PREFIXES:
            if message == failure_class or message.startswith(f"{failure_class}:"):
                return failure_class
        return "codex-auth-write-failed"

    def _finalize_result(
        self,
        *,
        occurred_at: datetime,
        active_slot: int | None,
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
                    fingerprint=result.fingerprint,
                )
            except TypeError:
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
            except Exception:
                pass
        return result


class CodexFileAuthTarget:
    def __init__(
        self,
        *,
        auth_file_path: Path | None = None,
    ) -> None:
        self._auth_file_path = auth_file_path

    def read_source_auth_json(self) -> dict[str, object]:
        auth_file_path = self._require_auth_file_path()
        if not auth_file_path.exists():
            raise RuntimeError("codex-auth-source-missing: live auth.json file not found")

        try:
            payload = json.loads(auth_file_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError("codex-auth-write-failed: unable to read auth.json") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("codex-auth-format-invalid: auth.json is not valid JSON") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("codex-auth-format-invalid: auth.json must be a JSON object")
        return payload

    def apply_auth_json(
        self,
        payload: dict[str, object],
        *,
        occurred_at: datetime,
    ) -> None:
        auth_file_path = self._require_auth_file_path()
        normalized = _normalize_auth_json_payload(payload, occurred_at=occurred_at)
        temp_path = auth_file_path.with_suffix(auth_file_path.suffix + ".tmp")

        try:
            auth_file_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(
                json.dumps(normalized, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(auth_file_path)
        except OSError as exc:
            raise RuntimeError("codex-auth-write-failed: unable to write auth.json") from exc

    def _require_auth_file_path(self) -> Path:
        if self._auth_file_path is None:
            raise RuntimeError("codex-auth-source-missing: auth.json path is not configured")
        return self._auth_file_path


class CodexEnvAuthTarget:
    def read_source_auth_json(self) -> dict[str, object]:
        raise RuntimeError("codex-auth-source-missing: env projection is not supported")

    def apply_auth_json(
        self,
        payload: dict[str, object],
        *,
        occurred_at: datetime,
    ) -> None:
        del payload, occurred_at
        raise RuntimeError("codex-auth-source-missing: env projection is not supported")

def raise_for_failed_sync(result: CodexSyncResult) -> None:
    if result.outcome != "failed":
        return
    raise CodexAuthSyncFailedError(
        result.message or result.failure_class or "Codex auth sync failed.",
        failure_class=result.failure_class,
    )

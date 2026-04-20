import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import threading
from typing import Any
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

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
    def __init__(
        self,
        *,
        managed_browser=None,
        auth_file_path: Path | None = None,
        authorization_endpoint: str = "https://auth.openai.com/authorize",
        token_endpoint: str = "https://auth0.openai.com/oauth/token",
        client_id: str = "app_EMoamEEZ73f0CkXaXp7hrann",
        callback_port: int = 1455,
    ) -> None:
        self._managed_browser = managed_browser
        self._auth_file_path = auth_file_path
        self._authorization_endpoint = authorization_endpoint
        self._token_endpoint = token_endpoint
        self._client_id = client_id
        self._callback_port = callback_port

    def apply(self, *, email: str, session_token: str, csrf_token: str | None) -> str:
        if self._managed_browser is None or self._auth_file_path is None:
            raise RuntimeError("codex-auth-target-missing")

        context, page = self._managed_browser.ensure_runtime()
        self._managed_browser.prepare_switch(
            context,
            page,
            session_token=session_token,
            csrf_token=csrf_token,
        )
        tokens = self._run_oauth_code_flow(page, email)
        account_id = self._extract_chatgpt_account_id(tokens.get("id_token"))
        if account_id is None:
            raise RuntimeError("codex-auth-verify-failed")
        self._write_auth_file(
            {
                "OPENAI_API_KEY": None,
                "auth_mode": "chatgpt",
                "last_refresh": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "tokens": {
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens["refresh_token"],
                    "id_token": tokens["id_token"],
                    "account_id": account_id,
                },
            }
        )
        return "file"

    def _run_oauth_code_flow(self, page, email: str) -> dict[str, str]:
        del email
        redirect_uri = f"http://localhost:{self._callback_port}/auth/callback"
        code_verifier = self._build_code_verifier()
        state = secrets.token_urlsafe(24)
        callback = self._wait_for_callback(page, redirect_uri, code_verifier, state)
        code = callback.get("code")
        if not isinstance(code, str) or not code:
            raise RuntimeError("codex-auth-verify-failed")
        return self._exchange_code(
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )

    def _wait_for_callback(
        self,
        page,
        redirect_uri: str,
        code_verifier: str,
        state: str,
    ) -> dict[str, str]:
        callback: dict[str, str] = {}
        error: dict[str, str] = {}
        challenge = self._build_code_challenge(code_verifier)
        authorize_url = (
            f"{self._authorization_endpoint}?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": self._client_id,
                    "redirect_uri": redirect_uri,
                    "scope": "openid profile email offline_access",
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                if parsed.path != "/auth/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                if query.get("state", [None])[0] != state:
                    error["message"] = "codex-auth-verify-failed"
                elif "error" in query:
                    error["message"] = "codex-auth-verify-failed"
                else:
                    code = query.get("code", [None])[0]
                    if isinstance(code, str) and code:
                        callback["code"] = code
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Codex login completed. You can close this window.")

            def log_message(self, format, *args):
                del format, args

        try:
            server = HTTPServer(("127.0.0.1", self._callback_port), CallbackHandler)
        except OSError as exc:
            raise RuntimeError("codex-auth-write-failed") from exc

        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        try:
            page.goto(authorize_url, wait_until="domcontentloaded", timeout=60_000)
            thread.join(timeout=60)
        finally:
            server.server_close()
        if error:
            raise RuntimeError(error["message"])
        if "code" not in callback:
            raise RuntimeError("codex-auth-verify-failed")
        return callback

    def _exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> dict[str, str]:
        body = urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self._client_id,
                "code_verifier": code_verifier,
            }
        ).encode("utf-8")
        request = Request(
            self._token_endpoint,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError("codex-auth-write-failed") from exc
        required = ("access_token", "refresh_token", "id_token")
        if any(not isinstance(payload.get(key), str) or not payload.get(key) for key in required):
            raise RuntimeError("codex-auth-verify-failed")
        return {key: payload[key] for key in required}

    def _extract_chatgpt_account_id(self, id_token: str | None) -> str | None:
        if not isinstance(id_token, str) or "." not in id_token:
            return None
        try:
            payload_segment = id_token.split(".")[1]
            payload_segment += "=" * (-len(payload_segment) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_segment))
        except (ValueError, json.JSONDecodeError):
            return None
        auth_claim = payload.get("https://api.openai.com/auth")
        if not isinstance(auth_claim, dict):
            return None
        account_id = auth_claim.get("chatgpt_account_id")
        return account_id if isinstance(account_id, str) and account_id else None

    def _write_auth_file(self, payload: dict[str, Any]) -> None:
        auth_file_path = self._auth_file_path
        if auth_file_path is None:
            raise RuntimeError("codex-auth-target-missing")
        auth_file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = auth_file_path.with_suffix(auth_file_path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(auth_file_path)

    def _build_code_verifier(self) -> str:
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")

    def _build_code_challenge(self, code_verifier: str) -> str:
        digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class CodexEnvAuthTarget:
    def apply(self, *, email: str, session_token: str, csrf_token: str | None) -> str:
        del email, session_token, csrf_token
        raise RuntimeError("codex-auth-target-missing")


def raise_for_failed_sync(result: CodexSyncResult) -> None:
    if result.outcome != "failed":
        return
    raise CodexAuthSyncFailedError(
        result.message or result.failure_class or "Codex auth sync failed.",
        failure_class=result.failure_class,
    )

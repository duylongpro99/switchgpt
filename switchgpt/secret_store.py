import json
from dataclasses import asdict, dataclass

import keyring

from .errors import SecretStoreError


@dataclass(frozen=True)
class CodexAuthPayload:
    access_token: str
    refresh_token: str
    id_token: str
    account_id: str


@dataclass(frozen=True)
class SessionSecret:
    session_token: str
    csrf_token: str | None
    codex_auth_json: dict[str, object] | None = None


class KeychainSecretStore:
    def __init__(self, service_name: str, backend=keyring) -> None:
        self._service_name = service_name
        self._backend = backend

    def write(self, key: str, secret: SessionSecret) -> None:
        self._backend.set_password(self._service_name, key, json.dumps(asdict(secret)))

    def read(self, key: str) -> SessionSecret | None:
        try:
            raw = self._backend.get_password(self._service_name, key)
        except Exception as exc:
            raise SecretStoreError("Secret backend read failed.") from exc
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            return self._load_secret(payload)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise SecretStoreError("Malformed secret payload.") from exc

    def _load_secret(self, payload: object) -> SessionSecret:
        if not isinstance(payload, dict):
            raise SecretStoreError("Malformed secret payload.")

        session_token = payload.get("session_token")
        csrf_token = payload.get("csrf_token")
        if type(session_token) is not str:
            raise SecretStoreError("Malformed secret payload.")
        if csrf_token is not None and type(csrf_token) is not str:
            raise SecretStoreError("Malformed secret payload.")
        codex_auth_json_raw = payload.get("codex_auth_json")
        if codex_auth_json_raw is None:
            codex_auth_json_raw = self._load_legacy_codex_auth_payload(payload.get("codex_auth_payload"))
        codex_auth_json = self._load_codex_auth_json(codex_auth_json_raw)
        return SessionSecret(
            session_token=session_token,
            csrf_token=csrf_token,
            codex_auth_json=codex_auth_json,
        )

    def _load_codex_auth_json(
        self,
        payload: object,
    ) -> dict[str, object] | None:
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise SecretStoreError("Malformed secret payload.")
        tokens = payload.get("tokens")
        if not isinstance(tokens, dict):
            raise SecretStoreError("Malformed secret payload.")
        required = ("access_token", "refresh_token", "id_token", "account_id")
        if not all(type(tokens.get(key)) is str and tokens.get(key) for key in required):
            raise SecretStoreError("Malformed secret payload.")
        return payload

    def _load_legacy_codex_auth_payload(self, payload: object) -> dict[str, object] | None:
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise SecretStoreError("Malformed secret payload.")
        required = ("access_token", "refresh_token", "id_token", "account_id")
        if not all(type(payload.get(key)) is str and payload.get(key) for key in required):
            raise SecretStoreError("Malformed secret payload.")
        return {
            "tokens": {
                "access_token": payload["access_token"],
                "refresh_token": payload["refresh_token"],
                "id_token": payload["id_token"],
                "account_id": payload["account_id"],
            }
        }

    def exists(self, key: str) -> bool:
        return self.read(key) is not None

    def replace(self, key: str, secret: SessionSecret) -> None:
        self.write(key, secret)

    def delete(self, key: str) -> None:
        self._backend.delete_password(self._service_name, key)

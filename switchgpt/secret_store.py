import json
from dataclasses import asdict, dataclass

import keyring

from .errors import SecretStoreError


@dataclass(frozen=True)
class SessionSecret:
    session_token: str
    csrf_token: str | None


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
        return SessionSecret(session_token=session_token, csrf_token=csrf_token)

    def exists(self, key: str) -> bool:
        return self.read(key) is not None

    def replace(self, key: str, secret: SessionSecret) -> None:
        self.write(key, secret)

    def delete(self, key: str) -> None:
        self._backend.delete_password(self._service_name, key)

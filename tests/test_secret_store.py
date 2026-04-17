from switchgpt.secret_store import KeychainSecretStore, SessionSecret
from switchgpt.errors import SecretStoreError


class FakeKeyring:
    def __init__(self) -> None:
        self.values = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


class FailingReadKeyring(FakeKeyring):
    def get_password(self, service: str, username: str) -> str | None:
        raise RuntimeError("backend unavailable")


def test_write_and_read_secret_round_trip() -> None:
    store = KeychainSecretStore(service_name="switchgpt", backend=FakeKeyring())
    secret = SessionSecret(session_token="token-1", csrf_token="csrf-1")
    store.write("switchgpt_account_0", secret)
    assert store.read("switchgpt_account_0") == secret


def test_replace_keeps_old_secret_until_new_secret_is_ready() -> None:
    store = KeychainSecretStore(service_name="switchgpt", backend=FakeKeyring())
    store.write(
        "switchgpt_account_0",
        SessionSecret(session_token="old", csrf_token="old"),
    )
    store.replace(
        "switchgpt_account_0",
        SessionSecret(session_token="new", csrf_token="new"),
    )
    assert store.read("switchgpt_account_0").session_token == "new"


def test_read_raises_store_error_for_malformed_json() -> None:
    backend = FakeKeyring()
    backend.set_password("switchgpt", "switchgpt_account_0", "{not-json")
    store = KeychainSecretStore(service_name="switchgpt", backend=backend)

    try:
        store.read("switchgpt_account_0")
    except SecretStoreError as exc:
        assert str(exc) == "Malformed secret payload."
    else:
        raise AssertionError("Expected SecretStoreError")


def test_read_raises_store_error_for_malformed_payload_shape() -> None:
    backend = FakeKeyring()
    backend.set_password("switchgpt", "switchgpt_account_0", "[]")
    store = KeychainSecretStore(service_name="switchgpt", backend=backend)

    try:
        store.read("switchgpt_account_0")
    except SecretStoreError as exc:
        assert str(exc) == "Malformed secret payload."
    else:
        raise AssertionError("Expected SecretStoreError")


def test_read_raises_store_error_for_wrong_typed_fields() -> None:
    backend = FakeKeyring()
    backend.set_password(
        "switchgpt",
        "switchgpt_account_0",
        '{"session_token": 123, "csrf_token": "csrf-1"}',
    )
    store = KeychainSecretStore(service_name="switchgpt", backend=backend)

    try:
        store.read("switchgpt_account_0")
    except SecretStoreError as exc:
        assert str(exc) == "Malformed secret payload."
    else:
        raise AssertionError("Expected SecretStoreError")


def test_read_raises_store_error_for_backend_failure() -> None:
    store = KeychainSecretStore(
        service_name="switchgpt",
        backend=FailingReadKeyring(),
    )

    try:
        store.read("switchgpt_account_0")
    except SecretStoreError as exc:
        assert str(exc) == "Secret backend read failed."
    else:
        raise AssertionError("Expected SecretStoreError")

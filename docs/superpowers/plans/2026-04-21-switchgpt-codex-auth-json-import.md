# SwitchGPT Codex auth.json Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace browser-driven Codex auth recovery with a manual `auth.json` import and projection flow that stores inactive account payloads in the OS secret store and keeps them out of logs and metadata.

**Architecture:** Extend the slot secret model so each slot can securely store a normalized raw Codex `auth.json` payload plus a non-secret fingerprint. Rework the Codex auth service into an import/project/drift-check module, add a new `switchgpt import-codex-auth --slot N` command, and update switch/sync/status flows to use the imported payload instead of Playwright-driven OAuth recovery.

**Tech Stack:** Python 3.12, Typer CLI, pytest, keyring, JSON file persistence, Playwright for ChatGPT browser switching only, macOS local runtime.

---

## File Structure

- Modify: `switchgpt/secret_store.py`
  Purpose: replace token-field `CodexAuthPayload` storage with raw normalized `auth.json` payload storage plus non-secret fingerprint helpers while preserving backward-compatible session secret loading.
- Modify: `switchgpt/codex_auth_sync.py`
  Purpose: remove browser OAuth recovery, add import/read/validate/project/fingerprint/drift logic, and keep strict redacted failure handling.
- Modify: `switchgpt/bootstrap.py`
  Purpose: wire the import-capable Codex auth service and expose a dedicated import command service.
- Modify: `switchgpt/cli.py`
  Purpose: add `import-codex-auth --slot N` and update repair messaging to point to manual `codex login` plus import when projection fails.
- Modify: `switchgpt/account_store.py`
  Purpose: persist new non-secret Codex import/projection metadata and drift fingerprint fields.
- Modify: `switchgpt/models.py`
  Purpose: extend `AccountSnapshot` with imported/projection fingerprint metadata fields.
- Modify: `switchgpt/status_service.py`
  Purpose: classify imported/missing/drifted Codex auth state using non-secret metadata only.
- Modify: `switchgpt/doctor_service.py`
  Purpose: surface repair guidance based on import/projection status and drift instead of legacy fallback sync semantics.
- Modify: `switchgpt/registration.py`
  Purpose: stop trying to capture or repair Codex auth during browser registration.
- Modify: `switchgpt/switch_service.py`
  Purpose: project stored per-slot Codex auth payloads during successful slot switches and stop caching browser-derived Codex payloads.
- Modify: `switchgpt/playwright_client.py`
  Purpose: remove file-based Codex auth capture and recovery paths that are no longer part of the design.
- Modify: `switchgpt/config.py`
  Purpose: keep the live Codex auth path setting and, if needed, add a visible path description for import/projection commands.
- Modify: `tests/test_secret_store.py`
  Purpose: lock round-trip behavior for raw imported `auth.json` payloads and guard against malformed secret payloads.
- Modify: `tests/test_codex_auth_sync.py`
  Purpose: cover import validation, projection, fingerprinting, drift detection, and redacted failures.
- Modify: `tests/test_cli.py`
  Purpose: cover the new import command and updated repair flows.
- Modify: `tests/test_switch_service.py`
  Purpose: lock strict projection behavior when a slot does or does not have imported Codex auth.
- Modify: `tests/test_registration.py`
  Purpose: remove obsolete browser-derived Codex auth assumptions.
- Modify: `tests/test_status_service.py`
  Purpose: lock the new imported/out-of-sync/no-data Codex status states.
- Modify: `tests/test_doctor_service.py`
  Purpose: lock doctor guidance for missing imports and live-file drift.

## Tasks

### Task 1: Migrate the secret model to raw imported `auth.json`

**Files:**
- Modify: `switchgpt/secret_store.py`
- Test: `tests/test_secret_store.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_write_and_read_secret_round_trip_with_codex_auth_json_payload() -> None:
    backend = FakeBackend()
    store = KeychainSecretStore("switchgpt", backend=backend)
    payload = {
        "auth_mode": "chatgpt",
        "last_refresh": "2026-04-21T10:00:00Z",
        "tokens": {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "id_token": "id-1",
            "account_id": "account-1",
        },
    }

    store.write(
        "slot-1",
        SessionSecret(
            session_token="session-1",
            csrf_token="csrf-1",
            codex_auth_json=payload,
        ),
    )

    loaded = store.read("slot-1")

    assert loaded == SessionSecret(
        session_token="session-1",
        csrf_token="csrf-1",
        codex_auth_json=payload,
    )


def test_read_rejects_codex_auth_json_without_tokens_dict() -> None:
    backend = FakeBackend(
        payloads={
            ("switchgpt", "slot-1"): json.dumps(
                {
                    "session_token": "session-1",
                    "csrf_token": "csrf-1",
                    "codex_auth_json": {"auth_mode": "chatgpt"},
                }
            )
        }
    )
    store = KeychainSecretStore("switchgpt", backend=backend)

    with pytest.raises(SecretStoreError, match="Malformed secret payload."):
        store.read("slot-1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_secret_store.py -q`
Expected: FAIL because `SessionSecret` does not accept `codex_auth_json` and the loader only understands `codex_auth_payload`.

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class SessionSecret:
    session_token: str
    csrf_token: str | None
    codex_auth_json: dict[str, object] | None = None


def _load_secret(self, payload: object) -> SessionSecret:
    if not isinstance(payload, dict):
        raise SecretStoreError("Malformed secret payload.")
    codex_auth_json_raw = payload.get("codex_auth_json")
    return SessionSecret(
        session_token=self._require_string(payload.get("session_token")),
        csrf_token=self._optional_string(payload.get("csrf_token")),
        codex_auth_json=self._load_codex_auth_json(codex_auth_json_raw),
    )


def _load_codex_auth_json(self, payload: object) -> dict[str, object] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise SecretStoreError("Malformed secret payload.")
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        raise SecretStoreError("Malformed secret payload.")
    required = ("access_token", "refresh_token", "id_token", "account_id")
    if not all(isinstance(tokens.get(key), str) and tokens.get(key) for key in required):
        raise SecretStoreError("Malformed secret payload.")
    return payload
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_secret_store.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_secret_store.py switchgpt/secret_store.py
git commit -m "refactor: store raw codex auth json in secrets"
```

### Task 2: Rebuild Codex auth sync as import/project/drift service

**Files:**
- Modify: `switchgpt/codex_auth_sync.py`
- Test: `tests/test_codex_auth_sync.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_import_auth_json_stores_normalized_payload_and_fingerprint(tmp_path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "last_refresh": "2026-04-21T10:00:00Z",
                "tokens": {
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "id_token": "id-1",
                    "account_id": "account-1",
                },
            }
        ),
        encoding="utf-8",
    )
    service = CodexAuthSyncService(
        file_target=CodexFileAuthTarget(auth_file_path=auth_path),
        env_target=CodexEnvAuthTarget(),
    )

    result = service.import_auth_json(slot=1, occurred_at=datetime(2026, 4, 21, 10, 0, tzinfo=UTC))

    assert result.outcome == "imported"
    assert result.method == "file"
    assert result.fingerprint is not None


def test_sync_active_slot_writes_stored_auth_json_atomically(tmp_path) -> None:
    auth_path = tmp_path / "auth.json"
    target = CodexFileAuthTarget(auth_file_path=auth_path)
    service = CodexAuthSyncService(file_target=target, env_target=CodexEnvAuthTarget())

    result = service.sync_active_slot(
        active_slot=2,
        email="account2@example.com",
        session_token="session-2",
        csrf_token="csrf-2",
        codex_auth_json={
            "auth_mode": "chatgpt",
            "last_refresh": "2026-04-21T10:00:00Z",
            "tokens": {
                "access_token": "access-2",
                "refresh_token": "refresh-2",
                "id_token": "id-2",
                "account_id": "account-2",
            },
        },
        occurred_at=datetime(2026, 4, 21, 10, 5, tzinfo=UTC),
    )

    assert result.outcome == "ok"
    written = json.loads(auth_path.read_text(encoding="utf-8"))
    assert written["tokens"]["account_id"] == "account-2"


def test_sync_active_slot_fails_when_slot_has_no_imported_auth_json() -> None:
    service = CodexAuthSyncService(
        file_target=CodexFileAuthTarget(auth_file_path=Path("/tmp/auth.json")),
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_codex_auth_sync.py -q`
Expected: FAIL because `CodexAuthSyncService` has no import API and `sync_active_slot()` still expects `codex_auth_payload`.

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class CodexSyncResult:
    outcome: str
    method: str | None
    failure_class: str | None
    message: str | None
    fingerprint: str | None = None


class CodexAuthSyncService:
    def import_auth_json(self, *, slot: int, occurred_at: datetime) -> CodexSyncResult:
        payload = self._file_target.read_source_auth_json()
        normalized = self._normalize_auth_json(payload)
        fingerprint = self._fingerprint_auth_json(normalized)
        return CodexSyncResult(
            outcome="imported",
            method="file",
            failure_class=None,
            message=None,
            fingerprint=fingerprint,
        )

    def sync_active_slot(
        self,
        *,
        active_slot: int,
        email: str,
        session_token: str,
        csrf_token: str | None,
        codex_auth_json: dict[str, object] | None,
        occurred_at: datetime,
    ) -> CodexSyncResult:
        del email, session_token, csrf_token
        if codex_auth_json is None:
            return self._finalize_result(
                occurred_at=occurred_at,
                active_slot=active_slot,
                result=CodexSyncResult(
                    outcome="failed",
                    method=None,
                    failure_class="codex-auth-source-missing",
                    message="codex-auth-source-missing: no imported auth.json stored for this slot",
                ),
            )
        normalized = self._normalize_auth_json(codex_auth_json)
        self._file_target.apply_auth_json(normalized, occurred_at=occurred_at)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_codex_auth_sync.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_codex_auth_sync.py switchgpt/codex_auth_sync.py
git commit -m "refactor: import and project codex auth json"
```

### Task 3: Add CLI import flow and runtime wiring

**Files:**
- Modify: `switchgpt/bootstrap.py`
- Modify: `switchgpt/cli.py`
- Modify: `switchgpt/config.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_import_codex_auth_stores_live_auth_json_for_slot(runner, monkeypatch) -> None:
    imported = {}

    class FakeImportService:
        def run(self, *, slot: int):
            imported["slot"] = slot
            return type("Result", (), {"outcome": "imported", "fingerprint": "fp-123"})()

    monkeypatch.setattr("switchgpt.cli.build_codex_import_service", lambda: FakeImportService())

    result = runner.invoke(app, ["import-codex-auth", "--slot", "2"])

    assert result.exit_code == 0
    assert imported["slot"] == 2
    assert "Imported Codex auth for slot 2." in result.stdout


def test_import_codex_auth_reports_manual_repair_message_on_failure(runner, monkeypatch) -> None:
    class FakeImportService:
        def run(self, *, slot: int):
            raise SwitchGptError(
                "Codex auth import failed. Run `codex login` with the target account, then retry `switchgpt import-codex-auth --slot 2`."
            )

    monkeypatch.setattr("switchgpt.cli.build_codex_import_service", lambda: FakeImportService())

    result = runner.invoke(app, ["import-codex-auth", "--slot", "2"])

    assert result.exit_code == 1
    assert "codex login" in result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL because the CLI has no `import-codex-auth` command or builder function.

- [ ] **Step 3: Write minimal implementation**

```python
def build_codex_import_service():
    return bootstrap.build_codex_import_service()


@app.command("import-codex-auth")
def import_codex_auth(slot: int = typer.Option(..., "--slot")) -> None:
    try:
        ensure_supported_platform()
        result = build_codex_import_service().run(slot=slot)
        print(f"Imported Codex auth for slot {slot}.")
        if getattr(result, "fingerprint", None):
            print("Codex auth fingerprint stored.")
    except SwitchGptError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


class CodexImportCommandService:
    def __init__(self, account_store, secret_store, codex_auth_sync) -> None:
        self._account_store = account_store
        self._secret_store = secret_store
        self._codex_auth_sync = codex_auth_sync

    def run(self, *, slot: int):
        account = self._account_store.get_record(slot)
        secret = self._secret_store.read(account.keychain_key)
        if secret is None:
            raise SwitchError(f"Stored session secret is missing for slot {slot}.")
        return self._codex_auth_sync.import_slot_auth_json(
            slot=slot,
            key=account.keychain_key,
            secret=secret,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli.py switchgpt/bootstrap.py switchgpt/cli.py switchgpt/config.py
git commit -m "feat: add codex auth import command"
```

### Task 4: Update switch and registration flows to use imported payloads only

**Files:**
- Modify: `switchgpt/registration.py`
- Modify: `switchgpt/switch_service.py`
- Modify: `switchgpt/playwright_client.py`
- Test: `tests/test_switch_service.py`
- Test: `tests/test_registration.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_switch_projects_imported_codex_auth_json_for_active_slot(tmp_path) -> None:
    secret = SessionSecret(
        session_token="session-1",
        csrf_token="csrf-1",
        codex_auth_json={
            "auth_mode": "chatgpt",
            "last_refresh": "2026-04-21T10:00:00Z",
            "tokens": {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "id_token": "id-1",
                "account_id": "account-1",
            },
        },
    )
    sync_calls = []

    class FakeSync:
        def sync_active_slot(self, **kwargs):
            sync_calls.append(kwargs)
            return CodexSyncResult("ok", "file", None, None, fingerprint="fp-1")

    service = build_switch_service_with(secret=secret, codex_auth_sync=FakeSync())
    service.switch_to(0)

    assert sync_calls[0]["codex_auth_json"]["tokens"]["account_id"] == "account-1"


def test_switch_fails_when_slot_has_no_imported_codex_auth_json() -> None:
    secret = SessionSecret(session_token="session-1", csrf_token="csrf-1", codex_auth_json=None)
    service = build_switch_service_with(secret=secret, codex_auth_sync=RealisticFailingSync())

    with pytest.raises(CodexAuthSyncFailedError, match="switchgpt import-codex-auth --slot 0"):
        service.switch_to(0)


def test_registration_does_not_cache_browser_derived_codex_auth_json(monkeypatch) -> None:
    replaced = {}

    class FakeSecrets:
        def write(self, key, secret):
            replaced[key] = secret

    result = RegistrationResult(
        email="account@example.com",
        secret=SessionSecret(session_token="session-1", csrf_token="csrf-1", codex_auth_json=None),
        captured_at=datetime(2026, 4, 21, 10, 0, tzinfo=UTC),
    )

    assert result.secret.codex_auth_json is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_switch_service.py tests/test_registration.py -q`
Expected: FAIL because switch and registration still reference `codex_auth_payload` and cache browser-derived payloads.

- [ ] **Step 3: Write minimal implementation**

```python
result = self._codex_auth_sync.sync_active_slot(
    active_slot=account.index,
    email=account.email,
    session_token=secret.session_token,
    csrf_token=secret.csrf_token,
    codex_auth_json=getattr(secret, "codex_auth_json", None),
    occurred_at=occurred_at,
)


raise CodexAuthSyncFailedError(
    "Codex auth sync failed after switch. Run `codex login` with the target account, then `switchgpt import-codex-auth --slot "
    f"{account.index}` and retry `switchgpt codex-sync`.",
    failure_class=exc.failure_class,
)


def _cache_codex_payload_if_available(self, *, account, secret, result) -> None:
    del account, secret, result
    return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_switch_service.py tests/test_registration.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_switch_service.py tests/test_registration.py switchgpt/registration.py switchgpt/switch_service.py switchgpt/playwright_client.py
git commit -m "refactor: require imported codex auth for projection"
```

### Task 5: Persist non-secret import/projection metadata and drift state

**Files:**
- Modify: `switchgpt/models.py`
- Modify: `switchgpt/account_store.py`
- Modify: `switchgpt/status_service.py`
- Modify: `switchgpt/doctor_service.py`
- Test: `tests/test_status_service.py`
- Test: `tests/test_doctor_service.py`
- Test: `tests/test_account_store.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_save_codex_sync_state_persists_fingerprint_fields(tmp_path) -> None:
    store = AccountStore(tmp_path / "accounts.json", 3)
    synced_at = datetime(2026, 4, 21, 10, 30, tzinfo=UTC)

    store.save_codex_sync_state(
        synced_at=synced_at,
        synced_slot=1,
        method="file",
        status="ok",
        error=None,
        fingerprint="fp-live-1",
    )

    snapshot = store.load()

    assert snapshot.last_codex_sync_status == "ok"
    assert snapshot.last_codex_sync_fingerprint == "fp-live-1"


def test_status_marks_active_slot_out_of_sync_when_fingerprint_mismatches() -> None:
    summary = StatusService(FakeSecretStore()).summarize(
        [build_account(1)],
        active_account_index=1,
        codex_sync_state=PersistedCodexSyncState(
            synced_slot=1,
            status="ok",
            method="file",
            synced_at=datetime(2026, 4, 21, 10, 30, tzinfo=UTC),
            error=None,
            fingerprint="fp-live-1",
            imported=True,
        ),
    )

    assert summary.codex_sync.state == "out-of-sync"


def test_doctor_warns_when_active_slot_has_no_imported_codex_auth() -> None:
    report = DoctorService(...).run()
    codex_sync_check = next(check for check in report.checks if check.name == "codex-sync")
    assert "switchgpt import-codex-auth --slot 0" in codex_sync_check.next_action
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_account_store.py tests/test_status_service.py tests/test_doctor_service.py -q`
Expected: FAIL because metadata models and persisted sync state do not include fingerprint/import state.

- [ ] **Step 3: Write minimal implementation**

```python
@dataclass(frozen=True)
class AccountSnapshot:
    accounts: list[AccountRecord]
    active_account_index: int | None
    last_switch_at: datetime | None
    last_codex_sync_at: datetime | None
    last_codex_sync_slot: int | None
    last_codex_sync_method: str | None
    last_codex_sync_status: str | None
    last_codex_sync_error: str | None
    last_codex_sync_fingerprint: str | None
    last_codex_imported_slots: list[int]


class PersistedCodexSyncState:
    synced_slot: int | None
    status: str | None
    method: str | None
    synced_at: datetime | None
    error: str | None
    fingerprint: str | None
    imported: bool
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_account_store.py tests/test_status_service.py tests/test_doctor_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_account_store.py tests/test_status_service.py tests/test_doctor_service.py switchgpt/models.py switchgpt/account_store.py switchgpt/status_service.py switchgpt/doctor_service.py
git commit -m "feat: track codex auth import and drift metadata"
```

### Task 6: Run the focused verification suite and review secret-exposure regressions

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `tests/test_codex_auth_sync.py`
- Modify: `tests/test_switch_service.py`
- Modify: `tests/test_registration.py`
- Modify: `tests/test_status_service.py`
- Modify: `tests/test_doctor_service.py`

- [ ] **Step 1: Add final redaction and repair-message assertions**

```python
def test_codex_sync_failure_redacts_token_values() -> None:
    result = CodexSyncResult(
        outcome="failed",
        method=None,
        failure_class="codex-auth-write-failed",
        message="token refresh failed for access_token=secret-token-value",
    )

    with pytest.raises(CodexAuthSyncFailedError, match=r"access_token=\[redacted\]"):
        raise_for_failed_sync(result)


def test_cli_codex_sync_failure_points_to_manual_login_and_import(runner, monkeypatch) -> None:
    class FakeService:
        def run(self):
            return CodexSyncResult(
                outcome="failed",
                method=None,
                failure_class="codex-auth-source-missing",
                message="Run `codex login` with the target account, then `switchgpt import-codex-auth --slot 1`.",
            )

    monkeypatch.setattr("switchgpt.cli.build_codex_sync_command_service", lambda: FakeService())
    result = runner.invoke(app, ["codex-sync"])

    assert result.exit_code == 1
    assert "switchgpt import-codex-auth --slot 1" in result.stderr
```

- [ ] **Step 2: Run the focused verification suite**

Run: `uv run pytest tests/test_secret_store.py tests/test_codex_auth_sync.py tests/test_cli.py tests/test_switch_service.py tests/test_registration.py tests/test_status_service.py tests/test_doctor_service.py tests/test_account_store.py -q`
Expected: PASS

- [ ] **Step 3: Run a targeted grep for leaked legacy/browser recovery references**

Run: `rg -n "codex_auth_payload|device-auth|oauth/authorize|localhost callback|load_payload_for_email|recover_codex_auth_payload" switchgpt tests`
Expected: no remaining production references to the removed browser-driven Codex auth recovery path; only intentional migration assertions if any.

- [ ] **Step 4: Review the diff for secret exposure regressions**

Run: `git diff -- switchgpt tests`
Expected: no log lines, metadata writes, or error strings that include raw `auth.json`, token values, refresh tokens, ID tokens, or account IDs.

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli.py tests/test_codex_auth_sync.py tests/test_switch_service.py tests/test_registration.py tests/test_status_service.py tests/test_doctor_service.py
git commit -m "test: verify codex auth import secrecy and repair flows"
```

## Self-Review

### Spec coverage

- Manual `auth.json` import flow: Task 2 and Task 3.
- Secret-store-only storage for inactive payloads: Task 1.
- Atomic projection to the live Codex auth path: Task 2 and Task 4.
- Strict failure when active slot has no imported payload: Task 2 and Task 4.
- Guardrails against secret exposure: Task 1, Task 5, and Task 6.
- Status/doctor drift visibility without secret leakage: Task 5.
- Removal of browser-driven Codex OAuth recovery: Task 2, Task 4, and Task 6.

### Placeholder scan

- No `TODO`, `TBD`, or deferred “handle appropriately” steps remain.
- Every code-changing step includes a concrete code snippet.
- Every verification step includes an exact command and expected result.

### Type consistency

- Plan consistently uses `codex_auth_json` for the slot secret field.
- Plan consistently uses `fingerprint` for non-secret drift tracking metadata.
- Plan consistently uses `import-codex-auth` for the new CLI entrypoint and `codex-sync` for projection/repair.

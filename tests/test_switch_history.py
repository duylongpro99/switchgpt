from datetime import UTC, datetime
import json

import pytest

from switchgpt.errors import SwitchHistoryError
from switchgpt.switch_history import SwitchEvent, SwitchHistoryStore


def test_append_writes_single_json_line_event(tmp_path) -> None:
    store = SwitchHistoryStore(tmp_path / "switch-history.jsonl")

    store.append(
        SwitchEvent(
            occurred_at=datetime(2026, 4, 16, 11, 15, tzinfo=UTC),
            from_account_index=0,
            to_account_index=1,
            mode="explicit-target",
            result="success",
            message=None,
        )
    )

    lines = (tmp_path / "switch-history.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert '"to_account_index": 1' in lines[0]


def test_append_creates_parent_directory(tmp_path) -> None:
    history_path = tmp_path / "nested" / "switch-history.jsonl"
    store = SwitchHistoryStore(history_path)

    store.append(
        SwitchEvent(
            occurred_at=datetime(2026, 4, 16, 11, 15, tzinfo=UTC),
            from_account_index=None,
            to_account_index=0,
            mode="auto-target",
            result="success",
            message=None,
        )
    )

    assert history_path.exists()


def test_append_serializes_null_target_slot(tmp_path) -> None:
    store = SwitchHistoryStore(tmp_path / "switch-history.jsonl")

    store.append(
        SwitchEvent(
            occurred_at=datetime(2026, 4, 16, 11, 15, tzinfo=UTC),
            from_account_index=0,
            to_account_index=None,
            mode="auto-target",
            result="failure",
            message="metadata load failed",
        )
    )

    lines = (tmp_path / "switch-history.jsonl").read_text().splitlines()
    assert '"to_account_index": null' in lines[0]


def test_load_reads_switch_events_from_jsonl(tmp_path) -> None:
    history_path = tmp_path / "switch-history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "occurred_at": "2026-04-16T11:15:00+00:00",
                        "from_account_index": 0,
                        "to_account_index": 1,
                        "mode": "explicit-target",
                        "result": "success",
                        "message": None,
                    }
                ),
                json.dumps(
                    {
                        "occurred_at": "2026-04-16T11:20:00+00:00",
                        "from_account_index": 1,
                        "to_account_index": 0,
                        "mode": "auto-target",
                        "result": "failure",
                        "message": "metadata load failed",
                    }
                ),
            ]
        )
        + "\n"
    )

    store = SwitchHistoryStore(history_path)

    events = store.load()

    assert events == [
        SwitchEvent(
            occurred_at=datetime(2026, 4, 16, 11, 15, tzinfo=UTC),
            from_account_index=0,
            to_account_index=1,
            mode="explicit-target",
            result="success",
            message=None,
        ),
        SwitchEvent(
            occurred_at=datetime(2026, 4, 16, 11, 20, tzinfo=UTC),
            from_account_index=1,
            to_account_index=0,
            mode="auto-target",
            result="failure",
            message="metadata load failed",
        ),
    ]


def test_load_raises_coherent_error_for_malformed_jsonl(tmp_path) -> None:
    history_path = tmp_path / "switch-history.jsonl"
    history_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "occurred_at": "2026-04-16T11:15:00+00:00",
                        "from_account_index": 0,
                        "to_account_index": 1,
                        "mode": "explicit-target",
                        "result": "success",
                        "message": None,
                    }
                ),
                "{not-json}",
            ]
        )
        + "\n"
    )

    store = SwitchHistoryStore(history_path)

    with pytest.raises(SwitchHistoryError, match="Malformed switch history line 2"):
        store.load()

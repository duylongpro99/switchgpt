from datetime import UTC, datetime

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

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class SwitchEvent:
    occurred_at: datetime
    from_account_index: int | None
    to_account_index: int
    mode: str
    result: str
    message: str | None


class SwitchHistoryStore:
    def __init__(self, history_path: Path) -> None:
        self._history_path = history_path

    def append(self, event: SwitchEvent) -> None:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(event)
        payload["occurred_at"] = event.occurred_at.isoformat()
        with self._history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")

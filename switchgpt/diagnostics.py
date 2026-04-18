from dataclasses import dataclass
import re


_REDACTION_PATTERN = re.compile(
    r"\b(?P<key>session_token|csrf_token|cookie|authorization)=(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DiagnosticEvent:
    subsystem: str
    result: str
    message: str | None
    account_index: int | None = None


def redact_text(text: str | None) -> str | None:
    if text is None:
        return None
    return _REDACTION_PATTERN.sub(
        lambda match: f"{match.group('key')}=[redacted]",
        text,
    )


def format_event(event: DiagnosticEvent) -> str:
    prefix = f"[{event.subsystem}] {event.result}"
    if event.account_index is not None:
        prefix += f" slot={event.account_index}"
    message = event.message if event.message is not None else ""
    return f"{prefix}: {message}"

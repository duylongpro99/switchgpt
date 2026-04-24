from .config import SettingsItem
from .doctor_service import DoctorReport
from .status_service import StatusSummary


def render_settings_items(items: list[SettingsItem]) -> list[str]:
    lines: list[str] = []
    for item in items:
        lines.append(f"{item.name}: {item.value} [{item.category}]")
        lines.append(f"  {item.description}")
    return lines


def render_status_summary(summary: StatusSummary) -> list[str]:
    lines = [f"Readiness: {summary.readiness}"]
    if summary.active_account_index is not None:
        lines.append(f"Active slot: {summary.active_account_index}")
    if summary.codex_sync is not None:
        lines.append(f"Codex sync: {summary.codex_sync.state}")
        lines.append(f"Codex auth check: {summary.codex_sync.detail}")
        if summary.codex_sync.method is not None:
            lines.append(f"Codex sync method: {summary.codex_sync.method}")
        if summary.codex_sync.synced_at is not None:
            lines.append(f"Codex sync at: {summary.codex_sync.synced_at.isoformat()}")
        if summary.codex_sync.error is not None:
            lines.append(f"Codex sync error: {summary.codex_sync.error}")
    if summary.latest_result is not None:
        lines.append(f"Latest result: {summary.latest_result}")
    if summary.next_action is not None:
        lines.append(f"Next action: {summary.next_action}")
    if not summary.slots:
        lines.append("No registered slots.")
    else:
        for slot in summary.slots:
            lines.append(f"[{slot.index}] {slot.email} - {slot.state}")
    return lines


def render_doctor_report(report: DoctorReport) -> list[str]:
    lines = [f"Readiness: {report.readiness}"]
    for check in report.checks:
        lines.append(f"{check.name}: {check.status} - {check.detail}")
        if check.next_action:
            lines.append(f"next: {check.next_action}")
    return lines

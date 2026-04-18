from switchgpt.diagnostics import DiagnosticEvent, format_event, redact_text


def test_redact_text_masks_token_and_cookie_values() -> None:
    message = (
        "prepare_switch failed with session_token=abc123 "
        "csrf_token=def456 cookie=ghi789"
    )

    assert redact_text(message) == (
        "prepare_switch failed with session_token=[redacted] "
        "csrf_token=[redacted] cookie=[redacted]"
    )


def test_format_event_includes_subsystem_result_and_slot() -> None:
    event = DiagnosticEvent(
        subsystem="watch",
        result="switch-succeeded",
        message="Switched to slot 1.",
        account_index=1,
    )

    assert format_event(event) == "[watch] switch-succeeded slot=1: Switched to slot 1."

from app.logging import redact_secrets


def test_sensitive_structured_log_fields_are_redacted() -> None:
    event = redact_secrets(None, "info", {"event": "exchange", "token": "secret"})

    assert event == {"event": "exchange", "token": "[redacted]"}

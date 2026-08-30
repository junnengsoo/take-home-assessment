import json
import logging

from fastapi.testclient import TestClient
from lead_api.config import Settings, get_settings
from lead_api.database import database
from lead_api.main import app
from lead_api.observability import JsonLogFormatter
from lead_worker.outbox import QueuedNotification, notification_log_fields


def format_json_log(message: str, **extra):
    record = logging.LogRecord(
        name="lead-intake-test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    formatted = JsonLogFormatter(service="api", environment="test").format(record)
    return json.loads(formatted)


def test_json_logs_include_required_operational_fields_without_sensitive_values() -> None:
    payload = format_json_log(
        "token eyJabc.def.ghi failed for ada@example.com",
        correlation_id="req-123",
        route_template="/api/v1/leads",
        status=201,
        latency_ms=42,
        actor_attorney_id="11111111-1111-4111-8111-111111111111",
        lead_id="33333333-3333-4333-8333-333333333333",
        authorization="Bearer local-test-token",
        prospect_email="ada@example.com",
        original_filename="Ada Resume.pdf",
        remote_address="203.0.113.10",
    )

    assert payload["timestamp"]
    assert payload["severity"] == "INFO"
    assert payload["service"] == "api"
    assert payload["environment"] == "test"
    assert payload["correlation_id"] == "req-123"
    assert payload["route_template"] == "/api/v1/leads"
    assert payload["status"] == 201
    assert payload["latency_ms"] == 42
    assert payload["actor_attorney_id"] == "11111111-1111-4111-8111-111111111111"
    assert payload["lead_id"] == "33333333-3333-4333-8333-333333333333"

    serialized = json.dumps(payload)
    assert "ada@example.com" not in serialized
    assert "Ada Resume.pdf" not in serialized
    assert "203.0.113.10" not in serialized
    assert "eyJabc.def.ghi" not in serialized


def test_worker_delivery_log_fields_link_outbox_without_recipient_or_payload_pii() -> None:
    notification = QueuedNotification(
        id="10000000-0000-4000-8000-000000000001",
        kind="INTERNAL_NEW_LEAD",
        recipient_email="attorney.local@example.test",
        payload={
            "prospectName": "Ada Lovelace",
            "prospectEmail": "ada@example.com",
            "correlationId": "req-outbox-123",
        },
        attempt_count=0,
        lead_id="33333333-3333-4333-8333-333333333333",
    )

    fields = notification_log_fields(notification, "local-smtp")
    payload = format_json_log("email_delivery_sent", **fields)

    assert payload["correlation_id"] == "req-outbox-123"
    assert payload["lead_id"] == "33333333-3333-4333-8333-333333333333"
    assert payload["notification_id"] == "10000000-0000-4000-8000-000000000001"
    assert payload["notification_kind"] == "INTERNAL_NEW_LEAD"
    assert payload["provider"] == "local-smtp"

    serialized = json.dumps(payload)
    assert "attorney.local@example.test" not in serialized
    assert "ada@example.com" not in serialized
    assert "Ada Lovelace" not in serialized


def test_request_middleware_emits_correlation_header_and_log_record(
    caplog,
) -> None:
    caplog.set_level(logging.INFO, logger="lead_api.main")

    with TestClient(app) as client:
        response = client.get("/health/live", headers={"X-Request-ID": "req-health-123"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-health-123"
    request_logs = [
        record for record in caplog.records if record.getMessage() == "api_request_completed"
    ]
    assert request_logs
    assert request_logs[-1].correlation_id == "req-health-123"
    assert request_logs[-1].route_template == "/health/live"
    assert request_logs[-1].status == 200
    assert isinstance(request_logs[-1].latency_ms, int)


def test_readiness_stays_ready_when_storage_or_email_configuration_is_degraded(
    monkeypatch,
) -> None:
    get_settings.cache_clear()
    monkeypatch.setattr(
        "lead_api.main.get_settings",
        lambda: Settings(
            supabase_anon_key="test-anon-key",
            supabase_service_role_key="test-service-role-key",
            fallback_intake_address="intake.local@example.test",
            resume_bucket="temporarily-missing-bucket",
            email_smtp_host="mailpit-temporarily-down.local",
        ),
    )

    async def ready() -> bool:
        return True

    monkeypatch.setattr(database, "ready", ready)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    get_settings.cache_clear()

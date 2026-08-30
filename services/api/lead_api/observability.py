from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

SENSITIVE_FIELD_NAMES = {
    "authorization",
    "bearer",
    "body",
    "content",
    "email",
    "filename",
    "first_name",
    "last_name",
    "network_address",
    "original_filename",
    "prospect_email",
    "prospect_name",
    "raw_address",
    "remote_addr",
    "remote_address",
    "request_body",
    "resume_content",
    "token",
}

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")

RESERVED_LOG_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__)


class JsonLogFormatter(logging.Formatter):
    def __init__(self, *, service: str, environment: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "severity": record.levelname,
            "service": self.service,
            "environment": self.environment,
            "logger": record.name,
            "event": redact_text(record.getMessage()),
        }
        for key, value in sorted(record.__dict__.items()):
            if key in RESERVED_LOG_RECORD_FIELDS or key.startswith("_"):
                continue
            payload[key] = sanitize_log_value(key, value)
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def configure_logging(*, service: str, environment: str, force: bool = False) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    if not force:
        for handler in root.handlers:
            if getattr(handler, "_lead_intake_json_handler", False):
                return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter(service=service, environment=environment))
    handler._lead_intake_json_handler = True  # type: ignore[attr-defined]

    if force:
        root.handlers = [handler]
    else:
        root.addHandler(handler)


def sanitize_log_value(key: str, value: Any) -> Any:
    normalized_key = key.lower()
    if normalized_key in SENSITIVE_FIELD_NAMES or any(
        marker in normalized_key
        for marker in ("authorization", "bearer", "password", "secret", "token")
    ):
        return "[REDACTED]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            str(item_key): sanitize_log_value(str(item_key), item_value)
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_log_value(key, item) for item in value]
    return redact_text(str(value))


def redact_text(value: str) -> str:
    redacted = BEARER_RE.sub("Bearer [REDACTED]", value)
    redacted = JWT_RE.sub("[REDACTED_JWT]", redacted)
    return EMAIL_RE.sub("[REDACTED_EMAIL]", redacted)

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import asyncpg

from lead_worker.providers import DeliveryError, EmailProvider, OutboundEmail

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@dataclass(frozen=True)
class QueuedNotification:
    id: str
    kind: str
    recipient_email: str
    payload: dict[str, Any]
    attempt_count: int
    lead_id: str | None = None


class OutboxStore(Protocol):
    async def claim_available(
        self,
        *,
        worker_id: str,
        batch_size: int,
        lease_seconds: int,
    ) -> list[QueuedNotification]:
        pass

    async def mark_sent(
        self,
        *,
        notification_id: str,
        provider_name: str,
        provider_message_id: str,
    ) -> None:
        pass

    async def mark_failed(
        self,
        *,
        notification_id: str,
        error_context: dict[str, str],
        next_attempt_delay_seconds: int,
    ) -> None:
        pass


class PostgresOutboxStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def claim_available(
        self,
        *,
        worker_id: str,
        batch_size: int,
        lease_seconds: int,
    ) -> list[QueuedNotification]:
        async with self._pool.acquire() as connection:
            records = await connection.fetch(
                """
                with available as (
                  select id
                  from app.email_outbox
                  where
                    status = 'PENDING'
                    and next_attempt_at <= now()
                    and (
                      claimed_at is null
                      or claimed_at <= now() - ($3 * interval '1 second')
                    )
                  order by next_attempt_at, created_at, id
                  limit $1
                  for update skip locked
                )
                update app.email_outbox notification
                set
                  claimed_at = now(),
                  claim_token = $2::uuid,
                  updated_at = now()
                from available
                where notification.id = available.id
                returning
                  notification.id::text as id,
                  notification.lead_id::text as lead_id,
                  notification.kind::text as kind,
                  notification.recipient_email::text as recipient_email,
                  notification.payload,
                  notification.attempt_count
                """,
                batch_size,
                worker_id,
                lease_seconds,
            )
        return [
            QueuedNotification(
                id=record["id"],
                kind=record["kind"],
                recipient_email=record["recipient_email"],
                payload=parse_payload(record["payload"]),
                attempt_count=record["attempt_count"],
                lead_id=record["lead_id"],
            )
            for record in records
        ]

    async def mark_sent(
        self,
        *,
        notification_id: str,
        provider_name: str,
        provider_message_id: str,
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                update app.email_outbox
                set
                  status = 'SENT',
                  attempt_count = attempt_count + 1,
                  provider_name = $2,
                  provider_message_id = $3,
                  delivered_at = now(),
                  claimed_at = null,
                  claim_token = null,
                  last_error_context = '{}'::jsonb,
                  updated_at = now()
                where id = $1::uuid and status = 'PENDING' and delivered_at is null
                """,
                notification_id,
                provider_name,
                provider_message_id,
            )

    async def mark_failed(
        self,
        *,
        notification_id: str,
        error_context: dict[str, str],
        next_attempt_delay_seconds: int,
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                update app.email_outbox
                set
                  attempt_count = attempt_count + 1,
                  status = case
                    when attempt_count + 1 >= $4 then 'FAILED'::app.email_outbox_status
                    else 'PENDING'::app.email_outbox_status
                  end,
                  next_attempt_at = case
                    when attempt_count + 1 >= $4 then next_attempt_at
                    else now() + ($3 * interval '1 second')
                  end,
                  claimed_at = null,
                  claim_token = null,
                  last_error_context = $2::jsonb,
                  updated_at = now()
                where id = $1::uuid and status = 'PENDING' and delivered_at is null
                """,
                notification_id,
                json.dumps(error_context),
                next_attempt_delay_seconds,
                MAX_ATTEMPTS,
            )


class OutboxWorker:
    def __init__(
        self,
        *,
        store: OutboxStore,
        provider: EmailProvider,
        batch_size: int,
        lease_seconds: int,
        base_retry_seconds: int,
        max_retry_seconds: int,
    ) -> None:
        self._store = store
        self._provider = provider
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._base_retry_seconds = base_retry_seconds
        self._max_retry_seconds = max_retry_seconds

    async def run_once(self, worker_id: str | None = None) -> int:
        worker_id = worker_id or str(uuid.uuid4())
        claimed = await self._store.claim_available(
            worker_id=worker_id,
            batch_size=self._batch_size,
            lease_seconds=self._lease_seconds,
        )
        if not claimed:
            return 0

        await asyncio.gather(*(self._deliver(notification) for notification in claimed))
        return len(claimed)

    async def _deliver(self, notification: QueuedNotification) -> None:
        log_fields = notification_log_fields(notification, self._provider.name)
        try:
            message = render_notification(notification)
            result = await self._provider.send(message)
        except DeliveryError as exc:
            await self._store.mark_failed(
                notification_id=notification.id,
                error_context=sanitize_error_context(exc, self._provider.name),
                next_attempt_delay_seconds=retry_delay_seconds(
                    notification.attempt_count + 1,
                    self._base_retry_seconds,
                    self._max_retry_seconds,
                ),
            )
            logger.info(
                "email_delivery_retry_or_failed",
                extra=log_fields,
            )
            return
        except Exception as exc:
            await self._store.mark_failed(
                notification_id=notification.id,
                error_context=sanitize_error_context(exc, self._provider.name),
                next_attempt_delay_seconds=retry_delay_seconds(
                    notification.attempt_count + 1,
                    self._base_retry_seconds,
                    self._max_retry_seconds,
                ),
            )
            logger.info(
                "email_delivery_retry_or_failed",
                extra=log_fields,
            )
            return

        await self._store.mark_sent(
            notification_id=notification.id,
            provider_name=self._provider.name,
            provider_message_id=result.provider_message_id,
        )
        logger.info(
            "email_delivery_sent",
            extra=log_fields,
        )


def render_notification(notification: QueuedNotification) -> OutboundEmail:
    if notification.kind == "PROSPECT_CONFIRMATION":
        return render_prospect_confirmation(notification)
    if notification.kind == "INTERNAL_NEW_LEAD":
        return render_internal_new_lead(notification)
    raise DeliveryError("unknown_notification_kind", temporary=False)


def render_prospect_confirmation(notification: QueuedNotification) -> OutboundEmail:
    first_name = clean_payload_value(notification.payload.get("prospectFirstName"), "there")
    body = (
        f"Hi {first_name},\n\n"
        "Thank you for contacting Alma. We received your Lead and our legal team "
        "will review it.\n\n"
        "Alma Intake"
    )
    return OutboundEmail(
        to_email=notification.recipient_email,
        subject="We received your Lead",
        text_body=body,
        html_body=paragraphs_to_html(body),
    )


def render_internal_new_lead(notification: QueuedNotification) -> OutboundEmail:
    prospect_name = clean_payload_value(notification.payload.get("prospectName"), "New Lead")
    prospect_email = clean_payload_value(notification.payload.get("prospectEmail"), "not provided")
    submitted_at = clean_payload_value(notification.payload.get("submittedAt"), "not provided")
    assignment = clean_payload_value(notification.payload.get("assignment"), "unassigned")
    body = (
        "A new Lead is ready for review.\n\n"
        f"Prospect: {prospect_name}\n"
        f"Email: {prospect_email}\n"
        f"Assignment: {assignment}\n"
        f"Submitted: {submitted_at}\n\n"
        "No resume is attached to this notification. Open the authenticated workspace to review it."
    )
    return OutboundEmail(
        to_email=notification.recipient_email,
        subject=f"New Lead: {prospect_name}",
        text_body=body,
        html_body=paragraphs_to_html(body),
    )


def clean_payload_value(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    clean = " ".join(value.split())
    return clean[:240] if clean else fallback


def parse_payload(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(decoded) if isinstance(decoded, dict) else {}
    return {}


def notification_log_fields(
    notification: QueuedNotification, provider_name: str
) -> dict[str, str | None]:
    correlation_id = notification.payload.get("correlationId")
    return {
        "correlation_id": correlation_id if isinstance(correlation_id, str) else None,
        "lead_id": notification.lead_id,
        "notification_id": notification.id,
        "notification_kind": notification.kind,
        "provider": provider_name,
    }


def paragraphs_to_html(body: str) -> str:
    paragraphs = []
    for paragraph in body.split("\n\n"):
        lines = "<br>".join(html.escape(line) for line in paragraph.splitlines())
        paragraphs.append(f"<p>{lines}</p>")
    return "\n".join(paragraphs)


def sanitize_error_context(exc: Exception, provider_name: str) -> dict[str, str]:
    if isinstance(exc, DeliveryError):
        code = exc.code
        temporary = str(exc.temporary).lower()
    else:
        code = exc.__class__.__name__
        temporary = "true"
    return {
        "provider": safe_context_value(provider_name),
        "errorCode": safe_context_value(code),
        "temporary": temporary,
    }


def safe_context_value(value: str) -> str:
    value = EMAIL_PATTERN.sub("redacted_email", value)
    allowed = []
    for character in value[:80]:
        if character.isalnum() or character in {"_", "-", "."}:
            allowed.append(character)
        else:
            allowed.append("_")
    return "".join(allowed) or "unknown"


def retry_delay_seconds(attempt_number: int, base_seconds: int, max_seconds: int) -> int:
    attempt = max(1, attempt_number)
    delay = base_seconds * (2 ** (attempt - 1))
    return min(delay, max_seconds)


async def run_forever(
    *,
    worker: OutboxWorker,
    stop: asyncio.Event,
    poll_seconds: float,
    worker_id: str | None = None,
) -> None:
    while not stop.is_set():
        processed = await worker.run_once(worker_id)
        timeout = 0 if processed else poll_seconds
        try:
            await asyncio.wait_for(stop.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

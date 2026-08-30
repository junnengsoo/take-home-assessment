from __future__ import annotations

import asyncio
from collections import Counter
from copy import deepcopy

from lead_api.config import Settings
from lead_worker.outbox import (
    OutboxWorker,
    PostgresOutboxStore,
    QueuedNotification,
    retry_delay_seconds,
    sanitize_error_context,
)
from lead_worker.providers import DeliveryError, DeliveryResult, provider_from_settings


class FakeProvider:
    name = "fake-provider"

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.messages = []
        self.fail_with = fail_with

    async def send(self, message):
        self.messages.append(message)
        if self.fail_with is not None:
            raise self.fail_with
        return DeliveryResult(provider_message_id=f"provider-{len(self.messages)}")


class FakeOutboxStore:
    def __init__(self, notifications) -> None:
        self._notifications = list(notifications)
        self._lock = asyncio.Lock()
        self._claimed = {}
        self.sent = []
        self.failed = []

    async def claim_available(self, *, worker_id: str, batch_size: int, lease_seconds: int):
        async with self._lock:
            claimed = self._notifications[:batch_size]
            self._notifications = self._notifications[batch_size:]
            self._claimed.update((notification.id, notification) for notification in claimed)
            return deepcopy(claimed)

    async def mark_sent(self, *, notification_id, provider_name, provider_message_id):
        attempt_count = self._claimed[notification_id].attempt_count + 1
        self.sent.append(
            {
                "notification_id": notification_id,
                "attempt_count": attempt_count,
                "provider_name": provider_name,
                "provider_message_id": provider_message_id,
            }
        )

    async def mark_failed(self, *, notification_id, error_context, next_attempt_delay_seconds):
        attempt_count = self._claimed[notification_id].attempt_count + 1
        self.failed.append(
            {
                "notification_id": notification_id,
                "status": "FAILED" if attempt_count >= 5 else "PENDING",
                "attempt_count": attempt_count,
                "error_context": error_context,
                "next_attempt_delay_seconds": next_attempt_delay_seconds,
            }
        )


def prospect_notification(notification_id: str = "10000000-0000-4000-8000-000000000001"):
    return QueuedNotification(
        id=notification_id,
        kind="PROSPECT_CONFIRMATION",
        recipient_email="ada@example.com",
        payload={"prospectFirstName": "Ada"},
        attempt_count=0,
    )


def internal_notification(notification_id: str = "10000000-0000-4000-8000-000000000002"):
    return QueuedNotification(
        id=notification_id,
        kind="INTERNAL_NEW_LEAD",
        recipient_email="attorney.local@example.test",
        payload={
            "prospectName": "Ada Lovelace",
            "prospectEmail": "ada@example.com",
            "assignment": "Local Attorney",
            "submittedAt": "2026-08-30T09:00:00Z",
            "resumeObjectKey": "private/resume.pdf",
            "downloadBearerLink": "https://example.test/private?token=secret",
        },
        attempt_count=0,
    )


def make_worker(store, provider):
    return OutboxWorker(
        store=store,
        provider=provider,
        batch_size=10,
        lease_seconds=300,
        base_retry_seconds=30,
        max_retry_seconds=3600,
    )


async def test_worker_delivers_prospect_and_internal_notifications_with_minimal_content():
    store = FakeOutboxStore([prospect_notification(), internal_notification()])
    provider = FakeProvider()
    worker = make_worker(store, provider)

    processed = await worker.run_once("00000000-0000-4000-8000-000000000001")

    assert processed == 2
    assert [message.to_email for message in provider.messages] == [
        "ada@example.com",
        "attorney.local@example.test",
    ]
    assert [message["notification_id"] for message in store.sent] == [
        "10000000-0000-4000-8000-000000000001",
        "10000000-0000-4000-8000-000000000002",
    ]
    assert [message["attempt_count"] for message in store.sent] == [1, 1]
    bodies = "\n".join(message.text_body for message in provider.messages)
    assert "Ada Lovelace" in bodies
    assert "ada@example.com" in bodies
    assert "private/resume.pdf" not in bodies
    assert "https://example.test/private" not in bodies
    assert "Bearer" not in bodies


async def test_successful_delivery_records_provider_identity():
    store = FakeOutboxStore([prospect_notification()])
    provider = FakeProvider()
    worker = make_worker(store, provider)

    await worker.run_once("00000000-0000-4000-8000-000000000002")

    assert store.sent == [
        {
            "notification_id": "10000000-0000-4000-8000-000000000001",
            "attempt_count": 1,
            "provider_name": "fake-provider",
            "provider_message_id": "provider-1",
        }
    ]


async def test_temporary_failure_records_sanitized_context_and_exponential_retry():
    store = FakeOutboxStore([prospect_notification()])
    provider = FakeProvider(fail_with=DeliveryError("smtp timeout for ada@example.com"))
    worker = make_worker(store, provider)

    await worker.run_once("00000000-0000-4000-8000-000000000003")

    assert store.sent == []
    assert store.failed == [
        {
            "notification_id": "10000000-0000-4000-8000-000000000001",
            "status": "PENDING",
            "attempt_count": 1,
            "error_context": {
                "provider": "fake-provider",
                "errorCode": "smtp_timeout_for_redacted_email",
                "temporary": "true",
            },
            "next_attempt_delay_seconds": 30,
        }
    ]


async def test_fifth_failed_attempt_moves_to_retained_terminal_failure():
    store = FakeOutboxStore(
        [
            QueuedNotification(
                id="10000000-0000-4000-8000-000000000005",
                kind="PROSPECT_CONFIRMATION",
                recipient_email="ada@example.com",
                payload={"prospectFirstName": "Ada"},
                attempt_count=4,
            )
        ]
    )
    provider = FakeProvider(fail_with=DeliveryError("smtp_timeout"))
    worker = make_worker(store, provider)

    await worker.run_once("00000000-0000-4000-8000-000000000004")

    assert store.failed[0]["status"] == "FAILED"
    assert store.failed[0]["attempt_count"] == 5
    assert store.failed[0]["next_attempt_delay_seconds"] == 480


async def test_concurrent_workers_do_not_intentionally_deliver_same_claimed_notification():
    notifications = [
        prospect_notification(f"10000000-0000-4000-8000-{index:012d}") for index in range(12)
    ]
    store = FakeOutboxStore(notifications)
    provider = FakeProvider()
    worker = OutboxWorker(
        store=store,
        provider=provider,
        batch_size=1,
        lease_seconds=300,
        base_retry_seconds=30,
        max_retry_seconds=3600,
    )

    processed = await asyncio.gather(
        *(worker.run_once(f"00000000-0000-4000-8000-{index:012d}") for index in range(12))
    )

    delivered = Counter(message["notification_id"] for message in store.sent)
    assert sum(processed) == 12
    assert len(delivered) == 12
    assert all(count == 1 for count in delivered.values())


def test_retry_delay_uses_exponential_backoff_with_cap():
    assert retry_delay_seconds(1, 30, 3600) == 30
    assert retry_delay_seconds(2, 30, 3600) == 60
    assert retry_delay_seconds(5, 30, 3600) == 480
    assert retry_delay_seconds(20, 30, 3600) == 3600


def test_error_context_excludes_provider_messages_that_may_contain_personal_information():
    context = sanitize_error_context(
        RuntimeError("failed to send to ada@example.com with token secret"),
        "fake-provider",
    )

    assert context == {
        "provider": "fake-provider",
        "errorCode": "RuntimeError",
        "temporary": "true",
    }


def test_provider_selection_defaults_to_mailpit_and_supports_resend():
    local_provider = provider_from_settings(Settings())
    resend_provider = provider_from_settings(
        Settings(email_provider="resend", resend_api_key="secret")
    )

    assert local_provider.name == "local-smtp"
    assert resend_provider.name == "resend"


class RecordingConnection:
    def __init__(self) -> None:
        self.sql = ""
        self.args = ()

    async def fetch(self, sql, *args):
        self.sql = sql
        self.args = args
        return [
            {
                "id": "10000000-0000-4000-8000-000000000001",
                "lead_id": "33333333-3333-4333-8333-333333333333",
                "kind": "PROSPECT_CONFIRMATION",
                "recipient_email": "ada@example.com",
                "payload": {"prospectFirstName": "Ada"},
                "attempt_count": 0,
            }
        ]


class RecordingAcquire:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class RecordingPool:
    def __init__(self, connection) -> None:
        self.connection = connection

    def acquire(self):
        return RecordingAcquire(self.connection)


async def test_postgres_claim_uses_row_locking_and_skip_locked():
    connection = RecordingConnection()
    store = PostgresOutboxStore(RecordingPool(connection))

    claimed = await store.claim_available(
        worker_id="00000000-0000-4000-8000-000000000001",
        batch_size=25,
        lease_seconds=300,
    )

    assert [notification.id for notification in claimed] == [
        "10000000-0000-4000-8000-000000000001"
    ]
    assert "for update skip locked" in " ".join(connection.sql.lower().split())
    assert connection.args == (
        25,
        "00000000-0000-4000-8000-000000000001",
        300,
    )

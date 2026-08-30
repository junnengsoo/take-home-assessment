import asyncio
import os
from uuid import uuid4

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient
from lead_api.config import get_settings
from lead_api.database import LeadPersistenceError
from lead_api.main import app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LOCAL_SUPABASE_TESTS") != "1",
    reason="set RUN_LOCAL_SUPABASE_TESTS=1 after starting and resetting local Supabase",
)


def pdf_bytes(label: str = "resume") -> bytes:
    return f"%PDF-1.7\n{label}\n%%EOF".encode()


def form_data(attempt_key: str, email: str = "ada@example.com") -> dict[str, str]:
    return {
        "firstName": "Ada",
        "lastName": "Lovelace",
        "email": email,
        "submissionAttemptKey": attempt_key,
    }


def resume_file(content: bytes = pdf_bytes()):
    return {"resume": ("private-name.pdf", content, "application/pdf")}


async def fetch_submission(attempt_key: str):
    settings = get_settings()
    connection = await asyncpg.connect(settings.database_url)
    try:
        return await connection.fetchrow(
            """
            select
              l.id::text as lead_id,
              l.first_name,
              l.last_name,
              l.normalized_email::text as normalized_email,
              l.version,
              r.original_filename,
              r.storage_bucket,
              r.storage_object_key,
              r.content_type,
              r.byte_size,
              r.sha256_digest,
              (
                select count(*) from app.lead_status_changes sc
                where sc.lead_id = l.id
                  and sc.status = 'PENDING'
                  and sc.actor_type = 'SYSTEM'
                  and sc.actor_attorney_id is null
              ) as pending_status_changes,
              (
                select count(*) from app.lead_audit_events ae
                where ae.lead_id = l.id
                  and ae.event_type = 'lead.created'
                  and ae.actor_type = 'SYSTEM'
              ) as creation_audit_events
            from app.submission_attempts sa
            join app.leads l on l.id = sa.lead_id
            join app.resume_metadata r on r.lead_id = l.id
            where sa.attempt_key = $1
            """,
            attempt_key,
        )
    finally:
        await connection.close()


def public_storage_response(object_key: str) -> int:
    settings = get_settings()
    response = httpx.get(
        f"{str(settings.supabase_url).rstrip('/')}/storage/v1/object/public/resumes/{object_key}",
        timeout=10,
    )
    return response.status_code


def service_storage_response(object_key: str) -> int:
    settings = get_settings()
    response = httpx.get(
        f"{str(settings.supabase_url).rstrip('/')}/storage/v1/object/resumes/{object_key}",
        headers={
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
        },
        timeout=10,
    )
    return response.status_code


def test_local_supabase_lead_submission_persists_private_resume() -> None:
    if not get_settings().supabase_service_role_key:
        pytest.skip("set SUPABASE_SERVICE_ROLE_KEY to the local service role key")

    attempt_key = f"local-{uuid4()}"

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/leads",
            data=form_data(attempt_key, "ADA@Example.COM"),
            files=resume_file(),
        )

    assert response.status_code == 201
    assert set(response.json()) == {"leadId", "confirmation"}
    stored = asyncio.run(fetch_submission(attempt_key))
    assert stored["lead_id"] == response.json()["leadId"]
    assert stored["first_name"] == "Ada"
    assert stored["last_name"] == "Lovelace"
    assert stored["normalized_email"] == "ada@example.com"
    assert stored["version"] == 1
    assert stored["original_filename"] == "private-name.pdf"
    assert stored["storage_bucket"] == "resumes"
    assert stored["storage_object_key"] != "private-name.pdf"
    assert stored["storage_object_key"].endswith(".pdf")
    assert stored["content_type"] == "application/pdf"
    assert stored["byte_size"] == len(pdf_bytes())
    assert stored["pending_status_changes"] == 1
    assert stored["creation_audit_events"] == 1
    assert public_storage_response(stored["storage_object_key"]) != 200
    assert service_storage_response(stored["storage_object_key"]) == 200


def test_local_supabase_submission_attempt_retry_conflict_and_repeated_email() -> None:
    if not get_settings().supabase_service_role_key:
        pytest.skip("set SUPABASE_SERVICE_ROLE_KEY to the local service role key")

    first_attempt = f"local-{uuid4()}"
    second_attempt = f"local-{uuid4()}"

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/leads", data=form_data(first_attempt), files=resume_file()
        )
        retry = client.post(
            "/api/v1/leads", data=form_data(first_attempt), files=resume_file()
        )
        conflict = client.post(
            "/api/v1/leads",
            data={**form_data(first_attempt), "lastName": "Byron"},
            files=resume_file(),
        )
        deliberate = client.post(
            "/api/v1/leads", data=form_data(second_attempt), files=resume_file()
        )

    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.json()["leadId"] == first.json()["leadId"]
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "submission_attempt_conflict"
    assert deliberate.status_code == 201
    assert deliberate.json()["leadId"] != first.json()["leadId"]


@pytest.mark.parametrize(
    ("data", "files", "expected_status", "expected_code"),
    [
        (
            {**form_data("local-validation-1"), "firstName": ""},
            resume_file(),
            400,
            "missing_required_field",
        ),
        (
            form_data("local-validation-2"),
            {"resume": ("bad.txt", b"text", "text/plain")},
            400,
            "unsupported_resume_type",
        ),
        (
            form_data("local-validation-3"),
            {"resume": ("bad.pdf", b"not pdf", "application/pdf")},
            400,
            "mismatched_resume_signature",
        ),
    ],
)
def test_local_supabase_validation_errors(
    data, files, expected_status: int, expected_code: str
) -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/leads", data=data, files=files)

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code


def test_local_supabase_storage_upload_is_compensated_after_database_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not get_settings().supabase_service_role_key:
        pytest.skip("set SUPABASE_SERVICE_ROLE_KEY to the local service role key")

    object_id = uuid4()
    object_key = f"{object_id}.pdf"

    async def fail_after_upload(**kwargs):
        raise LeadPersistenceError

    async def no_existing(attempt_key: str):
        return None

    monkeypatch.setattr("lead_api.leads.uuid.uuid4", lambda: object_id)
    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", no_existing)
    monkeypatch.setattr("lead_api.leads.database.create_lead_submission", fail_after_upload)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/leads",
            data=form_data(f"local-{uuid4()}"),
            files=resume_file(pdf_bytes("compensated")),
        )

    assert response.status_code == 503
    assert response.json()["code"] == "lead_persistence_failed"
    assert service_storage_response(object_key) != 200

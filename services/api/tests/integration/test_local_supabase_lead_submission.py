import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient
from lead_api.abuse import TurnstileOutcome
from lead_api.config import get_settings
from lead_api.database import LeadPersistenceError, database
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
        "turnstileToken": "integration-turnstile-token",
        "website": "",
    }


def resume_file(content: bytes = pdf_bytes()):
    return {"resume": ("private-name.pdf", content, "application/pdf")}


def admin_database_url() -> str:
    return os.getenv(
        "SUPABASE_TEST_ADMIN_DATABASE_URL",
        "postgresql://postgres:postgres@127.0.0.1:54322/postgres",
    )


async def execute_admin(sql: str, *args) -> None:
    connection = await asyncpg.connect(admin_database_url())
    try:
        await connection.execute(sql, *args)
    finally:
        await connection.close()


async def fetchval_admin(sql: str, *args):
    connection = await asyncpg.connect(admin_database_url())
    try:
        return await connection.fetchval(sql, *args)
    finally:
        await connection.close()


async def reset_application_records() -> None:
    await execute_admin(
        """
        truncate
          app.email_outbox,
          app.submission_attempts,
          app.lead_audit_events,
          app.lead_status_changes,
          app.resume_metadata,
          app.leads,
          app.public_lead_rate_limits
        restart identity
        """
    )


async def create_attorney(
    *,
    attorney_id: str,
    email: str,
    display_name: str,
    created_at: datetime = datetime(2026, 8, 30, tzinfo=timezone.utc),
    last_assigned_at: Optional[datetime] = None,
) -> None:
    await execute_admin(
        """
        insert into auth.users (
          instance_id,
          id,
          aud,
          role,
          email,
          encrypted_password,
          email_confirmed_at,
          raw_app_meta_data,
          raw_user_meta_data,
          created_at,
          updated_at,
          confirmation_token,
          recovery_token,
          email_change_token_new,
          email_change
        )
        values (
          '00000000-0000-0000-0000-000000000000',
          $1::uuid,
          'authenticated',
          'authenticated',
          $2,
          crypt('LocalAttorney123!', extensions.gen_salt('bf')),
          now(),
          '{"provider": "email", "providers": ["email"]}'::jsonb,
          jsonb_build_object('display_name', $3::text),
          $4::timestamptz,
          now(),
          '',
          '',
          '',
          ''
        )
        on conflict (id) do update
          set email = excluded.email,
              raw_user_meta_data = excluded.raw_user_meta_data,
              updated_at = now()
        """,
        attorney_id,
        email,
        display_name,
        created_at,
    )
    await execute_admin(
        """
        insert into auth.identities (
          id,
          user_id,
          provider_id,
          identity_data,
          provider,
          last_sign_in_at,
          created_at,
          updated_at
        )
        values (
          $1,
          $1::uuid,
          $1,
          jsonb_build_object('sub', $1::text, 'email', $2::text),
          'email',
          now(),
          now(),
          now()
        )
        on conflict (provider, provider_id) do update
          set identity_data = excluded.identity_data,
              updated_at = now()
        """,
        attorney_id,
        email,
    )
    await execute_admin(
        """
        update app.attorneys
        set
          email = $2,
          display_name = $3,
          created_at = $4::timestamptz,
          last_assigned_at = $5::timestamptz
        where id = $1::uuid
        """,
        attorney_id,
        email,
        display_name,
        created_at,
        last_assigned_at,
    )


async def ensure_seeded_attorney() -> None:
    await create_attorney(
        attorney_id="11111111-1111-4111-8111-111111111111",
        email="attorney.local@example.test",
        display_name="Local Attorney",
    )


async def remove_all_attorneys() -> None:
    await reset_application_records()
    await execute_admin("delete from auth.identities")
    await execute_admin("delete from auth.users")


async def prepare_assignment_attorneys(attorneys: list[tuple[str, str, str]]) -> None:
    await reset_application_records()
    await execute_admin("update app.attorneys set last_assigned_at = now() + interval '1 day'")
    for attorney_id, email, display_name in attorneys:
        await create_attorney(
            attorney_id=attorney_id,
            email=email,
            display_name=display_name,
            last_assigned_at=None,
        )


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
              l.assigned_attorney_id::text as assigned_attorney_id,
              r.original_filename,
              r.storage_bucket,
              r.storage_object_key,
              r.content_type,
              r.byte_size,
              r.sha256_digest,
              l.turnstile_verification_outcome::text as turnstile_verification_outcome,
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


async def fetch_outbox(lead_id: str):
    settings = get_settings()
    connection = await asyncpg.connect(settings.database_url)
    try:
        rows = await connection.fetch(
            """
            select
              id::text as id,
              kind::text as kind,
              recipient_email::text as recipient_email,
              payload::text as payload,
              status
            from app.email_outbox
            where lead_id = $1::uuid
            order by kind
            """,
            lead_id,
        )
        return [
            {
                **dict(row),
                "payload": json.loads(row["payload"]),
            }
            for row in rows
        ]
    finally:
        await connection.close()


async def fetch_assigned_attorney(attempt_key: str) -> Optional[str]:
    settings = get_settings()
    connection = await asyncpg.connect(settings.database_url)
    try:
        return await connection.fetchval(
            """
            select l.assigned_attorney_id::text
            from app.submission_attempts sa
            join app.leads l on l.id = sa.lead_id
            where sa.attempt_key = $1
            """,
            attempt_key,
        )
    finally:
        await connection.close()


async def fetch_status_evidence(lead_id: str) -> dict[str, object]:
    connection = await asyncpg.connect(admin_database_url())
    try:
        lead = await connection.fetchrow(
            """
            select
              current_status::text as current_status,
              version,
              assigned_attorney_id::text as assigned_attorney_id
            from app.leads
            where id = $1::uuid
            """,
            lead_id,
        )
        status_changes = await connection.fetch(
            """
            select
              status::text as status,
              actor_type::text as actor_type,
              actor_attorney_id::text as actor_attorney_id,
              created_at
            from app.lead_status_changes
            where lead_id = $1::uuid
            order by created_at, id
            """,
            lead_id,
        )
        audit_events = await connection.fetch(
            """
            select event_type, actor_type::text as actor_type, payload, created_at
            from app.lead_audit_events
            where lead_id = $1::uuid and event_type = 'lead.status_changed'
            order by created_at, id
            """,
            lead_id,
        )
        return {
            "lead": dict(lead),
            "status_changes": [dict(row) for row in status_changes],
            "audit_events": [
                {**dict(row), "payload": json.loads(row["payload"])} for row in audit_events
            ],
        }
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


def sign_in_attorney(email: str = "attorney.local@example.test") -> str:
    supabase_url = str(get_settings().supabase_url).rstrip("/")
    anon_key = get_settings().supabase_anon_key
    auth_response = httpx.post(
        f"{supabase_url}/auth/v1/token?grant_type=password",
        headers={"apikey": anon_key, "Content-Type": "application/json"},
        json={
            "email": email,
            "password": "LocalAttorney123!",
        },
        timeout=10,
    )
    assert auth_response.status_code == 200
    return auth_response.json()["access_token"]


@pytest.fixture(autouse=True)
def pass_turnstile(monkeypatch: pytest.MonkeyPatch) -> None:
    async def verify(*args, **kwargs):
        return TurnstileOutcome.SUCCESS

    monkeypatch.setattr("lead_api.leads.verify_turnstile", verify)


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
    assert stored["assigned_attorney_id"] is not None
    assert stored["original_filename"] == "private-name.pdf"
    assert stored["storage_bucket"] == "resumes"
    assert stored["storage_object_key"] != "private-name.pdf"
    assert stored["storage_object_key"].endswith(".pdf")
    assert stored["content_type"] == "application/pdf"
    assert stored["byte_size"] == len(pdf_bytes())
    assert stored["turnstile_verification_outcome"] == "SUCCESS"
    assert stored["pending_status_changes"] == 1
    assert stored["creation_audit_events"] == 1
    assert public_storage_response(stored["storage_object_key"]) != 200
    assert service_storage_response(stored["storage_object_key"]) == 200


def test_local_supabase_round_robin_assignment_and_notification_outbox() -> None:
    if not get_settings().supabase_service_role_key:
        pytest.skip("set SUPABASE_SERVICE_ROLE_KEY to the local service role key")

    first_attorney = "00000000-0000-4000-8000-000000000001"
    second_attorney = "00000000-0000-4000-8000-000000000002"
    asyncio.run(
        prepare_assignment_attorneys(
            [
                (second_attorney, "zeta.attorney@example.test", "Zeta Attorney"),
                (first_attorney, "alpha.attorney@example.test", "Alpha Attorney"),
            ]
        )
    )
    attempts = [f"local-assignment-{uuid4()}" for _ in range(3)]

    with TestClient(app) as client:
        responses = [
            client.post(
                "/api/v1/leads",
                data=form_data(attempt, "ADA@Example.COM"),
                files=resume_file(pdf_bytes(attempt)),
            )
            for attempt in attempts
        ]

    assert [response.status_code for response in responses] == [201, 201, 201]
    assigned = [asyncio.run(fetch_assigned_attorney(attempt)) for attempt in attempts]
    assert assigned == [first_attorney, second_attorney, first_attorney]

    stored = asyncio.run(fetch_submission(attempts[0]))
    outbox = asyncio.run(fetch_outbox(stored["lead_id"]))
    assert len(outbox) == 2
    assert len({row["id"] for row in outbox}) == 2
    assert {row["kind"] for row in outbox} == {
        "PROSPECT_CONFIRMATION",
        "INTERNAL_NEW_LEAD",
    }

    prospect = next(row for row in outbox if row["kind"] == "PROSPECT_CONFIRMATION")
    internal = next(row for row in outbox if row["kind"] == "INTERNAL_NEW_LEAD")
    assert prospect["recipient_email"] == "ada@example.com"
    assert internal["recipient_email"] == "alpha.attorney@example.test"
    assert set(internal["payload"]) == {
        "prospectName",
        "prospectEmail",
        "assignment",
        "submittedAt",
        "correlationId",
    }
    assert internal["payload"]["prospectName"] == "Ada Lovelace"
    assert internal["payload"]["prospectEmail"] == "ada@example.com"
    assert internal["payload"]["assignment"] == "Alpha Attorney"
    serialized_outbox = json.dumps(outbox)
    assert "private-name.pdf" not in serialized_outbox
    assert "resumeSha256Digest" not in serialized_outbox
    assert "storage_object_key" not in serialized_outbox


def test_local_supabase_concurrent_submissions_do_not_race_assignment() -> None:
    if not get_settings().supabase_service_role_key:
        pytest.skip("set SUPABASE_SERVICE_ROLE_KEY to the local service role key")

    first_attorney = "00000000-0000-4000-8000-000000000011"
    second_attorney = "00000000-0000-4000-8000-000000000012"
    asyncio.run(
        prepare_assignment_attorneys(
            [
                (first_attorney, "concurrent-a@example.test", "Concurrent A"),
                (second_attorney, "concurrent-b@example.test", "Concurrent B"),
            ]
        )
    )
    attempts = [f"local-concurrent-{uuid4()}" for _ in range(2)]

    async def submit_concurrently():
        await database.connect(get_settings())
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await asyncio.gather(
                    *[
                        client.post(
                            "/api/v1/leads",
                            data=form_data(attempt),
                            files=resume_file(pdf_bytes(attempt)),
                        )
                        for attempt in attempts
                    ]
                )
        finally:
            await database.close()

    responses = asyncio.run(submit_concurrently())

    assert sorted(response.status_code for response in responses) == [201, 201]
    assigned = [asyncio.run(fetch_assigned_attorney(attempt)) for attempt in attempts]
    assert set(assigned) == {first_attorney, second_attorney}


def test_local_supabase_no_attorney_uses_fallback_notification_recipient() -> None:
    if not get_settings().supabase_service_role_key:
        pytest.skip("set SUPABASE_SERVICE_ROLE_KEY to the local service role key")

    attempt_key = f"local-no-attorney-{uuid4()}"
    asyncio.run(remove_all_attorneys())
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/leads",
                data=form_data(attempt_key),
                files=resume_file(),
            )

        assert response.status_code == 201
        stored = asyncio.run(fetch_submission(attempt_key))
        assert stored["assigned_attorney_id"] is None
        outbox = asyncio.run(fetch_outbox(stored["lead_id"]))
        internal = next(row for row in outbox if row["kind"] == "INTERNAL_NEW_LEAD")
        assert internal["recipient_email"] == "intake.local@example.test"
        assert set(internal["payload"]) == {
            "prospectName",
            "prospectEmail",
            "assignment",
            "submittedAt",
            "correlationId",
        }
        assert internal["payload"]["assignment"] == "Unassigned"
    finally:
        asyncio.run(ensure_seeded_attorney())


def test_local_supabase_attorney_queue_scopes_filters_search_and_cursor() -> None:
    if not get_settings().supabase_service_role_key:
        pytest.skip("set SUPABASE_SERVICE_ROLE_KEY to the local service role key")

    first_attorney = "11111111-1111-4111-8111-111111111111"
    second_attorney = "00000000-0000-4000-8000-000000000022"
    asyncio.run(
        prepare_assignment_attorneys(
            [
                (first_attorney, "attorney.local@example.test", "Local Attorney"),
                (second_attorney, "coverage@example.test", "Coverage Attorney"),
            ]
        )
    )
    created_at = datetime(2026, 8, 30, 16, 0, tzinfo=timezone.utc)
    lead_ids = [
        "10000000-0000-4000-8000-000000000001",
        "10000000-0000-4000-8000-000000000002",
        "10000000-0000-4000-8000-000000000003",
        "10000000-0000-4000-8000-000000000004",
    ]
    asyncio.run(
        execute_admin(
            """
            insert into app.leads (
              id,
              first_name,
              last_name,
              normalized_email,
              current_status,
              assigned_attorney_id,
              created_at
            )
            values
              ($1::uuid, 'Ada', 'Lovelace', 'ada@example.com', 'PENDING', $5::uuid, $7),
              ($2::uuid, 'Ada', 'Byron', 'ada@example.com', 'REACHED_OUT', $6::uuid, $7),
              ($3::uuid, 'Grace', 'Hopper', 'grace@example.com', 'PENDING', null, $7),
              ($4::uuid, 'Katherine', 'Johnson', 'katherine@example.com', 'PENDING', $5::uuid, $7)
            """,
            *lead_ids,
            first_attorney,
            second_attorney,
            created_at,
        )
    )
    token = sign_in_attorney()
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(app) as client:
        my_leads = client.get("/api/v1/admin/leads", headers=headers)
        all_first_page = client.get(
            "/api/v1/admin/leads",
            params={"scope": "all", "pageSize": "2"},
            headers=headers,
        )
        all_second_page = client.get(
            "/api/v1/admin/leads",
            params={
                "scope": "all",
                "pageSize": "2",
                "cursor": all_first_page.json()["nextCursor"],
            },
            headers=headers,
        )
        reached_out = client.get(
            "/api/v1/admin/leads",
            params={"scope": "all", "status": "REACHED_OUT", "assignment": second_attorney},
            headers=headers,
        )
        unassigned = client.get(
            "/api/v1/admin/leads",
            params={"scope": "all", "assignment": "unassigned"},
            headers=headers,
        )
        email_search = client.get(
            "/api/v1/admin/leads",
            params={"scope": "all", "q": " ada@EXAMPLE.com "},
            headers=headers,
        )
        attorneys = client.get("/api/v1/admin/attorneys", headers=headers)

    assert my_leads.status_code == 200
    assert my_leads.json()["counts"] == {"my": 2, "unassigned": 1, "all": 4}
    assert [lead["id"] for lead in my_leads.json()["leads"]] == [
        "10000000-0000-4000-8000-000000000004",
        "10000000-0000-4000-8000-000000000001",
    ]
    assert all_first_page.status_code == 200
    assert all_second_page.status_code == 200
    first_ids = [lead["id"] for lead in all_first_page.json()["leads"]]
    second_ids = [lead["id"] for lead in all_second_page.json()["leads"]]
    assert first_ids == [
        "10000000-0000-4000-8000-000000000004",
        "10000000-0000-4000-8000-000000000003",
    ]
    assert second_ids == [
        "10000000-0000-4000-8000-000000000002",
        "10000000-0000-4000-8000-000000000001",
    ]
    assert not set(first_ids).intersection(second_ids)
    assert reached_out.json()["leads"][0]["id"] == "10000000-0000-4000-8000-000000000002"
    assert unassigned.json()["leads"][0]["assignedAttorney"] is None
    assert [lead["id"] for lead in email_search.json()["leads"]] == [
        "10000000-0000-4000-8000-000000000002",
        "10000000-0000-4000-8000-000000000001",
    ]
    assert attorneys.status_code == 200
    assert set(attorneys.json()[0]) == {"id", "email", "displayName"}


def test_local_supabase_status_transitions_preserve_assignment_and_append_history() -> None:
    if not get_settings().supabase_service_role_key:
        pytest.skip("set SUPABASE_SERVICE_ROLE_KEY to the local service role key")

    assigned_attorney = "00000000-0000-4000-8000-000000000031"
    acting_attorney = "11111111-1111-4111-8111-111111111111"
    asyncio.run(
        prepare_assignment_attorneys(
            [
                (assigned_attorney, "assigned-status@example.test", "Assigned Status Attorney"),
                (acting_attorney, "attorney.local@example.test", "Local Attorney"),
            ]
        )
    )
    attempt_key = f"local-status-{uuid4()}"

    with TestClient(app) as client:
        submitted = client.post(
            "/api/v1/leads",
            data=form_data(attempt_key),
            files=resume_file(pdf_bytes(attempt_key)),
        )

    assert submitted.status_code == 201
    lead_id = submitted.json()["leadId"]
    assert asyncio.run(fetch_assigned_attorney(attempt_key)) == assigned_attorney
    headers = {"Authorization": f"Bearer {sign_in_attorney()}"}

    with TestClient(app) as client:
        reached_out = client.patch(
            f"/api/v1/admin/leads/{lead_id}/status",
            json={"status": "REACHED_OUT", "version": 1},
            headers={**headers, "X-Request-ID": "integration-reached-out"},
        )
        repeated = client.patch(
            f"/api/v1/admin/leads/{lead_id}/status",
            json={"status": "REACHED_OUT", "version": 2},
            headers=headers,
        )
        stale = client.patch(
            f"/api/v1/admin/leads/{lead_id}/status",
            json={"status": "PENDING", "version": 1},
            headers=headers,
        )
        reversed_status = client.patch(
            f"/api/v1/admin/leads/{lead_id}/status",
            json={"status": "PENDING", "version": 2},
            headers={**headers, "X-Request-ID": "integration-reversed"},
        )
        refreshed = client.get(f"/api/v1/admin/leads/{lead_id}", headers=headers)

    assert reached_out.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json() == reached_out.json()
    assert stale.status_code == 409
    assert stale.json()["code"] == "lead_version_conflict"
    assert reversed_status.status_code == 200
    assert refreshed.json() == reversed_status.json()
    assert reversed_status.json()["status"] == "PENDING"
    assert reversed_status.json()["version"] == 3
    assert reversed_status.json()["assignedAttorney"]["id"] == assigned_attorney
    assert [row["status"] for row in reversed_status.json()["statusChanges"]] == [
        "PENDING",
        "REACHED_OUT",
        "PENDING",
    ]

    evidence = asyncio.run(fetch_status_evidence(lead_id))
    assert evidence["lead"] == {
        "current_status": "PENDING",
        "version": 3,
        "assigned_attorney_id": assigned_attorney,
    }
    assert [row["actor_attorney_id"] for row in evidence["status_changes"][1:]] == [
        acting_attorney,
        acting_attorney,
    ]
    assert all(row["created_at"] is not None for row in evidence["status_changes"])
    assert [row["payload"]["correlationId"] for row in evidence["audit_events"]] == [
        "integration-reached-out",
        "integration-reversed",
    ]
    assert all(row["actor_type"] == "ATTORNEY" for row in evidence["audit_events"])


def test_local_supabase_concurrent_status_mutations_expose_one_conflict() -> None:
    if not get_settings().supabase_service_role_key:
        pytest.skip("set SUPABASE_SERVICE_ROLE_KEY to the local service role key")

    asyncio.run(ensure_seeded_attorney())
    attempt_key = f"local-concurrent-status-{uuid4()}"
    with TestClient(app) as client:
        submitted = client.post(
            "/api/v1/leads",
            data=form_data(attempt_key),
            files=resume_file(pdf_bytes(attempt_key)),
        )

    assert submitted.status_code == 201
    lead_id = submitted.json()["leadId"]
    headers = {"Authorization": f"Bearer {sign_in_attorney()}"}

    async def mutate_concurrently():
        await database.connect(get_settings())
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await asyncio.gather(
                    client.patch(
                        f"/api/v1/admin/leads/{lead_id}/status",
                        json={"status": "REACHED_OUT", "version": 1},
                        headers=headers,
                    ),
                    client.patch(
                        f"/api/v1/admin/leads/{lead_id}/status",
                        json={"status": "REACHED_OUT", "version": 1},
                        headers=headers,
                    ),
                )
        finally:
            await database.close()

    responses = asyncio.run(mutate_concurrently())

    assert sorted(response.status_code for response in responses) == [200, 409]
    evidence = asyncio.run(fetch_status_evidence(lead_id))
    assert evidence["lead"]["current_status"] == "REACHED_OUT"
    assert evidence["lead"]["version"] == 2
    assert len(evidence["status_changes"]) == 2
    assert len(evidence["audit_events"]) == 1


def test_local_supabase_outbox_failure_rolls_back_and_compensates_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not get_settings().supabase_service_role_key:
        pytest.skip("set SUPABASE_SERVICE_ROLE_KEY to the local service role key")

    object_id = uuid4()
    object_key = f"{object_id}.pdf"
    attempt_key = f"local-outbox-failure-{uuid4()}"
    asyncio.run(ensure_seeded_attorney())
    asyncio.run(
        execute_admin(
            """
            create or replace function app.fail_internal_notification_for_test()
            returns trigger
              language plpgsql
              as $$
              begin
              if new.kind = 'INTERNAL_NEW_LEAD' then
                raise exception 'forced internal notification failure';
              end if;
              return new;
            end;
            $$;

            drop trigger if exists fail_internal_notification_for_test
              on app.email_outbox;

            create trigger fail_internal_notification_for_test
              before insert on app.email_outbox
              for each row execute function app.fail_internal_notification_for_test();
            """
        )
    )
    monkeypatch.setattr("lead_api.leads.uuid.uuid4", lambda: object_id)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/leads",
                data=form_data(attempt_key),
                files=resume_file(pdf_bytes("outbox-failure")),
            )

        assert response.status_code == 503
        assert response.json()["code"] == "lead_persistence_failed"
        attempt_count = asyncio.run(
            fetchval_admin(
                "select count(*) from app.submission_attempts where attempt_key = $1",
                attempt_key,
            )
        )
        assert attempt_count == 0
        assert service_storage_response(object_key) != 200
    finally:
        asyncio.run(
            execute_admin(
                """
                drop trigger if exists fail_internal_notification_for_test
                  on app.email_outbox;
                drop function if exists app.fail_internal_notification_for_test();
                """
            )
        )


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

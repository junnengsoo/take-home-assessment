import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from lead_api.auth import AttorneyIdentity, current_attorney
from lead_api.database import LeadVersionConflict
from lead_api.main import app

CURRENT_ATTORNEY = AttorneyIdentity(
    id="11111111-1111-4111-8111-111111111111",
    email="attorney.local@example.test",
    display_name="Local Attorney",
)

ASSIGNED_ATTORNEY = {
    "id": "22222222-2222-4222-8222-222222222222",
    "email": "assigned@example.test",
    "display_name": "Assigned Attorney",
}

LEAD_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def pending_detail_row() -> dict[str, object]:
    created_at = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)
    return {
        "id": LEAD_ID,
        "first_name": "Ada",
        "last_name": "Lovelace",
        "normalized_email": "ada@example.com",
        "current_status": "PENDING",
        "version": 1,
        "created_at": created_at,
        "assigned_attorney_id": ASSIGNED_ATTORNEY["id"],
        "assigned_attorney_email": ASSIGNED_ATTORNEY["email"],
        "assigned_attorney_display_name": ASSIGNED_ATTORNEY["display_name"],
        "resume_id": "33333333-3333-4333-8333-333333333333",
        "storage_bucket": "resumes",
        "storage_object_key": "private/generated.pdf",
        "original_filename": "Ada Resume.pdf",
        "content_type": "application/pdf",
        "byte_size": 18,
        "resume_created_at": created_at,
        "status_changes": [
            {
                "id": "44444444-4444-4444-8444-444444444444",
                "status": "PENDING",
                "actor_type": "SYSTEM",
                "actor_attorney_id": None,
                "actor_attorney_email": None,
                "actor_attorney_display_name": None,
                "created_at": created_at,
            }
        ],
    }


class StatusStore:
    def __init__(self) -> None:
        self.row = pending_detail_row()
        self.audit_events: list[dict[str, object]] = []
        self.lock = asyncio.Lock()

    async def fetch_lead_detail(self, lead_id: str) -> Optional[dict[str, object]]:
        if lead_id != LEAD_ID:
            return None
        return deepcopy(self.row)

    async def update_lead_status(
        self,
        *,
        lead_id: str,
        expected_version: int,
        desired_status: str,
        actor_attorney_id: str,
        correlation_id: str,
    ) -> Optional[dict[str, object]]:
        if lead_id != LEAD_ID:
            return None
        async with self.lock:
            if expected_version != self.row["version"]:
                raise LeadVersionConflict
            prior_status = self.row["current_status"]
            if prior_status == desired_status:
                return deepcopy(self.row)
            self.row["current_status"] = desired_status
            self.row["version"] = expected_version + 1
            change_index = len(self.row["status_changes"])
            changed_at = self.row["created_at"] + timedelta(hours=change_index)
            change_id = (
                "55555555-5555-4555-8555-555555555555"
                if change_index == 1
                else "66666666-6666-4666-8666-666666666666"
            )
            self.row["status_changes"].append(
                {
                    "id": change_id,
                    "status": desired_status,
                    "actor_type": "ATTORNEY",
                    "actor_attorney_id": CURRENT_ATTORNEY.id,
                    "actor_attorney_email": CURRENT_ATTORNEY.email,
                    "actor_attorney_display_name": CURRENT_ATTORNEY.display_name,
                    "created_at": changed_at,
                }
            )
            self.audit_events.append(
                {
                    "lead_id": lead_id,
                    "actor_attorney_id": actor_attorney_id,
                    "from_status": prior_status,
                    "to_status": desired_status,
                    "correlation_id": correlation_id,
                }
            )
            return deepcopy(self.row)


@pytest.fixture
def authenticated_status(monkeypatch: pytest.MonkeyPatch):
    async def authenticated():
        return CURRENT_ATTORNEY

    app.dependency_overrides[current_attorney] = authenticated
    store = StatusStore()
    monkeypatch.setattr(
        "lead_api.main.database.update_lead_status", store.update_lead_status, raising=False
    )
    monkeypatch.setattr(
        "lead_api.main.database.fetch_lead_detail", store.fetch_lead_detail, raising=False
    )
    yield store
    app.dependency_overrides.clear()


def test_any_attorney_can_mark_a_cross_assignment_lead_reached_out(
    authenticated_status: StatusStore,
) -> None:
    with TestClient(app) as client:
        response = client.patch(
            f"/api/v1/admin/leads/{LEAD_ID}/status",
            json={"status": "REACHED_OUT", "version": 1},
            headers={"X-Request-ID": "req-status-123"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REACHED_OUT"
    assert body["version"] == 2
    assert body["assignedAttorney"] == {
        "id": ASSIGNED_ATTORNEY["id"],
        "email": ASSIGNED_ATTORNEY["email"],
        "displayName": ASSIGNED_ATTORNEY["display_name"],
    }
    assert body["statusChanges"][-1] == {
        "id": "55555555-5555-4555-8555-555555555555",
        "status": "REACHED_OUT",
        "actor": {
            "type": "ATTORNEY",
            "attorney": {
                "id": CURRENT_ATTORNEY.id,
                "email": CURRENT_ATTORNEY.email,
                "displayName": CURRENT_ATTORNEY.display_name,
            },
        },
        "createdAt": "2026-08-30T15:00:00+00:00",
    }
    assert authenticated_status.audit_events == [
        {
            "lead_id": LEAD_ID,
            "actor_attorney_id": CURRENT_ATTORNEY.id,
            "from_status": "PENDING",
            "to_status": "REACHED_OUT",
            "correlation_id": "req-status-123",
        }
    ]


def test_attorney_can_reverse_reached_out_without_erasing_history(
    authenticated_status: StatusStore,
) -> None:
    with TestClient(app) as client:
        reached_out = client.patch(
            f"/api/v1/admin/leads/{LEAD_ID}/status",
            json={"status": "REACHED_OUT", "version": 1},
        )
        reversed_status = client.patch(
            f"/api/v1/admin/leads/{LEAD_ID}/status",
            json={"status": "PENDING", "version": reached_out.json()["version"]},
        )
        refreshed = client.get(f"/api/v1/admin/leads/{LEAD_ID}")

    assert reversed_status.status_code == 200
    assert reversed_status.json()["status"] == "PENDING"
    assert reversed_status.json()["version"] == 3
    assert [change["status"] for change in reversed_status.json()["statusChanges"]] == [
        "PENDING",
        "REACHED_OUT",
        "PENDING",
    ]
    assert reversed_status.json()["statusChanges"][-1]["actor"]["attorney"]["id"] == (
        CURRENT_ATTORNEY.id
    )
    assert refreshed.json() == reversed_status.json()
    assert len(authenticated_status.audit_events) == 2


def test_repeating_current_status_with_current_version_is_a_no_op(
    authenticated_status: StatusStore,
) -> None:
    with TestClient(app) as client:
        response = client.patch(
            f"/api/v1/admin/leads/{LEAD_ID}/status",
            json={"status": "PENDING", "version": 1},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "PENDING"
    assert response.json()["version"] == 1
    assert len(response.json()["statusChanges"]) == 1
    assert authenticated_status.audit_events == []


def test_stale_status_intent_returns_conflict_without_changing_history(
    authenticated_status: StatusStore,
) -> None:
    with TestClient(app) as client:
        accepted = client.patch(
            f"/api/v1/admin/leads/{LEAD_ID}/status",
            json={"status": "REACHED_OUT", "version": 1},
        )
        stale = client.patch(
            f"/api/v1/admin/leads/{LEAD_ID}/status",
            json={"status": "PENDING", "version": 1},
        )
        refreshed = client.get(f"/api/v1/admin/leads/{LEAD_ID}")

    assert accepted.status_code == 200
    assert stale.status_code == 409
    assert stale.headers["content-type"].startswith("application/problem+json")
    assert stale.json()["code"] == "lead_version_conflict"
    assert refreshed.json()["status"] == "REACHED_OUT"
    assert refreshed.json()["version"] == 2
    assert len(refreshed.json()["statusChanges"]) == 2
    assert len(authenticated_status.audit_events) == 1


def test_concurrent_status_mutations_accept_one_and_conflict_the_other(
    authenticated_status: StatusStore,
) -> None:
    async def mutate_concurrently():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await asyncio.gather(
                client.patch(
                    f"/api/v1/admin/leads/{LEAD_ID}/status",
                    json={"status": "REACHED_OUT", "version": 1},
                ),
                client.patch(
                    f"/api/v1/admin/leads/{LEAD_ID}/status",
                    json={"status": "REACHED_OUT", "version": 1},
                ),
            )

    responses = asyncio.run(mutate_concurrently())

    assert sorted(response.status_code for response in responses) == [200, 409]
    assert authenticated_status.row["current_status"] == "REACHED_OUT"
    assert authenticated_status.row["version"] == 2
    assert len(authenticated_status.row["status_changes"]) == 2
    assert len(authenticated_status.audit_events) == 1


def test_status_mutation_requires_attorney_authentication() -> None:
    with TestClient(app) as client:
        response = client.patch(
            f"/api/v1/admin/leads/{LEAD_ID}/status",
            json={"status": "REACHED_OUT", "version": 1},
        )

    assert response.status_code == 401
    assert response.json()["code"] == "missing_credentials"

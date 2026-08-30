from datetime import datetime, timezone
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from lead_api.auth import AttorneyIdentity, current_attorney
from lead_api.main import app

CURRENT_ATTORNEY = AttorneyIdentity(
    id="11111111-1111-4111-8111-111111111111",
    email="attorney.local@example.test",
    display_name="Local Attorney",
)
OTHER_ATTORNEY = {
    "id": "22222222-2222-4222-8222-222222222222",
    "email": "coverage@example.test",
    "display_name": "Coverage Attorney",
}


def lead_row(
    *,
    lead_id: str,
    created_at: datetime,
    normalized_email: str = "ada@example.com",
    status: str = "PENDING",
    assigned_attorney_id: Optional[str] = CURRENT_ATTORNEY.id,
    assigned_attorney_email: Optional[str] = CURRENT_ATTORNEY.email,
    assigned_attorney_display_name: Optional[str] = CURRENT_ATTORNEY.display_name,
) -> dict[str, object]:
    return {
        "id": lead_id,
        "first_name": "Ada",
        "last_name": "Lovelace",
        "normalized_email": normalized_email,
        "current_status": status,
        "version": 1,
        "created_at": created_at,
        "assigned_attorney_id": assigned_attorney_id,
        "assigned_attorney_email": assigned_attorney_email,
        "assigned_attorney_display_name": assigned_attorney_display_name,
    }


class QueueStore:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    async def list_leads(self, **kwargs):
        self.calls.append(kwargs)
        rows = list(self.rows)
        scope = kwargs["scope"]
        current_attorney_id = kwargs["current_attorney_id"]
        status = kwargs["status"]
        assignment = kwargs["assignment"]
        search_email = kwargs["search_email"]
        cursor = kwargs["cursor"]
        page_size = kwargs["page_size"]

        if scope == "my":
            rows = [row for row in rows if row["assigned_attorney_id"] == current_attorney_id]
        elif scope == "unassigned":
            rows = [row for row in rows if row["assigned_attorney_id"] is None]

        if status is not None:
            rows = [row for row in rows if row["current_status"] == status]

        if assignment == "me":
            rows = [row for row in rows if row["assigned_attorney_id"] == current_attorney_id]
        elif assignment == "unassigned":
            rows = [row for row in rows if row["assigned_attorney_id"] is None]
        elif assignment is not None:
            rows = [row for row in rows if row["assigned_attorney_id"] == assignment]

        if search_email is not None:
            rows = [row for row in rows if row["normalized_email"] == search_email]

        rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
        if cursor is not None:
            rows = [
                row
                for row in rows
                if (row["created_at"], row["id"]) < (cursor.created_at, cursor.lead_id)
            ]
        return rows[: page_size + 1]

    async def lead_queue_counts(self, *, current_attorney_id: str):
        return {
            "my": sum(1 for row in self.rows if row["assigned_attorney_id"] == current_attorney_id),
            "unassigned": sum(1 for row in self.rows if row["assigned_attorney_id"] is None),
            "all": len(self.rows),
        }

    async def list_attorneys(self):
        return [
            {
                "id": CURRENT_ATTORNEY.id,
                "email": CURRENT_ATTORNEY.email,
                "display_name": CURRENT_ATTORNEY.display_name,
            },
            OTHER_ATTORNEY,
        ]


@pytest.fixture
def authenticated_queue(monkeypatch: pytest.MonkeyPatch):
    async def authenticated():
        return CURRENT_ATTORNEY

    app.dependency_overrides[current_attorney] = authenticated
    store = QueueStore(
        [
            lead_row(
                lead_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                created_at=datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc),
            ),
            lead_row(
                lead_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                created_at=datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc),
                assigned_attorney_id=OTHER_ATTORNEY["id"],
                assigned_attorney_email=OTHER_ATTORNEY["email"],
                assigned_attorney_display_name=OTHER_ATTORNEY["display_name"],
            ),
            lead_row(
                lead_id="99999999-9999-4999-8999-999999999999",
                created_at=datetime(2026, 8, 30, 13, 0, tzinfo=timezone.utc),
                assigned_attorney_id=None,
                assigned_attorney_email=None,
                assigned_attorney_display_name=None,
            ),
            lead_row(
                lead_id="88888888-8888-4888-8888-888888888888",
                created_at=datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
                normalized_email="ada@example.com",
                status="REACHED_OUT",
            ),
        ]
    )
    monkeypatch.setattr("lead_api.main.database.list_leads", store.list_leads, raising=False)
    monkeypatch.setattr(
        "lead_api.main.database.lead_queue_counts", store.lead_queue_counts, raising=False
    )
    monkeypatch.setattr(
        "lead_api.main.database.list_attorneys", store.list_attorneys, raising=False
    )
    yield store
    app.dependency_overrides.clear()


def test_lead_queue_operations_require_attorney_authentication() -> None:
    with TestClient(app) as client:
        leads = client.get("/api/v1/admin/leads")
        counts = client.get("/api/v1/admin/leads/counts")
        attorneys = client.get("/api/v1/admin/attorneys")
        malformed_leads = client.get(
            "/api/v1/admin/leads", headers={"Authorization": "Basic abc"}
        )
        malformed_counts = client.get(
            "/api/v1/admin/leads/counts", headers={"Authorization": "Basic abc"}
        )
        malformed_attorneys = client.get(
            "/api/v1/admin/attorneys", headers={"Authorization": "Basic abc"}
        )

    assert leads.status_code == 401
    assert counts.status_code == 401
    assert attorneys.status_code == 401
    assert leads.json()["code"] == "missing_credentials"
    assert counts.json()["code"] == "missing_credentials"
    assert attorneys.json()["code"] == "missing_credentials"
    assert malformed_leads.status_code == 401
    assert malformed_counts.status_code == 401
    assert malformed_attorneys.status_code == 401
    assert malformed_leads.json()["code"] == "malformed_credentials"
    assert malformed_counts.json()["code"] == "malformed_credentials"
    assert malformed_attorneys.json()["code"] == "malformed_credentials"


def test_default_queue_is_my_leads_with_counts_and_cross_assignment_visibility(
    authenticated_queue: QueueStore,
) -> None:
    with TestClient(app) as client:
        default_response = client.get("/api/v1/admin/leads")
        all_response = client.get("/api/v1/admin/leads", params={"scope": "all"})

    assert default_response.status_code == 200
    assert default_response.json()["counts"] == {"my": 2, "unassigned": 1, "all": 4}
    assert [lead["id"] for lead in default_response.json()["leads"]] == [
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "88888888-8888-4888-8888-888888888888",
    ]
    assert authenticated_queue.calls[0]["page_size"] == 50

    assert all_response.status_code == 200
    all_leads = all_response.json()["leads"]
    assert [lead["id"] for lead in all_leads] == [
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "99999999-9999-4999-8999-999999999999",
        "88888888-8888-4888-8888-888888888888",
    ]
    assert all_leads[1]["assignedAttorney"] == {
        "id": OTHER_ATTORNEY["id"],
        "email": OTHER_ATTORNEY["email"],
        "displayName": OTHER_ATTORNEY["display_name"],
    }


def test_queue_filters_by_status_assignment_and_normalized_email_search(
    authenticated_queue: QueueStore,
) -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/admin/leads",
            params={
                "scope": "all",
                "status": "REACHED_OUT",
                "assignment": "me",
                "q": " ADA@EXAMPLE.COM ",
            },
        )
        unassigned = client.get(
            "/api/v1/admin/leads",
            params={"scope": "all", "assignment": "unassigned"},
        )

    assert response.status_code == 200
    assert [lead["id"] for lead in response.json()["leads"]] == [
        "88888888-8888-4888-8888-888888888888"
    ]
    assert authenticated_queue.calls[0]["search_email"] == "ada@example.com"
    assert unassigned.status_code == 200
    assert unassigned.json()["leads"][0]["assignedAttorney"] is None


def test_queue_cursor_is_stable_for_leads_with_matching_creation_timestamps(
    authenticated_queue: QueueStore,
) -> None:
    with TestClient(app) as client:
        first_page = client.get(
            "/api/v1/admin/leads",
            params={"scope": "all", "pageSize": "2"},
        )
        second_page = client.get(
            "/api/v1/admin/leads",
            params={
                "scope": "all",
                "pageSize": "2",
                "cursor": first_page.json()["nextCursor"],
            },
        )

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    first_ids = [lead["id"] for lead in first_page.json()["leads"]]
    second_ids = [lead["id"] for lead in second_page.json()["leads"]]
    assert first_ids == [
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    ]
    assert second_ids == [
        "99999999-9999-4999-8999-999999999999",
        "88888888-8888-4888-8888-888888888888",
    ]
    assert not set(first_ids).intersection(second_ids)
    assert second_page.json()["nextCursor"] is None


def test_current_attorney_and_attorney_list_expose_only_identity_data(
    authenticated_queue: QueueStore,
) -> None:
    with TestClient(app) as client:
        me = client.get("/api/v1/admin/attorneys/me")
        attorneys = client.get("/api/v1/admin/attorneys")

    assert me.status_code == 200
    assert me.json() == {
        "id": CURRENT_ATTORNEY.id,
        "email": CURRENT_ATTORNEY.email,
        "displayName": CURRENT_ATTORNEY.display_name,
    }
    assert attorneys.status_code == 200
    assert attorneys.json() == [
        {
            "id": CURRENT_ATTORNEY.id,
            "email": CURRENT_ATTORNEY.email,
            "displayName": CURRENT_ATTORNEY.display_name,
        },
        {
            "id": OTHER_ATTORNEY["id"],
            "email": OTHER_ATTORNEY["email"],
            "displayName": OTHER_ATTORNEY["display_name"],
        },
    ]


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"scope": "mine"}, "invalid_lead_scope"),
        ({"status": "CLOSED"}, "invalid_lead_status"),
        ({"assignment": "not-a-uuid"}, "invalid_assignment_filter"),
        ({"cursor": "not-a-cursor"}, "invalid_lead_cursor"),
        ({"pageSize": "101"}, "invalid_page_size"),
    ],
)
def test_queue_rejects_invalid_filter_and_cursor_state(
    authenticated_queue: QueueStore, params: dict[str, str], code: str
) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/leads", params=params)

    assert response.status_code == 400
    assert response.json()["code"] == code

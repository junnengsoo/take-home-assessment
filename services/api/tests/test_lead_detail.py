from datetime import datetime, timezone
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from lead_api.auth import AttorneyIdentity, current_attorney
from lead_api.main import app
from lead_api.problems import ProblemError

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

LEAD_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def detail_row(*, content_type: str = "application/pdf") -> dict[str, object]:
    created_at = datetime(2026, 8, 30, 14, 0, tzinfo=timezone.utc)
    return {
        "id": LEAD_ID,
        "first_name": "Ada",
        "last_name": "Lovelace",
        "normalized_email": "ada@example.com",
        "current_status": "PENDING",
        "version": 3,
        "created_at": created_at,
        "assigned_attorney_id": OTHER_ATTORNEY["id"],
        "assigned_attorney_email": OTHER_ATTORNEY["email"],
        "assigned_attorney_display_name": OTHER_ATTORNEY["display_name"],
        "resume_id": "33333333-3333-4333-8333-333333333333",
        "storage_bucket": "resumes",
        "storage_object_key": "private/generated.pdf",
        "original_filename": "Ada Resume.pdf",
        "content_type": content_type,
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
            },
            {
                "id": "55555555-5555-4555-8555-555555555555",
                "status": "REACHED_OUT",
                "actor_type": "ATTORNEY",
                "actor_attorney_id": CURRENT_ATTORNEY.id,
                "actor_attorney_email": CURRENT_ATTORNEY.email,
                "actor_attorney_display_name": CURRENT_ATTORNEY.display_name,
                "created_at": datetime(2026, 8, 30, 15, 0, tzinfo=timezone.utc),
            },
        ],
    }


class DetailStore:
    def __init__(self, row: Optional[dict[str, object]] = None) -> None:
        self.row = row if row is not None else detail_row()
        self.audit_events: list[dict[str, object]] = []

    async def fetch_lead_detail(self, lead_id: str):
        if lead_id == LEAD_ID:
            return self.row
        return None

    async def append_resume_download_audit_event(
        self, *, lead_id: str, actor_attorney_id: str, correlation_id: str
    ):
        self.audit_events.append(
            {
                "lead_id": lead_id,
                "actor_attorney_id": actor_attorney_id,
                "correlation_id": correlation_id,
            }
        )


class ResumeStore:
    def __init__(self, content: bytes = b"%PDF-1.7\nresume\n%%EOF") -> None:
        self.content = content
        self.keys: list[str] = []
        self.fail_missing = False

    async def download(self, settings, object_key: str) -> bytes:
        self.keys.append(object_key)
        if self.fail_missing:
            raise ProblemError(
                404,
                "Résumé unavailable",
                "The résumé could not be found for this Lead.",
                "resume_not_found",
            )
        return self.content


@pytest.fixture
def authenticated_detail(monkeypatch: pytest.MonkeyPatch):
    async def authenticated():
        return CURRENT_ATTORNEY

    app.dependency_overrides[current_attorney] = authenticated
    store = DetailStore()
    resumes = ResumeStore()
    monkeypatch.setattr("lead_api.main.database.fetch_lead_detail", store.fetch_lead_detail)
    monkeypatch.setattr(
        "lead_api.main.database.append_resume_download_audit_event",
        store.append_resume_download_audit_event,
    )
    monkeypatch.setattr("lead_api.main.resume_storage", resumes)
    yield store, resumes
    app.dependency_overrides.clear()


def test_lead_detail_requires_attorney_authentication() -> None:
    with TestClient(app) as client:
        detail = client.get(f"/api/v1/admin/leads/{LEAD_ID}")
        resume = client.get(f"/api/v1/admin/leads/{LEAD_ID}/resume")

    assert detail.status_code == 401
    assert resume.status_code == 401
    assert detail.json()["code"] == "missing_credentials"
    assert resume.json()["code"] == "missing_credentials"


def test_any_attorney_can_inspect_cross_assignment_lead_detail(
    authenticated_detail: tuple[DetailStore, ResumeStore],
) -> None:
    with TestClient(app) as client:
        response = client.get(f"/api/v1/admin/leads/{LEAD_ID}")

    assert response.status_code == 200
    assert response.json() == {
        "id": LEAD_ID,
        "firstName": "Ada",
        "lastName": "Lovelace",
        "email": "ada@example.com",
        "status": "PENDING",
        "version": 3,
        "createdAt": "2026-08-30T14:00:00+00:00",
        "assignedAttorney": {
            "id": OTHER_ATTORNEY["id"],
            "email": OTHER_ATTORNEY["email"],
            "displayName": OTHER_ATTORNEY["display_name"],
        },
        "resume": {
            "id": "33333333-3333-4333-8333-333333333333",
            "originalFilename": "Ada Resume.pdf",
            "contentType": "application/pdf",
            "byteSize": 18,
            "createdAt": "2026-08-30T14:00:00+00:00",
            "previewable": True,
        },
        "statusChanges": [
            {
                "id": "44444444-4444-4444-8444-444444444444",
                "status": "PENDING",
                "actor": {"type": "SYSTEM"},
                "createdAt": "2026-08-30T14:00:00+00:00",
            },
            {
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
            },
        ],
    }


def test_missing_lead_returns_non_leaking_problem_response(
    authenticated_detail: tuple[DetailStore, ResumeStore],
) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/admin/leads/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

    assert response.status_code == 404
    assert response.json()["code"] == "lead_not_found"
    assert "bbbbbbbb" not in response.json()["detail"]


def test_resume_preview_streams_pdf_inline_and_appends_audit_event(
    authenticated_detail: tuple[DetailStore, ResumeStore],
) -> None:
    store, resumes = authenticated_detail

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/admin/leads/{LEAD_ID}/resume",
            params={"disposition": "inline"},
            headers={"X-Request-ID": "req-preview-123"},
        )

    assert response.status_code == 200
    assert response.content == b"%PDF-1.7\nresume\n%%EOF"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'inline; filename="Ada Resume.pdf"'
    assert response.headers["cache-control"] == "no-store"
    assert resumes.keys == ["private/generated.pdf"]
    assert store.audit_events == [
        {
            "lead_id": LEAD_ID,
            "actor_attorney_id": CURRENT_ATTORNEY.id,
            "correlation_id": "req-preview-123",
        }
    ]


def test_resume_download_uses_attachment_for_non_previewable_resume(
    authenticated_detail: tuple[DetailStore, ResumeStore],
) -> None:
    store, _ = authenticated_detail
    store.row = detail_row(
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/admin/leads/{LEAD_ID}/resume",
            params={"disposition": "inline"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert response.headers["content-disposition"] == 'attachment; filename="Ada Resume.pdf"'


def test_missing_resume_object_does_not_append_false_audit_event(
    authenticated_detail: tuple[DetailStore, ResumeStore],
) -> None:
    store, resumes = authenticated_detail
    resumes.fail_missing = True

    with TestClient(app) as client:
        response = client.get(f"/api/v1/admin/leads/{LEAD_ID}/resume")

    assert response.status_code == 404
    assert response.json()["code"] == "resume_not_found"
    assert store.audit_events == []

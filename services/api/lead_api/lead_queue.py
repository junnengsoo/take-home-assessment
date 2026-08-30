import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from lead_api.problems import ProblemError

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
LEAD_SCOPES = {"my", "unassigned", "all"}
LEAD_STATUSES = {"PENDING", "REACHED_OUT"}
ASSIGNMENT_SHORTCUTS = {"me", "unassigned"}


@dataclass(frozen=True)
class LeadCursor:
    created_at: datetime
    lead_id: str


def normalize_email_search(query: Optional[str]) -> Optional[str]:
    if query is None:
        return None
    normalized = query.strip().lower()
    return normalized or None


def parse_scope(scope: str) -> str:
    if scope not in LEAD_SCOPES:
        raise ProblemError(
            400,
            "Invalid Lead scope",
            "Lead queue scope must be my, unassigned, or all.",
            "invalid_lead_scope",
        )
    return scope


def parse_status(status: Optional[str]) -> Optional[str]:
    if status is None or status == "":
        return None
    if status not in LEAD_STATUSES:
        raise ProblemError(
            400,
            "Invalid Lead Status",
            "Lead Status filter must be PENDING or REACHED_OUT.",
            "invalid_lead_status",
        )
    return status


def parse_assignment(assignment: Optional[str]) -> Optional[str]:
    if assignment is None or assignment == "":
        return None
    if assignment in ASSIGNMENT_SHORTCUTS:
        return assignment
    try:
        UUID(assignment)
    except ValueError as exc:
        raise ProblemError(
            400,
            "Invalid Assignment filter",
            "Assignment filter must be me, unassigned, or an Attorney identity.",
            "invalid_assignment_filter",
        ) from exc
    return assignment


def parse_page_size(page_size: int) -> int:
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ProblemError(
            400,
            "Invalid page size",
            f"Lead queue page size must be between 1 and {MAX_PAGE_SIZE}.",
            "invalid_page_size",
        )
    return page_size


def parse_cursor(cursor: Optional[str]) -> Optional[LeadCursor]:
    if cursor is None or cursor == "":
        return None
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        created_at = datetime.fromisoformat(payload["createdAt"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        lead_id = str(UUID(payload["leadId"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProblemError(
            400,
            "Invalid Lead cursor",
            "Lead cursor must come from a previous Lead queue response.",
            "invalid_lead_cursor",
        ) from exc
    return LeadCursor(created_at=created_at, lead_id=lead_id)


def encode_cursor(row) -> str:
    created_at = row["created_at"]
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    payload = {
        "createdAt": created_at.isoformat(),
        "leadId": row["id"],
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
    return encoded.decode().rstrip("=")


def attorney_payload(row) -> dict[str, str]:
    return {
        "id": row["id"],
        "email": row["email"],
        "displayName": row["display_name"],
    }


def current_attorney_payload(attorney) -> dict[str, str]:
    return {
        "id": attorney.id,
        "email": attorney.email,
        "displayName": attorney.display_name,
    }


def lead_payload(row) -> dict[str, object]:
    assigned_attorney = None
    if row["assigned_attorney_id"] is not None:
        assigned_attorney = {
            "id": row["assigned_attorney_id"],
            "email": row["assigned_attorney_email"],
            "displayName": row["assigned_attorney_display_name"],
        }

    return {
        "id": row["id"],
        "firstName": row["first_name"],
        "lastName": row["last_name"],
        "email": row["normalized_email"],
        "status": row["current_status"],
        "version": row["version"],
        "createdAt": row["created_at"].isoformat(),
        "assignedAttorney": assigned_attorney,
    }


def lead_queue_payload(rows, *, page_size: int, counts: dict[str, int]) -> dict[str, object]:
    page_rows = rows[:page_size]
    return {
        "leads": [lead_payload(row) for row in page_rows],
        "counts": counts,
        "nextCursor": encode_cursor(page_rows[-1]) if len(rows) > page_size else None,
    }

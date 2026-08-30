from typing import Literal, Optional
from uuid import UUID

from lead_api.problems import ProblemError

PREVIEWABLE_RESUME_TYPES = {"application/pdf"}


def parse_lead_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ProblemError(
            404,
            "Lead not found",
            "No Lead was found for the authenticated Attorney.",
            "lead_not_found",
        ) from exc


def parse_resume_disposition(disposition: str) -> Literal["inline", "attachment"]:
    if disposition == "inline":
        return "inline"
    if disposition == "attachment":
        return "attachment"
    raise ProblemError(
        400,
        "Invalid résumé disposition",
        "Résumé disposition must be inline or attachment.",
        "invalid_resume_disposition",
    )


def is_previewable_resume(content_type: str) -> bool:
    return content_type in PREVIEWABLE_RESUME_TYPES


def assigned_attorney_payload(row) -> Optional[dict[str, str]]:
    if row["assigned_attorney_id"] is None:
        return None
    return {
        "id": row["assigned_attorney_id"],
        "email": row["assigned_attorney_email"],
        "displayName": row["assigned_attorney_display_name"],
    }


def status_change_actor_payload(row) -> dict[str, object]:
    if row["actor_type"] == "SYSTEM":
        return {"type": "SYSTEM"}
    return {
        "type": "ATTORNEY",
        "attorney": {
            "id": row["actor_attorney_id"],
            "email": row["actor_attorney_email"],
            "displayName": row["actor_attorney_display_name"],
        },
    }


def status_change_payload(row) -> dict[str, object]:
    return {
        "id": row["id"],
        "status": row["status"],
        "actor": status_change_actor_payload(row),
        "createdAt": row["created_at"].isoformat(),
    }


def lead_detail_payload(row) -> dict[str, object]:
    content_type = row["content_type"]
    return {
        "id": row["id"],
        "firstName": row["first_name"],
        "lastName": row["last_name"],
        "email": row["normalized_email"],
        "status": row["current_status"],
        "version": row["version"],
        "createdAt": row["created_at"].isoformat(),
        "assignedAttorney": assigned_attorney_payload(row),
        "resume": {
            "id": row["resume_id"],
            "originalFilename": row["original_filename"],
            "contentType": content_type,
            "byteSize": row["byte_size"],
            "createdAt": row["resume_created_at"].isoformat(),
            "previewable": is_previewable_resume(content_type),
        },
        "statusChanges": [
            status_change_payload(status_change) for status_change in row["status_changes"]
        ],
    }


def safe_content_disposition(
    *, original_filename: str, requested_disposition: str, content_type: str
) -> str:
    disposition = "inline"
    if requested_disposition == "attachment" or not is_previewable_resume(content_type):
        disposition = "attachment"
    safe_filename = "".join(
        "_" if character in {'"', "\\", "\r", "\n"} else character
        for character in original_filename
    )
    return f'{disposition}; filename="{safe_filename}"'

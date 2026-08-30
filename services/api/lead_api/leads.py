import hashlib
import json
import logging
import re
import uuid
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from typing import Optional

from fastapi import File, Form, Response, UploadFile

from lead_api.config import get_settings
from lead_api.database import LeadPersistenceError, SubmissionAttemptAlreadyExists, database
from lead_api.problems import ProblemError
from lead_api.storage import resume_storage

logger = logging.getLogger(__name__)

MAX_RESUME_BYTES = 5 * 1024 * 1024
ALLOWED_RESUME_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
FIRST_NAME_FORM = Form(default=None, alias="firstName")
LAST_NAME_FORM = Form(default=None, alias="lastName")
EMAIL_FORM = Form(default=None)
SUBMISSION_ATTEMPT_KEY_FORM = Form(default=None, alias="submissionAttemptKey")
RESUME_FILE = File(default=None)


@dataclass(frozen=True)
class ValidatedResume:
    original_filename: str
    extension: str
    content_type: str
    content: bytes
    sha256_digest: str


def normalize_name(value: Optional[str], label: str) -> str:
    normalized = " ".join((value or "").strip().split())
    if not normalized:
        raise ProblemError(
            400,
            "Required field missing",
            f"{label} is required.",
            "missing_required_field",
        )
    if len(normalized) > 120:
        raise ProblemError(
            400,
            "Field is too long",
            f"{label} must be 120 characters or fewer.",
            "field_too_long",
        )
    return normalized


def normalize_email(value: Optional[str]) -> str:
    normalized = (value or "").strip().lower()
    if not normalized:
        raise ProblemError(
            400,
            "Required field missing",
            "Email is required.",
            "missing_required_field",
        )
    if len(normalized) > 320 or not EMAIL_RE.match(normalized):
        raise ProblemError(
            400,
            "Email is invalid",
            "Enter a valid email address.",
            "invalid_email",
        )
    return normalized


def normalize_attempt_key(value: Optional[str]) -> str:
    normalized = (value or "").strip()
    if len(normalized) < 12 or len(normalized) > 200:
        raise ProblemError(
            400,
            "Submission Attempt is invalid",
            "Refresh the page and submit the form again.",
            "invalid_submission_attempt",
        )
    return normalized


async def validate_resume(upload: Optional[UploadFile]) -> ValidatedResume:
    if upload is None:
        raise ProblemError(
            400,
            "Required file missing",
            "Résumé is required.",
            "missing_required_file",
        )

    original_filename = PurePath(upload.filename or "").name
    extension = PurePath(original_filename).suffix.lower()
    expected_content_type = ALLOWED_RESUME_TYPES.get(extension)
    declared_content_type = (upload.content_type or "").lower()

    if expected_content_type is None:
        raise ProblemError(
            400,
            "Résumé type is unsupported",
            "Upload a PDF, DOC, or DOCX résumé.",
            "unsupported_resume_type",
        )
    if declared_content_type != expected_content_type:
        raise ProblemError(
            400,
            "Résumé type does not match",
            "The filename extension and declared file type must match.",
            "mismatched_resume_type",
        )

    content = await upload.read(MAX_RESUME_BYTES + 1)
    if len(content) > MAX_RESUME_BYTES:
        raise ProblemError(
            413,
            "Résumé is too large",
            "Upload a résumé that is 5 MiB or smaller.",
            "resume_too_large",
        )
    if not content:
        raise ProblemError(
            400,
            "Résumé is empty",
            "Upload a non-empty résumé file.",
            "empty_resume",
        )
    if not file_signature_matches(extension, content):
        raise ProblemError(
            400,
            "Résumé contents do not match",
            "The uploaded file contents must match the PDF, DOC, or DOCX type.",
            "mismatched_resume_signature",
        )

    return ValidatedResume(
        original_filename=original_filename,
        extension=extension,
        content_type=expected_content_type,
        content=content,
        sha256_digest=hashlib.sha256(content).hexdigest(),
    )


def file_signature_matches(extension: str, content: bytes) -> bool:
    if extension == ".pdf":
        return content.startswith(b"%PDF-")
    if extension == ".doc":
        return content.startswith(bytes.fromhex("d0cf11e0a1b11ae1"))
    if extension == ".docx":
        if not content.startswith(b"PK"):
            return False
        try:
            with zipfile.ZipFile(BytesIO(content)) as docx:
                names = set(docx.namelist())
        except zipfile.BadZipFile:
            return False
        return "[Content_Types].xml" in names and any(name.startswith("word/") for name in names)
    return False


def request_fingerprint(
    *,
    first_name: str,
    last_name: str,
    normalized_email: str,
    resume_digest: str,
) -> str:
    body = {
        "firstName": first_name,
        "lastName": last_name,
        "normalizedEmail": normalized_email,
        "resumeSha256Digest": resume_digest,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def submit_lead(
    response: Response,
    first_name: Optional[str] = FIRST_NAME_FORM,
    last_name: Optional[str] = LAST_NAME_FORM,
    email: Optional[str] = EMAIL_FORM,
    submission_attempt_key: Optional[str] = SUBMISSION_ATTEMPT_KEY_FORM,
    resume: Optional[UploadFile] = RESUME_FILE,
) -> dict[str, object]:
    clean_first_name = normalize_name(first_name, "First name")
    clean_last_name = normalize_name(last_name, "Last name")
    normalized_email = normalize_email(email)
    attempt_key = normalize_attempt_key(submission_attempt_key)
    validated_resume = await validate_resume(resume)
    fingerprint = request_fingerprint(
        first_name=clean_first_name,
        last_name=clean_last_name,
        normalized_email=normalized_email,
        resume_digest=validated_resume.sha256_digest,
    )

    existing = await database.fetch_submission_attempt(attempt_key)
    if existing is not None:
        if existing["request_fingerprint"] != fingerprint:
            raise submission_attempt_conflict()
        response.status_code = 200
        return lead_confirmation(existing)

    settings = get_settings()
    object_key = f"{uuid.uuid4()}{validated_resume.extension}"
    stored_resume = await resume_storage.upload(
        settings,
        object_key,
        validated_resume.content,
        validated_resume.content_type,
    )

    try:
        lead = await database.create_lead_submission(
            attempt_key=attempt_key,
            request_fingerprint=fingerprint,
            first_name=clean_first_name,
            last_name=clean_last_name,
            normalized_email=normalized_email,
            storage_bucket=stored_resume.bucket,
            storage_object_key=stored_resume.object_key,
            original_filename=validated_resume.original_filename,
            content_type=validated_resume.content_type,
            byte_size=len(validated_resume.content),
            sha256_digest=validated_resume.sha256_digest,
        )
    except SubmissionAttemptAlreadyExists as exc:
        await compensate_resume_upload(settings, stored_resume.object_key)
        if exc.existing["request_fingerprint"] == fingerprint:
            response.status_code = 200
            return lead_confirmation(exc.existing)
        raise submission_attempt_conflict() from exc
    except Exception as exc:
        await compensate_resume_upload(settings, stored_resume.object_key)
        if isinstance(exc, LeadPersistenceError):
            raise ProblemError(
                503,
                "Lead could not be saved",
                "The résumé upload was rolled back after the Lead could not be saved.",
                "lead_persistence_failed",
            ) from exc
        raise

    return lead_confirmation(lead)


async def compensate_resume_upload(settings, object_key: str) -> None:
    try:
        await resume_storage.delete(settings, object_key)
    except Exception:
        logger.exception(
            "resume_compensation_delete_failed",
            extra={"storage_bucket": settings.resume_bucket, "storage_object_key": object_key},
        )


def lead_confirmation(lead) -> dict[str, object]:
    return {
        "leadId": lead["lead_id"],
        "confirmation": "Your résumé has been received.",
    }


def submission_attempt_conflict() -> ProblemError:
    return ProblemError(
        409,
        "Submission Attempt conflict",
        "This Submission Attempt was already used for different content.",
        "submission_attempt_conflict",
    )

import io
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from lead_api.abuse import TurnstileExplicitFailure, TurnstileOutcome, TurnstileUnavailable
from lead_api.config import Settings
from lead_api.database import LeadPersistenceError, SubmissionAttemptAlreadyExists
from lead_api.leads import MAX_RESUME_BYTES
from lead_api.main import app


class FakeStorage:
    def __init__(self) -> None:
        self.uploads = []
        self.deletes = []
        self.fail_delete = False

    async def upload(self, settings, object_key: str, content: bytes, content_type: str):
        self.uploads.append(
            {
                "bucket": settings.resume_bucket,
                "object_key": object_key,
                "content": content,
                "content_type": content_type,
            }
        )
        return SimpleNamespace(bucket=settings.resume_bucket, object_key=object_key)

    async def delete(self, settings, object_key: str) -> None:
        self.deletes.append({"bucket": settings.resume_bucket, "object_key": object_key})
        if self.fail_delete:
            raise RuntimeError("delete failed")


def pdf_bytes() -> bytes:
    return b"%PDF-1.7\nresume\n%%EOF"


def doc_bytes() -> bytes:
    return bytes.fromhex("d0cf11e0a1b11ae1") + b"legacy-doc"


def docx_bytes() -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as docx:
        docx.writestr("[Content_Types].xml", "<Types />")
        docx.writestr("word/document.xml", "<document />")
    return archive.getvalue()


def form_data(attempt_key: str = "attempt-123456") -> dict[str, str]:
    return {
        "firstName": "  Ada ",
        "lastName": " Lovelace ",
        "email": " ADA@example.COM ",
        "submissionAttemptKey": attempt_key,
        "turnstileToken": "fresh-turnstile-token",
        "website": "",
    }


def resume_file(
    filename: str = "resume.pdf",
    content: bytes = pdf_bytes(),
    content_type: str = "application/pdf",
) -> dict[str, tuple[str, bytes, str]]:
    return {"resume": (filename, content, content_type)}


def make_lead(lead_id: str = "33333333-3333-4333-8333-333333333333"):
    return {
        "lead_id": lead_id,
        "request_fingerprint": "a" * 64,
        "version": 1,
    }


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    storage = FakeStorage()
    monkeypatch.setattr("lead_api.leads.resume_storage", storage)
    return storage


@pytest.fixture(autouse=True)
def allow_abuse_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow_rate_limit(**kwargs):
        return True

    async def pass_turnstile(*args, **kwargs):
        return TurnstileOutcome.SUCCESS

    monkeypatch.setattr("lead_api.leads.database.consume_public_lead_rate_limit", allow_rate_limit)
    monkeypatch.setattr("lead_api.leads.verify_turnstile", pass_turnstile)


def test_public_lead_submission_persists_private_resume_metadata(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage
) -> None:
    created = {}

    async def no_existing(attempt_key: str):
        return None

    async def create_lead_submission(**kwargs):
        created.update(kwargs)
        return make_lead()

    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", no_existing)
    monkeypatch.setattr("lead_api.leads.database.create_lead_submission", create_lead_submission)

    with TestClient(app) as client:
        response = client.post("/api/v1/leads", data=form_data(), files=resume_file())

    assert response.status_code == 201
    assert response.json() == {
        "leadId": "33333333-3333-4333-8333-333333333333",
        "confirmation": "Your résumé has been received.",
    }
    assert created["first_name"] == "Ada"
    assert created["last_name"] == "Lovelace"
    assert created["normalized_email"] == "ada@example.com"
    assert created["original_filename"] == "resume.pdf"
    assert created["storage_bucket"] == "resumes"
    assert created["storage_object_key"].endswith(".pdf")
    assert created["storage_object_key"] != "resume.pdf"
    assert created["byte_size"] == len(pdf_bytes())
    assert created["sha256_digest"] != created["request_fingerprint"]
    assert created["fallback_intake_address"] == "intake.local@example.test"
    assert "storage_object_key" not in response.json()
    assert len(fake_storage.uploads) == 1
    assert created["turnstile_verification_outcome"] == "SUCCESS"


def test_explicit_turnstile_rejection_does_not_create_lead(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage
) -> None:
    async def fail_turnstile(*args, **kwargs):
        raise TurnstileExplicitFailure(["invalid-input-response"])

    async def no_existing(attempt_key: str):
        return None

    async def create_lead_submission(**kwargs):
        raise AssertionError("explicit bot verification failures must not persist a Lead")

    monkeypatch.setattr("lead_api.leads.verify_turnstile", fail_turnstile)
    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", no_existing)
    monkeypatch.setattr("lead_api.leads.database.create_lead_submission", create_lead_submission)

    with TestClient(app) as client:
        response = client.post("/api/v1/leads", data=form_data(), files=resume_file())

    assert response.status_code == 400
    assert response.json()["code"] == "turnstile_verification_failed"
    assert "try again" in response.json()["detail"].lower()
    assert fake_storage.uploads == []


def test_expired_or_replayed_turnstile_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage
) -> None:
    async def duplicate_turnstile(*args, **kwargs):
        raise TurnstileExplicitFailure(["timeout-or-duplicate"])

    async def no_existing(attempt_key: str):
        return None

    async def create_lead_submission(**kwargs):
        raise AssertionError("expired or replayed tokens must not persist a Lead")

    monkeypatch.setattr("lead_api.leads.verify_turnstile", duplicate_turnstile)
    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", no_existing)
    monkeypatch.setattr("lead_api.leads.database.create_lead_submission", create_lead_submission)

    with TestClient(app) as client:
        response = client.post("/api/v1/leads", data=form_data(), files=resume_file())

    assert response.status_code == 400
    assert response.json()["code"] == "turnstile_verification_failed"
    assert fake_storage.uploads == []


def test_turnstile_infrastructure_failure_accepts_lead_with_internal_outcome(
    monkeypatch: pytest.MonkeyPatch,
    fake_storage: FakeStorage,
    caplog: pytest.LogCaptureFixture,
) -> None:
    created = {}

    async def unavailable_turnstile(*args, **kwargs):
        raise TurnstileUnavailable("timeout")

    async def no_existing(attempt_key: str):
        return None

    async def create_lead_submission(**kwargs):
        created.update(kwargs)
        return make_lead()

    monkeypatch.setattr("lead_api.leads.verify_turnstile", unavailable_turnstile)
    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", no_existing)
    monkeypatch.setattr("lead_api.leads.database.create_lead_submission", create_lead_submission)

    with TestClient(app, client=("203.0.113.10", 50000)) as client:
        response = client.post("/api/v1/leads", data=form_data(), files=resume_file())

    assert response.status_code == 201
    assert created["turnstile_verification_outcome"] == "UNAVAILABLE"
    assert "turnstile_verification_unavailable" in caplog.text
    assert "fresh-turnstile-token" not in caplog.text
    assert "203.0.113.10" not in caplog.text
    assert "ada@example.com" not in caplog.text


def test_rate_limit_runs_before_turnstile_and_uses_hmac_address_key(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage
) -> None:
    captured = {}

    async def reject_rate_limit(**kwargs):
        captured.update(kwargs)
        return False

    async def pass_turnstile(*args, **kwargs):
        raise AssertionError("Turnstile should not run after the request limit rejects")

    async def no_existing(attempt_key: str):
        return None

    monkeypatch.setattr(
        "lead_api.leads.database.consume_public_lead_rate_limit", reject_rate_limit
    )
    monkeypatch.setattr("lead_api.leads.verify_turnstile", pass_turnstile)
    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", no_existing)

    with TestClient(app, client=("203.0.113.10", 50000)) as client:
        response = client.post("/api/v1/leads", data=form_data(), files=resume_file())

    assert response.status_code == 429
    assert response.json()["code"] == "public_lead_rate_limited"
    assert captured["address_key"] != "203.0.113.10"
    assert len(captured["address_key"]) == 64
    assert all(character in "0123456789abcdef" for character in captured["address_key"])
    assert fake_storage.uploads == []


def test_trusted_proxy_forwarded_address_changes_rate_limit_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = []

    async def capture_rate_limit(**kwargs):
        keys.append(kwargs["address_key"])
        return False

    async def no_existing(attempt_key: str):
        return None

    monkeypatch.setattr(
        "lead_api.leads.get_settings",
        lambda: Settings(trusted_proxy_addresses=["198.51.100.10"]),
    )
    monkeypatch.setattr(
        "lead_api.leads.database.consume_public_lead_rate_limit", capture_rate_limit
    )
    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", no_existing)

    data = form_data()
    with TestClient(app, client=("198.51.100.10", 50000)) as client:
        client.post(
            "/api/v1/leads",
            data={**data, "submissionAttemptKey": "trusted-proxy-1"},
            files=resume_file(),
            headers={"x-forwarded-for": "203.0.113.77, 198.51.100.10"},
        )
        client.post(
            "/api/v1/leads",
            data={**data, "submissionAttemptKey": "trusted-proxy-2"},
            files=resume_file(),
            headers={"x-forwarded-for": "203.0.113.78, 198.51.100.10"},
        )

    assert len(keys) == 2
    assert keys[0] != keys[1]


def test_untrusted_proxy_forwarded_address_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = []

    async def capture_rate_limit(**kwargs):
        keys.append(kwargs["address_key"])
        return False

    async def no_existing(attempt_key: str):
        return None

    monkeypatch.setattr(
        "lead_api.leads.database.consume_public_lead_rate_limit", capture_rate_limit
    )
    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", no_existing)

    data = form_data()
    with TestClient(app, client=("198.51.100.20", 50000)) as client:
        client.post(
            "/api/v1/leads",
            data={**data, "submissionAttemptKey": "untrusted-proxy-1"},
            files=resume_file(),
            headers={"x-forwarded-for": "203.0.113.77"},
        )
        client.post(
            "/api/v1/leads",
            data={**data, "submissionAttemptKey": "untrusted-proxy-2"},
            files=resume_file(),
            headers={"x-forwarded-for": "203.0.113.78"},
        )

    assert len(keys) == 2
    assert keys[0] == keys[1]


def test_honeypot_submission_is_rejected_before_turnstile(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage
) -> None:
    async def pass_turnstile(*args, **kwargs):
        raise AssertionError("Turnstile should not run for honeypot submissions")

    async def no_existing(attempt_key: str):
        return None

    monkeypatch.setattr("lead_api.leads.verify_turnstile", pass_turnstile)
    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", no_existing)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/leads",
            data={**form_data(), "website": "https://spam.example"},
            files=resume_file(),
        )

    assert response.status_code == 400
    assert response.json()["code"] == "honeypot_triggered"
    assert fake_storage.uploads == []


@pytest.mark.parametrize(
    ("data", "files", "expected_status", "expected_code"),
    [
        ({**form_data(), "firstName": ""}, resume_file(), 400, "missing_required_field"),
        ({**form_data(), "email": "not-email"}, resume_file(), 400, "invalid_email"),
        (form_data(), None, 400, "missing_required_file"),
        (
            form_data(),
            resume_file("resume.txt", b"text", "text/plain"),
            400,
            "unsupported_resume_type",
        ),
        (
            form_data(),
            resume_file("resume.pdf", pdf_bytes(), "application/msword"),
            400,
            "mismatched_resume_type",
        ),
        (
            form_data(),
            resume_file("resume.pdf", b"not really a pdf", "application/pdf"),
            400,
            "mismatched_resume_signature",
        ),
        (
            form_data(),
            resume_file("resume.pdf", b"%PDF-" + (b"x" * MAX_RESUME_BYTES), "application/pdf"),
            413,
            "resume_too_large",
        ),
    ],
)
def test_lead_submission_validation_errors(
    data, files, expected_status: int, expected_code: str
) -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/leads", data=data, files=files)

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == expected_code


@pytest.mark.parametrize(
    ("filename", "content", "content_type"),
    [
        ("resume.pdf", pdf_bytes(), "application/pdf"),
        ("resume.doc", doc_bytes(), "application/msword"),
        (
            "resume.docx",
            docx_bytes(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ],
)
def test_allowed_resume_types_are_accepted(
    monkeypatch: pytest.MonkeyPatch,
    fake_storage: FakeStorage,
    filename: str,
    content: bytes,
    content_type: str,
) -> None:
    async def no_existing(attempt_key: str):
        return None

    async def create_lead_submission(**kwargs):
        return make_lead(str(uuid4()))

    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", no_existing)
    monkeypatch.setattr("lead_api.leads.database.create_lead_submission", create_lead_submission)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/leads",
            data=form_data(str(uuid4())),
            files=resume_file(filename, content, content_type),
        )

    assert response.status_code == 201
    assert fake_storage.uploads[-1]["content_type"] == content_type


def test_idempotent_retry_returns_existing_lead_without_upload(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage
) -> None:
    async def existing(attempt_key: str):
        lead = make_lead("44444444-4444-4444-8444-444444444444")
        lead["request_fingerprint"] = (
            "3fc79d64df8e94ac4245e2b3bac9dabf4aea8a87e36e292b59e2cbfa1fd16e34"
        )
        return lead

    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", existing)

    async def fail_if_turnstile_runs(*args, **kwargs):
        raise AssertionError("idempotent response-loss retries should return the existing Lead")

    monkeypatch.setattr("lead_api.leads.verify_turnstile", fail_if_turnstile_runs)

    with TestClient(app) as client:
        response = client.post("/api/v1/leads", data=form_data(), files=resume_file())

    assert response.status_code == 200
    assert response.json()["leadId"] == "44444444-4444-4444-8444-444444444444"
    assert fake_storage.uploads == []


def test_submission_attempt_conflict_does_not_upload_or_change_original(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage
) -> None:
    async def existing(attempt_key: str):
        return make_lead()

    async def create_lead_submission(**kwargs):
        raise AssertionError("conflict should stop before persistence")

    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", existing)
    monkeypatch.setattr("lead_api.leads.database.create_lead_submission", create_lead_submission)

    with TestClient(app) as client:
        response = client.post("/api/v1/leads", data=form_data(), files=resume_file())

    assert response.status_code == 409
    assert response.json()["code"] == "submission_attempt_conflict"
    assert fake_storage.uploads == []


def test_same_email_with_new_submission_attempt_creates_distinct_leads(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage
) -> None:
    created_attempts = []

    async def no_existing(attempt_key: str):
        return None

    async def create_lead_submission(**kwargs):
        created_attempts.append(kwargs)
        return make_lead(str(uuid4()))

    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", no_existing)
    monkeypatch.setattr("lead_api.leads.database.create_lead_submission", create_lead_submission)

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/leads", data=form_data("attempt-one-123"), files=resume_file()
        )
        second = client.post(
            "/api/v1/leads", data=form_data("attempt-two-456"), files=resume_file()
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert [attempt["normalized_email"] for attempt in created_attempts] == [
        "ada@example.com",
        "ada@example.com",
    ]
    assert created_attempts[0]["attempt_key"] != created_attempts[1]["attempt_key"]
    assert len(fake_storage.uploads) == 2


def test_uploaded_resume_is_deleted_when_database_persistence_fails(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage
) -> None:
    async def no_existing(attempt_key: str):
        return None

    async def fail_persistence(**kwargs):
        raise LeadPersistenceError

    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", no_existing)
    monkeypatch.setattr("lead_api.leads.database.create_lead_submission", fail_persistence)

    with TestClient(app) as client:
        response = client.post("/api/v1/leads", data=form_data(), files=resume_file())

    assert response.status_code == 503
    assert response.json()["code"] == "lead_persistence_failed"
    assert fake_storage.deletes == [
        {
            "bucket": "resumes",
            "object_key": fake_storage.uploads[0]["object_key"],
        }
    ]


def test_uploaded_resume_is_deleted_when_retry_wins_database_race(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage
) -> None:
    existing = make_lead("44444444-4444-4444-8444-444444444444")
    existing["request_fingerprint"] = (
        "3fc79d64df8e94ac4245e2b3bac9dabf4aea8a87e36e292b59e2cbfa1fd16e34"
    )

    async def no_existing(attempt_key: str):
        return None

    async def race_existing(**kwargs):
        raise SubmissionAttemptAlreadyExists(existing)

    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", no_existing)
    monkeypatch.setattr("lead_api.leads.database.create_lead_submission", race_existing)

    with TestClient(app) as client:
        response = client.post("/api/v1/leads", data=form_data(), files=resume_file())

    assert response.status_code == 200
    assert response.json()["leadId"] == "44444444-4444-4444-8444-444444444444"
    assert fake_storage.deletes == [
        {
            "bucket": "resumes",
            "object_key": fake_storage.uploads[0]["object_key"],
        }
    ]


def test_failed_compensating_delete_is_observable(
    monkeypatch: pytest.MonkeyPatch, fake_storage: FakeStorage, caplog: pytest.LogCaptureFixture
) -> None:
    fake_storage.fail_delete = True

    async def no_existing(attempt_key: str):
        return None

    async def fail_persistence(**kwargs):
        raise LeadPersistenceError

    monkeypatch.setattr("lead_api.leads.database.fetch_submission_attempt", no_existing)
    monkeypatch.setattr("lead_api.leads.database.create_lead_submission", fail_persistence)

    with TestClient(app) as client:
        response = client.post("/api/v1/leads", data=form_data(), files=resume_file())

    assert response.status_code == 503
    assert "resume_compensation_delete_failed" in caplog.text

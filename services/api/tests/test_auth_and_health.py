import pytest
from fastapi.testclient import TestClient
from lead_api.auth import parse_bearer_token
from lead_api.config import get_settings
from lead_api.database import database
from lead_api.main import app
from lead_api.problems import ProblemError


def test_liveness_reports_process_running() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_protected_identity_requires_bearer_header() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/attorneys/me")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "missing_credentials"


def test_malformed_authorization_is_rejected() -> None:
    with pytest.raises(ProblemError) as exc:
        parse_bearer_token("Basic abc")

    assert exc.value.status == 401
    assert exc.value.code == "malformed_credentials"


def test_cors_allows_configured_frontend_origin_only() -> None:
    with TestClient(app) as client:
        allowed = client.options(
            "/api/v1/attorneys/me",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        blocked = client.options(
            "/api/v1/attorneys/me",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in blocked.headers


def test_cors_allows_resume_correlation_header_and_exposes_download_headers() -> None:
    with TestClient(app) as client:
        preflight = client.options(
            "/api/v1/admin/leads/00000000-0000-0000-0000-000000000000/resume?disposition=inline",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,x-request-id",
            },
        )
        actual = client.get(
            "/api/v1/admin/leads/00000000-0000-0000-0000-000000000000/resume?disposition=inline",
            headers={"Origin": "http://localhost:3000"},
        )

    assert preflight.status_code == 200
    assert "X-Request-ID" in preflight.headers["access-control-allow-headers"]
    assert "Content-Disposition" in actual.headers["access-control-expose-headers"]
    assert "X-Request-ID" in actual.headers["access-control-expose-headers"]


@pytest.mark.asyncio
async def test_readiness_reports_missing_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("SUPABASE_ANON_KEY", "")

    async def ready() -> bool:
        return True

    monkeypatch.setattr(database, "ready", ready)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["code"] == "configuration_incomplete"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_readiness_reports_database_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
    monkeypatch.setenv("FALLBACK_INTAKE_ADDRESS", "intake.local@example.test")

    async def ready() -> bool:
        return False

    monkeypatch.setattr(database, "ready", ready)

    async def connect(settings) -> None:
        return None

    async def close() -> None:
        return None

    monkeypatch.setattr(database, "connect", connect)
    monkeypatch.setattr(database, "close", close)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["code"] == "postgres_unavailable"
    get_settings.cache_clear()

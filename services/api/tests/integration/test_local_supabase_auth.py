import os

import httpx
import pytest
from fastapi.testclient import TestClient
from lead_api.main import app

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LOCAL_SUPABASE_TESTS") != "1",
    reason="set RUN_LOCAL_SUPABASE_TESTS=1 after starting and resetting local Supabase",
)


def test_health_endpoints_report_local_supabase_readiness() -> None:
    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "live"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


def test_seeded_attorney_can_sign_in_and_fastapi_resolves_identity() -> None:
    supabase_url = os.environ["SUPABASE_URL"].rstrip("/")
    anon_key = os.environ["SUPABASE_ANON_KEY"]

    auth_response = httpx.post(
        f"{supabase_url}/auth/v1/token?grant_type=password",
        headers={"apikey": anon_key, "Content-Type": "application/json"},
        json={
            "email": "attorney.local@example.test",
            "password": "LocalAttorney123!",
        },
        timeout=10,
    )
    assert auth_response.status_code == 200
    access_token = auth_response.json()["access_token"]

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/admin/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "id": "11111111-1111-4111-8111-111111111111",
        "email": "attorney.local@example.test",
        "displayName": "Local Attorney",
    }


def test_public_attorney_signup_is_disabled() -> None:
    supabase_url = os.environ["SUPABASE_URL"].rstrip("/")
    anon_key = os.environ["SUPABASE_ANON_KEY"]

    response = httpx.post(
        f"{supabase_url}/auth/v1/signup",
        headers={"apikey": anon_key, "Content-Type": "application/json"},
        json={
            "email": "public-signup@example.com",
            "password": "LocalAttorney123!",
        },
        timeout=10,
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "signup_disabled"


@pytest.mark.parametrize(
    ("token", "expected_code"),
    [
        ("not-a-jwt", "invalid_credentials"),
        (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJpc3MiOiJ3cm9uZyIsImF1ZCI6Indyb25nIiwiZXhwIjoxfQ."
            "bad-signature",
            "invalid_credentials",
        ),
    ],
)
def test_invalid_local_supabase_credentials_are_rejected(token: str, expected_code: str) -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/admin/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == expected_code


def test_browser_facing_supabase_api_cannot_read_private_attorneys_table() -> None:
    supabase_url = os.environ["SUPABASE_URL"].rstrip("/")
    anon_key = os.environ["SUPABASE_ANON_KEY"]

    response = httpx.get(
        f"{supabase_url}/rest/v1/attorneys",
        headers={"apikey": anon_key},
        timeout=10,
    )

    assert response.status_code == 404

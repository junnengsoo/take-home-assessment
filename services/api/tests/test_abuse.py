import pytest
from lead_api.abuse import (
    TurnstileExplicitFailure,
    TurnstileOutcome,
    TurnstileUnavailable,
    verify_turnstile,
)
from lead_api.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        turnstile_secret_key="test-secret",
        turnstile_expected_action="lead_submit",
        turnstile_allowed_hostnames=["localhost"],
    )


async def test_turnstile_success_requires_expected_action_and_hostname(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    async def valid_response(token: str, remote_ip: str, configured_settings: Settings):
        return {
            "success": True,
            "action": "lead_submit",
            "hostname": "localhost",
            "error-codes": [],
        }

    monkeypatch.setattr("lead_api.abuse._post_siteverify", valid_response)

    outcome = await verify_turnstile("token", "203.0.113.10", settings)

    assert outcome == TurnstileOutcome.SUCCESS


async def test_turnstile_rejects_action_mismatch(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    async def wrong_action(token: str, remote_ip: str, configured_settings: Settings):
        return {
            "success": True,
            "action": "other_action",
            "hostname": "localhost",
            "error-codes": [],
        }

    monkeypatch.setattr("lead_api.abuse._post_siteverify", wrong_action)

    with pytest.raises(TurnstileExplicitFailure) as exc:
        await verify_turnstile("token", "203.0.113.10", settings)

    assert exc.value.error_codes == ["action-mismatch"]


async def test_turnstile_rejects_hostname_mismatch(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    async def wrong_hostname(token: str, remote_ip: str, configured_settings: Settings):
        return {
            "success": True,
            "action": "lead_submit",
            "hostname": "evil.example",
            "error-codes": [],
        }

    monkeypatch.setattr("lead_api.abuse._post_siteverify", wrong_hostname)

    with pytest.raises(TurnstileExplicitFailure) as exc:
        await verify_turnstile("token", "203.0.113.10", settings)

    assert exc.value.error_codes == ["hostname-mismatch"]


async def test_turnstile_service_error_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    async def unavailable(token: str, remote_ip: str, configured_settings: Settings):
        raise TurnstileUnavailable("siteverify_503")

    monkeypatch.setattr("lead_api.abuse._post_siteverify", unavailable)

    with pytest.raises(TurnstileUnavailable):
        await verify_turnstile("token", "203.0.113.10", settings)

import hashlib
import hmac
import ipaddress
import logging
import uuid
from collections.abc import Mapping
from enum import Enum
from typing import Any, Optional

import httpx
from starlette.datastructures import Headers

from lead_api.config import Settings

logger = logging.getLogger(__name__)

MAX_TURNSTILE_TOKEN_LENGTH = 2048


class TurnstileOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    UNAVAILABLE = "UNAVAILABLE"


class TurnstileExplicitFailure(Exception):
    def __init__(self, error_codes: list[str]) -> None:
        self.error_codes = error_codes


class TurnstileUnavailable(Exception):
    pass


def address_hmac(address: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), address.encode("utf-8"), hashlib.sha256).hexdigest()


def client_address(headers: Headers, peer_host: Optional[str], trusted_proxies: list[str]) -> str:
    peer = peer_host or "unknown"
    if not _is_trusted_proxy(peer, trusted_proxies):
        return peer

    forwarded_for = headers.get("x-forwarded-for", "")
    first_forwarded = forwarded_for.split(",", 1)[0].strip()
    if first_forwarded:
        return first_forwarded

    real_ip = headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip

    return peer


async def verify_turnstile(
    token: Optional[str], remote_ip: str, settings: Settings
) -> TurnstileOutcome:
    if not token or len(token) > MAX_TURNSTILE_TOKEN_LENGTH:
        raise TurnstileExplicitFailure(["missing-input-response"])

    try:
        result = await _post_siteverify(token, remote_ip, settings)
    except TurnstileUnavailable:
        raise

    success = bool(result.get("success"))
    if not success:
        raise TurnstileExplicitFailure(_error_codes(result))

    action = result.get("action")
    if settings.turnstile_expected_action and action != settings.turnstile_expected_action:
        raise TurnstileExplicitFailure(["action-mismatch"])

    hostname = result.get("hostname")
    if (
        settings.turnstile_allowed_hostnames
        and hostname not in settings.turnstile_allowed_hostnames
    ):
        raise TurnstileExplicitFailure(["hostname-mismatch"])

    return TurnstileOutcome.SUCCESS


async def _post_siteverify(
    token: str,
    remote_ip: str,
    settings: Settings,
) -> Mapping[str, Any]:
    payload = {
        "secret": settings.turnstile_secret_key,
        "response": token,
        "remoteip": remote_ip,
        "idempotency_key": str(uuid.uuid4()),
    }
    timeout = httpx.Timeout(settings.turnstile_timeout_seconds)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(settings.turnstile_siteverify_url, data=payload)
    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
        raise TurnstileUnavailable(type(exc).__name__) from exc

    if response.status_code >= 500:
        raise TurnstileUnavailable(f"siteverify_{response.status_code}")

    try:
        return response.json()
    except ValueError as exc:
        raise TurnstileUnavailable("invalid_json") from exc


def _error_codes(result: Mapping[str, Any]) -> list[str]:
    errors = result.get("error-codes", [])
    if not isinstance(errors, list):
        return ["unknown-error"]
    return [str(error) for error in errors]


def _is_trusted_proxy(peer_host: str, trusted_proxies: list[str]) -> bool:
    for trusted_proxy in trusted_proxies:
        if peer_host == trusted_proxy:
            return True
        try:
            if ipaddress.ip_address(peer_host) in ipaddress.ip_network(trusted_proxy, strict=False):
                return True
        except ValueError:
            continue
    return False

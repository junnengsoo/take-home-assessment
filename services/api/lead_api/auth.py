from dataclasses import dataclass
from typing import Any, Optional

import httpx
from fastapi import Header, Request

from lead_api.config import Settings, get_settings
from lead_api.database import database
from lead_api.problems import ProblemError


@dataclass(frozen=True)
class AttorneyIdentity:
    id: str
    email: str
    display_name: str


class SupabaseAuthClient:
    def __init__(self, settings: Settings, client: Optional[httpx.AsyncClient] = None) -> None:
        self.settings = settings
        self.client = client

    async def get_user(self, token: str) -> dict[str, Any]:
        own_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=5)
        try:
            response = await client.get(
                f"{str(self.settings.supabase_url).rstrip('/')}/auth/v1/user",
                headers={
                    "apikey": self.settings.supabase_anon_key,
                    "Authorization": f"Bearer {token}",
                },
            )
        finally:
            if own_client:
                await client.aclose()

        if response.status_code != 200:
            raise ProblemError(
                401,
                "Invalid credentials",
                "The bearer token is missing, expired, malformed, or not accepted locally.",
                "invalid_credentials",
            )
        data = response.json()
        if not data.get("id") or not data.get("email"):
            raise ProblemError(
                401,
                "Invalid credentials",
                "The bearer token did not resolve to a Supabase user.",
                "invalid_credentials",
            )
        return data


def parse_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise ProblemError(
            401,
            "Missing credentials",
            "Protected endpoints require a Supabase bearer token.",
            "missing_credentials",
        )

    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise ProblemError(
            401,
            "Malformed credentials",
            "Use the Authorization header format: Bearer <token>.",
            "malformed_credentials",
        )
    return token.strip()


async def current_attorney(
    request: Request,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> AttorneyIdentity:
    settings = get_settings()
    token = parse_bearer_token(authorization)
    user = await SupabaseAuthClient(settings).get_user(token)
    attorney = await database.fetch_attorney(user["id"])
    if attorney is None:
        raise ProblemError(
            403,
            "Attorney profile missing",
            "The authenticated account does not have an Attorney profile.",
            "attorney_profile_missing",
        )
    identity = AttorneyIdentity(
        id=attorney["id"],
        email=attorney["email"],
        display_name=attorney["display_name"],
    )
    request.state.actor_attorney_id = identity.id
    return identity

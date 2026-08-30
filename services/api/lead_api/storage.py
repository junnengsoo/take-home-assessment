from dataclasses import dataclass

import httpx

from lead_api.config import Settings
from lead_api.problems import ProblemError


@dataclass(frozen=True)
class StoredResume:
    bucket: str
    object_key: str


class ResumeStorage:
    async def upload(
        self,
        settings: Settings,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> StoredResume:
        if not settings.supabase_service_role_key:
            raise ProblemError(
                503,
                "Storage configuration incomplete",
                "The API is missing server-side Storage credentials.",
                "storage_configuration_incomplete",
            )

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                (
                    f"{str(settings.supabase_url).rstrip('/')}/storage/v1/object/"
                    f"{settings.resume_bucket}/{object_key}"
                ),
                headers={
                    "apikey": settings.supabase_service_role_key,
                    "Authorization": f"Bearer {settings.supabase_service_role_key}",
                    "Content-Type": content_type,
                    "x-upsert": "false",
                },
                content=content,
            )

        if response.status_code not in {200, 201}:
            raise ProblemError(
                502,
                "Résumé upload failed",
                "The résumé could not be saved. Please try again.",
                "resume_upload_failed",
            )

        return StoredResume(bucket=settings.resume_bucket, object_key=object_key)

    async def delete(self, settings: Settings, object_key: str) -> None:
        if not settings.supabase_service_role_key:
            raise RuntimeError("missing Supabase service role key for Storage delete")

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.request(
                "DELETE",
                f"{str(settings.supabase_url).rstrip('/')}/storage/v1/object/{settings.resume_bucket}",
                headers={
                    "apikey": settings.supabase_service_role_key,
                    "Authorization": f"Bearer {settings.supabase_service_role_key}",
                    "Content-Type": "application/json",
                },
                json={"prefixes": [object_key]},
            )

        if response.status_code not in {200, 204}:
            raise RuntimeError(f"storage delete failed with status {response.status_code}")


resume_storage = ResumeStorage()

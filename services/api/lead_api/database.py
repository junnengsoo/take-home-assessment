from typing import Optional

import asyncpg

from lead_api.config import Settings


class Database:
    def __init__(self) -> None:
        self._pool: Optional[asyncpg.Pool] = None
        self._settings: Optional[Settings] = None

    async def connect(self, settings: Settings) -> None:
        self._settings = settings
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    settings.database_url,
                    min_size=1,
                    max_size=5,
                )
            except (OSError, asyncpg.PostgresError):
                self._pool = None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def fetch_attorney(self, attorney_id: str) -> Optional[asyncpg.Record]:
        if self._pool is None and self._settings is not None:
            await self.connect(self._settings)
        if self._pool is None:
            raise RuntimeError("database pool is not initialized")
        async with self._pool.acquire() as connection:
            return await connection.fetchrow(
                """
                select id::text as id, email::text as email, display_name
                from app.attorneys
                where id = $1::uuid
                """,
                attorney_id,
            )

    async def ready(self) -> bool:
        if self._pool is None and self._settings is not None:
            await self.connect(self._settings)
        if self._pool is None:
            return False
        async with self._pool.acquire() as connection:
            value = await connection.fetchval("select 1")
            return value == 1


database = Database()

from typing import Optional

import asyncpg

from lead_api.config import Settings


class SubmissionAttemptAlreadyExists(Exception):
    def __init__(self, existing: asyncpg.Record) -> None:
        self.existing = existing


class LeadPersistenceError(Exception):
    pass


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

    async def fetch_submission_attempt(self, attempt_key: str) -> Optional[asyncpg.Record]:
        if self._pool is None and self._settings is not None:
            await self.connect(self._settings)
        if self._pool is None:
            raise RuntimeError("database pool is not initialized")
        async with self._pool.acquire() as connection:
            return await self._fetch_submission_attempt(connection, attempt_key)

    async def create_lead_submission(
        self,
        *,
        attempt_key: str,
        request_fingerprint: str,
        first_name: str,
        last_name: str,
        normalized_email: str,
        storage_bucket: str,
        storage_object_key: str,
        original_filename: str,
        content_type: str,
        byte_size: int,
        sha256_digest: str,
        turnstile_verification_outcome: str,
        fallback_intake_address: str,
    ) -> asyncpg.Record:
        if self._pool is None and self._settings is not None:
            await self.connect(self._settings)
        if self._pool is None:
            raise RuntimeError("database pool is not initialized")

        async with self._pool.acquire() as connection:
            try:
                async with connection.transaction():
                    await connection.execute(
                        "select pg_advisory_xact_lock(hashtext('app.lead_assignment'))"
                    )
                    assignment = await connection.fetchrow(
                        """
                        select id, email::text as email, display_name
                        from app.attorneys
                        order by last_assigned_at asc nulls first, created_at asc, id asc
                        limit 1
                        for update
                        """
                    )
                    assigned_attorney_id = assignment["id"] if assignment is not None else None
                    internal_recipient = (
                        assignment["email"] if assignment is not None else fallback_intake_address
                    )
                    assignment_label = (
                        assignment["display_name"] if assignment is not None else "Unassigned"
                    )

                    lead = await connection.fetchrow(
                        """
                        insert into app.leads (
                          first_name,
                          last_name,
                          normalized_email,
                          turnstile_verification_outcome,
                          assigned_attorney_id
                        )
                        values ($1, $2, $3, $4, $5)
                        returning id, created_at
                        """,
                        first_name,
                        last_name,
                        normalized_email,
                        turnstile_verification_outcome,
                        assigned_attorney_id,
                    )
                    lead_id = lead["id"]
                    if assigned_attorney_id is not None:
                        await connection.execute(
                            """
                            update app.attorneys
                            set last_assigned_at = clock_timestamp()
                            where id = $1
                            """,
                            assigned_attorney_id,
                        )
                    await connection.execute(
                        """
                        insert into app.resume_metadata (
                          lead_id,
                          storage_bucket,
                          storage_object_key,
                          original_filename,
                          content_type,
                          byte_size,
                          sha256_digest
                        )
                        values ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        lead_id,
                        storage_bucket,
                        storage_object_key,
                        original_filename,
                        content_type,
                        byte_size,
                        sha256_digest,
                    )
                    await connection.execute(
                        """
                        insert into app.lead_status_changes (lead_id, status, actor_type)
                        values ($1, 'PENDING', 'SYSTEM')
                        """,
                        lead_id,
                    )
                    await connection.execute(
                        """
                        insert into app.lead_audit_events (
                          lead_id,
                          event_type,
                          actor_type,
                          payload
                        )
                        values (
                          $1,
                          'lead.created',
                          'SYSTEM',
                          jsonb_build_object(
                            'submissionAttemptKey', $2::text,
                            'resumeSha256Digest', $3::text
                          )
                        )
                        """,
                        lead_id,
                        attempt_key,
                        sha256_digest,
                    )
                    await connection.execute(
                        """
                        insert into app.submission_attempts (
                          attempt_key,
                          request_fingerprint,
                          lead_id
                        )
                        values ($1, $2, $3)
                        """,
                        attempt_key,
                        request_fingerprint,
                        lead_id,
                    )
                    await connection.execute(
                        """
                        insert into app.email_outbox (
                          lead_id,
                          kind,
                          recipient_email,
                          payload
                        )
                        values (
                          $1,
                          'PROSPECT_CONFIRMATION',
                          $2,
                          jsonb_build_object(
                            'prospectFirstName', $3::text,
                            'submittedAt', $4::timestamptz
                          )
                        )
                        """,
                        lead_id,
                        normalized_email,
                        first_name,
                        lead["created_at"],
                    )
                    await connection.execute(
                        """
                        insert into app.email_outbox (
                          lead_id,
                          kind,
                          recipient_email,
                          payload
                        )
                        values (
                          $1,
                          'INTERNAL_NEW_LEAD',
                          $2,
                          jsonb_build_object(
                            'prospectName', $3::text,
                            'prospectEmail', $4::text,
                            'assignment', $5::text,
                            'submittedAt', $6::timestamptz
                          )
                        )
                        """,
                        lead_id,
                        internal_recipient,
                        f"{first_name} {last_name}",
                        normalized_email,
                        assignment_label,
                        lead["created_at"],
                    )
            except asyncpg.UniqueViolationError as exc:
                existing = await self._fetch_submission_attempt(connection, attempt_key)
                if existing is not None:
                    raise SubmissionAttemptAlreadyExists(existing) from exc
                raise LeadPersistenceError from exc
            except asyncpg.PostgresError as exc:
                raise LeadPersistenceError from exc

            created = await self._fetch_submission_attempt(connection, attempt_key)
            if created is None:
                raise LeadPersistenceError
            return created

    async def consume_public_lead_rate_limit(
        self,
        *,
        address_key: str,
        max_requests: int,
        window_seconds: int,
    ) -> bool:
        if self._pool is None and self._settings is not None:
            await self.connect(self._settings)
        if self._pool is None:
            raise RuntimeError("database pool is not initialized")

        async with self._pool.acquire() as connection:
            request_count = await connection.fetchval(
                """
                insert into app.public_lead_rate_limits (
                  address_key,
                  window_start,
                  request_count
                )
                values ($1, now(), 1)
                on conflict (address_key) do update
                set
                  window_start = case
                    when app.public_lead_rate_limits.window_start
                      <= now() - ($3 * interval '1 second')
                    then now()
                    else app.public_lead_rate_limits.window_start
                  end,
                  request_count = case
                    when app.public_lead_rate_limits.window_start
                      <= now() - ($3 * interval '1 second')
                    then 1
                    else app.public_lead_rate_limits.request_count + 1
                  end
                returning request_count <= $2
                """,
                address_key,
                max_requests,
                window_seconds,
            )
            return bool(request_count)

    async def _fetch_submission_attempt(
        self, connection: asyncpg.Connection, attempt_key: str
    ) -> Optional[asyncpg.Record]:
        return await connection.fetchrow(
            """
            select
              sa.attempt_key,
              sa.request_fingerprint,
              sa.lead_id::text as lead_id,
              l.version,
              l.assigned_attorney_id::text as assigned_attorney_id
            from app.submission_attempts sa
            join app.leads l on l.id = sa.lead_id
            where sa.attempt_key = $1
            """,
            attempt_key,
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

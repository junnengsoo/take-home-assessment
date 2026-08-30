import asyncio
import logging
import signal
import uuid

import asyncpg
from lead_api.config import get_settings

from lead_worker.outbox import OutboxWorker, PostgresOutboxStore, run_forever
from lead_worker.providers import provider_from_settings


async def run() -> None:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s worker %(message)s")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=1,
        max_size=max(1, settings.email_worker_database_pool_size),
    )
    provider = provider_from_settings(settings)
    worker = OutboxWorker(
        store=PostgresOutboxStore(pool),
        provider=provider,
        batch_size=settings.email_worker_batch_size,
        lease_seconds=settings.email_worker_lease_seconds,
        base_retry_seconds=settings.email_worker_base_retry_seconds,
        max_retry_seconds=settings.email_worker_max_retry_seconds,
    )
    worker_id = str(uuid.uuid4())
    logging.info("started", extra={"worker_id": worker_id, "provider": provider.name})
    try:
        await run_forever(
            worker=worker,
            stop=stop,
            poll_seconds=settings.email_worker_poll_seconds,
            worker_id=worker_id,
        )
    finally:
        await pool.close()
        logging.info("stopped")


if __name__ == "__main__":
    asyncio.run(run())

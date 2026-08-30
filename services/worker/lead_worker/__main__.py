import asyncio
import logging
import signal

import asyncpg
from lead_api.config import get_settings


async def run() -> None:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s worker %(message)s")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=1)
    logging.info("started")
    try:
        while not stop.is_set():
            async with pool.acquire() as connection:
                await connection.fetchval("select 1")
            try:
                await asyncio.wait_for(stop.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass
    finally:
        await pool.close()
        logging.info("stopped")


if __name__ == "__main__":
    asyncio.run(run())

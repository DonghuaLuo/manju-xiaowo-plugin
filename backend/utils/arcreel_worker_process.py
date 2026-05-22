#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Isolated ArcReel generation worker for the Xiaowo plugin.

This process never imports the Xiaowo plugin SDK and must not write plugin
JSON-RPC packets to stdout. The parent process redirects stdout/stderr to a
plain log file before launching it.
"""

from __future__ import annotations

import asyncio
import os
import time


def _prepare_desktop_environment() -> None:
    os.environ["AUTH_ENABLED"] = "false"
    if os.environ.get("XIAOWO_ARCREEL_ALLOW_EXTERNAL_DATABASE") != "1":
        os.environ.pop("DATABASE_URL", None)


async def _wait_until_idle(timeout_seconds: float) -> None:
    from lib.generation_queue import get_generation_queue

    queue = get_generation_queue()
    idle_since: float | None = None
    while True:
        stats = await queue.get_task_stats()
        has_work = int(stats.get("queued", 0)) > 0 or int(stats.get("running", 0)) > 0
        if has_work:
            idle_since = None
        else:
            idle_since = idle_since or time.monotonic()
            if time.monotonic() - idle_since >= timeout_seconds:
                return
        await asyncio.sleep(5)


async def main() -> None:
    _prepare_desktop_environment()

    from lib.db import close_db, init_db
    from lib.generation_worker import GenerationWorker
    from lib.httpx_shared import shutdown_http_client, startup_http_client

    idle_timeout = max(30.0, float(os.environ.get("XIAOWO_ARCREEL_WORKER_IDLE_TIMEOUT_SEC", "120")))
    await init_db()
    await startup_http_client()
    worker = GenerationWorker()
    await worker.start()
    try:
        await _wait_until_idle(idle_timeout)
    finally:
        await worker.stop()
        await shutdown_http_client()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())

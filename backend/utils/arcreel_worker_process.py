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
from typing import Any


def _prepare_desktop_environment() -> None:
    os.environ["AUTH_ENABLED"] = "false"
    if os.environ.get("XIAOWO_ARCREEL_ALLOW_EXTERNAL_DATABASE") != "1":
        os.environ.pop("DATABASE_URL", None)


def _install_project_event_journal_listener() -> None:
    from lib.project_change_hints import register_project_change_batch_listener
    from utils.arcreel_desktop_sync import append_project_event_batch

    register_project_change_batch_listener(append_project_event_batch)


async def _maybe_reload_worker(worker, marker_state: str) -> str:
    from utils.arcreel_desktop_sync import read_worker_reload_marker

    current_state = read_worker_reload_marker()
    if not current_state or current_state == marker_state:
        return marker_state

    from server.services.generation_tasks import invalidate_backend_cache

    invalidate_backend_cache()
    await worker.reload_limits()
    return current_state


async def _wait_until_idle(timeout_seconds: float, worker: Any) -> None:
    from lib.generation_queue import get_generation_queue

    queue = get_generation_queue()
    idle_since: float | None = None
    reload_marker_state = ""
    while True:
        reload_marker_state = await _maybe_reload_worker(worker, reload_marker_state)
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
    _install_project_event_journal_listener()
    worker = GenerationWorker()
    await worker.reload_limits()
    await worker.start()
    try:
        await _wait_until_idle(idle_timeout, worker)
    finally:
        await worker.stop()
        await shutdown_http_client()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())

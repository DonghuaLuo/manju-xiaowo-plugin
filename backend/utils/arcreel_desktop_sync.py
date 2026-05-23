#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Small file-backed sync channel for ArcReel desktop helper processes."""

from __future__ import annotations

import json
import os
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def _state_dir() -> Path:
    from lib.app_data_dir import app_data_dir

    path = app_data_dir() / ".xiaowo"
    path.mkdir(parents=True, exist_ok=True)
    return path


def worker_reload_marker_path() -> Path:
    return _state_dir() / "worker-reload.json"


def project_event_journal_path() -> Path:
    return _state_dir() / "project-events.jsonl"


def project_event_journal_size() -> int:
    try:
        return project_event_journal_path().stat().st_size
    except FileNotFoundError:
        return 0


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def request_worker_reload(reason: str = "config_changed") -> None:
    marker_path = worker_reload_marker_path()
    payload = {
        "id": uuid4().hex,
        "reason": reason,
        "pid": os.getpid(),
        "created_at": utc_now_iso(),
        "monotonic": time.monotonic(),
    }
    tmp_path = marker_path.with_name(f"{marker_path.name}.{payload['id']}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, marker_path)


def read_worker_reload_marker() -> str:
    path = worker_reload_marker_path()
    try:
        stat = path.stat()
    except FileNotFoundError:
        return ""
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def append_project_event_batch(project_name: str, source: str, changes: Any) -> None:
    if source not in {"webui", "worker", "filesystem"}:
        source = "filesystem"
    if not isinstance(project_name, str) or not project_name:
        return
    payload_changes = [dict(change) for change in (changes or ()) if isinstance(change, dict)]
    if not payload_changes:
        return
    payload = {
        "id": uuid4().hex,
        "project_name": project_name,
        "source": source,
        "changes": payload_changes,
        "created_at": utc_now_iso(),
        "pid": os.getpid(),
    }
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    path = project_event_journal_path()
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()


def read_project_event_batches(offset: int) -> tuple[int, list[dict[str, Any]]]:
    path = project_event_journal_path()
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return 0, []

    if offset < 0 or offset > size:
        offset = 0

    events: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        handle.seek(offset)
        raw = handle.read()

    consumed = 0
    for raw_line in raw.splitlines(keepends=True):
        if not raw_line.endswith((b"\n", b"\r")):
            break
        consumed += len(raw_line)
        line = raw_line.strip()
        if not line:
            continue
        with suppress(json.JSONDecodeError, UnicodeDecodeError):
            payload = json.loads(line.decode("utf-8"))
            if isinstance(payload, dict):
                events.append(payload)
    return offset + consumed, events

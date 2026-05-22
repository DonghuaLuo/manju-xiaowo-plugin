#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ArcReel desktop IPC bridge for Xiaowo plugin.

The frontend keeps ArcReel's typed API surface, but requests arrive through
``PluginSDK.callBackend`` instead of HTTP. This module validates the desktop
IPC protocol, prepares ArcReel runtime state, and delegates resource requests
to a local desktop dispatcher instead of an ASGI app or web server.
"""

from __future__ import annotations

import asyncio
import atexit
import base64
import mimetypes
import json
import os
import subprocess
import sys
import time
import traceback
from collections.abc import MutableMapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlencode, urlsplit
from uuid import uuid4


_runtime_ready = False
_worker_process: subprocess.Popen | None = None
_worker_log_handle: Any | None = None
_worker_atexit_registered = False
_project_event_snapshots: dict[str, tuple[dict[str, Any], str]] = {}
_recent_webui_mutations: dict[str, float] = {}
_project_event_service: Any | None = None
_assistant_stream_snapshots: dict[str, tuple[str, str | None]] = {}
_event_id_seq = 0


def _prepare_desktop_environment(env: MutableMapping[str, str] | None = None) -> None:
    target = os.environ if env is None else env
    target["AUTH_ENABLED"] = "false"
    if target.get("XIAOWO_ARCREEL_ALLOW_EXTERNAL_DATABASE") != "1":
        target.pop("DATABASE_URL", None)


def _log_exception() -> None:
    sys.stderr.write(traceback.format_exc())
    sys.stderr.flush()


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _content_payload(content: bytes, content_type: str) -> dict[str, Any]:
    if not content:
        return {"content": {"kind": "empty"}}
    if content_type.startswith("application/json") or content_type.startswith("text/"):
        try:
            text = content.decode("utf-8")
            if content_type.startswith("application/json"):
                try:
                    return {"content": {"kind": "json", "value": json.loads(text)}}
                except json.JSONDecodeError:
                    pass
            return {"content": {"kind": "text", "text": text, "mimeType": content_type or "text/plain;charset=UTF-8"}}
        except UnicodeDecodeError:
            pass
    return {
        "content": {
            "kind": "binary",
            "base64": base64.b64encode(content).decode("ascii"),
            "mimeType": content_type or "application/octet-stream",
        }
    }


async def _ensure_runtime() -> None:
    global _runtime_ready

    # Desktop plugin runs as a trusted local client. The old WebUI login/JWT
    # flow is disabled before importing FastAPI dependencies.
    _prepare_desktop_environment()

    from lib.db import init_db
    from lib.httpx_shared import startup_http_client

    if not _runtime_ready:
        await init_db()
        _runtime_ready = True
    await startup_http_client()

    # FastAPI lifespan is not used in the plugin IPC bridge, so initialize the
    # assistant service explicitly for session snapshots and local requests.
    with suppress(Exception):
        from server.routers import assistant

        await assistant.assistant_service.startup()


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _stop_worker_process() -> None:
    global _worker_process, _worker_log_handle
    process = _worker_process
    _worker_process = None
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    if _worker_log_handle is not None:
        try:
            _worker_log_handle.close()
        except Exception:
            pass
        _worker_log_handle = None


def _ensure_worker_process() -> None:
    """Start ArcReel's queue worker as an isolated child process.

    The worker writes logs to a file instead of inheriting Xiaowo IPC stdout.
    """
    global _worker_process, _worker_log_handle, _worker_atexit_registered

    if os.environ.get("XIAOWO_ARCREEL_DISABLE_WORKER") == "1":
        return
    if _worker_process is not None and _worker_process.poll() is None:
        return

    if _worker_log_handle is not None:
        try:
            _worker_log_handle.close()
        except Exception:
            pass
        _worker_log_handle = None

    from lib.app_data_dir import app_data_dir

    log_dir = app_data_dir() / ".logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _worker_log_handle = (log_dir / "xiaowo-worker.log").open("ab", buffering=0)

    env = os.environ.copy()
    _prepare_desktop_environment(env)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    cmd = [sys.executable, str(_backend_root() / "utils" / "arcreel_worker_process.py")]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    _worker_process = subprocess.Popen(
        cmd,
        cwd=str(_backend_root()),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=_worker_log_handle,
        stderr=_worker_log_handle,
        close_fds=True,
        creationflags=creationflags,
    )
    if not _worker_atexit_registered:
        atexit.register(_stop_worker_process)
        _worker_atexit_registered = True


def _run_in_fresh_loop(coro):
    async def _runner():
        try:
            return await coro
        finally:
            with suppress(Exception):
                from lib.httpx_shared import shutdown_http_client

                await shutdown_http_client()
            with suppress(Exception):
                from lib.db import close_db

                await close_db()

    return asyncio.run(_runner())


def _project_name_from_resource(resource: str) -> str | None:
    parts = str(resource or "").strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "projects":
        return unquote(parts[1])
    return None


def _is_disabled_web_resource(resource: str) -> bool:
    parts = str(resource or "").strip("/").split("/")
    is_project_download = False
    if len(parts) >= 3 and parts[0] == "projects":
        tail = parts[2:]
        is_project_download = tail in (
            ["export", "token"],
            ["export"],
            ["export", "jianying-draft"],
        )
    return (
        parts[:1] == ["auth"]
        or parts[:1] == ["api-keys"]
        or parts == ["system", "logs", "download"]
        or is_project_download
    )


def _remember_webui_mutation(operation: str, resource: str, result: dict[str, Any]) -> None:
    if result.get("success") is False or operation not in {"create", "replace", "update", "delete"}:
        return
    project_name = _project_name_from_resource(resource)
    if project_name:
        _recent_webui_mutations[project_name] = time.monotonic() + 3.0


def _maybe_start_worker_for_result(operation: str, resource: str, result: dict[str, Any]) -> None:
    if result.get("success") is False or operation != "create":
        return
    value = (result.get("content") or {}).get("value") if isinstance(result.get("content"), dict) else None
    has_task_id = isinstance(value, dict) and ("task_id" in value or "task_ids" in value)
    if "/generate/" in f"/{resource.strip('/')}/" or has_task_id:
        _ensure_worker_process()


def _operation_to_method(operation: str) -> str:
    return {
        "read": "GET",
        "create": "POST",
        "replace": "PUT",
        "update": "PATCH",
        "delete": "DELETE",
    }.get(operation, "GET")


def _query_from_params(params: dict[str, Any]) -> dict[str, list[str]]:
    query: dict[str, list[str]] = {}
    for key, value in (params.get("query") or {}).items():
        if isinstance(value, list):
            query[str(key)] = [str(item) for item in value]
        elif value is not None:
            query[str(key)] = [str(value)]
    return query


def _desktop_resource_name(params: dict[str, Any]) -> str:
    raw_resource = str(params.get("resource") or "root").strip()
    if "://" in raw_resource or raw_resource.startswith(("/", "\\")) or ".." in raw_resource.split("/"):
        raise ValueError(f"Invalid desktop resource: {raw_resource}")
    resource = "root" if raw_resource == "root" else raw_resource.strip("/")
    if _is_disabled_web_resource(resource):
        raise ValueError("ArcReel Web auth/download endpoints are disabled in the Xiaowo plugin")
    return resource


def _error_code_from_status(status_code: int) -> str:
    if status_code in {401}:
        return "unauthorized"
    if status_code in {403}:
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 413:
        return "too_large"
    if status_code in {400, 422}:
        return "validation_error"
    return "backend_error"


def _detail_from_content(content: bytes, content_type: str, fallback: str) -> str:
    if content_type.startswith("application/json"):
        try:
            data = json.loads(content.decode("utf-8"))
            detail = data.get("detail") if isinstance(data, dict) else None
            if isinstance(detail, str):
                return detail
            if isinstance(detail, list):
                messages = [
                    str(item.get("msg") if isinstance(item, dict) else item)
                    for item in detail
                    if item
                ]
                if messages:
                    return "; ".join(messages)
        except Exception:
            return fallback
    return fallback


def _desktop_result_from_response(response: Any) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    content = _content_payload(response.content, content_type)
    if 200 <= response.status_code < 300:
        return {"success": True, **content}
    return {
        "success": False,
        "error": {
            "code": _error_code_from_status(response.status_code),
            "message": _detail_from_content(response.content, content_type, response.reason_phrase or "请求失败"),
        },
        **content,
    }


def _desktop_error_result(exc: Exception) -> dict[str, Any]:
    return {
        "success": False,
        "error": {"code": "backend_error", "message": str(exc)},
        "content": {"kind": "json", "value": {"detail": str(exc)}},
    }


def _desktop_validation_error_result(exc: Exception) -> dict[str, Any]:
    return {
        "success": False,
        "error": {"code": "validation_error", "message": str(exc)},
        "content": {"kind": "json", "value": {"detail": str(exc)}},
    }


async def _dispatch_desktop_resource_request(params: dict[str, Any]) -> dict[str, Any]:
    await _ensure_runtime()

    operation = str(params.get("operation") or "read")
    resource = _desktop_resource_name(params)
    from utils.arcreel_desktop_routes import dispatch_desktop_resource

    result = await dispatch_desktop_resource(params)
    _remember_webui_mutation(operation, resource, result)
    _maybe_start_worker_for_result(operation, resource, result)
    return result


async def _dispatch_desktop_file_request(params: dict[str, Any]) -> dict[str, Any]:
    await _ensure_runtime()

    operation = str(params.get("operation") or "create")
    resource = _desktop_resource_name(params)
    from utils.arcreel_desktop_routes import dispatch_desktop_file_resource

    result = await dispatch_desktop_file_resource(params)
    _remember_webui_mutation(operation, resource, result)
    _maybe_start_worker_for_result(operation, resource, result)
    return result


def dispatch_desktop_resource_request(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _run_in_fresh_loop(_dispatch_desktop_resource_request(params))
    except ValueError as exc:
        return _desktop_validation_error_result(exc)
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        return _desktop_error_result(exc)


def dispatch_desktop_file_request(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _run_in_fresh_loop(_dispatch_desktop_file_request(params))
    except ValueError as exc:
        return _desktop_validation_error_result(exc)
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        return _desktop_error_result(exc)


def read_local_file_base64(params: dict[str, Any]) -> dict[str, Any]:
    try:
        file_path = Path(str(params.get("path") or "")).expanduser()
        if not file_path.is_file():
            raise FileNotFoundError(f"Local file does not exist: {file_path}")

        max_bytes = int(params.get("maxBytes") or 0)
        size = file_path.stat().st_size
        if max_bytes > 0 and size > max_bytes:
            return {
                "ok": False,
                "code": "too_large",
                "detail": f"File exceeds the allowed size: {file_path.name}",
                "size": size,
            }

        filename = str(params.get("filename") or file_path.name)
        content_type = (
            str(params.get("contentType") or "")
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
        return {
            "ok": True,
            "name": filename,
            "mimeType": content_type,
            "size": size,
            "base64": base64.b64encode(file_path.read_bytes()).decode("ascii"),
        }
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        return {"ok": False, "code": "backend_error", "detail": str(exc)}


def _zip_blob_result(
    *,
    path: Path,
    filename: str,
    diagnostics: dict[str, Any] | None = None,
    cleanup_parent: bool = False,
) -> dict[str, Any]:
    try:
        content = path.read_bytes()
        result = {
            "ok": True,
            "filename": filename,
            "mimeType": "application/zip",
            "base64": base64.b64encode(content).decode("ascii"),
        }
        if diagnostics is not None:
            result["diagnostics"] = diagnostics
        return result
    finally:
        if cleanup_parent:
            import shutil

            shutil.rmtree(path.parent, ignore_errors=True)
        else:
            with suppress(FileNotFoundError):
                path.unlink()


async def _download_diagnostics_blob() -> dict[str, Any]:
    await _ensure_runtime()

    def _sync() -> tuple[bytes, str]:
        import io
        import zipfile

        from lib.logging_config import resolve_log_dir
        from server.services.diagnostics import collect_diagnostics

        max_file_bytes = 100 * 1024 * 1024
        log_dir = resolve_log_dir()
        diagnostics_lines: list[str] = []
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if log_dir.exists():
                for path in sorted(log_dir.glob("arcreel.log*")):
                    if path.is_symlink() or not path.is_file():
                        continue
                    size = path.stat().st_size
                    if size > max_file_bytes:
                        diagnostics_lines.append(f"[skipped: too large: {path.name} ({size} bytes)]")
                        continue
                    zf.write(path, arcname=f"logs/{path.name}")

            diagnostics_text = collect_diagnostics()
            if diagnostics_lines:
                diagnostics_text += "\n" + "\n".join(diagnostics_lines) + "\n"
            zf.writestr("diagnostics.txt", diagnostics_text)

        ts = datetime.now(UTC).strftime("%Y-%m-%d-%H%MZ")
        return buffer.getvalue(), f"arcreel-diagnostics-{ts}.zip"

    content, filename = await asyncio.to_thread(_sync)
    return {
        "ok": True,
        "filename": filename,
        "mimeType": "application/zip",
        "base64": base64.b64encode(content).decode("ascii"),
    }


def download_diagnostics_blob(params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return _run_in_fresh_loop(_download_diagnostics_blob())
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        return {"ok": False, "detail": str(exc)}


async def _export_project_archive_blob(params: dict[str, Any]) -> dict[str, Any]:
    await _ensure_runtime()
    project_name = str(params.get("projectName") or "").strip()
    scope = str(params.get("scope") or "full")
    if not project_name:
        raise ValueError("Missing projectName")
    if scope not in {"full", "current"}:
        raise ValueError("Invalid export scope")

    def _sync() -> tuple[dict[str, Any], Path, str]:
        from lib.app_data_dir import app_data_dir
        from lib.project_manager import ProjectManager
        from server.services.project_archive import ProjectArchiveService

        service = ProjectArchiveService(ProjectManager(app_data_dir()))
        diagnostics = service.get_export_diagnostics(project_name, scope=scope)
        archive_path, filename = service.export_project(project_name, scope=scope)
        return diagnostics, archive_path, filename

    diagnostics, archive_path, filename = await asyncio.to_thread(_sync)
    return _zip_blob_result(path=Path(archive_path), filename=filename, diagnostics=diagnostics)


def export_project_archive_blob(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _run_in_fresh_loop(_export_project_archive_blob(params))
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        return {"ok": False, "detail": str(exc)}


async def _export_jianying_draft_blob(params: dict[str, Any]) -> dict[str, Any]:
    await _ensure_runtime()
    project_name = str(params.get("projectName") or "").strip()
    draft_path = str(params.get("draftPath") or "").strip()
    jianying_version = str(params.get("jianyingVersion") or "6")
    try:
        episode = int(params.get("episode"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid episode") from exc

    if not project_name:
        raise ValueError("Missing projectName")
    if not draft_path:
        raise ValueError("Missing draftPath")
    if len(draft_path) > 1024 or any(ord(char) < 32 for char in draft_path):
        raise ValueError("Invalid draftPath")

    def _sync() -> Path:
        from lib.app_data_dir import app_data_dir
        from lib.project_manager import ProjectManager
        from server.services.jianying_draft_service import JianyingDraftService

        service = JianyingDraftService(ProjectManager(app_data_dir()))
        return service.export_episode_draft(
            project_name=project_name,
            episode=episode,
            draft_path=draft_path,
            use_draft_info_name=(jianying_version != "5"),
        )

    zip_path = Path(await asyncio.to_thread(_sync))
    filename = f"{project_name}_episode_{episode}_jianying_draft.zip"
    return _zip_blob_result(path=zip_path, filename=filename, cleanup_parent=True)


def export_jianying_draft_blob(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _run_in_fresh_loop(_export_jianying_draft_blob(params))
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        return {"ok": False, "detail": str(exc)}


async def _build_event_snapshot(params: dict[str, Any]) -> dict[str, Any]:
    await _ensure_runtime()
    stream = str(params.get("stream") or "")
    events: list[dict[str, Any]] = []

    if stream.startswith("tasks/stream"):
        query = _query_from_params(params)
        project_name = (query.get("project_name") or [None])[0]

        from lib.generation_queue import get_generation_queue

        queue = get_generation_queue()
        stats = await queue.get_task_stats(project_name=project_name)
        if int(stats.get("queued", 0)) > 0 or int(stats.get("running", 0)) > 0:
            _ensure_worker_process()
        events.append(
            {
                "stream": stream,
                "event": "snapshot",
                "id": _next_event_id(),
                "data": {
                    "project_name": project_name,
                    "tasks": await queue.get_recent_tasks_snapshot(project_name=project_name, limit=1000),
                    "stats": stats,
                    "last_event_id": await queue.get_latest_event_id(project_name=project_name),
                },
            }
        )

    elif stream.startswith("projects/") and stream.endswith("/events/stream"):
        project_name = _project_name_from_stream(stream)
        if project_name:
            events.append(await _build_project_event_snapshot(stream, project_name))

    elif stream.startswith("projects/") and "/assistant/sessions/" in stream:
        parts = _assistant_stream_parts(stream)
        if parts:
            project_name, session_id = parts
            events.extend(
                await _build_assistant_stream_events(
                    stream,
                    project_name,
                    session_id,
                    force_snapshot=True,
                )
            )

    return {"events": events}


def build_event_snapshot(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _run_in_fresh_loop(_build_event_snapshot(params))
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        return {"events": [], "error": str(exc)}


def _project_name_from_stream(stream: str) -> str | None:
    parts = stream.split("/")
    if len(parts) >= 4 and parts[0] == "projects" and parts[2] == "events":
        return unquote(parts[1])
    return None


def _next_event_id() -> str:
    global _event_id_seq
    _event_id_seq += 1
    return str(_event_id_seq)


def _assistant_stream_parts(stream: str) -> tuple[str, str] | None:
    parts = stream.split("/")
    if (
        len(parts) >= 6
        and parts[0] == "projects"
        and parts[2] == "assistant"
        and parts[3] == "sessions"
        and parts[5] == "stream"
    ):
        return unquote(parts[1]), unquote(parts[4])
    return None


def _fingerprint_payload(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


async def _build_assistant_stream_events(
    stream: str,
    project_name: str,
    session_id: str,
    *,
    force_snapshot: bool = False,
) -> list[dict[str, Any]]:
    from server.routers.assistant import get_assistant_service

    service = get_assistant_service()
    await service.startup()
    meta = await service.get_session(session_id)
    if meta is None or meta.project_name != project_name:
        return []

    snapshot = await service.get_snapshot(session_id, meta=meta)
    status = str(snapshot.get("status") or meta.status or "")
    fingerprint = _fingerprint_payload(snapshot)
    previous_fingerprint, previous_status = _assistant_stream_snapshots.get(stream, ("", None))
    events: list[dict[str, Any]] = []

    if force_snapshot or fingerprint != previous_fingerprint:
        events.append(
            {
                "stream": stream,
                "event": "snapshot",
                "id": _next_event_id(),
                "data": snapshot,
            }
        )

    if status in {"completed", "error", "interrupted"} and (force_snapshot or status != previous_status):
        events.append(
            {
                "stream": stream,
                "event": "status",
                "id": _next_event_id(),
                "data": {
                    "status": status,
                    "session_id": session_id,
                },
            }
        )

    _assistant_stream_snapshots[stream] = (fingerprint, status)
    return events


def _get_project_event_service():
    global _project_event_service
    if _project_event_service is None:
        from lib import PROJECT_ROOT
        from lib.app_data_dir import app_data_dir
        from server.services.project_events import ProjectEventService

        _project_event_service = ProjectEventService(PROJECT_ROOT, projects_root=app_data_dir())
    return _project_event_service


async def _rebuild_project_snapshot(project_name: str) -> tuple[dict[str, Any], str]:
    service = _get_project_event_service()
    return await asyncio.to_thread(service._rebuild_snapshot, project_name)


async def _build_project_event_snapshot(stream: str, project_name: str) -> dict[str, Any]:
    snapshot, fingerprint = await _rebuild_project_snapshot(project_name)
    _project_event_snapshots[project_name] = (snapshot, fingerprint)
    return {
        "stream": stream,
        "event": "snapshot",
        "id": _next_event_id(),
        "data": {
            "project_name": project_name,
            "fingerprint": fingerprint,
            "generated_at": _utc_now_iso(),
        },
    }


async def _poll_project_events(stream: str, project_name: str) -> list[dict[str, Any]]:
    previous = _project_event_snapshots.get(project_name)
    snapshot, fingerprint = await _rebuild_project_snapshot(project_name)
    if previous is None:
        _project_event_snapshots[project_name] = (snapshot, fingerprint)
        return [
            {
                "stream": stream,
                "event": "snapshot",
                "id": _next_event_id(),
                "data": {
                    "project_name": project_name,
                    "fingerprint": fingerprint,
                    "generated_at": _utc_now_iso(),
                },
            }
        ]

    previous_snapshot, previous_fingerprint = previous
    if fingerprint == previous_fingerprint:
        return []

    service = _get_project_event_service()
    changes = service._diff_snapshots(previous_snapshot, snapshot)
    _project_event_snapshots[project_name] = (snapshot, fingerprint)
    if not changes:
        return []

    mutation_deadline = _recent_webui_mutations.get(project_name, 0.0)
    source = "webui" if mutation_deadline >= time.monotonic() else "filesystem"
    return [
        {
            "stream": stream,
            "event": "changes",
            "id": _next_event_id(),
            "data": {
                "project_name": project_name,
                "batch_id": uuid4().hex,
                "fingerprint": fingerprint,
                "generated_at": _utc_now_iso(),
                "source": source,
                "changes": changes,
            },
        }
    ]


def _transform_task_event(raw_event: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    event_type = raw_event.get("event_type", "")
    return {
        "action": "created" if event_type == "queued" else "updated",
        "task": raw_event.get("data", {}),
        "stats": stats,
    }


async def _poll_task_events(params: dict[str, Any], stream: str) -> list[dict[str, Any]]:
    query = _query_from_params(params)
    project_name = (query.get("project_name") or [None])[0]
    raw_last_event_id = params.get("lastEventId")
    try:
        last_event_id = int(raw_last_event_id or 0)
    except (TypeError, ValueError):
        last_event_id = 0

    from lib.generation_queue import get_generation_queue

    queue = get_generation_queue()
    events = await queue.get_events_since(
        last_event_id=last_event_id,
        project_name=project_name,
        limit=200,
    )
    if not events:
        return []
    stats = await queue.get_task_stats(project_name=project_name)
    return [
        {
            "stream": stream,
            "event": "task",
            "id": raw_event.get("id"),
            "data": _transform_task_event(raw_event, stats),
        }
        for raw_event in events
    ]


async def _poll_event_streams(params: dict[str, Any]) -> dict[str, Any]:
    await _ensure_runtime()
    stream = str(params.get("stream") or "")

    if stream.startswith("tasks/stream"):
        return {"events": await _poll_task_events(params, stream)}

    if stream.startswith("projects/") and stream.endswith("/events/stream"):
        project_name = _project_name_from_stream(stream)
        if project_name:
            return {"events": await _poll_project_events(stream, project_name)}

    if stream.startswith("projects/") and "/assistant/sessions/" in stream:
        parts = _assistant_stream_parts(stream)
        if parts:
            project_name, session_id = parts
            return {
                "events": await _build_assistant_stream_events(
                    stream,
                    project_name,
                    session_id,
                    force_snapshot=False,
                )
            }

    return {"events": []}


def poll_event_streams(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _run_in_fresh_loop(_poll_event_streams(params))
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        return {"events": [], "error": str(exc)}

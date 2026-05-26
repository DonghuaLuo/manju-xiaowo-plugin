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
import hashlib
import json
import os
import platform
import threading
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
_runtime_lock = asyncio.Lock()
_worker_process: subprocess.Popen | None = None
_worker_log_handle: Any | None = None
_worker_atexit_registered = False
_project_event_snapshots: dict[str, tuple[dict[str, Any], str]] = {}
_recent_webui_mutations: dict[str, float] = {}
_project_event_service: Any | None = None
_project_event_journal_offset: int | None = None
_project_event_pending_batches: dict[str, list[dict[str, Any]]] = {}
_assistant_stream_snapshots: dict[str, tuple[str, str | None]] = {}
_assistant_stream_seen_messages: dict[str, set[str]] = {}
_export_tasks: dict[str, dict[str, Any]] = {}
_export_tasks_lock = threading.Lock()
_event_id_seq = 0


def _assistant_startup_kwargs() -> dict[str, bool]:
    """Return AssistantService startup flags for the desktop IPC runtime.

    FastAPI's lifespan runs the full sandbox availability probe. The plugin IPC
    bridge does not use lifespan, so it must still pass the same Windows fallback
    signal; otherwise the SDK can disable sandbox internally while our own
    allowed_tools list still treats Bash as sandboxed.
    """
    system = platform.system()
    sandbox_enabled = system in {"Darwin", "Linux"}
    return {"in_docker": False, "sandbox_enabled": sandbox_enabled}


def _prepare_desktop_environment(env: MutableMapping[str, str] | None = None) -> None:
    target = os.environ if env is None else env
    target["AUTH_ENABLED"] = "false"
    target["XIAOWO_ARCREEL_DESKTOP_RUNTIME"] = "1"
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

    async with _runtime_lock:
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

            await assistant.assistant_service.startup(**_assistant_startup_kwargs())
            session_manager = assistant.assistant_service.session_manager
            patrol_task = getattr(session_manager, "_patrol_task", None)
            if patrol_task is None or patrol_task.done():
                session_manager.start_patrol()
        _ensure_project_change_journal_listener()


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


def ensure_desktop_worker_process() -> bool:
    """Ensure the desktop queue worker subprocess is running."""
    _ensure_worker_process()
    return _worker_process is not None and _worker_process.poll() is None


def _ensure_project_change_journal_listener() -> None:
    global _project_event_journal_offset
    if getattr(_ensure_project_change_journal_listener, "_registered", False):
        return
    from lib.project_change_hints import register_project_change_batch_listener
    from utils.arcreel_desktop_sync import append_project_event_batch, project_event_journal_size

    if _project_event_journal_offset is None:
        _project_event_journal_offset = project_event_journal_size()
    register_project_change_batch_listener(append_project_event_batch)
    setattr(_ensure_project_change_journal_listener, "_registered", True)


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


async def dispatch_desktop_resource_request(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _dispatch_desktop_resource_request(params)
    except ValueError as exc:
        return _desktop_validation_error_result(exc)
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        return _desktop_error_result(exc)


async def dispatch_desktop_file_request(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _dispatch_desktop_file_request(params)
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


def _validate_desktop_path(raw_path: Any, *, field_name: str, max_length: int = 4096) -> Path:
    path_text = str(raw_path or "").strip()
    if not path_text:
        raise ValueError(f"Missing {field_name}")
    if len(path_text) > max_length or any(ord(char) < 32 for char in path_text):
        raise ValueError(f"Invalid {field_name}")
    return Path(path_text).expanduser()


def _normalize_zip_export_path(raw_path: Any) -> Path:
    path = _validate_desktop_path(raw_path, field_name="exportPath")
    if path.suffix.lower() != ".zip":
        path = Path(f"{path}.zip")
    return path


def _record_export_task(task_id: str, payload: dict[str, Any]) -> None:
    snapshot = {"taskId": task_id, "updatedAt": _utc_now_iso(), **payload}
    with _export_tasks_lock:
        _export_tasks[task_id] = snapshot


def _emit_export_task_event(task_id: str, payload: dict[str, Any]) -> None:
    event = {"taskId": task_id, "updatedAt": _utc_now_iso(), **payload}
    with _export_tasks_lock:
        _export_tasks[task_id] = event
    try:
        from utils.xiaowo_sdk import sdk

        sdk.send_event("arcreel_export_task", event)
    except Exception:
        _log_exception()


def _run_project_archive_export_task(
    *,
    task_id: str,
    project_name: str,
    scope: str,
    export_path: Path,
) -> None:
    _emit_export_task_event(
        task_id,
        {
            "kind": "project_archive",
            "status": "running",
            "projectName": project_name,
            "scope": scope,
            "exportPath": str(export_path),
        },
    )
    try:
        from lib.app_data_dir import app_data_dir
        from lib.project_manager import ProjectManager
        from server.services.project_archive import ProjectArchiveService

        service = ProjectArchiveService(ProjectManager(app_data_dir()))
        target_path, diagnostics = service.export_project_to_path(
            project_name,
            export_path,
            scope=scope,
        )
        _emit_export_task_event(
            task_id,
            {
                "kind": "project_archive",
                "status": "completed",
                "projectName": project_name,
                "scope": scope,
                "exportPath": str(target_path),
                "diagnostics": diagnostics,
            },
        )
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        _emit_export_task_event(
            task_id,
            {
                "kind": "project_archive",
                "status": "failed",
                "projectName": project_name,
                "scope": scope,
                "exportPath": str(export_path),
                "error": str(exc),
            },
        )


def _run_jianying_draft_export_task(
    *,
    task_id: str,
    project_name: str,
    episode: int,
    draft_path: Path,
    jianying_version: str,
) -> None:
    _emit_export_task_event(
        task_id,
        {
            "kind": "jianying_draft",
            "status": "running",
            "projectName": project_name,
            "episode": episode,
            "draftPath": str(draft_path),
        },
    )
    try:
        from lib.app_data_dir import app_data_dir
        from lib.project_manager import ProjectManager
        from server.services.jianying_draft_service import JianyingDraftService

        service = JianyingDraftService(ProjectManager(app_data_dir()))
        draft_dir = service.export_episode_draft_to_directory(
            project_name=project_name,
            episode=episode,
            draft_path=str(draft_path),
            use_draft_info_name=(jianying_version != "5"),
        )
        _emit_export_task_event(
            task_id,
            {
                "kind": "jianying_draft",
                "status": "completed",
                "projectName": project_name,
                "episode": episode,
                "draftPath": str(draft_path),
                "draftDir": str(draft_dir),
            },
        )
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        _emit_export_task_event(
            task_id,
            {
                "kind": "jianying_draft",
                "status": "failed",
                "projectName": project_name,
                "episode": episode,
                "draftPath": str(draft_path),
                "error": str(exc),
            },
        )


def _start_export_thread(name: str, target: Any, kwargs: dict[str, Any]) -> None:
    thread = threading.Thread(
        target=target,
        kwargs=kwargs,
        name=name,
    )
    thread.start()


def _detect_jianying_draft_root() -> str:
    candidates: list[Path] = []
    system = platform.system()
    home = Path.home()
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft")
        candidates.append(home / "AppData" / "Local" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft")
    elif system == "Darwin":
        candidates.append(home / "Movies" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft")
    else:
        candidates.append(home / ".config" / "JianyingPro" / "User Data" / "Projects" / "com.lveditor.draft")

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_dir():
            return key
    return ""


def _open_desktop_path(raw_path: Any) -> dict[str, str]:
    from utils.common import open_in_file_explorer

    path = _validate_desktop_path(raw_path, field_name="path")
    result = open_in_file_explorer(path)
    if not result.get("success"):
        message = str(result.get("message") or f"路径不存在: {path}")
        if "不存在" in message:
            raise FileNotFoundError(message)
        raise RuntimeError(message)

    return {
        "path": str(path),
        "openedPath": str(result.get("openedPath") or path),
    }


async def open_desktop_path(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return {"ok": True, **_open_desktop_path((params or {}).get("path"))}
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        return {"ok": False, "detail": str(exc)}


async def _start_project_archive_export(params: dict[str, Any]) -> dict[str, Any]:
    await _ensure_runtime()
    project_name = str(params.get("projectName") or "").strip()
    scope = str(params.get("scope") or "full")
    if not project_name:
        raise ValueError("Missing projectName")
    if scope not in {"full", "current"}:
        raise ValueError("Invalid export scope")

    export_path = _normalize_zip_export_path(params.get("exportPath"))
    task_id = uuid4().hex
    _record_export_task(
        task_id,
        {
            "kind": "project_archive",
            "status": "queued",
            "projectName": project_name,
            "scope": scope,
            "exportPath": str(export_path),
        },
    )
    _start_export_thread(
        f"arcreel-export-project-{task_id}",
        _run_project_archive_export_task,
        {
            "task_id": task_id,
            "project_name": project_name,
            "scope": scope,
            "export_path": export_path,
        },
    )
    return {"ok": True, "taskId": task_id, "status": "queued", "exportPath": str(export_path)}


async def start_project_archive_export(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _start_project_archive_export(params)
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        return {"ok": False, "detail": str(exc)}


async def _start_jianying_draft_export(params: dict[str, Any]) -> dict[str, Any]:
    await _ensure_runtime()
    project_name = str(params.get("projectName") or "").strip()
    jianying_version = str(params.get("jianyingVersion") or "6")
    try:
        episode = int(params.get("episode"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid episode") from exc

    if not project_name:
        raise ValueError("Missing projectName")
    draft_path = _validate_desktop_path(params.get("draftPath"), field_name="draftPath", max_length=1024)

    task_id = uuid4().hex
    _record_export_task(
        task_id,
        {
            "kind": "jianying_draft",
            "status": "queued",
            "projectName": project_name,
            "episode": episode,
            "draftPath": str(draft_path),
        },
    )
    _start_export_thread(
        f"arcreel-export-jianying-{task_id}",
        _run_jianying_draft_export_task,
        {
            "task_id": task_id,
            "project_name": project_name,
            "episode": episode,
            "draft_path": draft_path,
            "jianying_version": jianying_version,
        },
    )
    return {"ok": True, "taskId": task_id, "status": "queued", "draftPath": str(draft_path)}


async def start_jianying_draft_export(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _start_jianying_draft_export(params)
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        return {"ok": False, "detail": str(exc)}


async def get_export_task_status(params: dict[str, Any]) -> dict[str, Any]:
    task_id = str((params or {}).get("taskId") or "").strip()
    if not task_id:
        return {"ok": False, "detail": "Missing taskId"}
    with _export_tasks_lock:
        task = _export_tasks.get(task_id)
    if not task:
        return {"ok": False, "detail": "Task not found"}
    return {"ok": True, "task": task}


async def detect_jianying_draft_root(params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return {"ok": True, "path": _detect_jianying_draft_root()}
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        return {"ok": False, "detail": str(exc), "path": ""}


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


async def download_diagnostics_blob(params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return await _download_diagnostics_blob()
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


async def export_project_archive_blob(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _export_project_archive_blob(params)
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


async def export_jianying_draft_blob(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _export_jianying_draft_blob(params)
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
        raw_last_event_id = (query.get("last_event_id") or [None])[-1]
        resume_requested = raw_last_event_id is not None
        try:
            cursor = max(0, int(raw_last_event_id or 0))
        except (TypeError, ValueError):
            cursor = 0

        from lib.generation_queue import get_generation_queue

        queue = get_generation_queue()
        stats = await queue.get_task_stats(project_name=project_name)
        latest_event_id = await queue.get_latest_event_id(project_name=project_name)
        snapshot_last_event_id = max(cursor, latest_event_id) if resume_requested else latest_event_id
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
                    "last_event_id": snapshot_last_event_id,
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


async def build_event_snapshot(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _build_event_snapshot(params)
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


def _stable_event_id(stream: str, event: str, data: Any, salt: str = "") -> str:
    raw = json.dumps(
        {"stream": stream, "event": event, "data": data, "salt": salt},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _assistant_message_key(message: Any) -> str:
    if isinstance(message, dict):
        for key in ("uuid", "id", "message_id"):
            value = message.get(key)
            if value:
                return f"{key}:{value}"
    return "fp:" + hashlib.sha256(
        json.dumps(message, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _server_sent_event_payload(stream: str, event: Any, salt: str = "") -> dict[str, Any]:
    event_name = str(getattr(event, "event", None) or "message")
    data = getattr(event, "data", None)
    if isinstance(data, str):
        with suppress(json.JSONDecodeError):
            data = json.loads(data)
    event_id = getattr(event, "id", None)
    return {
        "stream": stream,
        "event": event_name,
        "id": str(event_id) if event_id else _stable_event_id(stream, event_name, data, salt),
        "data": data,
    }


async def _assistant_buffer_messages(service: Any, session_id: str) -> list[dict[str, Any]]:
    getter = getattr(service.session_manager, "get_message_buffer_snapshot", None)
    if getter is not None:
        messages = await getter(session_id)
    else:
        messages = service.session_manager.get_buffered_messages(session_id)
    return [message for message in messages if isinstance(message, dict)]


async def _build_assistant_stream_events(
    stream: str,
    project_name: str,
    session_id: str,
    *,
    force_snapshot: bool = False,
) -> list[dict[str, Any]]:
    from server.routers.assistant import get_assistant_service

    service = get_assistant_service()
    await service.startup(**_assistant_startup_kwargs())
    meta = await service.get_session(session_id)
    if meta is None or meta.project_name != project_name:
        return []

    buffer_messages = await _assistant_buffer_messages(service, session_id)
    snapshot = await service.get_snapshot(session_id, meta=meta)
    status = str(snapshot.get("status") or meta.status or "")
    fingerprint = _fingerprint_payload(snapshot)
    previous_fingerprint, previous_status = _assistant_stream_snapshots.get(stream, ("", None))
    events: list[dict[str, Any]] = []

    if force_snapshot:
        events.append(
            {
                "stream": stream,
                "event": "snapshot",
                "id": _stable_event_id(stream, "snapshot", snapshot, "initial"),
                "data": snapshot,
            }
        )
        _assistant_stream_seen_messages[stream] = {
            _assistant_message_key(message) for message in buffer_messages
        }
    else:
        seen_messages = _assistant_stream_seen_messages.setdefault(stream, set())
        old_messages: list[dict[str, Any]] = []
        new_messages: list[dict[str, Any]] = []
        for message in buffer_messages:
            key = _assistant_message_key(message)
            if key in seen_messages:
                old_messages.append(message)
            else:
                new_messages.append(message)

        if new_messages:
            projector = await service._build_projector(meta, session_id, old_messages)
            for message in new_messages:
                key = _assistant_message_key(message)
                emitted, should_break = await service._dispatch_live_message(
                    message,
                    projector,
                    session_id,
                )
                seen_messages.add(key)
                for index, server_event in enumerate(emitted):
                    events.append(
                        _server_sent_event_payload(
                            stream,
                            server_event,
                            salt=f"{key}:{index}",
                        )
                    )
                if should_break:
                    break
        elif fingerprint != previous_fingerprint:
            events.append(
                {
                    "stream": stream,
                    "event": "snapshot",
                    "id": _stable_event_id(stream, "snapshot", snapshot, fingerprint),
                    "data": snapshot,
                }
            )

    has_status_event = any(event.get("event") == "status" for event in events)
    if (
        not has_status_event
        and status in {"completed", "error", "interrupted"}
        and (force_snapshot or status != previous_status)
    ):
        events.append(
            {
                "stream": stream,
                "event": "status",
                "id": _stable_event_id(stream, "status", {"status": status, "session_id": session_id}, status),
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


def _consume_project_event_journal(project_name: str) -> list[dict[str, Any]]:
    global _project_event_journal_offset
    from utils.arcreel_desktop_sync import project_event_journal_size, read_project_event_batches

    pending = _project_event_pending_batches.pop(project_name, [])
    if _project_event_journal_offset is None:
        _project_event_journal_offset = project_event_journal_size()
    _project_event_journal_offset, batches = read_project_event_batches(_project_event_journal_offset)
    for batch in batches:
        batch_project_name = batch.get("project_name")
        if not isinstance(batch_project_name, str) or not batch_project_name:
            continue
        if str(batch.get("source") or "") not in {"webui", "worker", "filesystem"}:
            continue
        if not isinstance(batch.get("changes"), list):
            continue
        if batch_project_name == project_name:
            pending.append(batch)
        else:
            _project_event_pending_batches.setdefault(batch_project_name, []).append(batch)
    return pending


async def _poll_project_events(stream: str, project_name: str) -> list[dict[str, Any]]:
    journal_batches = _consume_project_event_journal(project_name)
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
    if journal_batches:
        service = _get_project_event_service()
        fallback_changes = [] if fingerprint == previous_fingerprint else service._diff_snapshots(previous_snapshot, snapshot)
        _project_event_snapshots[project_name] = (snapshot, fingerprint)
        events: list[dict[str, Any]] = []
        for batch in journal_batches:
            changes = batch.get("changes") or fallback_changes
            if not changes:
                continue
            events.append(
                {
                    "stream": stream,
                    "event": "changes",
                    "id": _next_event_id(),
                    "data": {
                        "project_name": project_name,
                        "batch_id": str(batch.get("id") or uuid4().hex),
                        "fingerprint": fingerprint,
                        "generated_at": str(batch.get("created_at") or _utc_now_iso()),
                        "source": str(batch.get("source") or "filesystem"),
                        "changes": changes,
                    },
                }
            )
        return events

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


async def poll_event_streams(params: dict[str, Any]) -> dict[str, Any]:
    try:
        return await _poll_event_streams(params)
    except Exception as exc:  # noqa: BLE001
        _log_exception()
        return {"events": [], "error": str(exc)}

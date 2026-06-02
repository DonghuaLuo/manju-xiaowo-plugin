#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Desktop resource dispatcher for ArcReel business endpoints.

The Xiaowo plugin frontend sends desktop-shaped IPC requests:
``operation + resource + query + body``.  This module maps that contract to
ArcReel's existing endpoint functions without creating a web server,
without importing the ASGI app, and without sending worker stdout to Xiaowo IPC.
"""

from __future__ import annotations

import inspect
import json
import mimetypes
import base64
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace, UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints
from urllib.parse import unquote

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel


@dataclass(frozen=True)
class _DesktopRoute:
    method: str
    path: str
    regex: Any
    converters: dict[str, Any]
    endpoint: Any
    status_code: int | None


class _DesktopGenerationWorkerProxy:
    async def reload_limits(self) -> None:
        from utils.arcreel_desktop_sync import request_worker_reload

        request_worker_reload("config_changed")


class _DesktopRequest:
    def __init__(self, *, locale: str, query: dict[str, list[str]]) -> None:
        self.headers = {"accept-language": locale} if locale else {}
        self.query_params = {key: values[-1] for key, values in query.items() if values}
        self.app = SimpleNamespace(state=SimpleNamespace(generation_worker=_DesktopGenerationWorkerProxy()))

    async def is_disconnected(self) -> bool:
        return False


class _DesktopUploadFile:
    def __init__(self, *, path: Path, filename: str, content_type: str, cleanup_path: bool = False) -> None:
        self.path = path
        self.filename = filename
        self.content_type = content_type
        self.cleanup_path = cleanup_path
        self.file = path.open("rb")
        self.size = path.stat().st_size

    async def read(self, size: int = -1) -> bytes:
        return self.file.read(size)

    async def close(self) -> None:
        self.file.close()

    def close_sync(self) -> None:
        self.file.close()
        if self.cleanup_path:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


_ROUTES: list[_DesktopRoute] | None = None
_ROUTE_MODULES: tuple[tuple[str, str], ...] = (
    ("server.routers.projects", ""),
    ("server.routers.characters", ""),
    ("server.routers.scenes", ""),
    ("server.routers.props", ""),
    ("server.routers.files", ""),
    ("server.routers.generate", ""),
    ("server.routers.versions", ""),
    ("server.routers.usage", ""),
    ("server.routers.assistant", "/projects/{project_name}/assistant"),
    ("server.routers.tasks", ""),
    ("server.routers.providers", ""),
    ("server.routers.system_config", ""),
    ("server.routers.system", ""),
    ("server.routers.agent_chat", ""),
    ("server.routers.agent_config", ""),
    ("server.routers.custom_providers", ""),
    ("server.routers.cost_estimation", ""),
    ("server.routers.grids", ""),
    ("server.routers.reference_videos", ""),
    ("server.routers.quality", ""),
    ("server.routers.assets", ""),
)


def _operation_to_method(operation: str) -> str:
    return {
        "read": "GET",
        "create": "POST",
        "replace": "PUT",
        "update": "PATCH",
        "delete": "DELETE",
    }.get(operation, "GET")


def _locale_from_params(params: dict[str, Any]) -> str:
    raw = str(params.get("locale") or "zh").split(",")[0].split("-")[0].strip().lower()
    return raw if raw in {"zh", "en", "vi"} else "zh"


def _translator(locale: str):
    from lib.i18n import _

    def translate(key: str, **kwargs: Any) -> str:
        return _(key, locale=locale, **kwargs)

    return translate


def _desktop_user():
    from lib.db.base import DEFAULT_USER_ID
    from server.auth import CurrentUserInfo

    return CurrentUserInfo(id=DEFAULT_USER_ID, sub="local", role="admin")


def _query_from_params(params: dict[str, Any]) -> dict[str, list[str]]:
    query: dict[str, list[str]] = {}
    for key, value in (params.get("query") or {}).items():
        if isinstance(value, list):
            query[str(key)] = [str(item) for item in value]
        elif value is not None:
            query[str(key)] = [str(value)]
    return query


def _resource_path(resource: str) -> str:
    raw = str(resource or "root").strip()
    if "://" in raw or raw.startswith(("/", "\\")) or ".." in raw.split("/"):
        raise ValueError(f"Invalid desktop resource: {raw}")
    stripped = "" if raw == "root" else raw.strip("/")
    return "/" if not stripped else "/" + "/".join(unquote(part) for part in stripped.split("/"))


def _compile_path(path: str):
    from starlette.routing import compile_path

    regex, _format, converters = compile_path(path)
    return regex, converters


def _is_disabled_desktop_route_path(path: str) -> bool:
    if path.startswith("/auth") or path.startswith("/api-keys"):
        return True
    if path in {
        "/projects/{name}/export",
        "/projects/{name}/export/token",
        "/projects/{name}/export/jianying-draft",
        "/system/logs/download",
    }:
        return True
    return False


def _load_routes() -> list[_DesktopRoute]:
    global _ROUTES
    if _ROUTES is not None:
        return _ROUTES

    import importlib

    routes: list[_DesktopRoute] = []
    for module_name, prefix in _ROUTE_MODULES:
        module = importlib.import_module(module_name)
        router = getattr(module, "router")
        for route in getattr(router, "routes", []):
            methods = getattr(route, "methods", None)
            endpoint = getattr(route, "endpoint", None)
            raw_path = getattr(route, "path", "")
            if not methods or endpoint is None or not raw_path:
                continue
            path = f"{prefix}{raw_path}" if prefix else raw_path
            if _is_disabled_desktop_route_path(path):
                continue
            regex, converters = _compile_path(path)
            for method in sorted(methods):
                routes.append(
                    _DesktopRoute(
                        method=method.upper(),
                        path=path,
                        regex=regex,
                        converters=converters,
                        endpoint=endpoint,
                        status_code=getattr(route, "status_code", None),
                    )
                )
    _ROUTES = routes
    return routes


def _match_route(method: str, path: str) -> tuple[_DesktopRoute, dict[str, Any]]:
    for route in _load_routes():
        if route.method != method:
            continue
        match = route.regex.match(path)
        if not match:
            continue
        params = {}
        for key, value in match.groupdict().items():
            converter = route.converters.get(key)
            params[key] = converter.convert(value) if converter is not None else value
        return route, params
    raise ValueError(f"Unsupported desktop resource: {method} {path.lstrip('/') or 'root'}")


def _body_value(raw: dict[str, Any] | None) -> tuple[Any, str | None]:
    if not raw:
        return None, None
    kind = str(raw.get("kind") or "empty")
    if kind == "json":
        return raw.get("value"), "application/json"
    if kind == "fields":
        return raw.get("fields") or {}, "application/x-www-form-urlencoded;charset=UTF-8"
    if kind == "text":
        return str(raw.get("text") or ""), str(raw.get("mimeType") or "") or "text/plain;charset=UTF-8"
    if kind == "binary":
        import base64

        return base64.b64decode(str(raw.get("base64") or "")), str(raw.get("mimeType") or "") or None
    return None, None


def _unwrap_annotated(annotation: Any) -> Any:
    if get_origin(annotation) is not None and str(get_origin(annotation)) == "typing.Annotated":
        args = get_args(annotation)
        return args[0] if args else Any
    return annotation


def _is_base_model_type(annotation: Any) -> bool:
    annotation = _unwrap_annotated(annotation)
    return inspect.isclass(annotation) and issubclass(annotation, BaseModel)


def _make_base_model(annotation: Any, value: Any) -> BaseModel:
    model_type = _unwrap_annotated(annotation)
    if value is None:
        value = {}
    if isinstance(value, model_type):
        return value
    return model_type.model_validate(value)


def _endpoint_type_hints(endpoint: Any) -> dict[str, Any]:
    try:
        return get_type_hints(endpoint, include_extras=True)
    except Exception:
        return {}


def _default_from_fastapi_param(default: Any) -> Any:
    if default is inspect._empty:
        return inspect._empty
    if hasattr(default, "default"):
        value = default.default
        if value is Ellipsis or str(value) == "PydanticUndefined":
            return inspect._empty
        return value
    return default


def _coerce_scalar(value: Any, annotation: Any) -> Any:
    if value is None:
        return None
    annotation = _unwrap_annotated(annotation)
    origin = get_origin(annotation)
    if origin in {Union, UnionType}:
        args = get_args(annotation)
        concrete_args = [arg for arg in args if arg is not type(None)]
        if len(concrete_args) == 1:
            return _coerce_scalar(value, concrete_args[0])
        for candidate in concrete_args:
            try:
                return _coerce_scalar(value, candidate)
            except (TypeError, ValueError):
                continue
        return value
    if origin in {list, tuple, set}:
        inner = get_args(annotation)[0] if get_args(annotation) else str
        values = value if isinstance(value, list) else [value]
        return [_coerce_scalar(item, inner) for item in values]
    if annotation is bool:
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if annotation is int:
        return int(value)
    if annotation is float:
        return float(value)
    return value


async def _open_upload_files(params: dict[str, Any]) -> tuple[list[_DesktopUploadFile], dict[str, list[_DesktopUploadFile]]]:
    opened: list[_DesktopUploadFile] = []
    by_field: dict[str, list[_DesktopUploadFile]] = {}
    for raw_file in params.get("files") or []:
        if not isinstance(raw_file, dict):
            raise ValueError("Invalid local file descriptor")
        field_name = str(raw_file.get("fieldName") or "file")
        filename = str(raw_file.get("filename") or "")
        cleanup_path = False
        if raw_file.get("base64") is not None:
            suffix = Path(filename).suffix if filename else ""
            with tempfile.NamedTemporaryFile(prefix="manju-upload-", suffix=suffix, delete=False) as tmp:
                tmp.write(base64.b64decode(str(raw_file.get("base64") or "")))
                file_path = Path(tmp.name)
            cleanup_path = True
        else:
            file_path = Path(str(raw_file.get("path") or "")).expanduser()
            if not file_path.is_file():
                raise FileNotFoundError(f"Local file does not exist: {file_path}")
        filename = filename or file_path.name
        content_type = (
            str(raw_file.get("contentType") or "")
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
        upload = _DesktopUploadFile(
            path=file_path,
            filename=filename,
            content_type=content_type,
            cleanup_path=cleanup_path,
        )
        opened.append(upload)
        by_field.setdefault(field_name, []).append(upload)
    return opened, by_field


async def _invoke_route(
    route: _DesktopRoute,
    *,
    path_params: dict[str, Any],
    query: dict[str, list[str]],
    body: Any,
    locale: str,
    fields: dict[str, Any] | None = None,
    files_by_field: dict[str, list[_DesktopUploadFile]] | None = None,
) -> Any:
    signature = inspect.signature(route.endpoint)
    type_hints = _endpoint_type_hints(route.endpoint)
    kwargs: dict[str, Any] = {}
    user = _desktop_user()
    translator = _translator(locale)
    request = _DesktopRequest(locale=locale, query=query)
    session = None

    try:
        for name, param in signature.parameters.items():
            annotation = _unwrap_annotated(type_hints.get(name, param.annotation))
            default = _default_from_fastapi_param(param.default)

            if name in path_params:
                kwargs[name] = _coerce_scalar(path_params[name], annotation)
                continue
            if name in {"_user", "current_user"}:
                kwargs[name] = user
                continue
            if name == "_t":
                kwargs[name] = translator
                continue
            if name == "request":
                kwargs[name] = request
                continue
            if name == "session":
                if session is None:
                    from lib.db import async_session_factory

                    session = async_session_factory()
                    session = await session.__aenter__()
                kwargs[name] = session
                continue
            if name == "svc":
                if session is None:
                    from lib.db import async_session_factory

                    session = async_session_factory()
                    session = await session.__aenter__()
                from lib.config.service import ConfigService

                kwargs[name] = ConfigService(session)
                continue
            if name in {"file", "image"}:
                files = (files_by_field or {}).get(name) or (files_by_field or {}).get("file") or []
                if files:
                    kwargs[name] = files[0]
                elif default is not inspect._empty:
                    kwargs[name] = default
                else:
                    kwargs[name] = None
                continue
            if _is_base_model_type(annotation):
                kwargs[name] = _make_base_model(annotation, body)
                continue
            if name in {"req", "body"}:
                kwargs[name] = body
                continue
            if name == "content" and isinstance(body, str):
                kwargs[name] = body
                continue
            if body is not None and param.default is not inspect._empty:
                default_kind = type(param.default).__name__
                if default_kind == "Body":
                    kwargs[name] = _coerce_scalar(body, annotation)
                    continue
            if fields and name in fields:
                value = fields[name]
                if isinstance(value, list):
                    value = value[-1] if value else None
                kwargs[name] = _coerce_scalar(value, annotation)
                continue
            if name in query:
                values = query[name]
                value: Any = values if get_origin(annotation) in {list, tuple, set} else values[-1]
                kwargs[name] = _coerce_scalar(value, annotation)
                continue
            if default is not inspect._empty:
                kwargs[name] = default
                continue
            kwargs[name] = None

        result = route.endpoint(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result
    finally:
        if session is not None:
            await session.__aexit__(None, None, None)


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
    import base64

    return {
        "content": {
            "kind": "binary",
            "base64": base64.b64encode(content).decode("ascii"),
            "mimeType": content_type or "application/octet-stream",
        }
    }


def _success_result(value: Any) -> dict[str, Any]:
    if value is None:
        return {"success": True, "content": {"kind": "empty"}}
    if isinstance(value, BaseModel):
        return {"success": True, "content": {"kind": "json", "value": value.model_dump(mode="json")}}
    if isinstance(value, (dict, list, str, int, float, bool)):
        if isinstance(value, str):
            return {"success": True, "content": {"kind": "text", "text": value, "mimeType": "text/plain;charset=UTF-8"}}
        return {"success": True, "content": {"kind": "json", "value": jsonable_encoder(value)}}

    status_code = getattr(value, "status_code", 200)
    media_type = str(getattr(value, "media_type", "") or "")
    headers = getattr(value, "headers", {}) or {}
    content_type = str(headers.get("content-type") or media_type or "application/octet-stream")

    if hasattr(value, "path") and getattr(value, "path", None):
        path = Path(str(getattr(value, "path")))
        content = path.read_bytes()
        content_type = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        payload = _content_payload(content, content_type)
    else:
        payload = _content_payload(bytes(getattr(value, "body", b"")), content_type)

    if status_code >= 400:
        detail = _detail_from_payload(payload)
        return {
            "success": False,
            "error": {"code": _error_code_from_status(status_code), "message": detail},
            **payload,
        }
    return {"success": True, **payload}


def _detail_from_payload(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, dict) and content.get("kind") == "json":
        value = content.get("value")
        detail = value.get("detail") if isinstance(value, dict) else None
        if isinstance(detail, str):
            return detail
        if isinstance(detail, dict):
            return str(detail.get("message") or detail)
        if isinstance(detail, list):
            return "; ".join(str(item.get("msg") if isinstance(item, dict) else item) for item in detail)
    if isinstance(content, dict) and content.get("kind") == "text":
        return str(content.get("text") or "请求失败")
    return "请求失败"


def _error_code_from_status(status_code: int) -> str:
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
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


def _error_result(exc: Exception) -> dict[str, Any]:
    status_code = int(getattr(exc, "status_code", 500) or 500)
    detail = getattr(exc, "detail", None)
    if detail is None:
        detail = str(exc)
    message = detail if isinstance(detail, str) else str(detail)
    return {
        "success": False,
        "error": {"code": _error_code_from_status(status_code), "message": message},
        "content": {"kind": "json", "value": {"detail": detail}},
    }


async def dispatch_desktop_resource(params: dict[str, Any]) -> dict[str, Any]:
    locale = _locale_from_params(params)
    method = _operation_to_method(str(params.get("operation") or "read"))
    path = _resource_path(str(params.get("resource") or "root"))
    query = _query_from_params(params)
    body, _content_type = _body_value(params.get("body"))

    try:
        route, path_params = _match_route(method, path)
        return _success_result(
            await _invoke_route(
                route,
                path_params=path_params,
                query=query,
                body=body,
                locale=locale,
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _error_result(exc)


async def dispatch_desktop_file_resource(params: dict[str, Any]) -> dict[str, Any]:
    locale = _locale_from_params(params)
    method = _operation_to_method(str(params.get("operation") or "create"))
    path = _resource_path(str(params.get("resource") or "root"))
    query = _query_from_params(params)
    fields = {
        str(key): value
        for key, value in (params.get("fields") or {}).items()
    }

    opened, files_by_field = await _open_upload_files(params)
    try:
        route, path_params = _match_route(method, path)
        return _success_result(
            await _invoke_route(
                route,
                path_params=path_params,
                query=query,
                body=fields,
                locale=locale,
                fields=fields,
                files_by_field=files_by_field,
            )
        )
    except Exception as exc:  # noqa: BLE001
        return _error_result(exc)
    finally:
        for upload in opened:
            upload.close_sync()

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Explicit IPC endpoints for project-level character / scene / prop CRUD."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import HTTPException

from lib.asset_types import ASSET_SPECS
from lib.project_change_hints import project_change_source
from server.routers._asset_router_factory import _CreateRequest, _I18N_KEYS
from server.services.design_resource_usage import find_design_resource_usages

logger = logging.getLogger(__name__)


def _project_manager(asset_type: str):
    if asset_type == "character":
        from server.routers import characters

        return characters.get_project_manager()
    if asset_type == "scene":
        from server.routers import scenes

        return scenes.get_project_manager()
    if asset_type == "prop":
        from server.routers import props

        return props.get_project_manager()
    raise ValueError(f"unknown asset_type: {asset_type}")


async def _add_asset(asset_type: str, project_name: str, req: dict[str, Any] | None, _t: Any) -> dict[str, Any]:
    spec = ASSET_SPECS[asset_type]
    keys = _I18N_KEYS[asset_type]
    result_key = asset_type
    payload = _CreateRequest.model_validate(req or {})

    try:
        extras = payload.model_extra or {}

        def _sync():
            manager = _project_manager(asset_type)
            entry: dict[str, Any] = {"description": payload.description, spec.sheet_field: ""}
            for field in spec.extra_string_fields:
                entry[field] = extras.get(field, "")
            with project_change_source("webui"):
                ok = manager._add_asset(asset_type, project_name, payload.name, entry)
            if not ok:
                raise HTTPException(status_code=409, detail=_t(keys["exists"], name=payload.name))
            data = manager.load_project(project_name)
            return {"success": True, result_key: data[spec.bucket_key][payload.name]}

        return await asyncio.to_thread(_sync)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(exc))


async def _update_asset(
    asset_type: str,
    project_name: str,
    entry_name: str,
    req: dict[str, Any] | None,
    _t: Any,
) -> dict[str, Any]:
    spec = ASSET_SPECS[asset_type]
    keys = _I18N_KEYS[asset_type]
    result_key = asset_type
    update_fields: tuple[str, ...] = ("description", spec.sheet_field, *spec.extra_string_fields)
    payload = req or {}

    for field in update_fields:
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            raise HTTPException(status_code=422, detail=f"field '{field}' must be a string")

    try:

        def _sync():
            manager = _project_manager(asset_type)
            result: dict[str, Any] = {}

            def _mutate(project):
                bucket = project.get(spec.bucket_key) or {}
                if entry_name not in bucket:
                    raise KeyError(entry_name)
                entry = bucket[entry_name]
                for field in update_fields:
                    if payload.get(field) is not None:
                        entry[field] = payload[field]
                result.update(entry)

            with project_change_source("webui"):
                manager.update_project(project_name, _mutate)
            return {"success": True, result_key: result}

        return await asyncio.to_thread(_sync)
    except KeyError:
        raise HTTPException(status_code=404, detail=_t(keys["not_found"], name=entry_name))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(exc))


async def _delete_asset(asset_type: str, project_name: str, entry_name: str, _t: Any) -> dict[str, Any]:
    spec = ASSET_SPECS[asset_type]
    keys = _I18N_KEYS[asset_type]

    try:

        def _sync():
            manager = _project_manager(asset_type)

            def _mutate(project):
                bucket = project.get(spec.bucket_key) or {}
                if entry_name not in bucket:
                    raise KeyError(entry_name)
                if find_design_resource_usages(manager, project_name, project, spec.bucket_key, entry_name):
                    raise HTTPException(status_code=409, detail="已应用，无法删除")
                del bucket[entry_name]

            with project_change_source("webui"):
                manager.update_project(project_name, _mutate)
            return {"success": True, "message": _t(keys["deleted"], name=entry_name)}

        return await asyncio.to_thread(_sync)
    except KeyError:
        raise HTTPException(status_code=404, detail=_t(keys["not_found"], name=entry_name))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(exc))


async def add_character(project_name: str, req: dict[str, Any], _user: Any, _t: Any):
    return await _add_asset("character", project_name, req, _t)


async def update_character(project_name: str, entry_name: str, req: dict[str, Any], _user: Any, _t: Any):
    return await _update_asset("character", project_name, entry_name, req, _t)


async def delete_character(project_name: str, entry_name: str, _user: Any, _t: Any):
    return await _delete_asset("character", project_name, entry_name, _t)


async def add_scene(project_name: str, req: dict[str, Any], _user: Any, _t: Any):
    return await _add_asset("scene", project_name, req, _t)


async def update_scene(project_name: str, entry_name: str, req: dict[str, Any], _user: Any, _t: Any):
    return await _update_asset("scene", project_name, entry_name, req, _t)


async def delete_scene(project_name: str, entry_name: str, _user: Any, _t: Any):
    return await _delete_asset("scene", project_name, entry_name, _t)


async def add_prop(project_name: str, req: dict[str, Any], _user: Any, _t: Any):
    return await _add_asset("prop", project_name, req, _t)


async def update_prop(project_name: str, entry_name: str, req: dict[str, Any], _user: Any, _t: Any):
    return await _update_asset("prop", project_name, entry_name, req, _t)


async def delete_prop(project_name: str, entry_name: str, _user: Any, _t: Any):
    return await _delete_asset("prop", project_name, entry_name, _t)

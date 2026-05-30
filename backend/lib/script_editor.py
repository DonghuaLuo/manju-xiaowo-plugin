"""剧本编辑核心纯函数。

MCP patch_script 工具通过这里按分镜 id 修改剧本 dict；文件锁、写盘和结构校验仍由
ProjectManager.locked_script / _write_script_unlocked 统一负责。
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

logger = logging.getLogger(__name__)


class ScriptEditError(ValueError):
    """剧本编辑操作非法。"""


_KIND_ID_FIELD = {"video_units": "unit_id", "scenes": "scene_id", "segments": "segment_id"}


def resolve_kind(script: dict[str, Any]) -> str:
    """判别剧本当前的分镜数组种类。"""
    if "video_units" in script and "segments" not in script and "scenes" not in script:
        return "video_units"
    content_mode = script.get("content_mode")
    if content_mode == "drama":
        return "scenes"
    if content_mode == "narration":
        if "segments" not in script and "scenes" in script:
            return "scenes"
        return "segments"
    if "scenes" in script and "segments" not in script:
        return "scenes"
    return "segments"


def resolve_items(script: dict[str, Any]) -> tuple[list[dict[str, Any]], str, str]:
    """返回当前剧本分镜数组、id 字段名和数组种类。"""
    kind = resolve_kind(script)
    if kind not in script:
        return [], _KIND_ID_FIELD[kind], kind
    items = script[kind]
    if not isinstance(items, list):
        raise ScriptEditError(f"{kind} 必须是列表，当前为 {type(items).__name__}")
    return items, _KIND_ID_FIELD[kind], kind


def _find_index(items: list[dict[str, Any]], id_field: str, item_id: str) -> int:
    for idx, item in enumerate(items):
        if isinstance(item, dict) and str(item.get(id_field)) == str(item_id):
            return idx
    raise ScriptEditError(f"未找到 id={item_id!r} 的分镜（{id_field}）")


def _existing_ids(items: list[dict[str, Any]], id_field: str) -> set[str]:
    return {str(item.get(id_field)) for item in items if isinstance(item, dict)}


def _next_suffixed_id(base: str, taken: set[str]) -> str:
    stem = base.split("_")[0]
    k = 1
    while f"{stem}_{k}" in taken:
        k += 1
    return f"{stem}_{k}"


def _set_nested(obj: dict[str, Any], field_path: str, value: Any) -> None:
    parts = field_path.split(".")
    if not parts or any(not p for p in parts):
        raise ScriptEditError(f"非法字段路径: {field_path!r}")
    if parts[0] == "generated_assets":
        raise ScriptEditError("patch_episode_script 不可改 generated_assets；资产生成/重生是独立动作")
    if parts[0] in {"segment_id", "scene_id", "unit_id"}:
        raise ScriptEditError(f"patch_episode_script 不可改分镜 id 字段 ({parts[0]})")

    cur: Any = obj
    for p in parts[:-1]:
        if not isinstance(cur, dict):
            raise ScriptEditError(f"父节点非对象 (类型 {type(cur).__name__}): {field_path!r}")
        if p not in cur:
            raise ScriptEditError(f"字段路径不存在: {field_path!r}")
        if not isinstance(cur[p], dict):
            raise ScriptEditError(f"父节点非对象 (键 {p!r} 类型为 {type(cur[p]).__name__}): {field_path!r}")
        cur = cur[p]
    if not isinstance(cur, dict):
        raise ScriptEditError(f"父节点非对象: {field_path!r}")
    cur[parts[-1]] = value


def patch_field(script: dict[str, Any], item_id: str, field_path: str, value: Any) -> dict[str, Any]:
    items, id_field, _kind = resolve_items(script)
    idx = _find_index(items, id_field, item_id)
    _set_nested(items[idx], field_path, value)
    return script


def insert_segment(script: dict[str, Any], after_id: str, new_item: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(new_item, dict):
        raise ScriptEditError("new_item 必须是对象")
    items, id_field, _kind = resolve_items(script)
    idx = _find_index(items, id_field, after_id)
    item = deepcopy(new_item)
    item[id_field] = _next_suffixed_id(str(after_id), _existing_ids(items, id_field))
    item["generated_assets"] = {}
    items.insert(idx + 1, item)
    return script


def remove_segment(script: dict[str, Any], item_id: str) -> dict[str, Any]:
    items, id_field, _kind = resolve_items(script)
    idx = _find_index(items, id_field, item_id)
    items.pop(idx)
    return script


def split_segment(script: dict[str, Any], item_id: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(parts, list) or len(parts) < 2:
        raise ScriptEditError("split 至少需要 2 个部分")
    if any(not isinstance(p, dict) for p in parts):
        raise ScriptEditError("split 的每个部分必须是对象")
    items, id_field, _kind = resolve_items(script)
    idx = _find_index(items, id_field, item_id)
    anchor_assets = items[idx].get("generated_assets")

    taken = _existing_ids(items, id_field)
    new_parts: list[dict[str, Any]] = []
    for offset, raw in enumerate(parts):
        part = deepcopy(raw)
        if offset == 0:
            part[id_field] = str(item_id)
            if isinstance(anchor_assets, dict):
                part["generated_assets"] = deepcopy(anchor_assets)
            else:
                if anchor_assets is not None:
                    logger.warning(
                        "split_segment: 锚点 %r generated_assets 形态异常(%s),退化为空 dict",
                        item_id,
                        type(anchor_assets).__name__,
                    )
                part["generated_assets"] = {}
        else:
            new_id = _next_suffixed_id(str(item_id), taken)
            taken.add(new_id)
            part[id_field] = new_id
            part["generated_assets"] = {}
        new_parts.append(part)

    items[idx : idx + 1] = new_parts
    return script

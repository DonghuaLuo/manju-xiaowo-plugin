"""SDK MCP tools for editing an episode script by id.

Agent 对 ``scripts/*.json`` 的修改应收敛到这组 MCP 工具：通用字段编辑
``patch_episode_script``，以及结构性增删拆 ``insert_segment`` /
``remove_segment`` / ``split_segment``。每个工具都在
``ProjectManager.locked_script`` 的读-改-写上下文里调用 ``lib.script_editor``
纯函数核心，退出时继续走写盘统一入口，继承文件锁、结构校验、metadata 重算和
filename/episode 一致性检查。
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from lib.script_editor import insert_segment, patch_field, remove_segment, resolve_items, split_segment
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error, validate_script_filename


def _item_ids(script: dict[str, Any]) -> list[str]:
    items, id_field, _kind = resolve_items(script)
    return [str(it.get(id_field)) for it in items if isinstance(it, dict)]


def patch_episode_script_tool(ctx: ToolContext):
    @tool(
        "patch_episode_script",
        "按分镜 id（segment_id/scene_id/unit_id）编辑剧本的一个字段，支持嵌套路径"
        "（如 image_prompt.scene、duration_seconds、video_prompt.action、shot_tier）。三种内容/生成模式通用。"
        "纯字段 setter，不触碰已生成资产；改 prompt 后如需重生图片/视频，应另行触发生成动作。"
        "叶子字段不存在会被创建（允许补 LLM 漏写的 optional 字段）；"
        "不可改 generated_assets 或分镜 id，拼写错误会在写盘结构校验阶段拒绝。",
        {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "剧本文件名（纯文件名，如 episode_1.json）"},
                "id": {"type": "string", "description": "分镜 id（如 E1S03 / E1U02）"},
                "field": {
                    "type": "string",
                    "description": "字段名或点分嵌套路径；不可改 generated_assets 或 segment_id/scene_id/unit_id",
                },
                "value": {"description": "新值（类型随字段而定）"},
            },
            "required": ["script", "id", "field", "value"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            script_filename = validate_script_filename(args["script"])
            item_id = str(args["id"])
            field = str(args["field"])
            value = args["value"]
            with ctx.pm.locked_script(ctx.project_name, script_filename) as script:
                patch_field(script, item_id, field, value)
            return {"content": [{"type": "text", "text": f"✅ 已更新 {item_id} 的 {field}"}]}
        except Exception as exc:  # noqa: BLE001
            return tool_error("patch_episode_script", exc)

    return _handler


def insert_segment_tool(ctx: ToolContext):
    @tool(
        "insert_segment",
        "在指定分镜 id 之后插入一个新分镜（segment/scene/unit）。新分镜由你提供完整内容，"
        "其 id 由系统分配（派生自锚点 id 的稳定后缀，不重排其余分镜），"
        "generated_assets 清空，资产待生成。reference 模式插入的是 video_unit。",
        {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "剧本文件名（纯文件名）"},
                "after_id": {"type": "string", "description": "在此分镜 id 之后插入"},
                "item": {"type": "object", "description": "新分镜完整内容对象；id 与 generated_assets 由系统处理"},
            },
            "required": ["script", "after_id", "item"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            script_filename = validate_script_filename(args["script"])
            after_id = str(args["after_id"])
            item = args["item"]
            with ctx.pm.locked_script(ctx.project_name, script_filename) as script:
                insert_segment(script, after_id, item)
                new_ids = _item_ids(script)
            return {"content": [{"type": "text", "text": f"✅ 已在 {after_id} 之后插入新分镜\n当前分镜顺序: {new_ids}"}]}
        except Exception as exc:  # noqa: BLE001
            return tool_error("insert_segment", exc)

    return _handler


def remove_segment_tool(ctx: ToolContext):
    @tool(
        "remove_segment",
        "按 id 删除一个分镜（segment/scene/unit）。其余分镜 id 不变、不重排，"
        "被删分镜的已生成资产随之失效。reference 模式删除的是 video_unit。",
        {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "剧本文件名（纯文件名）"},
                "id": {"type": "string", "description": "要删除的分镜 id"},
            },
            "required": ["script", "id"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            script_filename = validate_script_filename(args["script"])
            item_id = str(args["id"])
            with ctx.pm.locked_script(ctx.project_name, script_filename) as script:
                remove_segment(script, item_id)
                new_ids = _item_ids(script)
            return {"content": [{"type": "text", "text": f"✅ 已删除分镜 {item_id}\n当前分镜顺序: {new_ids}"}]}
        except Exception as exc:  # noqa: BLE001
            return tool_error("remove_segment", exc)

    return _handler


def split_segment_tool(ctx: ToolContext):
    @tool(
        "split_segment",
        "把一个分镜按你提供的各部分内容拆成多个（至少 2 份）。首份保留原 id，"
        "并沿用原分镜 generated_assets（锚点延续）；其余部分分配稳定派生 id，"
        "generated_assets 清空，需重新生成。只想微调原分镜内容时请用 patch_episode_script。"
        "reference 模式下各 unit 的 duration_seconds 仍需等于 shots 总时长。",
        {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "剧本文件名（纯文件名）"},
                "id": {"type": "string", "description": "要拆分的分镜 id"},
                "parts": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "拆分后各部分完整内容对象；至少 2 个，id 与 generated_assets 由系统处理",
                },
            },
            "required": ["script", "id", "parts"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            script_filename = validate_script_filename(args["script"])
            item_id = str(args["id"])
            parts = args["parts"]
            with ctx.pm.locked_script(ctx.project_name, script_filename) as script:
                split_segment(script, item_id, parts)
                new_ids = _item_ids(script)
            return {"content": [{"type": "text", "text": f"✅ 已把分镜 {item_id} 拆为 {len(parts)} 份\n当前分镜顺序: {new_ids}"}]}
        except Exception as exc:  # noqa: BLE001
            return tool_error("split_segment", exc)

    return _handler


__all__ = [
    "patch_episode_script_tool",
    "insert_segment_tool",
    "remove_segment_tool",
    "split_segment_tool",
]

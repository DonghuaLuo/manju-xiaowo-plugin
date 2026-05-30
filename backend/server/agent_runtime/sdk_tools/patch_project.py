"""SDK MCP tool for editing project.json assets or whitelisted settings.

Agent 对 ``project.json`` 的角色/场景/道具写入应通过 ``patch_project``：按
table（characters/scenes/props）+ name upsert，不存在则新增，存在则合并可编辑字段；
同时支持顶层 settings 白名单字段写入。所有修改都经 ``ProjectManager`` 的文件锁和结构
校验，非法数据不落盘。
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from server.agent_runtime.sdk_tools._context import ToolContext, tool_error

_TABLES = ("characters", "scenes", "props")
_SETTINGS_WHITELIST = ("episode_target_units", "source_language")
_SOURCE_LANGUAGE_VALUES = ("zh", "en", "vi")


def patch_project_tool(ctx: ToolContext):
    @tool(
        "patch_project",
        "新增或修改 project.json：（1）资产 upsert，传 table+entries，按 table+name 新增或合并字段；"
        "（2）顶层 settings 写入，传 settings，白名单字段 episode_target_units/source_language，"
        "值为 null 时清除。两种形态二选一，同时给出或都不给会被拒。"
        "结构非法时不落盘，并返回可读错误。",
        {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "enum": list(_TABLES),
                    "description": "资产 upsert 分支：characters / scenes / props",
                },
                "entries": {
                    "type": "object",
                    "description": "资产 upsert 分支：{ 名称: { description, voice_style 等字段 } }，至少一条",
                },
                "settings": {
                    "type": "object",
                    "description": (
                        "settings 写入分支：key 必须在白名单 "
                        f"{list(_SETTINGS_WHITELIST)} 内，值为 null 时清除该字段"
                    ),
                },
            },
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            has_upsert = "table" in args or "entries" in args
            has_settings = "settings" in args
            if has_upsert and has_settings:
                raise ValueError("table/entries 与 settings 二选一,不能同时给出")
            if not has_upsert and not has_settings:
                raise ValueError("必须提供 table+entries 或 settings")

            if has_settings:
                settings = args["settings"]
                if not isinstance(settings, dict) or not settings:
                    raise ValueError("settings 必须是非空对象")
                updated = _apply_settings(ctx, settings)
                return {"content": [{"type": "text", "text": _format_settings_result(updated)}]}

            if "table" not in args or "entries" not in args:
                raise ValueError("资产 upsert 分支必须同时提供 table 和 entries")
            table = str(args["table"])
            entries = args["entries"]
            if not isinstance(entries, dict) or not entries:
                raise ValueError("entries 必须是非空对象")
            result = ctx.pm.upsert_assets(ctx.project_name, table, entries)
            return {"content": [{"type": "text", "text": _format_upsert_result(table, result)}]}
        except Exception as exc:  # noqa: BLE001
            return tool_error("patch_project", exc)

    return _handler


def _apply_settings(ctx: ToolContext, settings: dict[str, Any]) -> dict[str, tuple[str, Any]]:
    for key, value in settings.items():
        if key not in _SETTINGS_WHITELIST:
            raise ValueError(f"settings 字段 {key!r} 不在白名单 {list(_SETTINGS_WHITELIST)} 内")
        _validate_setting_value(key, value)

    diagnostics: dict[str, tuple[str, Any]] = {}

    def _mutate(project: dict[str, Any]) -> None:
        for key, value in settings.items():
            current = project.get(key)
            if value is None:
                if key in project:
                    del project[key]
                    diagnostics[key] = ("clear", None)
                else:
                    diagnostics[key] = ("noop", None)
            elif current == value:
                diagnostics[key] = ("noop", current)
            else:
                project[key] = value
                diagnostics[key] = ("set", value)

    ctx.pm.update_project(ctx.project_name, _mutate)
    return diagnostics


def _validate_setting_value(key: str, value: Any) -> None:
    if key == "episode_target_units":
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"episode_target_units 必须是正整数或 null,收到 {value!r}")
        return
    if key == "source_language":
        if value is None:
            return
        if not isinstance(value, str) or value not in _SOURCE_LANGUAGE_VALUES:
            raise ValueError(f"source_language 必须是 {list(_SOURCE_LANGUAGE_VALUES)} 之一或 null,收到 {value!r}")
        return
    raise ValueError(f"settings 字段 {key!r} 缺类型校验")


def _format_settings_result(updated: dict[str, tuple[str, Any]]) -> str:
    set_items = [(k, v) for k, (op, v) in updated.items() if op == "set"]
    clear_items = [k for k, (op, _v) in updated.items() if op == "clear"]
    noop_items = [k for k, (op, _v) in updated.items() if op == "noop"]
    parts: list[str] = []
    if set_items:
        parts.append("已更新 " + ", ".join(f"{k}={v}" for k, v in set_items))
    if clear_items:
        parts.append("已清除 " + ", ".join(clear_items))
    if noop_items:
        parts.append("无变更 " + ", ".join(noop_items))
    icon = "ℹ️" if (not set_items and not clear_items) else "✅"
    return f"{icon} settings: {'; '.join(parts) if parts else '无变更'}"


def _format_upsert_result(table: str, result: dict[str, Any]) -> str:
    added: list[str] = sorted(result.get("added") or [])
    merged: list[str] = sorted(result.get("merged") or [])
    noop: list[str] = sorted(result.get("noop") or [])
    dropped_fields: dict[str, list[str]] = result.get("dropped_fields") or {}
    dropped_legacy: dict[str, list[str]] = result.get("dropped_legacy") or {}

    summary_parts: list[str] = []
    if added:
        summary_parts.append(f"新增 {len(added)} 个: {', '.join(added)}")
    if merged:
        summary_parts.append(f"合并改字段 {len(merged)} 个: {', '.join(merged)}")
    if noop:
        summary_parts.append(f"无可写字段已跳过 {len(noop)} 个: {', '.join(noop)}")
    summary = "; ".join(summary_parts) if summary_parts else "无变更（所有条目均无可写字段）"
    icon = "ℹ️" if (not added and not merged) else "✅"
    lines = [f"{icon} {table}: {summary}"]

    if dropped_fields:
        detail = "; ".join(f"{name}: {', '.join(fields)}" for name, fields in sorted(dropped_fields.items()))
        lines.append(f"⚠️ 以下字段不在 agent 可编辑范围,已忽略 → {detail}")
        lines.append("说明: reference_image 与 *_sheet 由用户上传或资产生成流水线管理。")
    if dropped_legacy:
        detail = "; ".join(f"{name}: {', '.join(fields)}" for name, fields in sorted(dropped_legacy.items()))
        lines.append(f"ℹ️ 以下历史字段已废弃,本次未持久化 → {detail}")
    return "\n".join(lines)


__all__ = ["patch_project_tool"]

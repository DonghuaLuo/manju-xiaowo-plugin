"""SDK MCP tool for grid storyboard generation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import tool

from lib.generation_queue_client import TaskSpec, enqueue_task_only, wait_for_task
from lib.grid.layout import (
    calculate_grid_layout,
    plan_grid_chunk_sizes,
    resolve_storyboard_aspect_ratio,
)
from lib.grid.models import GridGeneration
from lib.grid.prompt_builder import build_grid_prompt
from lib.grid_manager import GridManager
from lib.project_manager import ProjectManager
from lib.storyboard_sequence import get_storyboard_items, group_scenes_by_segment_break
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error, validate_script_filename


@dataclass(frozen=True)
class _PendingGeneration:
    kind: str
    resource_id: str
    task_id: str
    scene_ids: list[str]


def _list_groups(project: dict, script: dict, scene_ids: list[str] | None = None) -> list[str]:
    """List grid groups, optionally filtered to groups containing ``scene_ids``.

    Empty list (``[]``) and ``None`` carry different intents: ``None`` means
    "no filter, list all groups"; ``[]`` means "filter to zero groups"
    (explicit zero selection). Use ``is not None`` to keep them distinct.
    """
    items, id_field, _, _, _ = get_storyboard_items(script)
    aspect_ratio = resolve_storyboard_aspect_ratio(project)
    groups = group_scenes_by_segment_break(items, id_field)
    if scene_ids is not None:
        wanted = set(scene_ids)
        groups = [g for g in groups if any(item[id_field] in wanted for item in g)]
    lines = [f"共 {len(groups)} 个分组："]
    for i, group in enumerate(groups):
        ids = [item[id_field] for item in group]
        if len(ids) == 1:
            status = "普通分镜（单镜头）"
        else:
            parts = []
            for size in plan_grid_chunk_sizes(len(ids)):
                layout = calculate_grid_layout(size, aspect_ratio)
                if layout:
                    parts.append(f"{layout.grid_size} ({layout.rows}×{layout.cols})")
            status = " + ".join(parts) if parts else "无宫格批次"
        lines.append(f"  组 {i + 1}: {ids[0]}..{ids[-1]} ({len(ids)} 场景) → {status}")
    return lines


def generate_grid_tool(ctx: ToolContext):
    @tool(
        "generate_grid",
        "为 grid 模式项目生成宫格分镜图（按 segment_break 分组）。"
        "list_only=true 时只列出分组不执行生成。scene_ids 过滤包含这些场景的分组。",
        {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "剧本文件名（如 episode_1.json），必须是纯文件名，禁止任何路径分隔符",
                },
                "scene_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "只生成包含这些场景的分组",
                },
                "list_only": {"type": "boolean", "description": "仅列出分组信息，不入队"},
            },
            "required": ["script"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            script_filename = validate_script_filename(args["script"])
            scene_ids = args.get("scene_ids")
            list_only = bool(args.get("list_only"))

            project = ctx.pm.load_project(ctx.project_name)
            script = ctx.pm.load_script(ctx.project_name, script_filename)

            # ``list_only`` 是 ``generate_grid`` 工具的预览模式，与生成分支一样
            # 必须先过 generation_mode 校验——否则非 grid 项目靠 ``list_only=true``
            # 就能拿到成功响应，调用方会误以为该工具适用于当前项目。
            if project.get("generation_mode") != "grid":
                return {
                    "content": [{"type": "text", "text": "⚠️  项目未启用宫格模式（generation_mode != 'grid'）"}],
                    "is_error": True,
                }

            if list_only:
                return {"content": [{"type": "text", "text": "\n".join(_list_groups(project, script, scene_ids))}]}

            episode = ProjectManager.resolve_episode_from_script(script, script_filename)
            project_path = ctx.project_path
            items, id_field, _, _, _ = get_storyboard_items(script)
            aspect_ratio = resolve_storyboard_aspect_ratio(project)
            style = project.get("style", "")
            groups = group_scenes_by_segment_break(items, id_field)

            # ``scene_ids is not None`` 区分"不传 = 不过滤"和"传 [] = 过滤到 0
            # 个"——后者是显式空选择，按 ``not groups`` 分支当错误返回。同样
            # 处理 list_only 预览（见 ``_list_groups``）保持一致。
            if scene_ids is not None:
                wanted = set(scene_ids)
                groups = [g for g in groups if any(item[id_field] in wanted for item in g)]

            if not groups:
                # 显式传了 ``scene_ids`` 但全部不命中（或传了 []）→ 错误；
                # 不传 ``scene_ids`` 但脚本本身没有 segment_break 分组也走
                # 这条路（罕见），按信息文案不带 is_error。
                return {
                    "content": [{"type": "text", "text": "没有匹配的场景组"}],
                    "is_error": scene_ids is not None,
                }

            gm = GridManager(project_path)
            pending: list[_PendingGeneration] = []
            enqueue_failures: list[tuple[str, str, list[str], str]] = []

            for group in groups:
                group_ids = [item[id_field] for item in group]
                if len(group_ids) == 1:
                    try:
                        spec = TaskSpec.from_request(
                            task_type="storyboard",
                            media_type="image",
                            resource_id=str(group_ids[0]),
                            prompt=group[0].get("image_prompt", ""),
                            script_file=script_filename,
                            source="skill",
                            extra_payload={"quality": "draft"},
                        )
                        enqueue_result = await enqueue_task_only(
                            project_name=ctx.project_name,
                            task_type=spec.task_type,
                            media_type=spec.media_type,
                            resource_id=spec.resource_id,
                            payload=spec.payload,
                            script_file=spec.script_file,
                            source=spec.source,
                        )
                    except Exception as exc:  # noqa: BLE001
                        enqueue_failures.append(("storyboard", str(group_ids[0]), group_ids, str(exc)))
                        continue
                    pending.append(
                        _PendingGeneration(
                            kind="storyboard",
                            resource_id=spec.resource_id,
                            task_id=enqueue_result["task_id"],
                            scene_ids=group_ids,
                        )
                    )
                    continue

                offset = 0
                for size in plan_grid_chunk_sizes(len(group_ids)):
                    chunk = group[offset : offset + size]
                    offset += size
                    chunk_ids = [item[id_field] for item in chunk]
                    layout = calculate_grid_layout(len(chunk_ids), aspect_ratio)
                    if layout is None:
                        continue

                    prompt = build_grid_prompt(
                        scenes=chunk,
                        id_field=id_field,
                        rows=layout.rows,
                        cols=layout.cols,
                        style=style,
                        aspect_ratio=aspect_ratio,
                        grid_aspect_ratio=layout.grid_aspect_ratio,
                    )

                    grid = GridGeneration.create(
                        episode=episode,
                        script_file=script_filename,
                        scene_ids=chunk_ids,
                        rows=layout.rows,
                        cols=layout.cols,
                        grid_size=layout.grid_size,
                        provider="",
                        model="",
                        prompt=prompt,
                    )
                    # 先 save 后 enqueue 给 worker 提供可读的 grid 文件；入队失败时
                    # 用 ``gm.delete`` 回收孤儿记录，并把该组并入 failures——前面已
                    # 入队成功的分组继续跑，调用方不会被一组失败导致全量重试。
                    gm.save(grid)
                    try:
                        enqueue_result = await enqueue_task_only(
                            project_name=ctx.project_name,
                            task_type="grid",
                            media_type="image",
                            resource_id=grid.id,
                            payload={
                                "prompt": prompt,
                                "script_file": script_filename,
                                "scene_ids": chunk_ids,
                                "grid_size": layout.grid_size,
                                "rows": layout.rows,
                                "cols": layout.cols,
                                "grid_aspect_ratio": layout.grid_aspect_ratio,
                                "video_aspect_ratio": aspect_ratio,
                                "quality": "final",
                            },
                            script_file=script_filename,
                            source="skill",
                        )
                    except Exception as exc:  # noqa: BLE001
                        gm.delete(grid.id)
                        enqueue_failures.append(("grid", grid.id, chunk_ids, str(exc)))
                        continue
                    pending.append(
                        _PendingGeneration(
                            kind="grid",
                            resource_id=grid.id,
                            task_id=enqueue_result["task_id"],
                            scene_ids=chunk_ids,
                        )
                    )

            details: list[str] = []
            for kind, resource_id, group_ids, err in enqueue_failures:
                label = "普通分镜" if kind == "storyboard" else "宫格"
                range_text = group_ids[0] if len(group_ids) == 1 else f"{group_ids[0]}..{group_ids[-1]}"
                details.append(f"  ✗ {resource_id}（{label}: {range_text}）入队失败: {err}")

            if not pending:
                final_line = "没有宫格任务成功入队" if enqueue_failures else "没有需要生成的宫格组"
                msg = "\n".join([*details, final_line])
                return {
                    "content": [{"type": "text", "text": msg}],
                    "is_error": bool(enqueue_failures),
                }

            successes: list[str] = []
            failures: list[tuple[str, str]] = []
            # Wait for all queued image tasks concurrently — image worker channel can run
            # multiple in parallel, so serial wait_for_task would mask that throughput.
            results = await asyncio.gather(
                *(wait_for_task(item.task_id) for item in pending),
                return_exceptions=True,
            )
            for item, result in zip(pending, results, strict=True):
                if isinstance(result, BaseException):
                    failures.append((item.resource_id, str(result)))
                    details.append(f"  ✗ {item.resource_id}: {result}")
                    continue
                if result.get("status") == "succeeded":
                    successes.append(item.resource_id)
                    label = "普通分镜" if item.kind == "storyboard" else "宫格"
                    range_text = (
                        item.scene_ids[0] if len(item.scene_ids) == 1 else f"{item.scene_ids[0]}..{item.scene_ids[-1]}"
                    )
                    details.append(f"  ✓ {item.resource_id}（{label}: {range_text}）")
                else:
                    err = result.get("error_message") or "unknown"
                    failures.append((item.resource_id, err))
                    details.append(f"  ✗ {item.resource_id}: {err}")

            total_failed = len(failures) + len(enqueue_failures)
            header = f"generate_grid summary: {len(successes)} succeeded, {total_failed} failed"
            return {
                "content": [{"type": "text", "text": "\n".join([header, *details])}],
                "is_error": bool(failures) or bool(enqueue_failures),
            }
        except Exception as exc:  # noqa: BLE001
            return tool_error("generate_grid", exc)

    return _handler


__all__ = ["generate_grid_tool"]

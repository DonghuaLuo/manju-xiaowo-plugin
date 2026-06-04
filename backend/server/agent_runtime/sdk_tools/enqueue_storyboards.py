"""SDK MCP tool for storyboard image generation (narration / drama)."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import tool

from lib.generation_queue_client import (
    BatchTaskResult,
    TaskSpec,
    batch_enqueue_and_wait,
)
from lib.prompt_utils import image_prompt_to_yaml, is_structured_image_prompt
from lib.storyboard_sequence import (
    StoryboardTaskPlan,
    build_storyboard_dependency_plan,
    get_storyboard_items,
)
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error, validate_script_filename
from server.agent_runtime.sdk_tools._generation_quality import (
    QUALITY_SCHEMA,
    is_current_refined,
    normalize_quality,
    route_summary,
)

StoryboardSelectionMode = Literal["missing", "selected", "current_unrefined", "current_all"]

SELECTION_MODE_SCHEMA: dict[str, Any] = {
    "type": "string",
    "enum": ["missing", "selected", "current_unrefined", "current_all"],
    "description": (
        "分镜选择范围；missing=只生成缺失分镜（默认，快速版批量补图），"
        "selected=仅处理 segment_ids 指定项，current_unrefined=只精修当前未精修的已有分镜，"
        "current_all=当前已有分镜全量重精修（包括已精修项）。历史版本不参与判断。"
    ),
}


class _FailureRecorder:
    """Records storyboard failures to ``storyboards/generation_failures.json``."""

    def __init__(self, output_dir: Path) -> None:
        self.output_path = output_dir / "generation_failures.json"
        self.failures: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, resource_id: str, resource_type: str, error: str, attempts: int = 3) -> None:
        """Append a failure entry. ``resource_type`` is ``segment`` (narration)
        or ``scene`` (drama) — driven by the script's ``id_field``."""
        with self._lock:
            self.failures.append(
                {
                    "resource_id": resource_id,
                    "type": resource_type,
                    "error": error,
                    "attempts": attempts,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

    def save(self) -> None:
        if not self.failures:
            return
        with self._lock:
            data = {
                "generated_at": datetime.now(UTC).isoformat(),
                "total_failures": len(self.failures),
                "failures": self.failures,
            }
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_prompt(
    segment: dict[str, Any],
    style: str,
    style_description: str,
    id_field: str,
) -> str:
    image_prompt = segment.get("image_prompt", "")
    if not image_prompt:
        raise ValueError(f"片段/场景 {segment[id_field]} 缺少 image_prompt 字段")

    style_parts: list[str] = []
    if style:
        style_parts.append(f"Style: {style}")
    if style_description:
        style_parts.append(f"Visual style: {style_description}")
    style_prefix = "\n".join(style_parts) + "\n\n" if style_parts else ""

    if is_structured_image_prompt(image_prompt):
        yaml_prompt = image_prompt_to_yaml(image_prompt, style)
        return f"{style_prefix}{yaml_prompt}"
    return f"{style_prefix}{image_prompt}"


def _has_storyboard_source(project_dir: Path, item: dict[str, Any]) -> bool:
    rel = (item.get("generated_assets") or {}).get("storyboard_image")
    if not isinstance(rel, str) or not rel.strip():
        return False
    try:
        project_root = project_dir.resolve()
        path = (project_dir / rel).resolve()
        if not path.is_relative_to(project_root):
            return False
    except Exception:
        return False
    return path.is_file()


def _normalize_selection_mode(args: dict[str, Any], segment_ids: list[str] | None) -> StoryboardSelectionMode:
    raw_mode = args.get("selection_mode")
    if raw_mode is None:
        return "selected" if segment_ids is not None else "missing"
    if not isinstance(raw_mode, str):
        raise TypeError("selection_mode 必须是字符串")
    value = raw_mode.strip()
    if value in {"missing", "selected", "current_unrefined", "current_all"}:
        return value  # type: ignore[return-value]
    raise ValueError("selection_mode 必须是 missing、selected、current_unrefined 或 current_all")


def _resolve_selection(
    *,
    items: list[dict[str, Any]],
    id_field: str,
    segment_ids: list[str] | None,
    selection_mode: StoryboardSelectionMode,
    quality: str,
    quality_explicit: bool,
    selection_mode_explicit: bool,
    project_dir: Path,
) -> list[dict[str, Any]]:
    if quality == "final" and not (quality_explicit and selection_mode_explicit):
        raise ValueError(
            "精修分镜必须显式传 quality='final'，并显式传 "
            "selection_mode='selected'、selection_mode='current_unrefined' 或 selection_mode='current_all'"
        )
    if quality == "final" and selection_mode == "missing":
        raise ValueError("精修分镜不能使用 selection_mode='missing'；请改用 selected、current_unrefined 或 current_all")
    if selection_mode in {"current_unrefined", "current_all"} and quality != "final":
        raise ValueError(f"selection_mode='{selection_mode}' 只用于精修；请同时传 quality='final'")
    if selection_mode != "selected" and segment_ids is not None:
        raise ValueError("只有 selection_mode='selected' 时才允许传 segment_ids")

    if selection_mode == "missing":
        return [item for item in items if not _has_storyboard_source(project_dir, item)]

    if selection_mode == "selected":
        if segment_ids is None or len(segment_ids) == 0:
            raise ValueError("selection_mode='selected' 必须传非空 segment_ids")
        wanted = {str(s) for s in segment_ids}
        existing = {str(item.get(id_field)) for item in items}
        missing_ids = [str(item_id) for item_id in segment_ids if str(item_id) not in existing]
        if missing_ids:
            raise ValueError(f"以下片段/场景 ID 不存在：{missing_ids}")
        selected = [item for item in items if str(item.get(id_field)) in wanted]
        if quality == "final":
            missing_source = [
                str(item.get(id_field)) for item in selected if not _has_storyboard_source(project_dir, item)
            ]
            if missing_source:
                raise ValueError(f"精修要求已有分镜文件；以下 ID 缺少可精修源图：{missing_source}")
        return selected

    existing = [item for item in items if _has_storyboard_source(project_dir, item)]
    if selection_mode == "current_all":
        return existing
    return [
        item
        for item in existing
        if not is_current_refined(project_dir, "storyboards", str(item.get(id_field) or ""))
    ]


def _missing_requested_ids(items: list[dict[str, Any]], id_field: str, segment_ids: list[str] | None) -> list[str]:
    if segment_ids is None:
        return []
    existing = {str(item.get(id_field)) for item in items}
    return [str(item_id) for item_id in segment_ids if str(item_id) not in existing]


def _selection_empty_text(
    *,
    selection_mode: StoryboardSelectionMode,
    segment_ids: list[str] | None,
    missing_ids: list[str],
) -> str:
    if selection_mode == "selected":
        return f"❌ 没有找到匹配的片段/场景：segment_ids={segment_ids}" if missing_ids else "❌ 没有选中任何片段/场景"
    if selection_mode == "current_unrefined":
        return "✨ 当前没有未精修的已有分镜图"
    if selection_mode == "current_all":
        return "✨ 没有可精修的当前分镜图；请先生成快速版分镜"
    return "✨ 所有片段的分镜图都已生成"


def _build_specs(
    plans: list[StoryboardTaskPlan],
    items_by_id: dict[str, dict[str, Any]],
    style: str,
    style_description: str,
    id_field: str,
    script_filename: str,
    quality: str = "draft",
) -> list[TaskSpec]:
    specs: list[TaskSpec] = []
    for plan in plans:
        item = items_by_id[plan.resource_id]
        prompt = _build_prompt(item, style, style_description, id_field)
        specs.append(
            TaskSpec.from_request(
                task_type="storyboard",
                media_type="image",
                resource_id=plan.resource_id,
                prompt=prompt,
                script_file=script_filename,
                extra_payload={"quality": quality},
                dependency_resource_id=plan.dependency_resource_id,
                dependency_group=plan.dependency_group,
                dependency_index=plan.dependency_index,
            )
        )
    return specs


def generate_storyboards_tool(ctx: ToolContext):
    @tool(
        "generate_storyboards",
        "为 narration/drama 模式剧本生成分镜图。"
        "script 为剧本文件名（如 episode_1.json）；默认只生成缺失分镜。"
        "精修必须显式传 quality='final' 与明确的 selection_mode。",
        {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "剧本文件名（如 episode_1.json），必须是纯文件名，禁止任何路径分隔符",
                },
                "segment_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "片段或场景 ID 列表；仅 selection_mode='selected' 时允许传",
                },
                "selection_mode": {
                    **SELECTION_MODE_SCHEMA,
                },
                "quality": {
                    **QUALITY_SCHEMA,
                    "description": "生成质量档位；默认 draft（分镜快速版）。精修必须显式传 final，并配合 selection_mode 指定精修范围。",
                },
            },
            "required": ["script"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            script_filename = validate_script_filename(args["script"])
            segment_ids = args.get("segment_ids")
            if segment_ids is not None and not isinstance(segment_ids, list):
                raise TypeError("segment_ids 必须是字符串数组")
            quality = normalize_quality(args, "draft")
            selection_mode = _normalize_selection_mode(args, segment_ids)

            script = ctx.pm.load_script(ctx.project_name, script_filename)
            project_dir = ctx.project_path

            try:
                project_data = ctx.pm.load_project(ctx.project_name)
            except FileNotFoundError:
                # project.json 缺失时允许降级到空 dict（style 走默认值）；
                # JSON 损坏 / 权限错误等其他异常应该让外层 tool_error 暴露出来，
                # 否则会用空 style 静默继续入队，丢掉了配置。
                project_data = {}

            items, id_field, _char_field, _scene_field, _prop_field = get_storyboard_items(script)
            selected = _resolve_selection(
                items=items,
                id_field=id_field,
                segment_ids=segment_ids,
                selection_mode=selection_mode,
                quality=quality,
                quality_explicit="quality" in args,
                selection_mode_explicit="selection_mode" in args,
                project_dir=project_dir,
            )
            if not selected:
                missing_ids = _missing_requested_ids(items, id_field, segment_ids)
                is_error = selection_mode == "selected"
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": _selection_empty_text(
                                selection_mode=selection_mode,
                                segment_ids=segment_ids,
                                missing_ids=missing_ids,
                            ),
                        }
                    ],
                    "is_error": is_error,
                }

            style = project_data.get("style", "")
            style_description = project_data.get("style_description", "")
            items_by_id = {str(item[id_field]): item for item in items if item.get(id_field)}
            plans = build_storyboard_dependency_plan(
                items,
                id_field,
                [str(item[id_field]) for item in selected],
                script_filename,
            )
            specs = _build_specs(
                plans,
                items_by_id,
                style,
                style_description,
                id_field,
                script_filename,
                quality,
            )

            recorder = _FailureRecorder(project_dir / "storyboards")
            successes, failures = await batch_enqueue_and_wait(
                project_name=ctx.project_name,
                specs=specs,
            )
            # narration → segment_id / drama → scene_id：``id_field`` 是脚本里
            # 的规范字段名，``"segment"`` / ``"scene"`` 是对应的资源类型。
            resource_type = "segment" if id_field == "segment_id" else "scene"
            for f in failures:
                recorder.record(f.resource_id, resource_type, f.error or "unknown")
            recorder.save()

            details: list[str] = []
            success_map = {s.resource_id: s for s in successes}
            for plan in plans:
                br: BatchTaskResult | None = success_map.get(plan.resource_id)
                if br is None:
                    continue
                result = br.result or {}
                rel = result.get("file_path") or f"storyboards/scene_{plan.resource_id}.png"
                details.append(f"  ✓ {plan.resource_id} → {rel}{route_summary(result)}")
            for f in failures:
                details.append(f"  ✗ {f.resource_id}: {f.error}")

            header = f"generate_storyboards summary: {len(successes)} succeeded, {len(failures)} failed"
            return {
                "content": [{"type": "text", "text": "\n".join([header, *details])}],
                "is_error": bool(failures),
            }
        except Exception as exc:  # noqa: BLE001
            return tool_error("generate_storyboards", exc)

    return _handler


__all__ = ["generate_storyboards_tool"]

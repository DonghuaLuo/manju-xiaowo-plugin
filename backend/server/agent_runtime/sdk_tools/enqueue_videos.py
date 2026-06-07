"""SDK MCP tools for video generation (episode / scene / all / selected)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

from lib.generation_queue_client import (
    BatchTaskResult,
    TaskSpec,
    batch_enqueue_and_wait,
    enqueue_and_wait,
)
from lib.project_manager import ProjectManager
from lib.prompt_utils import is_structured_video_prompt
from lib.reference_video import assemble_shots_text
from lib.storyboard_sequence import get_storyboard_items
from server.agent_runtime.sdk_tools._context import (
    ToolContext,
    tool_error,
    tool_result_text,
    validate_script_filename,
)
from server.agent_runtime.sdk_tools._generation_quality import (
    QUALITY_SCHEMA,
    REFINE_SCOPE_SCHEMA,
    RefineScope,
    is_current_refined,
    normalize_quality,
    normalize_refine_scope,
    route_summary,
)


def _get_video_prompt(item: dict[str, Any]) -> str | dict[str, Any]:
    prompt = item.get("video_prompt")
    if not prompt:
        item_id = item.get("segment_id") or item.get("scene_id")
        raise ValueError(f"片段/场景缺少 video_prompt 字段: {item_id}")
    if is_structured_video_prompt(prompt):
        return prompt
    if isinstance(prompt, dict):
        item_id = item.get("segment_id") or item.get("scene_id")
        raise ValueError(f"片段/场景 video_prompt 为对象但格式不符合结构化规范: {item_id}")
    if not isinstance(prompt, str):
        item_id = item.get("segment_id") or item.get("scene_id")
        raise TypeError(f"片段/场景 video_prompt 类型无效（期望 str 或 dict）: {item_id}")
    return prompt


def _is_reference_script(script: dict[str, Any]) -> bool:
    return script.get("generation_mode") == "reference_video"


def _validate_bulk_refine_scope(quality: str, refine_scope: RefineScope | None) -> None:
    if quality == "final" and refine_scope is None:
        raise ValueError("批量精修视频必须显式传 refine_scope='current_unrefined' 或 refine_scope='current_all'")
    if quality != "final" and refine_scope is not None:
        raise ValueError("refine_scope 只允许和 quality='final' 一起使用")


def _current_video_path(project_dir: Path, item: dict[str, Any]) -> Path | None:
    rel = (item.get("generated_assets") or {}).get("video_clip")
    if not isinstance(rel, str) or not rel.strip():
        return None
    try:
        project_root = project_dir.resolve()
        path = (project_dir / rel).resolve()
        if not path.is_relative_to(project_root):
            return None
    except Exception:
        return None
    return path if path.is_file() else None


def _has_current_video(project_dir: Path, item: dict[str, Any]) -> bool:
    return _current_video_path(project_dir, item) is not None


def _select_current_video_items(
    *,
    items: list[dict[str, Any]],
    id_field: str,
    project_dir: Path,
    resource_type: str,
    refine_scope: RefineScope,
) -> list[dict[str, Any]]:
    current_items = [item for item in items if _has_current_video(project_dir, item)]
    if refine_scope == "current_all":
        return current_items
    return [
        item
        for item in current_items
        if not is_current_refined(project_dir, resource_type, str(item.get(id_field) or ""))
    ]


def _refine_scope_empty_text(refine_scope: RefineScope, noun: str) -> str:
    if refine_scope == "current_unrefined":
        return f"当前没有未精修的已有{noun}"
    return f"当前没有可重精修的已有{noun}"


def _mark_current_video_items(
    *,
    items: list[dict[str, Any]],
    id_field: str,
    project_dir: Path,
    ordered_paths: list[Path | None],
    already_done: list[str],
    completed: list[str],
) -> None:
    already_done_set = set(already_done)
    completed_set = set(completed)
    for idx, item in enumerate(items):
        item_id = str(item.get(id_field, item.get("scene_id", f"item_{idx}")))
        if item_id in already_done_set:
            continue
        current_path = _current_video_path(project_dir, item)
        if current_path is None:
            continue
        ordered_paths[idx] = current_path
        already_done.append(item_id)
        already_done_set.add(item_id)
        if item_id not in completed_set:
            completed.append(item_id)
            completed_set.add(item_id)


# Checkpoint helpers


def _episode_checkpoint_path(project_dir: Path, episode: int) -> Path:
    return project_dir / "videos" / f".checkpoint_ep{episode}.json"


def _selected_checkpoint_path(project_dir: Path, scenes_hash: str) -> Path:
    return project_dir / "videos" / f".checkpoint_selected_{scenes_hash}.json"


def _load_checkpoint_at(path: Path) -> dict[str, Any] | None:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _save_checkpoint_at(path: Path, completed: list[str], started_at: str, **extra: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "completed_scenes": completed,
        "started_at": started_at,
        "updated_at": datetime.now(UTC).isoformat(),
        **extra,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _clear_checkpoint_at(path: Path) -> None:
    if path.exists():
        path.unlink()


def _build_video_specs(
    *,
    items: list[dict[str, Any]],
    id_field: str,
    content_mode: str,
    script_filename: str,
    project_dir: Path,
    skip_ids: list[str] | None,
    log: list[str],
    quality: str = "draft",
) -> tuple[list[TaskSpec], dict[str, int]]:
    item_type = "片段" if content_mode == "narration" else "场景"
    skip_set = set(skip_ids or [])

    specs: list[TaskSpec] = []
    order_map: dict[str, int] = {}
    for idx, item in enumerate(items):
        item_id = item.get(id_field) or item.get("scene_id") or item.get("segment_id") or f"item_{idx}"
        if item_id in skip_set:
            continue

        storyboard_image = (item.get("generated_assets") or {}).get("storyboard_image")
        if not storyboard_image:
            log.append(f"⚠️  {item_type} {item_id} 没有分镜图，跳过")
            continue
        storyboard_path = project_dir / storyboard_image
        if not storyboard_path.is_file():
            log.append(f"⚠️  分镜图不存在: {storyboard_path}，跳过")
            continue

        try:
            prompt = _get_video_prompt(item)
        except Exception as exc:  # noqa: BLE001
            log.append(f"⚠️  {item_type} {item_id} 的 video_prompt 无效，跳过: {exc}")
            continue

        # duration 是能力维度，留待执行层在 provider 解析后校验（见 ADR-0001）；
        # 原样透传调用方显式指定的值，不在入队侧做 int() 截断式归一化（否则会把
        # 本应被执行层拒绝的非法值静默修正）。缺省由执行层按 caps 收口默认。
        extra_payload: dict[str, Any] = {"quality": quality}
        video_settings = item.get("video_generation") if isinstance(item.get("video_generation"), dict) else {}
        duration = item.get("duration_seconds")
        if duration is not None:
            extra_payload["duration_seconds"] = duration
        if video_settings.get("resolution"):
            extra_payload["resolution"] = video_settings["resolution"]
        if video_settings.get("video_backend"):
            extra_payload["video_backend"] = video_settings["video_backend"]
        if video_settings.get("video_continuity_policy"):
            extra_payload["video_continuity_policy"] = video_settings["video_continuity_policy"]

        specs.append(
            TaskSpec.from_request(
                task_type="video",
                media_type="video",
                resource_id=item_id,
                prompt=prompt,
                script_file=script_filename,
                extra_payload=extra_payload,
            )
        )
        order_map[item_id] = idx
    return specs, order_map


def _build_reference_specs(
    *,
    units: list[dict[str, Any]],
    script_filename: str,
    skip_ids: list[str] | None,
    log: list[str],
    quality: str = "draft",
) -> tuple[list[TaskSpec], dict[str, int]]:
    skip_set = set(skip_ids or [])
    specs: list[TaskSpec] = []
    order_map: dict[str, int] = {}
    for idx, unit in enumerate(units):
        # 用 .get 归一化：缺失 unit_id 的坏数据（Agent 可裸写 script JSON）会被 from_request
        # 当作空 resource_id 拒绝并走下面的跳过分支，而不是在此抛 KeyError 中断整批。
        unit_id = str(unit.get("unit_id") or "")
        if unit_id in skip_set:
            continue
        if not unit.get("shots"):
            log.append(f"⚠️  {unit_id} 没有 shots，跳过")
            continue
        # prompt 由 shots[*].text 拼接，经统一守卫点做空提示词结构校验（见 ADR-0001）；
        # 任一 unit 不合法（空提示词、或 from_request 对空 resource_id 抛的裸 ValueError）
        # 都跳过并告警，与「没有 shots」一致，不让一个坏 unit 中断整批。
        # 注意 TaskSpecValidationError 是 ValueError 子类，捕 ValueError 同时覆盖两者。
        try:
            extra_payload: dict[str, Any] = {"quality": quality}
            duration = unit.get("duration_seconds")
            if duration is not None:
                extra_payload["duration_seconds"] = duration
            spec = TaskSpec.from_request(
                task_type="reference_video",
                media_type="video",
                resource_id=unit_id,
                prompt=assemble_shots_text(unit["shots"]),
                script_file=script_filename,
                extra_payload=extra_payload,
            )
        except ValueError as exc:
            log.append(f"⚠️  {unit_id} 入队校验未通过，跳过：{exc}")
            continue
        specs.append(spec)
        order_map[unit_id] = idx
    return specs, order_map


def _select_reference_units(
    units: list[dict[str, Any]],
    unit_ids: list[str] | None,
    log: list[str],
) -> list[dict[str, Any]]:
    if unit_ids is None:
        return units

    requested = [str(uid) for uid in dict.fromkeys(unit_ids) if str(uid)]
    units_by_id = {str(unit.get("unit_id") or ""): unit for unit in units}
    selected: list[dict[str, Any]] = []
    for unit_id in requested:
        unit = units_by_id.get(unit_id)
        if unit is None:
            log.append(f"⚠️  video_unit '{unit_id}' 不存在，跳过")
            continue
        selected.append(unit)
    return selected


def _scan_completed_items(
    items: list[dict[str, Any]],
    id_field: str,
    completed_scenes: list[str],
    videos_dir: Path,
) -> tuple[list[Path | None], list[str], list[str]]:
    """Pure scan: reconcile checkpoint claims against on-disk videos.

    Returns ``(ordered_paths, already_done, completed_filtered)``:
    - ``ordered_paths[i]`` is the existing mp4 path for items[i] iff the
      checkpoint claimed it AND the file is on disk; else ``None``.
    - ``already_done`` is the subset of items the caller can skip enqueueing.
    - ``completed_filtered`` drops ids the checkpoint claimed but whose file
      is missing — caller should write this back instead of mutating its
      checkpoint list in place.
    """
    ordered_paths: list[Path | None] = [None] * len(items)
    already_done: list[str] = []
    stale_completions: set[str] = set()
    for idx, item in enumerate(items):
        item_id = item.get(id_field, item.get("scene_id", f"item_{idx}"))
        if item_id not in completed_scenes:
            continue
        video_output = videos_dir / f"scene_{item_id}.mp4"
        if video_output.is_file():
            ordered_paths[idx] = video_output
            already_done.append(item_id)
        else:
            stale_completions.add(item_id)
    completed_filtered = [cid for cid in completed_scenes if cid not in stale_completions]
    return ordered_paths, already_done, completed_filtered


def _scene_fallback_relpath(resource_id: str) -> str:
    return f"videos/scene_{resource_id}.mp4"


def _reference_fallback_relpath(resource_id: str) -> str:
    return f"reference_videos/{resource_id}.mp4"


async def _submit_with_checkpoint(
    *,
    project_name: str,
    project_dir: Path,
    specs: list[TaskSpec],
    order_map: dict[str, int],
    ordered_paths: list[Path | None],
    completed: list[str],
    fallback_relpath: Callable[[str], str],
    save_fn: Callable[[], None],
    log: list[str],
) -> list[BatchTaskResult]:
    """Run a batch and update checkpoint per success. Returns failures.

    ``fallback_relpath`` is called only when the queue result lacks
    ``file_path``; reference_video tasks need a different naming convention
    than scene videos, so the caller chooses per task family.
    """

    def on_success(br: BatchTaskResult) -> None:
        result = br.result or {}
        relative_path = result.get("file_path") or fallback_relpath(br.resource_id)
        output_path = project_dir / relative_path
        ordered_paths[order_map[br.resource_id]] = output_path
        completed.append(br.resource_id)
        save_fn()
        log.append(f"    ✓ {output_path.name}{route_summary(result)}")

    def on_failure(br: BatchTaskResult) -> None:
        log.append(f"    ✗ {br.resource_id}: {br.error}")

    _, failures = await batch_enqueue_and_wait(
        project_name=project_name,
        specs=specs,
        on_success=on_success,
        on_failure=on_failure,
    )
    return failures


async def _generate_reference_episode(
    *,
    ctx: ToolContext,
    script: dict[str, Any],
    script_filename: str,
    episode: int,
    resume: bool,
    log: list[str],
    quality: str = "draft",
    unit_ids: list[str] | None = None,
    refine_scope: RefineScope | None = None,
    regenerate_existing: bool = False,
) -> list[Path]:
    project_dir = ctx.project_path
    units = script.get("video_units") or []
    if not units:
        raise ValueError(f"第 {episode} 集 video_units 为空：{script_filename}")
    units = _select_reference_units(units, unit_ids, log)
    if not units:
        raise ValueError("没有找到任何有效的 video_unit")

    if quality == "final" and unit_ids is None and refine_scope is not None:
        units = _select_current_video_items(
            items=units,
            id_field="unit_id",
            project_dir=project_dir,
            resource_type="reference_videos",
            refine_scope=refine_scope,
        )
        if not units:
            raise RuntimeError(_refine_scope_empty_text(refine_scope, "参考视频"))

    if unit_ids is None:
        ckpt_path = _episode_checkpoint_path(project_dir, episode)
    else:
        unit_hash = hashlib.md5(",".join(sorted({str(uid) for uid in unit_ids})).encode("utf-8")).hexdigest()[:8]
        ckpt_path = _selected_checkpoint_path(project_dir, f"ref_{unit_hash}")
    completed: list[str] = []
    started_at = datetime.now(UTC).isoformat()
    if resume:
        ckpt = _load_checkpoint_at(ckpt_path)
        if ckpt:
            completed = ckpt.get("completed_scenes", [])
            started_at = ckpt.get("started_at", started_at)

    output_dir = project_dir / "reference_videos"
    output_dir.mkdir(parents=True, exist_ok=True)

    ordered_paths: list[Path | None] = [None] * len(units)
    already_done: list[str] = []
    for idx, unit in enumerate(units):
        unit_id = unit["unit_id"]
        candidate = output_dir / f"{unit_id}.mp4"
        current_path = _current_video_path(project_dir, unit)
        existing_path = current_path or (candidate if candidate.is_file() else None)
        if existing_path is not None and quality != "final" and not regenerate_existing:
            ordered_paths[idx] = existing_path
            already_done.append(unit_id)
            if unit_id not in completed:
                completed.append(unit_id)
        elif unit_id in completed:
            completed.remove(unit_id)

    specs, order_map = _build_reference_specs(
        units=units,
        script_filename=script_filename,
        skip_ids=already_done,
        log=log,
        quality=quality,
    )
    if specs:
        failures = await _submit_with_checkpoint(
            project_name=ctx.project_name,
            project_dir=project_dir,
            specs=specs,
            order_map=order_map,
            ordered_paths=ordered_paths,
            completed=completed,
            fallback_relpath=_reference_fallback_relpath,
            save_fn=lambda: _save_checkpoint_at(ckpt_path, completed, started_at, episode=episode),
            log=log,
        )
        if failures:
            raise RuntimeError(f"{len(failures)} 个 unit 生成失败")

    final = [p for p in ordered_paths if p is not None]
    if not final:
        raise RuntimeError("没有生成任何 video_unit")
    _clear_checkpoint_at(ckpt_path)
    return final


async def _run_reference_episode(
    *,
    ctx: ToolContext,
    script: dict[str, Any],
    script_filename: str,
    resume: bool,
    log: list[str],
    quality: str = "draft",
    unit_ids: list[str] | None = None,
    refine_scope: RefineScope | None = None,
    regenerate_existing: bool = False,
) -> dict[str, Any]:
    """Run reference_video-mode generation and format the tool response.

    All 4 video handlers share the same reference_video tail. Episode / all
    pass ``unit_ids=None`` for whole-episode generation; scene / selected pass
    unit ids so they do not accidentally regenerate the entire episode.
    """
    episode = ProjectManager.resolve_episode_from_script(script, script_filename)
    paths = await _generate_reference_episode(
        ctx=ctx,
        script=script,
        script_filename=script_filename,
        episode=episode,
        resume=resume,
        log=log,
        quality=quality,
        unit_ids=unit_ids,
        refine_scope=refine_scope,
        regenerate_existing=regenerate_existing,
    )
    scope = "指定参考视频" if unit_ids is not None else "参考视频"
    header = f"第 {episode} 集{scope}生成完成，共 {len(paths)} 个 unit"
    return tool_result_text("\n".join([header, *log]), label="视频生成日志")


def generate_video_episode_tool(ctx: ToolContext):
    @tool(
        "generate_video_episode",
        "为剧本对应的整集生成场景视频；默认跳过已有当前视频，只补缺失项。resume=true 时从 checkpoint 续传。"
        "reference_video 模式会自动按 video_units 处理。",
        {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "剧本文件名（如 episode_1.json），必须是纯文件名，禁止任何路径分隔符",
                },
                "resume": {"type": "boolean", "description": "是否从上次中断处继续"},
                "regenerate_existing": {
                    "type": "boolean",
                    "description": "快速版整集重抽开关；默认 false 会跳过已有当前视频。仅当用户明确要求重跑/重抽整集已有视频时传 true。quality='final' 时禁止使用，请改用 refine_scope。",
                },
                "refine_scope": {
                    **REFINE_SCOPE_SCHEMA,
                    "description": "批量精修范围；仅 quality='final' 时允许传，且整集精修必须传。current_unrefined=只精修当前未精修视频，current_all=当前已有视频全量重精修。",
                },
                "quality": {
                    **QUALITY_SCHEMA,
                    "description": "生成质量档位；默认 draft（视频快速版）。批量/Agent 自动生成默认使用快速版，final 仅在用户明确要求精修时使用，可单镜头或批量精修。",
                },
            },
            "required": ["script"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        log: list[str] = []
        try:
            script_filename = validate_script_filename(args["script"])
            resume = bool(args.get("resume"))
            regenerate_existing = bool(args.get("regenerate_existing"))
            quality = normalize_quality(args, "draft")
            refine_scope = normalize_refine_scope(args)
            _validate_bulk_refine_scope(quality, refine_scope)
            if quality == "final" and regenerate_existing:
                raise ValueError("quality='final' 时不能传 regenerate_existing；批量精修请使用 refine_scope")

            project_dir = ctx.project_path
            script = ctx.pm.load_script(ctx.project_name, script_filename)

            if _is_reference_script(script):
                return await _run_reference_episode(
                    ctx=ctx,
                    script=script,
                    script_filename=script_filename,
                    resume=resume,
                    log=log,
                    quality=quality,
                    refine_scope=refine_scope,
                    regenerate_existing=regenerate_existing,
                )

            episode = ProjectManager.resolve_episode_from_script(script, script_filename)
            items, id_field, _char_field, _scenes, _props = get_storyboard_items(script)
            content_mode = script.get("content_mode", "narration")
            if not items:
                raise ValueError(f"第 {episode} 集剧本为空：{script_filename}")
            if quality == "final" and refine_scope is not None:
                items = _select_current_video_items(
                    items=items,
                    id_field=id_field,
                    project_dir=project_dir,
                    resource_type="videos",
                    refine_scope=refine_scope,
                )
                if not items:
                    raise RuntimeError(_refine_scope_empty_text(refine_scope, "视频片段"))

            ckpt_path = _episode_checkpoint_path(project_dir, episode)
            completed: list[str] = []
            started_at = datetime.now(UTC).isoformat()
            if resume:
                ckpt = _load_checkpoint_at(ckpt_path)
                if ckpt:
                    completed = ckpt.get("completed_scenes", [])
                    started_at = ckpt.get("started_at", started_at)

            videos_dir = project_dir / "videos"
            videos_dir.mkdir(parents=True, exist_ok=True)
            ordered_paths, already_done, completed = _scan_completed_items(items, id_field, completed, videos_dir)
            if quality != "final" and not regenerate_existing:
                _mark_current_video_items(
                    items=items,
                    id_field=id_field,
                    project_dir=project_dir,
                    ordered_paths=ordered_paths,
                    already_done=already_done,
                    completed=completed,
                )
            specs, order_map = _build_video_specs(
                items=items,
                id_field=id_field,
                content_mode=content_mode,
                script_filename=script_filename,
                project_dir=project_dir,
                skip_ids=already_done,
                log=log,
                quality=quality,
            )

            if not specs and not any(ordered_paths):
                raise RuntimeError("没有可生成的视频片段")

            if specs:
                failures = await _submit_with_checkpoint(
                    project_name=ctx.project_name,
                    project_dir=project_dir,
                    specs=specs,
                    order_map=order_map,
                    ordered_paths=ordered_paths,
                    completed=completed,
                    fallback_relpath=_scene_fallback_relpath,
                    save_fn=lambda: _save_checkpoint_at(ckpt_path, completed, started_at, episode=episode),
                    log=log,
                )
                if failures:
                    raise RuntimeError(f"{len(failures)} 个视频生成失败（使用 resume=true 续传）")

            scene_videos = [p for p in ordered_paths if p is not None]
            _clear_checkpoint_at(ckpt_path)
            header = f"第 {episode} 集视频生成完成，共 {len(scene_videos)} 个片段"
            return tool_result_text("\n".join([header, *log]), label="视频生成日志")
        except Exception as exc:  # noqa: BLE001
            return tool_error("generate_video_episode", exc, log)

    return _handler


def generate_video_scene_tool(ctx: ToolContext):
    @tool(
        "generate_video_scene",
        "生成单个场景/片段的视频。reference_video 模式下 scene_id 视为 video_unit 的 unit_id。",
        {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "剧本文件名（如 episode_1.json），必须是纯文件名，禁止任何路径分隔符",
                },
                "scene_id": {"type": "string", "description": "场景或片段 ID"},
                "quality": {
                    **QUALITY_SCHEMA,
                    "description": "生成质量档位；默认 draft（视频快速版）。批量/Agent 自动生成默认使用快速版，final 仅在用户明确要求精修时使用，可单镜头或批量精修。",
                },
            },
            "required": ["script", "scene_id"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            script_filename = validate_script_filename(args["script"])
            scene_id = args["scene_id"]
            quality = normalize_quality(args, "draft")

            project_dir = ctx.project_path
            script = ctx.pm.load_script(ctx.project_name, script_filename)

            if _is_reference_script(script):
                log: list[str] = []
                return await _run_reference_episode(
                    ctx=ctx,
                    script=script,
                    script_filename=script_filename,
                    resume=False,
                    log=log,
                    quality=quality,
                    unit_ids=[scene_id],
                )

            items, id_field, _char_field, _scenes, _props = get_storyboard_items(script)
            item = next((s for s in items if s.get(id_field) == scene_id or s.get("scene_id") == scene_id), None)
            if not item:
                raise ValueError(f"场景/片段 '{scene_id}' 不存在")
            # 调用方可能用 ``scene_id`` 别名命中条目，但入队 / 文件名 / fallback
            # 必须用脚本里的规范 ``id_field`` 值，否则下游 generate_video_all 和
            # checkpoint 扫描会找不到产物。
            item_id = str(item[id_field])

            storyboard_image = item.get("generated_assets", {}).get("storyboard_image")
            if not storyboard_image:
                raise ValueError(f"场景/片段 '{item_id}' 没有分镜图，请先运行 generate_storyboards")
            if not (project_dir / storyboard_image).is_file():
                raise FileNotFoundError(f"分镜图不存在: {project_dir / storyboard_image}")

            prompt = _get_video_prompt(item)
            # duration 是能力维度，留待执行层在 provider 解析后校验（见 ADR-0001）；
            # 原样透传调用方显式指定的值，不在入队侧做 int() 截断式归一化（否则会把
            # 本应被执行层拒绝的非法值静默修正）。缺省由执行层按 caps 收口默认。
            extra_payload: dict[str, Any] = {"quality": quality}
            duration = item.get("duration_seconds")
            if duration is not None:
                extra_payload["duration_seconds"] = duration
            spec = TaskSpec.from_request(
                task_type="video",
                media_type="video",
                resource_id=item_id,
                prompt=prompt,
                script_file=script_filename,
                extra_payload=extra_payload,
            )

            queued = await enqueue_and_wait(
                project_name=ctx.project_name,
                task_type=spec.task_type,
                media_type=spec.media_type,
                resource_id=spec.resource_id,
                payload=spec.payload,
                script_file=spec.script_file,
                source="skill",
            )
            result = queued.get("result") or {}
            rel = result.get("file_path") or f"videos/scene_{item_id}.mp4"
            output_path = project_dir / rel
            return {"content": [{"type": "text", "text": f"✅ 视频已保存: {output_path}{route_summary(result)}"}]}
        except Exception as exc:  # noqa: BLE001
            return tool_error("generate_video_scene", exc)

    return _handler


def generate_video_all_tool(ctx: ToolContext):
    @tool(
        "generate_video_all",
        "为剧本批量生成所有缺视频的场景/片段（独立模式，不拼接）。reference_video 模式等同 episode 模式。",
        {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "剧本文件名（如 episode_1.json），必须是纯文件名，禁止任何路径分隔符",
                },
                "refine_scope": {
                    **REFINE_SCOPE_SCHEMA,
                    "description": "批量精修范围；仅 quality='final' 时允许传，且批量精修必须传。current_unrefined=只精修当前未精修视频，current_all=当前已有视频全量重精修。",
                },
                "quality": {
                    **QUALITY_SCHEMA,
                    "description": "生成质量档位；默认 draft（视频快速版）。批量/Agent 自动生成默认使用快速版，final 仅在用户明确要求精修时使用，可单镜头或批量精修。",
                },
            },
            "required": ["script"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        log: list[str] = []
        try:
            script_filename = validate_script_filename(args["script"])
            quality = normalize_quality(args, "draft")
            refine_scope = normalize_refine_scope(args)
            _validate_bulk_refine_scope(quality, refine_scope)
            project_dir = ctx.project_path
            script = ctx.pm.load_script(ctx.project_name, script_filename)

            if _is_reference_script(script):
                return await _run_reference_episode(
                    ctx=ctx,
                    script=script,
                    script_filename=script_filename,
                    resume=False,
                    log=log,
                    quality=quality,
                    refine_scope=refine_scope,
                )

            items, id_field, _chars, _scenes, _props = get_storyboard_items(script)
            content_mode = script.get("content_mode", "narration")
            if quality == "final" and refine_scope is not None:
                pending = _select_current_video_items(
                    items=items,
                    id_field=id_field,
                    project_dir=project_dir,
                    resource_type="videos",
                    refine_scope=refine_scope,
                )
                if not pending:
                    return {"content": [{"type": "text", "text": f"✨ {_refine_scope_empty_text(refine_scope, '视频片段')}"}]}
            else:
                pending = [it for it in items if not _has_current_video(project_dir, it)]
                if not pending:
                    return {"content": [{"type": "text", "text": "✨ 所有场景/片段的视频都已生成"}]}

            specs, _order_map = _build_video_specs(
                items=pending,
                id_field=id_field,
                content_mode=content_mode,
                script_filename=script_filename,
                project_dir=project_dir,
                skip_ids=None,
                log=log,
                quality=quality,
            )
            if not specs:
                return tool_result_text("\n".join([*log, "⚠️  没有任何可生成的视频任务"]), label="视频生成日志")

            successes, failures = await batch_enqueue_and_wait(project_name=ctx.project_name, specs=specs)
            details: list[str] = []
            for br in successes:
                rel = (br.result or {}).get("file_path") or f"videos/scene_{br.resource_id}.mp4"
                details.append(f"  ✓ {br.resource_id} → {rel}{route_summary(br.result)}")
            for br in failures:
                details.append(f"  ✗ {br.resource_id}: {br.error}")
            header = f"generate_video_all summary: {len(successes)} succeeded, {len(failures)} failed"
            result = tool_result_text("\n".join([header, *log, *details]), label="视频生成日志")
            result["is_error"] = bool(failures)
            return result
        except Exception as exc:  # noqa: BLE001
            return tool_error("generate_video_all", exc, log)

    return _handler


def generate_video_selected_tool(ctx: ToolContext):
    @tool(
        "generate_video_selected",
        "生成指定多个场景的视频（独立 checkpoint，按 scene_ids 哈希）。reference_video 模式下 scene_ids 视为 video_unit 的 unit_id 列表。",
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
                    "description": "场景或片段 ID 列表",
                },
                "resume": {"type": "boolean", "description": "是否从上次中断处继续"},
                "quality": {
                    **QUALITY_SCHEMA,
                    "description": "生成质量档位；默认 draft（视频快速版）。批量/Agent 自动生成默认使用快速版，final 仅在用户明确要求精修时使用，可单镜头或批量精修。",
                },
            },
            "required": ["script", "scene_ids"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        log: list[str] = []
        try:
            script_filename = validate_script_filename(args["script"])
            # 去重以避免同一 ID 重复入队；保留首次出现顺序便于人读日志，
            # checkpoint hash 再单独排序（见下方 ``canonical_scene_ids``）。
            scene_ids: list[str] = list(dict.fromkeys(args["scene_ids"]))
            resume = bool(args.get("resume"))
            quality = normalize_quality(args, "draft")

            project_dir = ctx.project_path
            script = ctx.pm.load_script(ctx.project_name, script_filename)

            if _is_reference_script(script):
                return await _run_reference_episode(
                    ctx=ctx,
                    script=script,
                    script_filename=script_filename,
                    resume=resume,
                    log=log,
                    quality=quality,
                    unit_ids=scene_ids,
                )

            items, id_field, _chars, _scenes, _props = get_storyboard_items(script)
            content_mode = script.get("content_mode", "narration")

            items_by_id: dict[str, dict[str, Any]] = {}
            for item in items:
                items_by_id[item.get(id_field, "")] = item
                if "scene_id" in item:
                    items_by_id[item["scene_id"]] = item

            selected: list[dict[str, Any]] = []
            seen_canonical: set[str] = set()
            # ``items_by_id`` 同时按 ``id_field`` 与 ``scene_id`` 索引同一个 item，
            # 调用方若把两个值都列入 ``scene_ids`` 会让同一场景重复入队——必须按
            # 规范 ``id_field`` 再去一次重。
            for sid in scene_ids:
                if sid not in items_by_id:
                    log.append(f"⚠️  场景/片段 '{sid}' 不存在，跳过")
                    continue
                item = items_by_id[sid]
                canonical = str(item.get(id_field, ""))
                if canonical and canonical in seen_canonical:
                    continue
                seen_canonical.add(canonical)
                selected.append(item)
            if not selected:
                raise ValueError("没有找到任何有效的场景/片段")

            # checkpoint hash 用 ``selected`` 解析出的规范 ID 集合，让同一批
            # 场景无论用别名 ``scene_id`` 还是规范 ``id_field`` 调用都落到同一
            # checkpoint 文件（否则 resume 会因 hash 不同读到空 ``completed_scenes``，
            # 已生成的视频被 ``_scan_completed_items`` 漏判，重复入队）。
            canonical_scene_ids = sorted(seen_canonical)
            scenes_hash = hashlib.md5(",".join(canonical_scene_ids).encode("utf-8")).hexdigest()[:8]
            ckpt_path = _selected_checkpoint_path(project_dir, scenes_hash)
            completed: list[str] = []
            started_at = datetime.now(UTC).isoformat()
            if resume:
                ckpt = _load_checkpoint_at(ckpt_path)
                if ckpt:
                    completed = ckpt.get("completed_scenes", [])
                    started_at = ckpt.get("started_at", started_at)

            videos_dir = project_dir / "videos"
            videos_dir.mkdir(parents=True, exist_ok=True)
            ordered_paths, already_done, completed = _scan_completed_items(selected, id_field, completed, videos_dir)
            specs, order_map = _build_video_specs(
                items=selected,
                id_field=id_field,
                content_mode=content_mode,
                script_filename=script_filename,
                project_dir=project_dir,
                skip_ids=already_done,
                log=log,
                quality=quality,
            )

            # ``_build_video_specs`` 可能把所有 selected 都过滤掉（缺分镜图 /
            # video_prompt 无效），此时如果 ``ordered_paths`` 也没有已生成项就是
            # "什么也没做"，必须抛错，否则下游会把 "完成：0 个" 当成功推进流程。
            if not specs and not any(ordered_paths):
                raise RuntimeError("没有任何可生成的视频任务（全部 selected 都被跳过）")

            if specs:
                failures = await _submit_with_checkpoint(
                    project_name=ctx.project_name,
                    project_dir=project_dir,
                    specs=specs,
                    order_map=order_map,
                    ordered_paths=ordered_paths,
                    completed=completed,
                    fallback_relpath=_scene_fallback_relpath,
                    save_fn=lambda: _save_checkpoint_at(ckpt_path, completed, started_at, scene_ids=scene_ids),
                    log=log,
                )
                if failures:
                    raise RuntimeError(f"{len(failures)} 个视频生成失败（使用 resume=true 续传）")

            final_results = [p for p in ordered_paths if p is not None]
            _clear_checkpoint_at(ckpt_path)
            header = f"generate_video_selected 完成：{len(final_results)} 个"
            return tool_result_text("\n".join([header, *log]), label="视频生成日志")
        except Exception as exc:  # noqa: BLE001
            return tool_error("generate_video_selected", exc, log)

    return _handler


__all__ = [
    "generate_video_episode_tool",
    "generate_video_scene_tool",
    "generate_video_all_tool",
    "generate_video_selected_tool",
]

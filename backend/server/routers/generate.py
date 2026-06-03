"""
生成 API 路由

处理分镜图、视频、角色图、线索图的生成请求。
所有生成请求入队到 GenerationQueue，由 GenerationWorker 异步执行。
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from lib.app_data_dir import app_data_dir
from lib.asset_types import ASSET_SPECS
from lib.generation_queue import get_generation_queue
from lib.generation_queue_client import TaskSpec, TaskSpecValidationError
from lib.i18n import Translator
from lib.project_manager import ProjectManager
from lib.script_editor import ScriptEditError
from lib.storyboard_sequence import (
    find_storyboard_item,
    get_storyboard_items,
    resolve_previous_storyboard_path,
)
from server.auth import CurrentUser
from server.services.finalization import EpisodeFinalizationService, build_finalization_task_report
from server.services.generation_route_resolver import compact_generation_payload, resolve_generation_route
from server.services.generation_tasks import (
    _END_FRAME_SKIP_TRANSITIONS,
    _collect_reference_images,
    _item_reference_values,
    _normalize_continuity_policy,
    _normalize_storyboard_prompt,
    _normalize_video_prompt,
    _storyboard_path_for_item,
    resolve_video_prompt_policy,
)

router = APIRouter()

# 初始化管理器
pm = ProjectManager(app_data_dir())


def get_project_manager() -> ProjectManager:
    return pm


def _project_relative(project_path: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(project_path.resolve()).as_posix()
    except ValueError:
        return None


def _reference_labels(project: dict, project_path: Path) -> dict[str, str]:
    labels: dict[str, str] = {}

    for name, data in project.get("characters", {}).items():
        if not isinstance(data, dict):
            continue
        sheet = data.get("character_sheet")
        if isinstance(sheet, str) and sheet:
            labels[sheet] = f"角色：{name}"

    for name, data in project.get("scenes", {}).items():
        if not isinstance(data, dict):
            continue
        sheet = data.get("scene_sheet")
        if isinstance(sheet, str) and sheet:
            labels[sheet] = f"场景：{name}"

    for name, data in project.get("props", {}).items():
        if not isinstance(data, dict):
            continue
        sheet = data.get("prop_sheet")
        if isinstance(sheet, str) and sheet:
            labels[sheet] = f"道具：{name}"

    return {str((project_path / rel).resolve()): label for rel, label in labels.items()}


def _serialize_reference(
    *,
    project_name: str,
    project_path: Path,
    ref: object,
    labels: dict[str, str],
    fallback_label: str = "参考图",
) -> dict[str, str] | None:
    label = fallback_label
    description = ""
    raw_path: object = ref
    if isinstance(ref, dict):
        raw_path = ref.get("image")
        label = str(ref.get("label") or label)
        description = str(ref.get("description") or "")

    if raw_path is None:
        return None

    path = Path(raw_path)
    if not path.is_absolute():
        path = project_path / path
    if not path.exists():
        return None

    resolved = str(path.resolve())
    rel = _project_relative(project_path, path)
    if not rel:
        return None

    label = labels.get(resolved, label)
    result = {
        "label": label,
        "path": rel,
        "url": f"/api/v1/files/{project_name}/{rel}",
    }
    if description:
        result["description"] = description
    return result


_INVALID_EXPORT_FILENAME_CHARS = set('<>:"/\\|?*：')


def _safe_export_stem(value: object, fallback: str) -> str:
    text = str(value or "").strip() or fallback
    chars = [
        "_" if ord(char) < 32 or char in _INVALID_EXPORT_FILENAME_CHARS else char
        for char in text
    ]
    safe = re.sub(r"\s+", "_", "".join(chars))
    safe = re.sub(r"_+", "_", safe).strip(" ._")
    return (safe[:60].strip(" ._") or fallback)


def _reference_export_ext(path: object) -> str:
    ext = Path(str(path or "")).suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        return ext
    return ".png"


def _with_external_reference_names(references: list[dict[str, str]]) -> list[dict[str, Any]]:
    named: list[dict[str, Any]] = []
    for index, ref in enumerate(references, start=1):
        item: dict[str, Any] = dict(ref)
        item["index"] = index
        stem = _safe_export_stem(ref.get("label"), "参考图")
        item["filename"] = f"{index:02d}_{stem}{_reference_export_ext(ref.get('path'))}"
        named.append(item)
    return named


def _format_reference_lines(references: list[dict[str, Any]]) -> str:
    if not references:
        return "参考图：无"
    lines = [
        "参考图（文件名和上传/粘贴顺序只用于辅助对应；如果文件名无法读取或顺序不准确，请以图片实际内容和下方含义为准）："
    ]
    for index, ref in enumerate(references, start=1):
        ref_index = int(ref.get("index") or index)
        filename = str(ref.get("filename") or f"参考图{ref_index}")
        suffix = f"；{ref['description']}" if ref.get("description") else ""
        lines.append(f"参考图{ref_index}：{filename}，{ref['label']}{suffix}")
    return "\n".join(lines)


def _external_storyboard_text(prompt_text: str, references: list[dict[str, Any]]) -> str:
    return (
        "我会上传/粘贴下列参考图，请使用这些参考图生成这一镜的分镜图，保持角色、场景、道具与参考图一致；不要添加字幕、水印或多余文字。\n\n"
        f"{_format_reference_lines(references)}\n\n"
        "分镜图生成提示词：\n"
        f"{prompt_text}"
    )


def _external_video_text(prompt_text: str, references: list[dict[str, Any]]) -> str:
    return (
        "我会上传/粘贴下列参考图，请使用分镜图参考生成视频；如果包含“视频首帧”，请把它作为首帧，动作从这张图开始，保持主体、构图和风格一致。"
        "如果包含“下一张分镜图”，支持 end_image / last frame 的模型请把它作为尾帧；仅支持参考图的模型可作为过渡参考；不支持则忽略。\n\n"
        f"{_format_reference_lines(references)}\n\n"
        "视频生成提示词：\n"
        f"{prompt_text}"
    )


def _external_video_continuity_reference(
    *,
    project: dict,
    project_path: Path,
    items: list[dict],
    id_field: str,
    item_index: int | None,
    current_item: dict,
    resource_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    policy = _normalize_continuity_policy(project, {})
    meta: dict[str, Any] = {
        "requested_policy": policy,
        "effective_policy": "start_only",
        "start_storyboard_id": resource_id,
    }

    if policy == "start_only":
        meta["skip_reason"] = "policy_start_only"
        return None, meta
    if item_index is None:
        meta["skip_reason"] = "storyboard_item_not_found"
        return None, meta

    next_index = item_index + 1
    if next_index >= len(items):
        meta["skip_reason"] = "last_storyboard"
        return None, meta

    next_item = items[next_index]
    next_id, next_storyboard = _storyboard_path_for_item(project_path, next_item, id_field)
    if next_id:
        meta["end_storyboard_id"] = next_id
    if not next_storyboard or not next_storyboard.exists():
        meta["skip_reason"] = "next_storyboard_missing"
        return None, meta

    transition_to_next = str(current_item.get("transition_to_next") or "cut").strip().lower()
    meta["transition_to_next"] = transition_to_next
    if policy == "auto":
        if transition_to_next in _END_FRAME_SKIP_TRANSITIONS:
            meta["skip_reason"] = f"transition_{transition_to_next}"
            return None, meta
        if bool(next_item.get("segment_break")):
            meta["skip_reason"] = "next_segment_break"
            return None, meta

        current_scenes = _item_reference_values(current_item, "scenes")
        next_scenes = _item_reference_values(next_item, "scenes")
        if current_scenes and next_scenes and current_scenes.isdisjoint(next_scenes):
            meta["skip_reason"] = "scene_changed"
            return None, meta

    if policy == "reference_assisted":
        meta["effective_policy"] = "reference_assisted"
        meta["external_suggested_use"] = "reference_image"
        description = "外部生成时可作为下一镜头参考图，用于保持前后镜头过渡一致"
    else:
        meta["effective_policy"] = "end_frame"
        meta["external_suggested_use"] = "end_image"
        description = "外部生成时建议作为 end_image / last_frame 使用，用于衔接下一镜头"

    return (
        {
            "image": next_storyboard,
            "label": "下一张分镜图（视频尾帧/过渡参考）",
            "description": description,
        },
        meta,
    )


# ==================== 请求模型 ====================


class GenerateStoryboardRequest(BaseModel):
    prompt: str | dict
    script_file: str
    quality: Literal["draft", "final", "custom"] | None = None
    shot_tier: Literal["S", "A", "B"] | None = None
    resolution: str | None = None
    source_version: int | None = None
    image_provider_t2i: str | None = None
    image_provider_i2i: str | None = None
    image_provider: str | None = None
    image_model: str | None = None


class GenerateVideoRequest(BaseModel):
    prompt: str | dict
    script_file: str
    quality: Literal["draft", "final", "custom"] | None = None
    shot_tier: Literal["S", "A", "B"] | None = None
    resolution: str | None = None
    source_version: int | None = None
    video_backend: str | None = None
    video_provider: str | None = None
    video_model: str | None = None
    duration_seconds: int | None = None  # 改为 None，由服务层解析
    generate_audio: bool | None = None
    service_tier: str | None = None
    seed: int | None = None


class GenerateCharacterRequest(BaseModel):
    prompt: str
    quality: Literal["draft", "final", "custom"] | None = None
    resolution: str | None = None
    source_version: int | None = None
    image_provider_t2i: str | None = None
    image_provider_i2i: str | None = None
    image_provider: str | None = None
    image_model: str | None = None


class GenerateSceneRequest(BaseModel):
    prompt: str
    quality: Literal["draft", "final", "custom"] | None = None
    resolution: str | None = None
    source_version: int | None = None
    image_provider_t2i: str | None = None
    image_provider_i2i: str | None = None
    image_provider: str | None = None
    image_model: str | None = None


class GeneratePropRequest(BaseModel):
    prompt: str
    quality: Literal["draft", "final", "custom"] | None = None
    resolution: str | None = None
    source_version: int | None = None
    image_provider_t2i: str | None = None
    image_provider_i2i: str | None = None
    image_provider: str | None = None
    image_model: str | None = None


class GenerationRoutePreviewItem(BaseModel):
    label: str | None = None
    task_kind: Literal["character", "scene", "prop", "storyboard", "grid", "video", "reference_video"]
    quality: Literal["draft", "final", "custom"] | None = None
    capability: Literal["t2i", "i2i"] | None = None
    payload: dict[str, Any] | None = None


class GenerationRoutePreviewRequest(BaseModel):
    project_overrides: dict[str, Any] | None = None
    routes: list[GenerationRoutePreviewItem]


_IMAGE_GENERATION_FIELDS = (
    "quality",
    "shot_tier",
    "resolution",
    "source_version",
    "image_provider_t2i",
    "image_provider_i2i",
    "image_provider",
    "image_model",
)

_VIDEO_GENERATION_FIELDS = (
    "quality",
    "shot_tier",
    "resolution",
    "source_version",
    "video_backend",
    "video_provider",
    "video_model",
    "duration_seconds",
    "generate_audio",
    "service_tier",
    "seed",
)


def _request_generation_payload(req: BaseModel, fields: tuple[str, ...]) -> dict[str, Any]:
    return compact_generation_payload({field: getattr(req, field, None) for field in fields})


_ROUTE_PREVIEW_PROJECT_FIELDS = frozenset(
    {
        "generation_profiles",
        "shot_tier_profiles",
        "video_backend",
        "image_backend",
        "image_provider_t2i",
        "image_provider_i2i",
        "video_generate_audio",
        "default_duration",
        "model_settings",
    }
)


def _route_preview_project(project: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    preview = dict(project)
    if not isinstance(overrides, dict):
        return preview
    for key, value in overrides.items():
        if key not in _ROUTE_PREVIEW_PROJECT_FIELDS:
            continue
        if value is None:
            preview.pop(key, None)
        else:
            preview[key] = value
    return preview


def _route_to_preview_dict(route) -> dict[str, Any]:
    return {
        "ok": True,
        "task_kind": route.task_kind,
        "media_type": route.media_type,
        "quality": route.quality,
        "profile_key": route.profile_key,
        "provider_id": route.provider_id,
        "model_id": route.model_id,
        "resolution": route.resolution,
        "duration_seconds": route.duration_seconds,
        "generate_audio": route.generate_audio,
        "service_tier": route.service_tier,
        "seed": route.seed,
        "supported_resolutions": route.supported_resolutions,
        "supported_durations": route.supported_durations,
        "duration_resolution_constraints": route.duration_resolution_constraints,
        "shot_tier": route.shot_tier,
        "shot_tier_strategy": route.shot_tier_strategy,
        "warnings": route.warnings,
        "metadata": route.metadata,
    }


# ==================== 外部生成辅助 ====================


@router.post("/projects/{project_name}/generation/route-preview")
async def preview_generation_routes(
    project_name: str,
    req: GenerationRoutePreviewRequest,
    _user: CurrentUser,
):
    """Resolve generation routes against unsaved project settings for instant validation."""

    try:
        project = await asyncio.to_thread(get_project_manager().load_project, project_name)
        preview_project = _route_preview_project(project, req.project_overrides)

        from lib.config.resolver import ConfigResolver
        from lib.db import async_session_factory

        resolver = ConfigResolver(async_session_factory)
        routes: list[dict[str, Any]] = []
        for item in req.routes[:24]:
            payload = dict(item.payload or {})
            if item.quality is not None:
                payload.setdefault("quality", item.quality)
            try:
                route = await resolve_generation_route(
                    project=preview_project,
                    payload=payload,
                    task_kind=item.task_kind,
                    quality=item.quality,
                    capability=item.capability or "t2i",
                    resolver=resolver,
                    project_name=project_name,
                )
                routes.append({"label": item.label, **_route_to_preview_dict(route)})
            except Exception as exc:
                routes.append(
                    {
                        "ok": False,
                        "label": item.label,
                        "task_kind": item.task_kind,
                        "quality": item.quality,
                        "error": str(exc),
                    }
                )
        return {"routes": routes}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("生成路由预览失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_name}/generate/external-package/{segment_id}")
async def get_external_generation_package(
    project_name: str,
    segment_id: str,
    _user: CurrentUser,
    _t: Translator,
    script_file: str = Query(...),
):
    """返回当前分镜用于外部生成的真实 prompt 与参考图清单。"""
    try:
        manager = get_project_manager()
        project = await asyncio.to_thread(manager.load_project, project_name)
        video_prompt_policy = await resolve_video_prompt_policy(project, project_name=project_name)

        def _sync() -> dict[str, Any]:
            project_path = manager.get_project_path(project_name)
            script = manager.load_script(project_name, script_file)
            items, id_field, char_field, scene_field, prop_field = get_storyboard_items(script)
            resolved = find_storyboard_item(items, id_field, segment_id)
            if resolved is None:
                raise HTTPException(status_code=404, detail=_t("segment_not_found", id=segment_id))
            target_item, item_index = resolved

            storyboard_prompt = _normalize_storyboard_prompt(
                target_item.get("image_prompt"),
                project.get("style", ""),
            )
            video_prompt = _normalize_video_prompt(
                target_item.get("video_prompt"),
                project=project,
                target_item=target_item,
                char_field=char_field,
                policy=video_prompt_policy,
            )

            labels = _reference_labels(project, project_path)
            previous_path = resolve_previous_storyboard_path(project_path, items, id_field, segment_id)
            raw_storyboard_refs = _collect_reference_images(
                project,
                project_path,
                target_item,
                char_field=char_field,
                scene_field=scene_field,
                prop_field=prop_field,
                previous_storyboard_path=previous_path,
            ) or []
            storyboard_refs: list[dict[str, Any]] = [
                serialized
                for ref in raw_storyboard_refs
                if (
                    serialized := _serialize_reference(
                        project_name=project_name,
                        project_path=project_path,
                        ref=ref,
                        labels=labels,
                    )
                )
            ]

            assets = target_item.get("generated_assets") if isinstance(target_item, dict) else None
            storyboard_rel = assets.get("storyboard_image") if isinstance(assets, dict) else None
            storyboard_path = (
                project_path / storyboard_rel
                if isinstance(storyboard_rel, str) and storyboard_rel
                else project_path / "storyboards" / f"scene_{segment_id}.png"
            )
            video_refs: list[dict[str, Any]] = []
            if storyboard_path.exists():
                raw_video_ref = {
                    "image": storyboard_path,
                    "label": "当前分镜图（视频首帧）",
                    "description": "视频生成时实际作为 start_image 使用",
                }
                serialized_video_ref = _serialize_reference(
                    project_name=project_name,
                    project_path=project_path,
                    ref=raw_video_ref,
                    labels={},
                )
                if serialized_video_ref:
                    video_refs.append(serialized_video_ref)
            raw_continuity_ref, continuity_meta = _external_video_continuity_reference(
                project=project,
                project_path=project_path,
                items=items,
                id_field=id_field,
                item_index=item_index,
                current_item=target_item,
                resource_id=segment_id,
            )
            if raw_continuity_ref is not None:
                serialized_continuity_ref = _serialize_reference(
                    project_name=project_name,
                    project_path=project_path,
                    ref=raw_continuity_ref,
                    labels={},
                )
                if serialized_continuity_ref:
                    video_refs.append(serialized_continuity_ref)

            storyboard_refs = _with_external_reference_names(storyboard_refs)
            video_refs = _with_external_reference_names(video_refs)

            return {
                "project_name": project_name,
                "script_file": script_file,
                "segment_id": segment_id,
                "storyboard": {
                    "prompt": storyboard_prompt,
                    "external_prompt": _external_storyboard_text(storyboard_prompt, storyboard_refs),
                    "references": storyboard_refs,
                },
                "video": {
                    "prompt": video_prompt,
                    "external_prompt": _external_video_text(video_prompt, video_refs),
                    "references": video_refs,
                    "continuity": continuity_meta,
                },
            }

        return await asyncio.to_thread(_sync)

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except ScriptEditError as e:
        raise HTTPException(status_code=400, detail=_t("script_data_corrupted", reason=str(e)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 分镜图生成 ====================


@router.post("/projects/{project_name}/generate/storyboard/{segment_id}")
async def generate_storyboard(
    project_name: str,
    segment_id: str,
    req: GenerateStoryboardRequest,
    _user: CurrentUser,
    _t: Translator,
):
    """
    提交分镜图生成任务到队列，立即返回 task_id。

    生成由 GenerationWorker 异步执行，状态通过 SSE 推送。
    """
    try:

        def _sync():
            get_project_manager().load_project(project_name)
            script = get_project_manager().load_script(project_name, req.script_file)
            items, id_field, _, _, _ = get_storyboard_items(script)
            resolved = find_storyboard_item(items, id_field, segment_id)
            if resolved is None:
                raise HTTPException(status_code=404, detail=_t("segment_not_found", id=segment_id))

        await asyncio.to_thread(_sync)

        # 结构校验 + 构造经单一守卫点（与 SDK 入队同源，规则不分叉）
        try:
            spec = TaskSpec.from_request(
                task_type="storyboard",
                media_type="image",
                resource_id=segment_id,
                prompt=req.prompt,
                script_file=req.script_file,
                extra_payload=_request_generation_payload(req, _IMAGE_GENERATION_FIELDS),
            )
        except TaskSpecValidationError as e:
            raise HTTPException(status_code=400, detail=_t(e.code, **e.params))

        # 入队
        queue = get_generation_queue()
        result = await queue.enqueue_task(
            project_name=project_name,
            task_type=spec.task_type,
            media_type=spec.media_type,
            resource_id=spec.resource_id,
            script_file=spec.script_file,
            payload=spec.payload,
            source="webui",
            user_id=_user.id,
        )

        return {
            "success": True,
            "task_id": result["task_id"],
            "message": _t("storyboard_task_submitted", segment_id=segment_id),
        }

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except ScriptEditError as e:
        raise HTTPException(status_code=400, detail=_t("script_data_corrupted", reason=str(e)))
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 视频生成 ====================


@router.post("/projects/{project_name}/generate/video/{segment_id}")
async def generate_video(
    project_name: str,
    segment_id: str,
    req: GenerateVideoRequest,
    _user: CurrentUser,
    _t: Translator,
):
    """
    提交视频生成任务到队列，立即返回 task_id。

    需要先有分镜图作为起始帧。生成由 GenerationWorker 异步执行。
    """
    try:

        def _sync():
            pm_local = get_project_manager()
            pm_local.load_project(project_name)
            project_path = pm_local.get_project_path(project_name)

            # 与 worker 一致：优先读取 generated_assets.storyboard_image，回退默认路径。
            # 旧宫格项目 storyboard_image 指向 scene_{id}_first.png，仍可正常解析。
            storyboard_rel: str | None = None
            try:
                script = pm_local.load_script(project_name, req.script_file)
                items, id_field, _, _, _ = get_storyboard_items(script)
                resolved = find_storyboard_item(items, id_field, segment_id)
                if resolved:
                    assets = resolved[0].get("generated_assets") or {}
                    if isinstance(assets, dict):
                        storyboard_rel = assets.get("storyboard_image")
            except FileNotFoundError:
                # 脚本不存在交由后续流程报错；此处只负责存在性检查
                pass
            except ScriptEditError as exc:
                raise HTTPException(status_code=400, detail=_t("script_data_corrupted", reason=str(exc)))

            storyboard_file = (
                project_path / storyboard_rel
                if storyboard_rel
                else project_path / "storyboards" / f"scene_{segment_id}.png"
            )
            if not storyboard_file.exists():
                raise HTTPException(status_code=400, detail=_t("generate_storyboard_first", segment_id=segment_id))

        await asyncio.to_thread(_sync)

        # 结构校验 + 构造经单一守卫点（与 SDK 入队同源，规则不分叉）。
        # duration 是能力维度，留待执行层在 provider 解析后校验（见 ADR-0001）。
        try:
            spec = TaskSpec.from_request(
                task_type="video",
                media_type="video",
                resource_id=segment_id,
                prompt=req.prompt,
                script_file=req.script_file,
                extra_payload=_request_generation_payload(req, _VIDEO_GENERATION_FIELDS),
            )
        except TaskSpecValidationError as e:
            raise HTTPException(status_code=400, detail=_t(e.code, **e.params))

        # 入队（provider 由服务层根据配置自动解析，调用方无需传递）
        queue = get_generation_queue()
        result = await queue.enqueue_task(
            project_name=project_name,
            task_type=spec.task_type,
            media_type=spec.media_type,
            resource_id=spec.resource_id,
            script_file=spec.script_file,
            payload=spec.payload,
            source="webui",
            user_id=_user.id,
        )

        return {
            "success": True,
            "task_id": result["task_id"],
            "message": _t("video_task_submitted", segment_id=segment_id),
        }

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_name}/finalize/episode/{episode}")
async def finalize_episode(
    project_name: str,
    episode: int,
    _user: CurrentUser,
):
    """提交本集最终化任务：补齐最终分镜和最终视频，返回即时报告。"""

    try:
        service = EpisodeFinalizationService(get_project_manager(), get_generation_queue())
        return await service.finalize_episode(
            project_name=project_name,
            episode=episode,
            user_id=_user.id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("最终化本集失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_name}/finalize/report")
async def get_finalization_report(
    project_name: str,
    _user: CurrentUser,
    limit: int = 100,
):
    """Return recent finalize-sourced task outcomes with failure categories."""

    try:
        queue = get_generation_queue()
        tasks = await queue.list_tasks(
            project_name=project_name,
            source="finalize",
            page=1,
            page_size=max(1, min(200, limit)),
        )
        return build_finalization_task_report(tasks.get("items") or [])
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 资产设计图生成（character / scene / prop 共用） ====================


# i18n key 命名差异：scene 用历史前缀 "project_scene_*"
_ASSET_GENERATE_I18N: dict[str, dict[str, str]] = {
    "character": {"not_found": "character_not_found", "submitted": "character_task_submitted"},
    "scene": {"not_found": "project_scene_not_found", "submitted": "scene_task_submitted"},
    "prop": {"not_found": "prop_not_found", "submitted": "prop_task_submitted"},
}


async def _enqueue_asset_generation(
    *,
    asset_type: str,
    project_name: str,
    resource_name: str,
    prompt: str,
    extra_payload: dict[str, Any] | None = None,
    user_id: str,
    _t: Translator,
) -> dict:
    """三类资产（character / scene / prop）设计图生成共用入队逻辑。"""
    spec = ASSET_SPECS[asset_type]
    keys = _ASSET_GENERATE_I18N[asset_type]

    def _sync():
        project = get_project_manager().load_project(project_name)
        if resource_name not in project.get(spec.bucket_key, {}):
            raise HTTPException(status_code=404, detail=_t(keys["not_found"], name=resource_name))

    await asyncio.to_thread(_sync)

    try:
        task_spec = TaskSpec.from_request(
            task_type=asset_type,
            media_type="image",
            resource_id=resource_name,
            prompt=prompt,
            extra_payload=extra_payload,
        )
    except TaskSpecValidationError as e:
        raise HTTPException(status_code=400, detail=_t(e.code, **e.params))

    queue = get_generation_queue()
    result = await queue.enqueue_task(
        project_name=project_name,
        task_type=task_spec.task_type,
        media_type=task_spec.media_type,
        resource_id=task_spec.resource_id,
        payload=task_spec.payload,
        source="webui",
        user_id=user_id,
    )

    return {
        "success": True,
        "task_id": result["task_id"],
        "message": _t(keys["submitted"], name=resource_name),
    }


@router.post("/projects/{project_name}/generate/character/{char_name}")
async def generate_character(
    project_name: str,
    char_name: str,
    req: GenerateCharacterRequest,
    _user: CurrentUser,
    _t: Translator,
):
    """提交角色设计图生成任务到队列，立即返回 task_id。"""
    try:
        return await _enqueue_asset_generation(
            asset_type="character",
            project_name=project_name,
            resource_name=char_name,
            prompt=req.prompt,
            extra_payload=_request_generation_payload(req, _IMAGE_GENERATION_FIELDS),
            user_id=_user.id,
            _t=_t,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_name}/generate/scene/{scene_name}")
async def generate_scene(
    project_name: str,
    scene_name: str,
    req: GenerateSceneRequest,
    _user: CurrentUser,
    _t: Translator,
):
    """提交场景设计图生成任务到队列，立即返回 task_id。"""
    try:
        return await _enqueue_asset_generation(
            asset_type="scene",
            project_name=project_name,
            resource_name=scene_name,
            prompt=req.prompt,
            extra_payload=_request_generation_payload(req, _IMAGE_GENERATION_FIELDS),
            user_id=_user.id,
            _t=_t,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{project_name}/generate/prop/{prop_name}")
async def generate_prop(
    project_name: str,
    prop_name: str,
    req: GeneratePropRequest,
    _user: CurrentUser,
    _t: Translator,
):
    """提交道具设计图生成任务到队列，立即返回 task_id。"""
    try:
        return await _enqueue_asset_generation(
            asset_type="prop",
            project_name=project_name,
            resource_name=prop_name,
            prompt=req.prompt,
            extra_payload=_request_generation_payload(req, _IMAGE_GENERATION_FIELDS),
            user_id=_user.id,
            _t=_t,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))

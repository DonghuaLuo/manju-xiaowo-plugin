"""
项目管理路由

处理项目的 CRUD 操作，复用 lib/project_manager.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

if TYPE_CHECKING:
    from server.services.jianying_draft_service import JianyingDraftService

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi import Path as FastAPIPath
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.background import BackgroundTask

logger = logging.getLogger(__name__)

from lib.app_data_dir import app_data_dir
from lib.asset_fingerprints import compute_asset_fingerprints
from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.i18n import Translator
from lib.profile_manifest import ContentMode
from lib.project_change_hints import project_change_source
from lib.project_manager import ProjectManager
from lib.script_splitting_templates import (
    delete_custom_script_splitting_template,
    export_script_splitting_template,
    list_script_splitting_templates,
    mark_template_change_stale_assets,
    preview_template_change,
    resolve_script_splitting_profile,
    snapshot_from_profile,
    upsert_custom_script_splitting_template,
    validate_script_splitting_template,
)
from lib.status_calculator import StatusCalculator
from lib.style_templates import (
    favorite_style_thumbnail_path,
    get_favorite_style_template,
    is_known_template,
    list_style_templates,
    resolve_template_prompt,
)
from lib.upload_utils import copy_upload_file, local_upload_path, read_upload_bytes
from lib.video_input_preflight import run_video_input_preflight
from server.auth import CurrentUser, create_download_token, verify_download_token
from server.routers._validators import validate_backend_value
from server.services.asset_archive import (
    UNSUPPORTED_ARCHIVE_DETAIL,
    AssetArchiveService,
    detect_import_archive_kind,
)
from server.services.project_archive import (
    ProjectArchiveService,
    ProjectArchiveValidationError,
)
from server.services.project_cover import resolve_project_cover

router = APIRouter()

# 初始化项目管理器和状态计算器
pm = ProjectManager(app_data_dir())
calc = StatusCalculator(pm)

# episode 字段白名单：只允许持久化合法的 on-disk 字段。
# StatusCalculator 注入的统计字段（scenes_count / status / storyboards / videos 等）
# 是读时计算值，禁止写回 project.json。
EPISODE_PERSIST_FIELDS = {"title", "script_file"}
GenerationMode = Literal["storyboard", "grid", "reference_video"]


def get_project_manager() -> ProjectManager:
    return pm


def get_status_calculator() -> StatusCalculator:
    return calc


def _manager_data_root(manager: ProjectManager) -> Path:
    return Path(getattr(manager, "projects_root", getattr(manager, "base", app_data_dir())))


def _materialize_favorite_style_for_project(
    manager: ProjectManager,
    project_name: str,
    template: dict,
    style_prompt: str,
    _t: Translator,
) -> dict[str, str]:
    """把用户收藏风格复制为项目级自定义风格。"""
    thumbnail_file = str(template.get("thumbnail_file") or "").strip()
    try:
        source_path = favorite_style_thumbnail_path(thumbnail_file, data_root=_manager_data_root(manager))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_t("forbidden_access")) from exc
    if not source_path.is_file():
        raise HTTPException(status_code=404, detail=_t("file_not_found", path=thumbnail_file))

    suffix = source_path.suffix.lower() or ".png"
    style_filename = f"style_reference{suffix}"
    target_path = manager.get_project_path(project_name) / style_filename
    shutil.copyfile(source_path, target_path)
    return {
        "style_image": style_filename,
        "style_description": style_prompt,
    }


def get_archive_service() -> ProjectArchiveService:
    return ProjectArchiveService(get_project_manager())


def get_asset_archive_service() -> AssetArchiveService:
    return AssetArchiveService(_manager_data_root(get_project_manager()))


class CreateProjectRequest(BaseModel):
    name: str | None = None
    title: str | None = None
    style: str | None = ""  # 保留但不再是用户入口
    content_mode: ContentMode | None = "narration"
    aspect_ratio: str | None = "9:16"
    default_duration: int | None = None
    episode_target_units: int | None = 1000
    source_language: Literal["zh", "en", "vi"] | None = "zh"
    generation_mode: GenerationMode = "storyboard"
    script_splitting_template_id: str | None = None
    # ===== 新增 =====
    style_template_id: str | None = None
    video_backend: str | None = None
    image_backend: str | None = None
    image_provider_t2i: str | None = None
    image_provider_i2i: str | None = None
    text_backend_script: str | None = None
    text_backend_overview: str | None = None
    text_backend_style: str | None = None
    model_settings: dict[str, dict[str, str | None]] | None = None
    generation_profiles: dict[str, dict[str, Any | None]] | None = None
    video_service_tier: Literal["default", "flex"] | None = None


class EpisodePatch(BaseModel):
    """PATCH body entry for a single episode.

    Only whitelisted fields persist; computed fields (scenes_count, status,
    storyboards, etc.) are silently dropped via extra='ignore'.
    """

    model_config = ConfigDict(extra="ignore")
    episode: int
    title: str | None = None
    script_file: str | None = None
    generation_mode: GenerationMode | None = None


class UpdateProjectRequest(BaseModel):
    title: str | None = None
    style: str | None = None
    style_description: str | None = None
    content_mode: ContentMode | None = None
    aspect_ratio: str | None = None
    default_duration: int | None = None
    episode_target_units: int | None = None
    source_language: Literal["zh", "en", "vi"] | None = None
    generation_mode: str | None = None
    script_splitting_template_id: str | None = None
    video_backend: str | None = None
    image_backend: str | None = None
    image_provider_t2i: str | None = None
    image_provider_i2i: str | None = None
    video_generate_audio: bool | None = None
    text_backend_script: str | None = None
    text_backend_overview: str | None = None
    text_backend_style: str | None = None
    style_template_id: str | None = None
    clear_style_image: bool | None = None
    episodes: list[EpisodePatch] | None = None
    model_settings: dict[str, dict[str, str | None]] | None = None
    generation_profiles: dict[str, dict[str, Any | None]] | None = None
    video_service_tier: Literal["default", "flex"] | None = None


class ScriptSplittingTemplateChangeRequest(BaseModel):
    template_id: str
    generation_mode: GenerationMode | None = None
    confirm: bool = False
    mode: Literal["preview", "apply_keep_drafts", "apply_rebuild_step1"] = "apply_keep_drafts"


class ScriptSplittingTemplateUpsertRequest(BaseModel):
    id: str | None = None
    base_template_id: str | None = None
    derived_from_template_id: str | None = None
    creation_mode: Literal["improve", "new_style"] | None = None
    name: str | None = None
    description: str | None = None
    supported_generation_modes: list[GenerationMode] | None = None
    recommended_generation_modes: list[GenerationMode] | None = None
    intent_brief: str | None = None
    derivation_note: str | None = None
    tone_preferences: list[str] | None = None
    extra_split_rules: list[str] | None = None
    extra_forbidden_patterns: list[str] | None = None
    example_source: str | None = None
    example_expected_output: str | None = None


class ScriptSplittingTemplateImportRequest(BaseModel):
    template: dict[str, Any]


class VideoInputPreflightRequest(BaseModel):
    aspect_ratio: str | None = None
    duration_seconds: int | None = None
    generate_audio: bool | None = None
    reference_images_count: int | None = None
    reference_images: list[str] | None = None
    first_frame_path: str | None = None
    last_frame_path: str | None = None


def _validate_episode_target_units(value: int | None) -> int | None:
    if value is None:
        return None
    if value < 1:
        raise HTTPException(status_code=400, detail="每集目标长度必须大于 0")
    return int(value)


@router.get("/style-templates")
async def get_style_templates(_user: CurrentUser):
    """返回后端注册的预设风格清单，prompt 以后端为唯一来源。"""
    manager = get_project_manager()
    return {"success": True, "templates": list_style_templates(data_root=_manager_data_root(manager))}


@router.get("/script-splitting-templates")
async def get_script_splitting_templates(
    _user: CurrentUser,
    content_mode: ContentMode | None = Query(None),
):
    """返回内置和用户拆分方案模板清单。"""
    manager = get_project_manager()
    return {
        "success": True,
        "templates": list_script_splitting_templates(content_mode, data_root=_manager_data_root(manager)),
    }


@router.post("/script-splitting-templates")
async def upsert_script_splitting_template(
    req: ScriptSplittingTemplateUpsertRequest,
    _user: CurrentUser,
):
    """复制内置模板并保存为用户拆分方案。"""
    try:
        manager = get_project_manager()
        template = upsert_custom_script_splitting_template(
            req.model_dump(exclude_none=True),
            data_root=_manager_data_root(manager),
            source="user_generated",
        )
        validation = validate_script_splitting_template(template)
        return {"success": True, "template": template, "validation": validation}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/script-splitting-templates/import")
async def import_script_splitting_template(
    req: ScriptSplittingTemplateImportRequest,
    _user: CurrentUser,
):
    """导入一个经过校验的用户拆分方案 JSON。"""
    try:
        manager = get_project_manager()
        template = upsert_custom_script_splitting_template(
            req.template,
            data_root=_manager_data_root(manager),
            source="imported",
        )
        validation = validate_script_splitting_template(template)
        return {"success": True, "template": template, "validation": validation}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/script-splitting-templates/{template_id}/export")
async def export_script_splitting_template_payload(
    template_id: str,
    _user: CurrentUser,
):
    """导出拆分方案模板 JSON。"""
    try:
        manager = get_project_manager()
        payload = export_script_splitting_template(template_id, data_root=_manager_data_root(manager))
        return {"success": True, **payload}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/script-splitting-templates/{template_id}")
async def delete_script_splitting_template(
    template_id: str,
    _user: CurrentUser,
):
    """删除用户拆分方案模板；内置模板不可删除。"""
    try:
        manager = get_project_manager()
        deleted = delete_custom_script_splitting_template(template_id, data_root=_manager_data_root(manager))
        if not deleted:
            raise HTTPException(status_code=404, detail="拆分方案模板不存在")
        return {"success": True}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _cleanup_temp_file(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return


def _cleanup_temp_dir(dir_path: str) -> None:
    shutil.rmtree(dir_path, ignore_errors=True)


@router.post("/projects/import")
async def import_project_archive(
    _user: CurrentUser,
    _t: Translator,
    file: UploadFile = File(...),
    conflict_policy: str = Form("prompt"),
):
    """从 ZIP 导入项目包或全局资产/配置包。"""
    upload_path: str | None = None
    try:
        source_path = local_upload_path(file)
        if source_path is not None:
            archive_path = source_path
        else:
            fd, upload_path = tempfile.mkstemp(prefix="arcreel-upload-", suffix=".zip")
            os.close(fd)
            archive_path = Path(upload_path)
            await asyncio.to_thread(copy_upload_file, file, archive_path)

        archive_kind = await asyncio.to_thread(detect_import_archive_kind, archive_path)
        if archive_kind.kind == "unsupported":
            raise ProjectArchiveValidationError(
                UNSUPPORTED_ARCHIVE_DETAIL,
                errors=["请选择项目导出 ZIP，或通过“导出资产”生成的全局资产 ZIP。"],
                extra={"archive_type": "unsupported"},
            )

        if archive_kind.kind == "asset_archive":
            result = await get_asset_archive_service().import_archive(archive_path)
            return {
                "success": True,
                "import_type": "asset_archive",
                "summary": result.summary,
                "warnings": result.warnings,
                "diagnostics": result.diagnostics,
            }

        def _sync_project():
            return get_archive_service().import_project_archive(
                archive_path,
                uploaded_filename=file.filename,
                conflict_policy=conflict_policy,
            )

        result = await asyncio.to_thread(_sync_project)
        return {
            "success": True,
            "import_type": "project",
            "project_name": result.project_name,
            "project": result.project,
            "warnings": result.warnings,
            "conflict_resolution": result.conflict_resolution,
            "diagnostics": result.diagnostics,
        }
    except ProjectArchiveValidationError as exc:
        diagnostics = exc.extra.get(
            "diagnostics",
            {"blocking": [], "auto_fixable": [], "warnings": []},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "errors": exc.errors,
                "warnings": exc.warnings,
                "diagnostics": diagnostics,
                **exc.extra,
            },
        )
    except Exception as e:
        logger.exception("请求处理失败")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e), "errors": [], "warnings": []},
        )
    finally:
        await file.close()
        if upload_path:
            _cleanup_temp_file(upload_path)


@router.post("/projects/{name}/export/token")
async def create_export_token(
    name: str,
    current_user: CurrentUser,
    _t: Translator,
    scope: str = Query("full"),
):
    """签发短时效下载 token，用于浏览器原生下载认证。"""
    try:
        if scope not in ("full", "current"):
            raise HTTPException(status_code=422, detail=_t("scope_invalid"))

        def _sync():
            if not get_project_manager().project_exists(name):
                raise HTTPException(status_code=404, detail=_t("project_not_found", name=name))
            return get_archive_service().get_export_diagnostics(name, scope=scope)

        diagnostics = await asyncio.to_thread(_sync)
        username = current_user.sub
        download_token = create_download_token(username, name)
        return {
            "download_token": download_token,
            "expires_in": 300,
            "diagnostics": diagnostics,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{name}/export")
async def export_project_archive(
    name: str,
    _t: Translator,
    download_token: str = Query(...),
    scope: str = Query("full"),
):
    """将项目导出为 ZIP。需要 download_token 认证（通过 POST /export/token 获取）。"""
    if scope not in ("full", "current"):
        raise HTTPException(status_code=422, detail=_t("scope_invalid"))

    # 验证 download_token
    import jwt as pyjwt

    try:
        verify_download_token(download_token, name)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail=_t("download_expired"))
    except ValueError:
        raise HTTPException(status_code=403, detail=_t("download_token_mismatch"))
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail=_t("download_token_invalid"))

    try:
        archive_path, download_name = await asyncio.to_thread(
            lambda: get_archive_service().export_project(name, scope=scope)
        )
        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename=download_name,
            background=BackgroundTask(_cleanup_temp_file, str(archive_path)),
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=name))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


# --- 剪映草稿导出 ---


def get_jianying_draft_service() -> JianyingDraftService:
    from server.services.jianying_draft_service import JianyingDraftService

    return JianyingDraftService(get_project_manager())


def _validate_draft_path(draft_path: str, _t: Callable[..., str]) -> str:
    """校验 draft_path 合法性"""
    if not draft_path or not draft_path.strip():
        raise HTTPException(status_code=422, detail=_t("jianying_path_invalid"))
    if len(draft_path) > 1024:
        raise HTTPException(status_code=422, detail=_t("jianying_path_too_long"))
    if any(ord(c) < 32 for c in draft_path):
        raise HTTPException(status_code=422, detail=_t("jianying_path_illegal"))
    return draft_path.strip()


@router.get("/projects/{name}/export/jianying-draft")
def export_jianying_draft(
    name: str,
    _t: Translator,
    episode: int = Query(..., description="集数编号"),
    draft_path: str = Query(..., description="用户本地剪映草稿目录"),
    download_token: str = Query(..., description="下载 token"),
    jianying_version: str = Query("6", description="剪映版本：6 或 5"),
):
    """导出指定集的剪映草稿 ZIP"""
    import jwt as pyjwt

    # 1. 验证 download_token
    try:
        verify_download_token(download_token, name)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail=_t("download_expired"))
    except ValueError:
        raise HTTPException(status_code=403, detail=_t("download_token_mismatch"))
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail=_t("download_token_invalid"))

    # 2. 校验 draft_path
    draft_path = _validate_draft_path(draft_path, _t)

    # 3. 调用服务
    svc = get_jianying_draft_service()
    try:
        zip_path = svc.export_episode_draft(
            project_name=name,
            episode=episode,
            draft_path=draft_path,
            use_draft_info_name=(jianying_version != "5"),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("剪映草稿导出失败: project=%s episode=%d", name, episode)
        raise HTTPException(status_code=500, detail=_t("jianying_export_failed"))

    download_name = f"{name}_episode_{episode}_jianying_draft.zip"

    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=download_name,
        background=BackgroundTask(_cleanup_temp_dir, str(zip_path.parent)),
    )


@router.get("/projects")
async def list_projects(_user: CurrentUser):
    """列出所有项目"""

    def _sync():
        manager = get_project_manager()
        calculator = get_status_calculator()
        projects = []
        for name in manager.list_projects():
            try:
                # 尝试加载项目元数据
                if manager.project_exists(name):
                    project = manager.load_project(name)
                    # 一次性预加载每集剧本，喂给 cover + status 两路下游，去除重复 JSON I/O。
                    # key 为 episode['script_file'] 原值（match resolve_project_cover /
                    # StatusCalculator 对 key 的期望）。任何一集加载失败都不影响列表：
                    # 仅跳过入 map，下游消费者自然按"缺失"路径兜底。
                    preloaded_scripts: dict[str, dict] = {}
                    for ep in project.get("episodes") or []:
                        script_file = ep.get("script_file")
                        if not script_file:
                            continue
                        try:
                            preloaded_scripts[script_file] = manager.load_script(name, script_file)
                        except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError) as load_err:
                            # 与 resolve_project_cover / StatusCalculator._load_episode_script
                            # 对齐：I/O 缺失 + JSON/schema 解析失败 → 跳过此集，继续预加载其他集；
                            # 非预期异常（RuntimeError/MemoryError 等）让其冒泡到外层 try，走 basic info 兜底行。
                            logger.debug(
                                "list_projects 预加载剧本失败 project=%s script=%s err=%s",
                                name,
                                script_file,
                                load_err,
                            )

                    # 封面走 resolve_project_cover fallback 链：
                    # video_thumbnail → storyboard_image → scene_sheet → character_sheet
                    # —— 兼顾 reference / grid / storyboard 三种生成模式。
                    thumbnail = resolve_project_cover(manager, name, project, preloaded_scripts=preloaded_scripts)

                    # 使用 StatusCalculator 计算进度（读时计算）
                    status = calculator.calculate_project_status(name, project, preloaded_scripts=preloaded_scripts)

                    raw_title = project.get("title")
                    projects.append(
                        {
                            "name": name,
                            # title 缺失/为 None/类型异常时统一归一为空串,前端 i18n
                            # 兜底显示「未命名项目」,确保接口契约始终返回 str。
                            "title": raw_title if isinstance(raw_title, str) else "",
                            "style": project.get("style", ""),
                            "style_template_id": project.get("style_template_id"),
                            "style_image": project.get("style_image"),
                            "thumbnail": thumbnail,
                            "status": status,
                        }
                    )
                else:
                    # 没有 project.json 的项目
                    projects.append(
                        {
                            "name": name,
                            "title": "",
                            "style": "",
                            "thumbnail": None,
                            "status": {},
                        }
                    )
            except Exception as e:
                # 出错时返回基本信息
                logger.warning("加载项目 '%s' 元数据失败: %s", name, e)
                projects.append(
                    {"name": name, "title": "", "style": "", "thumbnail": None, "status": {}, "error": str(e)}
                )

        return {"projects": projects}

    return await asyncio.to_thread(_sync)


@router.post("/projects")
async def create_project(
    req: CreateProjectRequest,
    _user: CurrentUser,
    _t: Translator,
):
    """创建新项目"""
    try:

        def _sync():
            manager = get_project_manager()
            title = (req.title or "").strip()
            manual_name = (req.name or "").strip()
            if not title and not manual_name:
                raise HTTPException(status_code=400, detail=_t("title_required"))
            project_name = manual_name or manager.generate_project_name(title)

            style_prompt = (req.style or "").strip()
            favorite_style_template: dict | None = None
            if req.style_template_id:
                data_root = _manager_data_root(manager)
                if not is_known_template(req.style_template_id, data_root=data_root):
                    raise HTTPException(
                        status_code=400,
                        detail=_t("unknown_style_template", template_id=req.style_template_id),
                    )
                style_prompt = style_prompt or resolve_template_prompt(req.style_template_id, data_root=data_root)
                favorite_style_template = get_favorite_style_template(req.style_template_id, data_root=data_root)

            # legacy image_backend 已退役（拆为 image_provider_t2i/i2i）；写路径直接拒绝，
            # 避免迁移后再写时被解析链忽略、静默落到全局默认的另一供应商。
            if req.image_backend:
                raise HTTPException(status_code=400, detail=_t("deprecated_image_backend"))
            episode_target_units = _validate_episode_target_units(req.episode_target_units)
            resolve_script_splitting_profile(
                req.content_mode or "narration",
                req.generation_mode,
                req.script_splitting_template_id,
                data_root=_manager_data_root(manager),
            )

            # 与 update 路径对称：校验所有 backend 字段
            for field_name in (
                "video_backend",
                "image_provider_t2i",
                "image_provider_i2i",
                "text_backend_script",
                "text_backend_overview",
                "text_backend_style",
            ):
                value = getattr(req, field_name)
                if value:
                    validate_backend_value(value, field_name, _t)

            try:
                manager.create_project(project_name, content_mode=req.content_mode or "narration")
            except FileExistsError:
                raise HTTPException(status_code=400, detail=_t("project_exists", name=project_name))
            extras = {
                field: value
                for field in (
                    "video_backend",
                    "image_provider_t2i",
                    "image_provider_i2i",
                    "text_backend_script",
                    "text_backend_overview",
                    "text_backend_style",
                )
                if (value := getattr(req, field))
            }
            if req.model_settings is not None:
                extras["model_settings"] = req.model_settings
            if req.generation_profiles is not None:
                extras["generation_profiles"] = req.generation_profiles
            if req.video_service_tier is not None:
                extras["video_service_tier"] = req.video_service_tier
            if req.source_language is not None:
                extras["source_language"] = req.source_language
            if episode_target_units is not None:
                extras["episode_target_units"] = episode_target_units
            # generation_mode 是项目级固定选择，创建时一次性写入。
            extras["generation_mode"] = req.generation_mode
            metadata_style = style_prompt
            style_template_id = req.style_template_id
            if favorite_style_template is not None:
                extras.update(
                    _materialize_favorite_style_for_project(
                        manager,
                        project_name,
                        favorite_style_template,
                        style_prompt,
                        _t,
                    )
                )
                metadata_style = ""
                style_template_id = None
            with project_change_source("webui"):
                project = manager.create_project_metadata(
                    project_name,
                    title or manual_name,
                    metadata_style,
                    req.content_mode,
                    aspect_ratio=req.aspect_ratio,
                    default_duration=req.default_duration,
                    style_template_id=style_template_id,
                    script_splitting_template_id=req.script_splitting_template_id,
                    extras=extras or None,
                )
            return {"success": True, "name": project_name, "project": project}

        return await asyncio.to_thread(_sync)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{name}/video-capabilities")
async def get_video_capabilities(
    name: str,
    _user: CurrentUser,
    _t: Translator,
):
    """解析当前项目视频模型能力 + 用户项目偏好。

    三级模型选择（项目 > 系统设置 > 系统默认）后，读 model 的 `supported_durations`
    并派生 `max_duration`；同时带回 `project.json.default_duration`（用户偏好）。
    所有 generation_mode（storyboard/grid/reference_video）都可复用。
    """
    resolver = ConfigResolver(async_session_factory)
    try:
        return await resolver.video_capabilities(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=name)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=_t("video_capabilities_unresolved", name=name, reason=str(exc)),
        ) from exc


@router.post("/projects/{name}/script-splitting-template/preview")
async def preview_script_splitting_template_change(
    name: str,
    req: ScriptSplittingTemplateChangeRequest,
    _user: CurrentUser,
    _t: Translator,
):
    """预览拆分方案切换；已生成产物保留，仅未来未生成分集使用新方案。"""
    try:
        project = await asyncio.to_thread(get_project_manager().load_project, name)
        current_generation_mode = (
            project.get("generation_mode") if project.get("generation_mode") in {"storyboard", "grid", "reference_video"} else "storyboard"
        )
        if req.generation_mode and req.generation_mode != current_generation_mode:
            raise HTTPException(status_code=400, detail=_t("project_generation_mode_not_editable"))
        resolver = ConfigResolver(async_session_factory)
        try:
            provider_capabilities = await resolver.video_capabilities_for_project(project)
        except ValueError:
            provider_capabilities = None
        return {
            "success": True,
            "preview": preview_template_change(
                project,
                req.template_id,
                provider_capabilities=provider_capabilities,
                data_root=_manager_data_root(get_project_manager()),
                project_path=get_project_manager().get_project_path(name),
            ),
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{name}/script-splitting-template/apply")
@router.post("/projects/{name}/script-splitting-template")
async def change_script_splitting_template(
    name: str,
    req: ScriptSplittingTemplateChangeRequest,
    _user: CurrentUser,
    _t: Translator,
):
    """通过专用动作切换项目拆分方案；切换只影响未来未生成分集。"""
    try:
        project_for_caps = await asyncio.to_thread(get_project_manager().load_project, name)
        current_generation_mode = (
            project_for_caps.get("generation_mode")
            if project_for_caps.get("generation_mode") in {"storyboard", "grid", "reference_video"}
            else "storyboard"
        )
        if req.generation_mode and req.generation_mode != current_generation_mode:
            raise HTTPException(status_code=400, detail=_t("project_generation_mode_not_editable"))
        resolver = ConfigResolver(async_session_factory)
        try:
            provider_capabilities = await resolver.video_capabilities_for_project(project_for_caps)
        except ValueError:
            provider_capabilities = None
        if req.mode == "preview":
            return {
                "success": True,
                "preview": preview_template_change(
                    project_for_caps,
                    req.template_id,
                    provider_capabilities=provider_capabilities,
                    data_root=_manager_data_root(get_project_manager()),
                    project_path=get_project_manager().get_project_path(name),
                ),
            }

        def _sync():
            manager = get_project_manager()

            def _mutate(project: dict) -> None:
                preview = preview_template_change(
                    project,
                    req.template_id,
                    provider_capabilities=provider_capabilities,
                    data_root=_manager_data_root(manager),
                    project_path=manager.get_project_path(name),
                )
                profile = resolve_script_splitting_profile(
                    project.get("content_mode"),
                    project.get("generation_mode"),
                    req.template_id,
                    provider_capabilities=provider_capabilities,
                    data_root=_manager_data_root(manager),
                )
                project["script_splitting_template_id"] = profile["id"]
                project["script_splitting"] = snapshot_from_profile(profile)
                mark_template_change_stale_assets(
                    project,
                    preview=preview,
                    mode=req.mode,
                    data_root=_manager_data_root(manager),
                )

            with project_change_source("webui"):
                project = manager.update_project(name, _mutate)
            return {"success": True, "project": project}

        return await asyncio.to_thread(_sync)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=name))
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{name}/video-input-preflight")
async def video_input_preflight(
    name: str,
    req: VideoInputPreflightRequest,
    _user: CurrentUser,
    _t: Translator,
):
    """视频生成前规则型检查。视觉判断首版返回 manual / vision_ai_pending。"""
    try:
        project = await asyncio.to_thread(get_project_manager().load_project, name)
        resolver = ConfigResolver(async_session_factory)
        try:
            capabilities = await resolver.video_capabilities_for_project(project)
        except ValueError:
            capabilities = None
        result = run_video_input_preflight(
            project=project,
            capabilities=capabilities,
            request=req.model_dump(exclude_none=True),
        )
        return {"success": True, "preflight": result}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=name))


@router.get("/projects/{name}")
async def get_project(
    name: str,
    _user: CurrentUser,
    _t: Translator,
):
    """获取项目详情（含实时计算字段）"""
    try:

        def _sync():
            manager = get_project_manager()
            calculator = get_status_calculator()
            if not manager.project_exists(name):
                raise HTTPException(status_code=404, detail=_t("project_not_found", name=name))

            project = manager.load_project(name)

            # 注入计算字段（不写入 JSON，仅用于 API 响应）
            project = calculator.enrich_project(name, project)

            # 加载所有剧本并注入计算字段
            scripts = {}
            for ep in project.get("episodes", []):
                script_file = ep.get("script_file", "")
                if script_file:
                    try:
                        script = manager.load_script(name, script_file)
                        script = calculator.enrich_script(script)
                        key = (
                            script_file.replace("scripts/", "", 1)
                            if script_file.startswith("scripts/")
                            else script_file
                        )
                        scripts[key] = script
                    except FileNotFoundError:
                        logger.debug("剧本文件不存在，跳过: %s/%s", name, script_file)

            # 计算媒体文件指纹（用于前端内容寻址缓存）
            project_path = manager.get_project_path(name)
            fingerprints = compute_asset_fingerprints(project_path)

            return {
                "project": project,
                "scripts": scripts,
                "asset_fingerprints": fingerprints,
            }

        return await asyncio.to_thread(_sync)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=name))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/projects/{name}")
async def update_project(name: str, req: UpdateProjectRequest, _user: CurrentUser, _t: Translator):
    """更新项目元数据"""
    try:

        def _sync():
            manager = get_project_manager()
            if req.content_mode is not None:
                raise HTTPException(
                    status_code=400,
                    detail=_t("project_id_not_editable"),
                )
            if "generation_mode" in req.model_fields_set:
                raise HTTPException(
                    status_code=400,
                    detail=_t("project_generation_mode_not_editable"),
                )
            if "script_splitting_template_id" in req.model_fields_set:
                raise HTTPException(
                    status_code=400,
                    detail="普通项目 PATCH 不支持直接修改拆分方案，请使用专用模板切换接口",
                )

            # legacy image_backend 已退役（拆为 image_provider_t2i/i2i）；写路径直接拒绝，
            # 避免迁移后再写时被解析链忽略、静默落到全局默认的另一供应商。
            if req.image_backend:
                raise HTTPException(status_code=400, detail=_t("deprecated_image_backend"))

            def _mutate(project: dict) -> None:
                # 整段 read-modify-write 在单一 _project_lock 内完成，避免并发 PATCH / 任务回写丢更新
                if req.title is not None:
                    project["title"] = req.title
                style_override = (req.style or "").strip() if req.style is not None else None
                if "style" in req.model_fields_set and "style_template_id" not in req.model_fields_set:
                    project["style"] = style_override or ""
                for field in (
                    "video_backend",
                    "image_provider_t2i",
                    "image_provider_i2i",
                    "text_backend_script",
                    "text_backend_overview",
                    "text_backend_style",
                ):
                    if field in req.model_fields_set:
                        value = getattr(req, field)
                        if value:
                            validate_backend_value(value, field, _t)
                            project[field] = value
                        else:
                            project.pop(field, None)

                if "video_generate_audio" in req.model_fields_set:
                    if req.video_generate_audio is None:
                        project.pop("video_generate_audio", None)
                    else:
                        project["video_generate_audio"] = req.video_generate_audio
                if "aspect_ratio" in req.model_fields_set and req.aspect_ratio is not None:
                    project["aspect_ratio"] = req.aspect_ratio
                if "default_duration" in req.model_fields_set:
                    if req.default_duration is None:
                        project.pop("default_duration", None)
                    else:
                        project["default_duration"] = req.default_duration
                if "episode_target_units" in req.model_fields_set:
                    episode_target_units = _validate_episode_target_units(req.episode_target_units)
                    if episode_target_units is None:
                        project.pop("episode_target_units", None)
                    else:
                        project["episode_target_units"] = episode_target_units
                if "source_language" in req.model_fields_set:
                    if req.source_language is None:
                        project.pop("source_language", None)
                    else:
                        project["source_language"] = req.source_language

                if "style_template_id" in req.model_fields_set:
                    if req.style_template_id is None:
                        # 取消模版选择：同时清掉展开的 style prompt，避免遗留孤儿文本
                        project.pop("style_template_id", None)
                        project["style"] = style_override or ""
                    else:
                        data_root = _manager_data_root(manager)
                        if not is_known_template(req.style_template_id, data_root=data_root):
                            raise HTTPException(
                                status_code=400,
                                detail=_t("unknown_style_template", template_id=req.style_template_id),
                            )
                        favorite_style_template = get_favorite_style_template(req.style_template_id, data_root=data_root)
                        if favorite_style_template is not None:
                            style_prompt = style_override or str(favorite_style_template.get("prompt") or "").strip()
                            project.pop("style_template_id", None)
                            project["style"] = ""
                            project.update(
                                _materialize_favorite_style_for_project(
                                    manager,
                                    name,
                                    favorite_style_template,
                                    style_prompt,
                                    _t,
                                )
                            )
                        else:
                            project["style_template_id"] = req.style_template_id
                            project["style"] = style_override or resolve_template_prompt(
                                req.style_template_id,
                                data_root=data_root,
                            )
                            # 强互斥:模版与参考图二选一
                            project.pop("style_image", None)
                            project.pop("style_description", None)

                if req.clear_style_image:
                    # 显式清除自定义参考图，用于"清空风格"流程
                    project.pop("style_image", None)
                    project.pop("style_description", None)

                if "style_description" in req.model_fields_set and not req.clear_style_image:
                    if req.style_description is None:
                        project.pop("style_description", None)
                    elif project.get("style_image"):
                        project["style_description"] = req.style_description.strip()
                        project.pop("style_template_id", None)
                        project["style"] = ""
                    else:
                        project.pop("style_description", None)

                if "model_settings" in req.model_fields_set:
                    if req.model_settings is None:
                        project.pop("model_settings", None)
                    else:
                        project["model_settings"] = req.model_settings

                if "generation_profiles" in req.model_fields_set:
                    if req.generation_profiles is None:
                        project.pop("generation_profiles", None)
                    else:
                        project["generation_profiles"] = req.generation_profiles

                if "video_service_tier" in req.model_fields_set:
                    if req.video_service_tier is None:
                        project.pop("video_service_tier", None)
                    else:
                        project["video_service_tier"] = req.video_service_tier

                if "episodes" in req.model_fields_set and req.episodes is not None:
                    # 合并 episodes：保留现有 episode 的完整数据，仅更新请求中显式提供的字段。
                    # generation_mode 是项目级固定选择，分集不得覆盖，避免混合模式项目。
                    # 白名单同时拦截 StatusCalculator 注入的计算字段（scenes_count / status
                    # / storyboards / videos 等），防止写回 project.json。
                    existing_list = project.get("episodes", [])
                    patch_map: dict[int, EpisodePatch] = {}
                    for ep in req.episodes:
                        if "generation_mode" in ep.model_fields_set:
                            raise HTTPException(
                                status_code=400,
                                detail=_t("project_generation_mode_not_editable"),
                            )
                        patch_map[ep.episode] = ep  # 重复编号：后者覆盖前者

                    new_episodes: list[dict] = []
                    for existing_ep in existing_list:
                        ep_num = existing_ep.get("episode")
                        patch = patch_map.pop(ep_num, None)
                        if patch is None:
                            new_episodes.append(existing_ep)
                            continue
                        updated = dict(existing_ep)
                        for field_name in EPISODE_PERSIST_FIELDS:
                            if field_name not in patch.model_fields_set:
                                continue
                            value = getattr(patch, field_name)
                            if value is None:
                                updated.pop(field_name, None)
                            else:
                                updated[field_name] = value
                        new_episodes.append(updated)

                    for unknown_ep in patch_map:
                        logger.warning("Skipping patch for unknown episode %s", unknown_ep)

                    project["episodes"] = new_episodes

            with project_change_source("webui"):
                # update_project 已在持锁窗口内统一应用迁移，返回升级后字段，无需二次 load_project
                return {"success": True, "project": manager.update_project(name, _mutate)}

        return await asyncio.to_thread(_sync)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=name))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/projects/{name}")
async def delete_project(name: str, _user: CurrentUser, _t: Translator):
    """删除项目"""
    try:

        def _sync():
            project_dir = get_project_manager().get_project_path(name)
            shutil.rmtree(project_dir)
            return {"success": True, "message": _t("project_deleted", name=name)}

        return await asyncio.to_thread(_sync)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=name))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{name}/scripts/{script_file}")
async def get_script(name: str, script_file: str, _user: CurrentUser, _t: Translator):
    """获取剧本内容"""
    try:
        script = await asyncio.to_thread(get_project_manager().load_script, name, script_file)
        return {"script": script}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("script_not_found", name=script_file))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


class UpdateSceneRequest(BaseModel):
    script_file: str
    updates: dict


@router.patch("/projects/{name}/script-scenes/{scene_id}")
async def update_scene(name: str, scene_id: str, req: UpdateSceneRequest, _user: CurrentUser, _t: Translator):
    """更新 drama 模式剧本中的单个场景镜头（按 scene_id 定位）。

    路径与项目场景资产 CRUD（``/projects/{name}/scenes/{entry_name}``）做明确区分，
    避免 FastAPI 按注册顺序优先匹配本端点导致 SceneCard 保存请求被截获、Pydantic
    必填字段校验返回双 "Field required"。
    """
    try:

        def _sync():
            manager = get_project_manager()

            # 整段 RMW 在单一 _script_lock 内完成；未命中时在锁内 raise，跳过写回
            matched_scene: dict[str, Any] | None = None
            with project_change_source("webui"):
                with manager.locked_script(name, req.script_file) as script:
                    for scene in script.get("scenes", []):
                        if scene.get("scene_id") == scene_id:
                            matched_scene = scene
                            # 更新允许的字段
                            for key, value in req.updates.items():
                                if key in [
                                    "duration_seconds",
                                    "image_prompt",
                                    "video_prompt",
                                    "characters_in_scene",
                                    "scenes",
                                    "props",
                                    "storyboard_generation",
                                    "video_generation",
                                    "segment_break",
                                    "note",
                                ]:
                                    if value is None and key != "note":
                                        continue
                                    scene[key] = value
                            break

                    if matched_scene is None:
                        raise HTTPException(status_code=404, detail=_t("scene_not_found", id=scene_id))
            return {"success": True, "scene": matched_scene}

        return await asyncio.to_thread(_sync)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("script_not_found", name=req.script_file))
    except ValueError as exc:
        # 结构校验失败、集号错配、非法文件名都抛 ValueError（ScriptStructureValidationError
        # 即其子类）：统一转 422 客户端错误，避免落到下面的 500 兜底。
        raise HTTPException(
            status_code=422,
            detail=_t("script_validation_failed", details=str(exc)),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


class UpdateSegmentRequest(BaseModel):
    script_file: str
    duration_seconds: int | None = None
    segment_break: bool | None = None
    image_prompt: dict | str | None = None
    video_prompt: dict | str | None = None
    transition_to_next: str | None = None
    storyboard_generation: dict[str, Any] | None = None
    video_generation: dict[str, Any] | None = None
    note: str | None = None
    characters_in_segment: list[str] | None = None
    scenes: list[str] | None = None
    props: list[str] | None = None


class UpdateOverviewRequest(BaseModel):
    synopsis: str | None = None
    genre: str | None = None
    theme: str | None = None
    world_setting: str | None = None


@router.patch("/projects/{name}/segments/{segment_id}")
async def update_segment(name: str, segment_id: str, req: UpdateSegmentRequest, _user: CurrentUser, _t: Translator):
    """更新说书模式片段"""
    try:

        def _sync():
            manager = get_project_manager()

            # 整段 RMW 在单一 _script_lock 内完成；模式不符 / 未命中时在锁内 raise，跳过写回
            matched_segment: dict[str, Any] | None = None
            with project_change_source("webui"):
                with manager.locked_script(name, req.script_file) as script:
                    # 检查是否为说书模式：仅 narration 且含 segments 键才放行；
                    # drama 脚本即使残留 segments 键也拒绝，避免被当 narration 改写
                    if script.get("content_mode") != "narration" or "segments" not in script:
                        raise HTTPException(status_code=400, detail=_t("narration_mode_required"))

                    for segment in script.get("segments", []):
                        if segment.get("segment_id") == segment_id:
                            matched_segment = segment
                            if req.duration_seconds is not None:
                                segment["duration_seconds"] = req.duration_seconds
                            if req.segment_break is not None:
                                segment["segment_break"] = req.segment_break
                            if req.image_prompt is not None:
                                segment["image_prompt"] = req.image_prompt
                            if req.video_prompt is not None:
                                segment["video_prompt"] = req.video_prompt
                            if req.transition_to_next is not None:
                                segment["transition_to_next"] = req.transition_to_next
                            if "storyboard_generation" in req.model_fields_set:
                                segment["storyboard_generation"] = req.storyboard_generation or {}
                            if "video_generation" in req.model_fields_set:
                                segment["video_generation"] = req.video_generation or {}
                            if "note" in req.model_fields_set:
                                segment["note"] = req.note
                            for field in ("characters_in_segment", "scenes", "props"):
                                if field in req.model_fields_set:
                                    segment[field] = getattr(req, field) or []
                            break

                    if matched_segment is None:
                        raise HTTPException(status_code=404, detail=_t("segment_not_found", id=segment_id))
            return {"success": True, "segment": matched_segment}

        return await asyncio.to_thread(_sync)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("script_not_found", name=req.script_file))
    except ValueError as exc:
        # 结构校验失败、集号错配、非法文件名都抛 ValueError（ScriptStructureValidationError
        # 即其子类）：统一转 422 客户端错误，避免落到下面的 500 兜底。
        raise HTTPException(
            status_code=422,
            detail=_t("script_validation_failed", details=str(exc)),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 源文件管理 ====================


@router.post("/projects/{name}/source")
async def set_project_source(
    name: Annotated[str, FastAPIPath(pattern=r"^[a-zA-Z0-9_-]+$")],
    _user: CurrentUser,
    _t: Translator,
    generate_overview: Annotated[bool, Form()] = True,
    content: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
):
    """上传小说源文件或直接提交文本内容，可选触发 AI 概述生成。

    两种输入方式（互斥，均使用 multipart/form-data）：
    - file：上传 .txt/.md 文件，文件名取自上传文件
    - content：直接提交文本内容，自动命名为 novel.txt

    最大 200000 字符（约 10 万汉字）。
    """
    MAX_CHARS = 200_000
    ALLOWED_SUFFIXES = {".txt", ".md"}

    if not content and not file:
        raise HTTPException(status_code=400, detail=_t("content_or_file_required"))
    if content and file:
        raise HTTPException(status_code=400, detail=_t("one_of_content_or_file"))

    try:
        manager = get_project_manager()

        # 异步读取上传文件
        raw: bytes | None = None
        original_name: str = "novel.txt"
        if file:
            original_name = file.filename or "novel.txt"
            suffix = Path(original_name).suffix.lower()
            if suffix not in ALLOWED_SUFFIXES:
                raise HTTPException(status_code=400, detail=_t("unsupported_file_type", name=suffix))
            if file.size is not None and file.size > MAX_CHARS * 4:
                raise HTTPException(status_code=400, detail=_t("file_too_large", max_chars=MAX_CHARS))
            raw = await asyncio.to_thread(read_upload_bytes, file)
        text_content: str = content or ""

        # 同步文件 I/O 在线程中执行
        def _sync_write():
            if not manager.project_exists(name):
                raise HTTPException(status_code=404, detail=_t("project_not_found", name=name))
            project_dir = manager.get_project_path(name)
            source_dir = project_dir / "source"
            source_dir.mkdir(parents=True, exist_ok=True)

            if raw is not None:
                safe_filename = Path(original_name).name
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    raise HTTPException(status_code=400, detail=_t("invalid_encoding"))
                if len(text) > MAX_CHARS:
                    raise HTTPException(status_code=400, detail=_t("file_too_large", max_chars=MAX_CHARS))
                (source_dir / safe_filename).write_text(text, encoding="utf-8")
                return safe_filename, len(text)
            else:
                if len(text_content) > MAX_CHARS:
                    raise HTTPException(status_code=400, detail=_t("file_too_large", max_chars=MAX_CHARS))
                safe_filename = "novel.txt"
                (source_dir / safe_filename).write_text(text_content, encoding="utf-8")
                return safe_filename, len(text_content)

        safe_filename, chars = await asyncio.to_thread(_sync_write)

        result: dict = {"success": True, "filename": safe_filename, "chars": chars}

        if generate_overview:
            try:
                with project_change_source("webui"):
                    overview = await manager.generate_overview(name)
                result["overview"] = overview
            except Exception as ov_err:
                result["overview"] = None
                result["overview_error"] = str(ov_err)

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if file:
            await file.close()


# ==================== 项目概述管理 ====================


@router.post("/projects/{name}/generate-overview")
async def generate_overview(name: str, _user: CurrentUser, _t: Translator):
    """使用 AI 生成项目概述"""
    try:
        with project_change_source("webui"):
            overview = await get_project_manager().generate_overview(name)
        return {"success": True, "overview": overview}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=name))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/projects/{name}/overview")
async def update_overview(name: str, req: UpdateOverviewRequest, _user: CurrentUser, _t: Translator):
    """更新项目概述（手动编辑）"""
    try:

        def _sync():
            manager = get_project_manager()
            captured: dict[str, Any] = {}

            def _mutate(project: dict) -> None:
                # 整段 RMW 在单一 _project_lock 内完成，避免与并发生成的 overview 回写互相覆盖
                if "overview" not in project:
                    project["overview"] = {}
                if req.synopsis is not None:
                    project["overview"]["synopsis"] = req.synopsis
                if req.genre is not None:
                    project["overview"]["genre"] = req.genre
                if req.theme is not None:
                    project["overview"]["theme"] = req.theme
                if req.world_setting is not None:
                    project["overview"]["world_setting"] = req.world_setting
                captured["overview"] = project["overview"]

            with project_change_source("webui"):
                manager.update_project(name, _mutate)
            return {"success": True, "overview": captured["overview"]}

        return await asyncio.to_thread(_sync)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=name))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))

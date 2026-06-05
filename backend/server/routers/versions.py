"""
版本管理 API 路由

处理版本查询和还原请求。
"""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

logger = logging.getLogger(__name__)

from lib.app_data_dir import app_data_dir
from lib.asset_types import ASSET_SPECS
from lib.i18n import Translator
from lib.image_utils import convert_image_bytes_to_png, save_image_file_as_png
from lib.project_change_hints import emit_project_change_batch, project_change_source
from lib.project_manager import ProjectManager
from lib.resource_paths import resource_relative_path
from lib.script_editor import ScriptEditError
from lib.script_splitting_templates import script_splitting_asset_metadata
from lib.storyboard_sequence import find_storyboard_item, get_storyboard_items
from lib.thumbnail import extract_video_thumbnail
from lib.upload_utils import copy_upload_file, local_upload_path, read_upload_bytes
from lib.version_manager import VersionManager
from server.auth import CurrentUser
from server.services.design_resource_usage import (
    RESOURCE_TO_ASSET_TYPE as _RESOURCE_TO_ASSET_TYPE,
)
from server.services.design_resource_usage import (
    asset_entry as _asset_entry,
)
from server.services.design_resource_usage import (
    ensure_design_resource_type as _ensure_design_resource_type,
)
from server.services.design_resource_usage import (
    find_design_resource_usages as _find_design_resource_usages,
)
from server.services.generation_tasks import (
    _normalize_storyboard_prompt,
    _normalize_video_prompt,
    get_aspect_ratio,
    resolve_video_prompt_policy,
)

router = APIRouter()

# 初始化项目管理器
pm = ProjectManager(app_data_dir())

# 经此路由可还原的资源类型（API 面策略）。路径形状委托 lib.resource_paths，但本路由
# 仅放行有还原后元数据同步分支的这五类；grids/reference_videos 的还原是独立议题。
_RESTORABLE_RESOURCE_TYPES = frozenset({"storyboards", "videos", "characters", "scenes", "props"})
_EXTERNAL_UPLOAD_RESOURCE_TYPES = frozenset({"storyboards", "videos"})
_EXTERNAL_UPLOAD_EXTENSIONS = {
    "storyboards": frozenset({".png", ".jpg", ".jpeg", ".webp"}),
    "videos": frozenset({".mp4"}),
}
_CURRENT_VERSION_BACKFILL_METADATA = {"version_origin": "current_asset_backfill"}


def get_project_manager() -> ProjectManager:
    return pm


def get_version_manager(project_name: str) -> VersionManager:
    """获取项目的版本管理器"""
    project_path = get_project_manager().get_project_path(project_name)
    return VersionManager(project_path)


def _resolve_resource_path(
    resource_type: str,
    resource_id: str,
    project_path: Path,
    _t: Callable[..., str],
) -> tuple[Path, str]:
    """返回 (current_file_absolute, relative_file_path)；资源类型不可还原或 ID 越界时抛出 HTTPException。"""
    if resource_type not in _RESTORABLE_RESOURCE_TYPES:
        raise HTTPException(status_code=400, detail=_t("unsupported_resource_type", resource_type=resource_type))
    relative = resource_relative_path(resource_type, resource_id)
    current_file = project_path / relative
    # 路径遍历防护：resource_id 拼出的绝对路径不得逃出项目目录（与 MediaGenerator._get_output_path 对齐）。
    try:
        current_file.resolve().relative_to(project_path.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail=_t("invalid_resource_id", resource_id=resource_id))
    return current_file, relative


def _backfill_current_version_if_needed(
    *,
    project_name: str,
    resource_type: str,
    resource_id: str,
    version_manager: VersionManager,
    versions_info: dict[str, Any],
) -> dict[str, Any]:
    """Register legacy current files that predate per-resource version tracking."""
    if versions_info.get("current_version", 0) > 0 or resource_type not in _RESTORABLE_RESOURCE_TYPES:
        return versions_info

    project_path = get_project_manager().get_project_path(project_name)
    current_file, _ = _resolve_resource_path(resource_type, resource_id, project_path, lambda key, **_kw: key)
    if not current_file.is_file():
        return versions_info

    created_version = version_manager.ensure_current_tracked(
        resource_type=resource_type,
        resource_id=resource_id,
        current_file=current_file,
        prompt="",
        **_CURRENT_VERSION_BACKFILL_METADATA,
    )
    if created_version is None:
        return versions_info
    return version_manager.get_versions(resource_type, resource_id)


def _sync_storyboard_metadata(
    project_name: str,
    resource_id: str,
    file_path: str,
    project_path: Path,
) -> None:
    scripts_dir = project_path / "scripts"
    if not scripts_dir.exists():
        return
    for script_file in scripts_dir.glob("*.json"):
        try:
            with project_change_source("webui"):
                get_project_manager().update_scene_asset(
                    project_name=project_name,
                    script_filename=script_file.name,
                    scene_id=resource_id,
                    asset_type="storyboard_image",
                    asset_path=file_path,
                )
        except KeyError:
            continue
        except ScriptEditError as exc:
            logger.warning("跨集同步元数据跳过脏脚本 %s: %s", script_file.name, exc)
            continue
        except OSError as exc:
            logger.warning("跨集同步元数据 sibling 集 %s IO 失败: %s", script_file.name, exc)
            continue


def _safe_project_file(project_path: Path, rel_path: str) -> Path:
    candidate = (project_path / rel_path).resolve()
    try:
        candidate.relative_to(project_path.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"资源路径越界: {rel_path}") from exc
    return candidate


def _collect_design_file_paths(
    resource_type: str,
    resource_id: str,
    asset_type: str,
    entry: dict,
) -> list[str]:
    spec = ASSET_SPECS[asset_type]
    candidates = [
        entry.get(spec.sheet_field),
        resource_relative_path(resource_type, resource_id),
    ]
    if asset_type == "character":
        candidates.append(entry.get("reference_image"))

    rel_paths: list[str] = []
    seen: set[str] = set()
    for rel_path in candidates:
        if not isinstance(rel_path, str) or not rel_path:
            continue
        if rel_path not in seen:
            seen.add(rel_path)
            rel_paths.append(rel_path)
    return rel_paths


def _delete_project_files_best_effort(
    project_path: Path,
    rel_paths: list[str],
) -> tuple[dict[str, int], list[str], list[dict[str, str]]]:
    asset_fingerprints: dict[str, int] = {}
    failed_files: list[str] = []
    file_delete_errors: list[dict[str, str]] = []
    for rel_path in rel_paths:
        try:
            path = _safe_project_file(project_path, rel_path)
            if path.exists():
                if not path.is_file():
                    raise ValueError(f"资源路径不是文件: {rel_path}")
                path.unlink()
            asset_fingerprints[rel_path] = 0
        except Exception as exc:
            print(f"[versions] 删除项目文件失败 {rel_path}: {exc}", flush=True)
            failed_files.append(rel_path)
            file_delete_errors.append({"file": rel_path, "message": str(exc)})
            asset_fingerprints[rel_path] = 0
    return asset_fingerprints, failed_files, file_delete_errors


def _sync_metadata(
    resource_type: str,
    project_name: str,
    resource_id: str,
    file_path: str,
    project_path: Path,
) -> None:
    """还原后同步元数据，确保引用指向统一文件路径。"""
    asset_type = _RESOURCE_TO_ASSET_TYPE.get(resource_type)
    if asset_type is not None:
        try:
            with project_change_source("webui"):
                get_project_manager()._update_asset_sheet(asset_type, project_name, resource_id, file_path)
        except KeyError:
            pass  # 资产条目可能已从 project.json 删除，跳过元数据同步
    elif resource_type == "storyboards":
        _sync_storyboard_metadata(project_name, resource_id, file_path, project_path)


def _require_upload_filename(file: UploadFile) -> str:
    filename = file.filename
    if not filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    return filename


def _coerce_duration_seconds(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _script_media_version_payload(
    resource_type: str,
    project: dict,
    script: dict,
    resource_id: str,
    video_prompt_policy=None,
) -> tuple[str, dict[str, Any]]:
    try:
        items, id_field, char_field, _, _ = get_storyboard_items(script)
        resolved = find_storyboard_item(items, id_field, resource_id)
        if resolved is None:
            raise ValueError(f"未找到当前分镜/场景: {resource_id}")
        item, _ = resolved
        splitting_metadata = script_splitting_asset_metadata(project)
        if resource_type == "storyboards":
            prompt = _normalize_storyboard_prompt(item.get("image_prompt"), project.get("style", ""))
            return prompt, {
                "aspect_ratio": get_aspect_ratio(project, "storyboards"),
                **splitting_metadata,
            }

        prompt = _normalize_video_prompt(
            item.get("video_prompt"),
            project=project,
            target_item=item,
            char_field=char_field,
            policy=video_prompt_policy,
        )
        duration_seconds = _coerce_duration_seconds(item.get("duration_seconds"))
        if duration_seconds is None:
            duration_seconds = _coerce_duration_seconds(project.get("default_duration"))
        metadata = dict(splitting_metadata)
        if duration_seconds is not None:
            metadata["duration_seconds"] = duration_seconds
        return prompt, metadata
    except (ValueError, ScriptEditError):
        raise
    except Exception as exc:
        logger.warning("读取上传前媒体 prompt 失败 resource=%s/%s", resource_type, resource_id, exc_info=True)
        raise ValueError("无法读取当前分镜/视频提示词，上传版本未保存") from exc


def _emit_media_upload_change(
    *,
    project_name: str,
    resource_type: str,
    resource_id: str,
    script_file: str,
    episode: int | None,
    asset_fingerprints: dict[str, int],
) -> None:
    action = "storyboard_ready" if resource_type == "storyboards" else "video_ready"
    label = "分镜图" if resource_type == "storyboards" else "视频"
    try:
        emit_project_change_batch(
            project_name,
            [
                {
                    "entity_type": "segment",
                    "action": action,
                    "entity_id": resource_id,
                    "label": f"分镜「{resource_id}」{label}",
                    "script_file": script_file,
                    "episode": episode,
                    "focus": None,
                    "important": True,
                    "asset_fingerprints": asset_fingerprints,
                }
            ],
            source="webui",
        )
    except Exception:
        logger.exception("发送外部上传项目事件失败 project=%s resource=%s/%s", project_name, resource_type, resource_id)


# ==================== 版本查询 ====================


@router.get("/projects/{project_name}/versions/{resource_type}/{resource_id}/usage")
async def get_design_resource_usage(
    project_name: str,
    resource_type: str,
    resource_id: str,
    _user: CurrentUser,
):
    """检查项目级角色/场景/道具设计图是否被剧本实际引用。"""
    try:

        def _sync():
            _ensure_design_resource_type(resource_type)
            manager = get_project_manager()
            project = manager.load_project(project_name)
            _asset_entry(project, resource_type, resource_id)
            usages = _find_design_resource_usages(
                manager=manager,
                project_name=project_name,
                project=project,
                resource_type=resource_type,
                resource_id=resource_id,
            )
            return {
                "resource_type": resource_type,
                "resource_id": resource_id,
                "in_use": bool(usages),
                "usages": usages,
            }

        return await asyncio.to_thread(_sync)

    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_name}/versions/{resource_type}/{resource_id}")
async def get_versions(
    project_name: str,
    resource_type: str,
    resource_id: str,
    _user: CurrentUser,
):
    """
    获取资源的所有版本列表

    Args:
        project_name: 项目名称
        resource_type: 资源类型 (storyboards, videos, characters, scenes, props)
        resource_id: 资源 ID
    """
    try:

        def _sync():
            vm = get_version_manager(project_name)
            versions_info = vm.get_versions(resource_type, resource_id)
            versions_info = _backfill_current_version_if_needed(
                project_name=project_name,
                resource_type=resource_type,
                resource_id=resource_id,
                version_manager=vm,
                versions_info=versions_info,
            )
            return {"resource_type": resource_type, "resource_id": resource_id, **versions_info}

        return await asyncio.to_thread(_sync)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 设计图删除 ====================


@router.delete("/projects/{project_name}/versions/{resource_type}/{resource_id}")
async def delete_design_resource(
    project_name: str,
    resource_type: str,
    resource_id: str,
    _user: CurrentUser,
):
    """删除整张角色/场景/道具设计图及其全部历史版本。"""
    try:

        def _sync():
            _ensure_design_resource_type(resource_type)
            manager = get_project_manager()
            project_path = manager.get_project_path(project_name)
            project = manager.load_project(project_name)
            asset_type, entry = _asset_entry(project, resource_type, resource_id)

            usages = _find_design_resource_usages(
                manager=manager,
                project_name=project_name,
                project=project,
                resource_type=resource_type,
                resource_id=resource_id,
            )
            if usages:
                raise HTTPException(status_code=409, detail="已应用，无法删除")

            spec = ASSET_SPECS[asset_type]
            rel_paths = _collect_design_file_paths(resource_type, resource_id, asset_type, entry)
            version_manager = get_version_manager(project_name)

            def _mutate(project_doc: dict) -> None:
                bucket = project_doc.get(spec.bucket_key)
                if not isinstance(bucket, dict) or resource_id not in bucket:
                    raise KeyError(resource_id)
                bucket.pop(resource_id)

            with project_change_source("webui"):
                manager.update_project(project_name, _mutate)

            asset_fingerprints, failed_files, file_delete_errors = _delete_project_files_best_effort(
                project_path,
                rel_paths,
            )
            version_result = version_manager.delete_resource(resource_type, resource_id)
            for rel_path in version_result.get("deleted_files", []):
                if isinstance(rel_path, str):
                    asset_fingerprints[rel_path] = 0
            failed_files.extend(item for item in version_result.get("failed_files", []) if isinstance(item, str))
            file_delete_errors.extend(
                item for item in version_result.get("file_delete_errors", []) if isinstance(item, dict)
            )

            return {
                "success": True,
                "resource_type": resource_type,
                "resource_id": resource_id,
                **version_result,
                "failed_files": failed_files,
                "file_delete_errors": file_delete_errors,
                "asset_fingerprints": asset_fingerprints,
            }

        return await asyncio.to_thread(_sync)

    except HTTPException:
        raise
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"设计图不存在: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 版本还原 ====================


@router.post("/projects/{project_name}/versions/{resource_type}/{resource_id}/restore/{version}")
async def restore_version(
    project_name: str,
    resource_type: str,
    resource_id: str,
    version: int,
    _user: CurrentUser,
    _t: Translator,
):
    """
    切换到指定版本

    会将指定版本复制到当前路径，并把当前版本指针切换到该版本。

    Args:
        project_name: 项目名称
        resource_type: 资源类型
        resource_id: 资源 ID
        version: 要还原的版本号
    """
    try:

        def _sync():
            vm = get_version_manager(project_name)
            project_path = get_project_manager().get_project_path(project_name)
            current_file, file_path = _resolve_resource_path(resource_type, resource_id, project_path, _t)

            result = vm.restore_version(
                resource_type=resource_type,
                resource_id=resource_id,
                version=version,
                current_file=current_file,
            )

            _sync_metadata(resource_type, project_name, resource_id, file_path, project_path)

            # 计算还原后文件的 fingerprint；视频还原时同步删除缩略图（内容已失效）
            asset_fingerprints: dict[str, int] = {}
            if current_file.exists():
                asset_fingerprints[file_path] = current_file.stat().st_mtime_ns

            if resource_type == "videos":
                thumbnail_path = project_path / "thumbnails" / f"scene_{resource_id}.jpg"
                thumbnail_key = f"thumbnails/scene_{resource_id}.jpg"
                thumbnail_path.unlink(missing_ok=True)
                # fingerprint=0 通知前端该文件已失效（poster 消失直到重新生成）
                asset_fingerprints[thumbnail_key] = 0

            return {
                "success": True,
                **result,
                "file_path": file_path,
                "asset_fingerprints": asset_fingerprints,
            }

        return await asyncio.to_thread(_sync)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 版本删除 ====================


@router.post("/projects/{project_name}/versions/{resource_type}/{resource_id}/upload")
async def upload_external_media_version(
    project_name: str,
    resource_type: str,
    resource_id: str,
    _user: CurrentUser,
    _t: Translator,
    script_file: str = Form(...),
    file: UploadFile = File(...),
):
    """上传外部生成的分镜图/视频，并作为当前资源的新版本登记。"""
    try:
        if resource_type not in _EXTERNAL_UPLOAD_RESOURCE_TYPES:
            raise HTTPException(status_code=400, detail=f"不支持外部上传的资源类型: {resource_type}")

        original_filename = _require_upload_filename(file)
        ext = Path(original_filename).suffix.lower()
        if ext not in _EXTERNAL_UPLOAD_EXTENSIONS[resource_type]:
            allowed = ", ".join(sorted(_EXTERNAL_UPLOAD_EXTENSIONS[resource_type]))
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext or '无扩展名'}，允许: {allowed}")

        video_prompt_policy = None
        if resource_type == "videos":
            manager = get_project_manager()
            project_for_policy = await asyncio.to_thread(manager.load_project, project_name)
            video_prompt_policy = await resolve_video_prompt_policy(project_for_policy, project_name=project_name)

        def _write_current() -> dict[str, Any]:
            manager = get_project_manager()
            project = manager.load_project(project_name)
            project_path = manager.get_project_path(project_name)
            script = manager.load_script(project_name, script_file)
            episode = script.get("episode") if isinstance(script.get("episode"), int) else None
            current_file, rel_path = _resolve_resource_path(resource_type, resource_id, project_path, _t)
            current_file.parent.mkdir(parents=True, exist_ok=True)

            version_manager = get_version_manager(project_name)
            version_prompt, version_metadata = _script_media_version_payload(
                resource_type,
                project,
                script,
                resource_id,
                video_prompt_policy=video_prompt_policy,
            )
            if current_file.exists():
                version_manager.ensure_current_tracked(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    current_file=current_file,
                    prompt=version_prompt,
                    **version_metadata,
                )

            if resource_type == "storyboards":
                try:
                    source_path = local_upload_path(file)
                    if source_path is not None:
                        if source_path.stat().st_size <= 0:
                            raise HTTPException(status_code=400, detail="上传文件为空")
                        save_image_file_as_png(source_path, current_file)
                    else:
                        content = read_upload_bytes(file)
                        if not content:
                            raise HTTPException(status_code=400, detail="上传文件为空")
                        current_file.write_bytes(convert_image_bytes_to_png(content))
                except ValueError:
                    raise HTTPException(status_code=400, detail="无效的图片文件")
                with project_change_source("webui"):
                    manager.update_scene_asset(
                        project_name=project_name,
                        script_filename=script_file,
                        scene_id=resource_id,
                        asset_type="storyboard_image",
                        asset_path=rel_path,
                    )
            else:
                copy_upload_file(file, current_file)
                if not current_file.exists() or current_file.stat().st_size <= 0:
                    current_file.unlink(missing_ok=True)
                    raise HTTPException(status_code=400, detail="上传文件为空")
                with project_change_source("webui"):
                    manager.update_scene_asset(
                        project_name=project_name,
                        script_filename=script_file,
                        scene_id=resource_id,
                        asset_type="video_clip",
                        asset_path=rel_path,
                    )
                    manager.update_scene_asset(
                        project_name=project_name,
                        script_filename=script_file,
                        scene_id=resource_id,
                        asset_type="video_uri",
                        asset_path=None,
                    )

            version = version_manager.add_version(
                resource_type=resource_type,
                resource_id=resource_id,
                prompt=version_prompt,
                source_file=current_file,
                **version_metadata,
            )
            versions = version_manager.get_versions(resource_type, resource_id)["versions"]
            created_at = versions[-1]["created_at"] if versions else None
            asset_fingerprints = {rel_path: current_file.stat().st_mtime_ns}

            return {
                "project_path": project_path,
                "current_file": current_file,
                "rel_path": rel_path,
                "version": version,
                "created_at": created_at,
                "episode": episode,
                "asset_fingerprints": asset_fingerprints,
            }

        result = await asyncio.to_thread(_write_current)

        if resource_type == "videos":
            project_path: Path = result["project_path"]
            current_file: Path = result["current_file"]
            thumbnail_file = project_path / "thumbnails" / f"scene_{resource_id}.jpg"
            thumbnail_key = f"thumbnails/scene_{resource_id}.jpg"
            thumbnail_file.unlink(missing_ok=True)
            thumbnail_path = await extract_video_thumbnail(current_file, thumbnail_file)

            def _sync_thumbnail() -> None:
                manager = get_project_manager()
                with project_change_source("webui"):
                    manager.update_scene_asset(
                        project_name=project_name,
                        script_filename=script_file,
                        scene_id=resource_id,
                        asset_type="video_thumbnail",
                        asset_path=thumbnail_key if thumbnail_path else None,
                    )

            await asyncio.to_thread(_sync_thumbnail)
            result["asset_fingerprints"][thumbnail_key] = (
                thumbnail_file.stat().st_mtime_ns if thumbnail_file.exists() else 0
            )

        _emit_media_upload_change(
            project_name=project_name,
            resource_type=resource_type,
            resource_id=resource_id,
            script_file=script_file,
            episode=result["episode"],
            asset_fingerprints=result["asset_fingerprints"],
        )

        return {
            "success": True,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "version": result["version"],
            "created_at": result["created_at"],
            "file_path": result["rel_path"],
            "asset_fingerprints": result["asset_fingerprints"],
        }

    except HTTPException:
        raise
    except ScriptEditError as e:
        raise HTTPException(status_code=400, detail=f"剧本数据损坏: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/projects/{project_name}/versions/{resource_type}/{resource_id}/{version}")
async def delete_version(
    project_name: str,
    resource_type: str,
    resource_id: str,
    version: int,
    _user: CurrentUser,
):
    """删除单个非当前历史版本。当前版本和最后一个版本不可删除。"""
    try:

        def _sync():
            if resource_type not in _RESTORABLE_RESOURCE_TYPES:
                raise HTTPException(status_code=400, detail=f"不支持的资源类型: {resource_type}")
            result = get_version_manager(project_name).delete_version(resource_type, resource_id, version)
            asset_fingerprints = {}
            deleted_file = result.get("deleted_file")
            if isinstance(deleted_file, str):
                asset_fingerprints[deleted_file] = 0
            return {
                "success": True,
                **result,
                "asset_fingerprints": asset_fingerprints,
            }

        return await asyncio.to_thread(_sync)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))

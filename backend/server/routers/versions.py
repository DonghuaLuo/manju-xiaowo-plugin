"""
版本管理 API 路由

处理版本查询和还原请求。
"""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

from lib.app_data_dir import app_data_dir
from lib.asset_types import ASSET_SPECS
from lib.i18n import Translator
from lib.project_change_hints import project_change_source
from lib.project_manager import ProjectManager
from lib.resource_paths import resource_relative_path
from lib.script_editor import ScriptEditError
from lib.version_manager import VersionManager
from server.auth import CurrentUser

router = APIRouter()

# 初始化项目管理器
pm = ProjectManager(app_data_dir())

# 经此路由可还原的资源类型（API 面策略）。路径形状委托 lib.resource_paths，但本路由
# 仅放行有还原后元数据同步分支的这五类；grids/reference_videos 的还原是独立议题。
_RESTORABLE_RESOURCE_TYPES = frozenset({"storyboards", "videos", "characters", "scenes", "props"})


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


# resource_type（复数，URL 段）→ asset_type（单数，ASSET_SPECS 键）
_RESOURCE_TO_ASSET_TYPE: dict[str, str] = {
    "characters": "character",
    "scenes": "scene",
    "props": "prop",
}
_DESIGN_RESOURCE_TYPES = frozenset(_RESOURCE_TO_ASSET_TYPE)
_REFERENCE_VIDEO_TYPE_BY_RESOURCE: dict[str, str] = {
    "characters": "character",
    "scenes": "scene",
    "props": "prop",
}
_SCRIPT_REFERENCE_FIELDS: dict[str, tuple[str, ...]] = {
    "characters": ("characters_in_segment", "characters_in_scene"),
    "scenes": ("scenes",),
    "props": ("props", "props_in_scene"),
}


def _ensure_design_resource_type(resource_type: str) -> None:
    if resource_type not in _DESIGN_RESOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持删除的设计图类型: {resource_type}")


def _asset_entry(project: dict, resource_type: str, resource_id: str) -> tuple[str, dict]:
    _ensure_design_resource_type(resource_type)
    asset_type = _RESOURCE_TO_ASSET_TYPE[resource_type]
    spec = ASSET_SPECS[asset_type]
    bucket = project.get(spec.bucket_key)
    if not isinstance(bucket, dict) or resource_id not in bucket:
        raise HTTPException(status_code=404, detail=f"设计图不存在: {resource_id}")
    entry = bucket.get(resource_id)
    return asset_type, entry if isinstance(entry, dict) else {}


def _script_files_for_usage(manager: ProjectManager, project_name: str, project: dict) -> list[str]:
    seen: set[str] = set()
    script_files: list[str] = []

    for episode in project.get("episodes", []) if isinstance(project.get("episodes"), list) else []:
        if not isinstance(episode, dict):
            continue
        script_file = episode.get("script_file")
        if isinstance(script_file, str) and script_file and script_file not in seen:
            seen.add(script_file)
            script_files.append(script_file)

    try:
        listed = manager.list_scripts(project_name)
    except (FileNotFoundError, AttributeError):
        listed = []
    for script_file in listed:
        if isinstance(script_file, str) and script_file and script_file not in seen:
            seen.add(script_file)
            script_files.append(script_file)

    return script_files


def _references_resource(item: Any, resource_type: str, resource_id: str) -> bool:
    if not isinstance(item, dict):
        return False
    for field in _SCRIPT_REFERENCE_FIELDS[resource_type]:
        value = item.get(field)
        if isinstance(value, list) and resource_id in value:
            return True
    return False


def _find_design_resource_usages(
    manager: ProjectManager,
    project_name: str,
    project: dict,
    resource_type: str,
    resource_id: str,
) -> list[dict[str, Any]]:
    _ensure_design_resource_type(resource_type)
    usages: list[dict[str, Any]] = []
    reference_video_type = _REFERENCE_VIDEO_TYPE_BY_RESOURCE[resource_type]

    for script_file in _script_files_for_usage(manager, project_name, project):
        try:
            script = manager.load_script(project_name, script_file)
        except FileNotFoundError:
            logger.warning("引用检查跳过缺失剧本 %s/%s", project_name, script_file)
            continue

        if not isinstance(script, dict):
            continue
        episode = script.get("episode")

        segments = script.get("segments")
        if isinstance(segments, list):
            for segment in segments:
                if _references_resource(segment, resource_type, resource_id):
                    usages.append(
                        {
                            "script_file": script_file,
                            "episode": episode,
                            "kind": "segment",
                            "item_id": segment.get("segment_id") if isinstance(segment, dict) else None,
                        }
                    )

        scenes = script.get("scenes")
        if isinstance(scenes, list):
            for scene in scenes:
                if _references_resource(scene, resource_type, resource_id):
                    usages.append(
                        {
                            "script_file": script_file,
                            "episode": episode,
                            "kind": "scene",
                            "item_id": scene.get("scene_id") if isinstance(scene, dict) else None,
                        }
                    )

        video_units = script.get("video_units")
        if isinstance(video_units, list):
            for unit in video_units:
                if not isinstance(unit, dict):
                    continue
                references = unit.get("references")
                if not isinstance(references, list):
                    continue
                if any(
                    isinstance(ref, dict)
                    and ref.get("type") == reference_video_type
                    and ref.get("name") == resource_id
                    for ref in references
                ):
                    usages.append(
                        {
                            "script_file": script_file,
                            "episode": episode,
                            "kind": "video_unit",
                            "item_id": unit.get("unit_id"),
                        }
                    )

    return usages


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

"""
宫格图生成 API 路由

处理宫格图（grid-image）的生成、列表查询、单项查询和重新生成请求。
所有生成请求入队到 GenerationQueue，由 GenerationWorker 异步执行。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lib.app_data_dir import app_data_dir
from lib.generation_queue import ACTIVE_TASK_STATUSES, get_generation_queue
from lib.grid.layout import (
    calculate_grid_layout,
    plan_grid_chunk_sizes,
    resolve_storyboard_aspect_ratio,
)
from lib.grid.models import GridGeneration, build_frame_chain
from lib.grid.prompt_builder import build_grid_prompt
from lib.grid_manager import GridManager
from lib.i18n import Translator
from lib.project_manager import ProjectManager
from lib.script_editor import ScriptEditError
from lib.storyboard_sequence import get_storyboard_items, group_scenes_by_segment_break
from server.auth import CurrentUser

router = APIRouter(prefix="/projects/{project_name}", tags=["grids"])

# 初始化管理器
pm = ProjectManager(app_data_dir())

IN_PROGRESS_GRID_STATUSES = {"pending", "generating", "splitting"}
STALE_GRID_ERROR_MESSAGE = "生成任务已不存在，请重新生成宫格。"
STALE_GRID_RECONCILE_GRACE = timedelta(seconds=30)


def get_project_manager() -> ProjectManager:
    return pm


def _build_grid_task_payload(
    *,
    prompt: str | None,
    script_file: str,
    scene_ids: list[str],
    grid_size: str,
    rows: int,
    cols: int,
    grid_aspect_ratio: str,
    video_aspect_ratio: str,
) -> dict:
    """Build a consistent payload dict for grid generation tasks.

    入队不携带 provider 信息——provider 在执行时由 ConfigResolver 按当前项目配置解析
    （见 docs/adr/0001）。
    """
    return {
        "prompt": prompt,
        "script_file": script_file,
        "scene_ids": scene_ids,
        "grid_size": grid_size,
        "rows": rows,
        "cols": cols,
        "grid_aspect_ratio": grid_aspect_ratio,
        "video_aspect_ratio": video_aspect_ratio,
        "quality": "final",
    }


async def _list_active_grid_resource_ids(project_name: str) -> set[str]:
    """Return active grid task resource ids for a project."""
    queue = get_generation_queue()
    resource_ids: set[str] = set()

    for status in ACTIVE_TASK_STATUSES:
        page = 1
        page_size = 500
        while True:
            result = await queue.list_tasks(
                project_name=project_name,
                status=status,
                task_type="grid",
                page=page,
                page_size=page_size,
            )
            items = result.get("items", [])
            for item in items:
                resource_id = item.get("resource_id")
                if resource_id:
                    resource_ids.add(str(resource_id))

            total = int(result.get("total") or 0)
            current_page_size = int(result.get("page_size") or page_size)
            if page * current_page_size >= total:
                break
            page += 1

    return resource_ids


async def _reconcile_stale_grid_statuses(
    project_name: str,
    gm: GridManager,
    grids: list[GridGeneration],
) -> list[GridGeneration]:
    """Mark in-progress grid records as failed when no active task owns them."""
    in_progress_grids = [grid for grid in grids if grid.status in IN_PROGRESS_GRID_STATUSES]
    if not in_progress_grids:
        return grids

    try:
        active_resource_ids = await _list_active_grid_resource_ids(project_name)
    except Exception:
        logger.warning("跳过宫格状态校准：读取任务队列失败", exc_info=True)
        return grids

    for grid in in_progress_grids:
        if grid.id in active_resource_ids:
            continue
        try:
            created_at = datetime.fromisoformat(grid.created_at.replace("Z", "+00:00"))
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - created_at < STALE_GRID_RECONCILE_GRACE:
                continue
        except ValueError:
            pass
        grid.status = "failed"
        if not grid.error_message:
            grid.error_message = STALE_GRID_ERROR_MESSAGE
        gm.save(grid)

    return grids


# ==================== 请求/响应模型 ====================


class GenerateGridRequest(BaseModel):
    script_file: str
    scene_ids: list[str] | None = None


class GenerateGridResponse(BaseModel):
    success: bool
    grid_ids: list[str]
    task_ids: list[str]
    message: str


# ==================== 宫格图生成 ====================


@router.post("/generate/grid/{episode}", response_model=GenerateGridResponse)
async def generate_grid(
    project_name: str,
    episode: int,
    req: GenerateGridRequest,
    _user: CurrentUser,
    _t: Translator,
):
    """
    提交宫格图生成任务到队列，按 segment_break 分组。
    1-4 镜头组统一生成 2×2 宫格；多镜头组在连续段内按最多 4 格拆批。

    立即返回 grid_ids 和 task_ids。生成由 GenerationWorker 异步执行。
    """
    try:
        project = get_project_manager().load_project(project_name)
        script = get_project_manager().load_script(project_name, req.script_file)
        project_path = get_project_manager().get_project_path(project_name)

        items, id_field, _, _, _ = get_storyboard_items(script)
        aspect_ratio = resolve_storyboard_aspect_ratio(project)
        style = project.get("style", "")

        groups = group_scenes_by_segment_break(items, id_field)

        # 若指定了 scene_ids，只保留包含这些 scene 的分组，并在组内继续筛选实际 chunk。
        wanted_scene_ids = set(req.scene_ids) if req.scene_ids is not None else None
        if wanted_scene_ids is not None:
            groups = [g for g in groups if any(item[id_field] in wanted_scene_ids for item in g)]

        grid_ids: list[str] = []
        task_ids: list[str] = []
        queue = get_generation_queue()
        gm = GridManager(project_path)

        # Pre-load existing grids for cleanup, after marking orphaned in-progress records.
        existing_grids = await _reconcile_stale_grid_statuses(project_name, gm, gm.list_all())
        deleted_grid_ids: set[str] = set()

        for group in groups:
            all_scene_ids = [item[id_field] for item in group]
            n = len(all_scene_ids)

            group_id_set = set(all_scene_ids)

            # 只在 segment_break 划出的连续组内拆批；每批最多 4 个真实镜头，不跨组拼接。
            chunks: list[list] = []
            offset = 0
            for size in plan_grid_chunk_sizes(n):
                chunks.append(group[offset : offset + size])
                offset += size

            for chunk in chunks:
                chunk_ids = [item[id_field] for item in chunk]
                if wanted_scene_ids is not None and not any(scene_id in wanted_scene_ids for scene_id in chunk_ids):
                    continue

                chunk_layout = calculate_grid_layout(len(chunk_ids), aspect_ratio)
                if chunk_layout is None:
                    continue

                # 清理本次实际要替换的旧 grid。补生成单个缺失 chunk 时，只清理该 chunk，
                # 避免把同组其它已完成宫格删掉；完整生成时仍按整组替换。
                cleanup_scope_ids = group_id_set if wanted_scene_ids is None else set(chunk_ids)
                for old_grid in existing_grids:
                    if old_grid.id in deleted_grid_ids:
                        continue
                    if (
                        old_grid.script_file == req.script_file
                        and old_grid.episode == episode
                        and old_grid.status not in IN_PROGRESS_GRID_STATUSES
                        and old_grid.scene_ids
                        and set(old_grid.scene_ids) <= cleanup_scope_ids
                    ):
                        if gm.delete(old_grid.id):
                            deleted_grid_ids.add(old_grid.id)

                # provider/model 由 execute_grid_task 在 _resolve_effective_image_backend
                # 之后回填，因为只有 task 层能根据 reference_images 判断走 T2I 还是 I2I 槽
                grid = GridGeneration.create(
                    episode=episode,
                    script_file=req.script_file,
                    scene_ids=chunk_ids,
                    rows=chunk_layout.rows,
                    cols=chunk_layout.cols,
                    grid_size=chunk_layout.grid_size,
                    provider="",
                    model="",
                )

                prompt = build_grid_prompt(
                    scenes=chunk,
                    id_field=id_field,
                    rows=chunk_layout.rows,
                    cols=chunk_layout.cols,
                    style=style,
                    aspect_ratio=aspect_ratio,
                    grid_aspect_ratio=chunk_layout.grid_aspect_ratio,
                )

                grid.prompt = prompt
                gm.save(grid)

                task = await queue.enqueue_task(
                    project_name=project_name,
                    task_type="grid",
                    media_type="image",
                    resource_id=grid.id,
                    payload=_build_grid_task_payload(
                        prompt=prompt,
                        script_file=req.script_file,
                        scene_ids=chunk_ids,
                        grid_size=chunk_layout.grid_size,
                        rows=chunk_layout.rows,
                        cols=chunk_layout.cols,
                        grid_aspect_ratio=chunk_layout.grid_aspect_ratio,
                        video_aspect_ratio=aspect_ratio,
                    ),
                    script_file=req.script_file,
                    source="webui",
                    user_id=_user.id,
                )
                grid_ids.append(grid.id)
                task_ids.append(task["task_id"])

        return GenerateGridResponse(
            success=True,
            grid_ids=grid_ids,
            task_ids=task_ids,
            message=f"已提交 {len(grid_ids)} 个宫格生成任务",
        )

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except ScriptEditError as e:
        raise HTTPException(status_code=400, detail=_t("script_data_corrupted", reason=str(e)))
    except Exception as e:
        logger.exception("宫格生成请求处理失败")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 宫格图列表 ====================


@router.get("/grids")
async def list_grids(project_name: str, _user: CurrentUser):
    """列出项目下所有宫格图记录。"""
    try:
        project_path = get_project_manager().get_project_path(project_name)
        gm = GridManager(project_path)
        grids = await _reconcile_stale_grid_statuses(project_name, gm, gm.list_all())
        return [g.to_dict() for g in grids]
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("列出宫格图失败")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 宫格图详情 ====================


@router.get("/grids/{grid_id}")
async def get_grid(project_name: str, grid_id: str, _user: CurrentUser):
    """获取单个宫格图记录。"""
    try:
        project_path = get_project_manager().get_project_path(project_name)
        gm = GridManager(project_path)
        grid = gm.get(grid_id)
        if grid is None:
            raise HTTPException(status_code=404, detail=f"Grid {grid_id} 不存在")
        await _reconcile_stale_grid_statuses(project_name, gm, [grid])
        return grid.to_dict()
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("获取宫格图失败")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 重新生成宫格图 ====================


@router.post("/grids/{grid_id}/regenerate")
async def regenerate_grid(project_name: str, grid_id: str, _user: CurrentUser):
    """重置宫格图状态并重新入队生成任务。"""
    try:
        project_path = get_project_manager().get_project_path(project_name)
        gm = GridManager(project_path)
        grid = gm.get(grid_id)
        if grid is None:
            raise HTTPException(status_code=404, detail=f"Grid {grid_id} 不存在")

        project = get_project_manager().load_project(project_name)
        aspect_ratio = resolve_storyboard_aspect_ratio(project)
        layout = calculate_grid_layout(len(grid.scene_ids), aspect_ratio)
        if layout is None:
            raise HTTPException(status_code=400, detail="该记录不是 1-4 镜头宫格，请重新按分组生成")

        script = get_project_manager().load_script(project_name, grid.script_file)
        items, id_field, _, _, _ = get_storyboard_items(script)
        items_by_id = {str(item.get(id_field)): item for item in items}
        scenes = [items_by_id.get(str(scene_id)) for scene_id in grid.scene_ids]
        if any(scene is None for scene in scenes):
            raise HTTPException(status_code=400, detail="宫格记录中的分镜已不存在，请重新按分组生成")

        grid.status = "pending"
        grid.error_message = None
        # 清空旧 metadata，由 execute_grid_task 按 needs_i2i 重新回填
        grid.provider = ""
        grid.model = ""
        grid.rows = layout.rows
        grid.cols = layout.cols
        grid.cell_count = layout.cell_count
        grid.grid_size = layout.grid_size
        grid.frame_chain = build_frame_chain(grid.scene_ids, layout.rows, layout.cols)
        grid.prompt = build_grid_prompt(
            scenes=[scene for scene in scenes if scene is not None],
            id_field=id_field,
            rows=layout.rows,
            cols=layout.cols,
            style=project.get("style", ""),
            aspect_ratio=aspect_ratio,
            grid_aspect_ratio=layout.grid_aspect_ratio,
        )
        gm.save(grid)

        queue = get_generation_queue()
        task = await queue.enqueue_task(
            project_name=project_name,
            task_type="grid",
            media_type="image",
            resource_id=grid.id,
            payload=_build_grid_task_payload(
                prompt=grid.prompt,
                script_file=grid.script_file,
                scene_ids=grid.scene_ids,
                grid_size=grid.grid_size,
                rows=grid.rows,
                cols=grid.cols,
                grid_aspect_ratio=layout.grid_aspect_ratio,
                video_aspect_ratio=aspect_ratio,
            ),
            script_file=grid.script_file,
            source="webui",
            user_id=_user.id,
        )

        return {"success": True, "task_id": task["task_id"]}

    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("重新生成宫格图失败")
        raise HTTPException(status_code=500, detail=str(e))

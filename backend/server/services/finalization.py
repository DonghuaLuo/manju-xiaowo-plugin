"""Episode readiness checks for the legacy finalization endpoint.

The previous endpoint submitted "final" storyboard/video tasks. Product
positioning has changed: bulk and Agent workflows stay on quick generation,
while refined generation is a manual per-shot action. This service therefore
only reports what is missing and never enqueues model work.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from lib.generation_queue import GenerationQueue
from lib.project_manager import ProjectManager, effective_mode
from lib.storyboard_sequence import get_storyboard_items


def _project_file_exists(project_dir: Path, relative_path: object) -> bool:
    if not isinstance(relative_path, str) or not relative_path.strip():
        return False
    path = (project_dir / relative_path).resolve()
    try:
        path.relative_to(project_dir.resolve())
    except ValueError:
        return False
    return path.is_file()


def build_finalization_task_report(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize legacy finalize-sourced queue tasks with retry hints."""

    from lib.friendly_errors import classify_generation_failure

    items: list[dict[str, Any]] = []
    summary = {
        "total": len(tasks),
        "queued": 0,
        "running": 0,
        "succeeded": 0,
        "failed": 0,
        "cancelled": 0,
    }
    for task in tasks:
        status = str(task.get("status") or "unknown")
        if status in summary:
            summary[status] += 1
        error_message = task.get("error_message") or ""
        failure = classify_generation_failure(error_message) if error_message else None
        items.append(
            {
                "task_id": task.get("task_id"),
                "task_type": task.get("task_type"),
                "resource_id": task.get("resource_id"),
                "status": status,
                "provider_id": task.get("provider_id"),
                "error_message": error_message,
                "failure": failure,
                "retry_suggestion": failure.get("retry_suggestion") if isinstance(failure, dict) else None,
                "updated_at": task.get("updated_at"),
            }
        )
    return {"summary": summary, "items": items}


class EpisodeFinalizationService:
    def __init__(self, project_manager: ProjectManager, queue: GenerationQueue):
        self.pm = project_manager
        # Kept for constructor compatibility; this service no longer enqueues.
        self.queue = queue

    def _load_episode(self, project_name: str, episode: int) -> tuple[dict, dict, str, Path, str]:
        project = self.pm.load_project(project_name)
        episodes = project.get("episodes") or []
        entry = next((item for item in episodes if item.get("episode") == episode), None)
        if entry is None or not entry.get("script_file"):
            raise FileNotFoundError(f"第 {episode} 集不存在")
        script_file = Path(str(entry["script_file"])).name
        script = self.pm.load_script(project_name, script_file)
        project_dir = self.pm.get_project_path(project_name)
        mode = effective_mode(project=project, episode=entry)
        return project, script, script_file, project_dir, mode

    async def finalize_episode(
        self,
        *,
        project_name: str,
        episode: int,
        user_id: str,
    ) -> dict[str, Any]:
        _ = user_id
        project, script, script_file, project_dir, mode = await asyncio.to_thread(
            self._load_episode,
            project_name,
            episode,
        )
        if mode == "reference_video" or script.get("generation_mode") == "reference_video":
            return self._check_reference_video_episode(
                project_name=project_name,
                episode=episode,
                script=script,
                script_file=script_file,
                project_dir=project_dir,
            )
        return self._check_storyboard_episode(
            project_name=project_name,
            episode=episode,
            mode=mode,
            script=script,
            script_file=script_file,
            project_dir=project_dir,
        )

    def _check_storyboard_episode(
        self,
        *,
        project_name: str,
        episode: int,
        mode: str,
        script: dict[str, Any],
        script_file: str,
        project_dir: Path,
    ) -> dict[str, Any]:
        items, id_field, _char_field, _scenes_field, _props_field = get_storyboard_items(script)
        issues: list[dict[str, Any]] = []
        ready_videos = 0
        missing_storyboards = 0
        missing_videos = 0

        for item in items:
            resource_id = str(item.get(id_field) or "").strip()
            if not resource_id:
                continue
            assets = item.get("generated_assets") if isinstance(item.get("generated_assets"), dict) else {}
            if not _project_file_exists(project_dir, assets.get("storyboard_image")):
                missing_storyboards += 1
                issues.append(
                    {
                        "resource_id": resource_id,
                        "kind": "storyboard",
                        "message": "缺少当前分镜图；请先生成快速版分镜，或手动上传分镜图。",
                    }
                )
            if _project_file_exists(project_dir, assets.get("video_clip")):
                ready_videos += 1
            else:
                missing_videos += 1
                issues.append(
                    {
                        "resource_id": resource_id,
                        "kind": "video",
                        "message": "缺少已生成视频；合并成片前请先生成快速版视频，或手动上传视频。",
                    }
                )

        ready_for_merge = missing_videos == 0 and ready_videos > 0
        message = (
            "本集所有视频已生成，可直接合并片段；不会自动生成精修版。"
            if ready_for_merge
            else "本集还有镜头缺少视频，已停止检查；不会自动补生成或自动精修。"
        )
        return {
            "success": True,
            "mode": mode if mode in {"storyboard", "grid"} else "storyboard",
            "project_name": project_name,
            "episode": episode,
            "script_file": script_file,
            "storyboards": [],
            "videos": [],
            "issues": issues,
            "summary": {
                "storyboards_enqueued": 0,
                "videos_enqueued": 0,
                "already_final": ready_videos,
                "ready_videos": ready_videos,
                "missing_storyboards": missing_storyboards,
                "missing_videos": missing_videos,
                "ready_for_merge": ready_for_merge,
                "issues": len(issues),
                "message": message,
            },
        }

    def _check_reference_video_episode(
        self,
        *,
        project_name: str,
        episode: int,
        script: dict[str, Any],
        script_file: str,
        project_dir: Path,
    ) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        ready_videos = 0
        missing_videos = 0

        for unit in script.get("video_units") or []:
            unit_id = str(unit.get("unit_id") or "").strip()
            if not unit_id:
                continue
            assets = unit.get("generated_assets") if isinstance(unit.get("generated_assets"), dict) else {}
            if _project_file_exists(project_dir, assets.get("video_clip")):
                ready_videos += 1
            else:
                missing_videos += 1
                issues.append(
                    {
                        "resource_id": unit_id,
                        "kind": "reference_video",
                        "message": "缺少已生成参考视频；合并或导出前请先生成快速版视频。",
                    }
                )

        ready_for_merge = missing_videos == 0 and ready_videos > 0
        message = (
            "本集所有参考视频已生成，可直接使用现有片段；不会自动生成精修版。"
            if ready_for_merge
            else "本集还有参考视频缺失，已停止检查；不会自动补生成或自动精修。"
        )
        return {
            "success": True,
            "mode": "reference_video",
            "project_name": project_name,
            "episode": episode,
            "script_file": script_file,
            "reference_videos": [],
            "issues": issues,
            "summary": {
                "reference_videos_enqueued": 0,
                "already_final": ready_videos,
                "ready_videos": ready_videos,
                "missing_videos": missing_videos,
                "ready_for_merge": ready_for_merge,
                "issues": len(issues),
                "message": message,
            },
        }

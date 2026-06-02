"""Episode finalization helpers.

Finalization is an async queue submission step: it finds storyboard/video assets
that are not final-ready, enqueues the missing final tasks, and returns a report
that the UI can show immediately while the normal task HUD tracks execution.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from lib.generation_queue import GenerationQueue
from lib.generation_queue_client import TaskSpec, TaskSpecValidationError
from lib.project_manager import ProjectManager, effective_mode
from lib.reference_video import assemble_shots_text
from lib.storyboard_sequence import build_storyboard_dependency_plan, get_storyboard_items
from server.services.generation_route_resolver import is_video_resolution_below, merged_generation_profiles

FINAL_ENOUGH_STORYBOARD_QUALITIES = {"final", "grid", "custom"}


def _load_versions(project_dir: Path) -> dict[str, Any]:
    versions_path = project_dir / "versions" / "versions.json"
    if not versions_path.is_file():
        return {}
    try:
        payload = json.loads(versions_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _current_version_metadata(
    versions: dict[str, Any],
    resource_type: str,
    resource_id: str,
) -> dict[str, Any]:
    resource_info = versions.get(resource_type, {}).get(resource_id)
    if not isinstance(resource_info, dict):
        return {}
    items = resource_info.get("versions")
    if not isinstance(items, list):
        return {}
    current_version = resource_info.get("current_version")
    for item in items:
        if isinstance(item, dict) and (
            item.get("version") == current_version or item.get("is_current")
        ):
            return item
    for item in reversed(items):
        if isinstance(item, dict):
            return item
    return {}


def _quality(metadata: dict[str, Any]) -> str:
    value = metadata.get("generation_quality")
    return str(value) if value in {"draft", "final", "custom"} else "unknown"


def _route_resolution(metadata: dict[str, Any]) -> str | None:
    route = metadata.get("generation_route")
    if isinstance(route, dict) and route.get("resolution"):
        return str(route["resolution"])
    value = metadata.get("resolution")
    return str(value) if value else None


def _project_path_exists(project_dir: Path, relative_path: object) -> bool:
    if not isinstance(relative_path, str) or not relative_path.strip():
        return False
    path = (project_dir / relative_path).resolve()
    try:
        path.relative_to(project_dir.resolve())
    except ValueError:
        return False
    return path.exists()


def _final_video_resolution(project: dict[str, Any]) -> str | None:
    profile = merged_generation_profiles(project).get("video_final") or {}
    value = profile.get("resolution")
    return str(value) if value else None


def _final_reference_video_resolution(project: dict[str, Any]) -> str | None:
    profile = merged_generation_profiles(project).get("reference_video_final") or {}
    value = profile.get("resolution")
    return str(value) if value else None


def _final_ready_source_quality(source_quality: str, storyboard_quality: str) -> bool:
    if source_quality:
        return source_quality in FINAL_ENOUGH_STORYBOARD_QUALITIES
    return storyboard_quality in FINAL_ENOUGH_STORYBOARD_QUALITIES


def build_finalization_task_report(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize finalized queue tasks with failure categories and retry hints."""

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
        project, script, script_file, project_dir, mode = await asyncio.to_thread(
            self._load_episode,
            project_name,
            episode,
        )
        if mode == "reference_video" or script.get("generation_mode") == "reference_video":
            return await self._finalize_reference_video_episode(
                project_name=project_name,
                episode=episode,
                script=script,
                script_file=script_file,
                project_dir=project_dir,
                project=project,
                user_id=user_id,
            )
        return await self._finalize_storyboard_episode(
            project_name=project_name,
            episode=episode,
            script=script,
            script_file=script_file,
            project_dir=project_dir,
            project=project,
            user_id=user_id,
        )

    async def _finalize_storyboard_episode(
        self,
        *,
        project_name: str,
        episode: int,
        script: dict[str, Any],
        script_file: str,
        project_dir: Path,
        project: dict[str, Any],
        user_id: str,
    ) -> dict[str, Any]:
        items, id_field, _char_field, _scenes_field, _props_field = get_storyboard_items(script)
        versions = _load_versions(project_dir)
        target_video_resolution = _final_video_resolution(project)
        issues: list[dict[str, Any]] = []
        storyboard_ids: list[str] = []
        item_by_id: dict[str, dict[str, Any]] = {}

        for item in items:
            resource_id = str(item.get(id_field) or "").strip()
            if not resource_id:
                continue
            item_by_id[resource_id] = item
            assets = item.get("generated_assets") if isinstance(item.get("generated_assets"), dict) else {}
            storyboard_meta = _current_version_metadata(versions, "storyboards", resource_id)
            storyboard_quality = "grid" if assets.get("grid_id") else _quality(storyboard_meta)
            storyboard_exists = _project_path_exists(project_dir, assets.get("storyboard_image"))
            if not storyboard_exists or storyboard_quality not in FINAL_ENOUGH_STORYBOARD_QUALITIES:
                storyboard_ids.append(resource_id)

        storyboard_plans = build_storyboard_dependency_plan(
            items,
            id_field,
            storyboard_ids,
            script_file,
        )
        storyboard_task_ids: dict[str, str] = {}
        enqueued_storyboards: list[dict[str, Any]] = []

        for plan in storyboard_plans:
            item = item_by_id.get(plan.resource_id) or {}
            try:
                extra_payload: dict[str, Any] = {"quality": "final"}
                if item.get("shot_tier") in {"S", "A", "B"}:
                    extra_payload["shot_tier"] = item.get("shot_tier")
                spec = TaskSpec.from_request(
                    task_type="storyboard",
                    media_type="image",
                    resource_id=plan.resource_id,
                    prompt=item.get("image_prompt"),
                    script_file=script_file,
                    extra_payload=extra_payload,
                )
            except TaskSpecValidationError as exc:
                issues.append(
                    {
                        "resource_id": plan.resource_id,
                        "kind": "storyboard",
                        "message": str(exc),
                    }
                )
                continue

            dependency_task_id = (
                storyboard_task_ids.get(plan.dependency_resource_id)
                if plan.dependency_resource_id
                else None
            )
            result = await self.queue.enqueue_task(
                project_name=project_name,
                task_type=spec.task_type,
                media_type=spec.media_type,
                resource_id=spec.resource_id,
                payload=spec.payload,
                script_file=spec.script_file,
                source="finalize",
                dependency_task_id=dependency_task_id,
                dependency_group=plan.dependency_group,
                dependency_index=plan.dependency_index,
                user_id=user_id,
            )
            storyboard_task_ids[plan.resource_id] = result["task_id"]
            enqueued_storyboards.append(
                {
                    "resource_id": plan.resource_id,
                    "task_id": result["task_id"],
                    "deduped": bool(result.get("deduped")),
                }
            )

        enqueued_videos: list[dict[str, Any]] = []
        already_final = 0

        for item in items:
            resource_id = str(item.get(id_field) or "").strip()
            if not resource_id:
                continue
            assets = item.get("generated_assets") if isinstance(item.get("generated_assets"), dict) else {}
            storyboard_meta = _current_version_metadata(versions, "storyboards", resource_id)
            storyboard_quality = "grid" if assets.get("grid_id") else _quality(storyboard_meta)
            storyboard_exists = _project_path_exists(project_dir, assets.get("storyboard_image"))
            video_meta = _current_version_metadata(versions, "videos", resource_id)
            video_quality = _quality(video_meta)
            source_quality = str(video_meta.get("source_storyboard_generation_quality") or "")
            video_resolution = _route_resolution(video_meta)
            video_exists = _project_path_exists(project_dir, assets.get("video_clip"))

            needs_video = (
                not video_exists
                or video_quality != "final"
                or not _final_ready_source_quality(source_quality, storyboard_quality)
                or is_video_resolution_below(video_resolution, target_video_resolution)
            )
            if not needs_video:
                already_final += 1
                continue

            dependency_task_id = storyboard_task_ids.get(resource_id)
            if not dependency_task_id and (
                not storyboard_exists or storyboard_quality not in FINAL_ENOUGH_STORYBOARD_QUALITIES
            ):
                issues.append(
                    {
                        "resource_id": resource_id,
                        "kind": "video",
                        "message": "缺少可用于最终视频的最终版分镜",
                    }
                )
                continue

            try:
                extra_payload: dict[str, Any] = {"quality": "final"}
                if item.get("duration_seconds") is not None:
                    extra_payload["duration_seconds"] = item.get("duration_seconds")
                if item.get("shot_tier") in {"S", "A", "B"}:
                    extra_payload["shot_tier"] = item.get("shot_tier")
                spec = TaskSpec.from_request(
                    task_type="video",
                    media_type="video",
                    resource_id=resource_id,
                    prompt=item.get("video_prompt"),
                    script_file=script_file,
                    extra_payload=extra_payload,
                )
            except TaskSpecValidationError as exc:
                issues.append(
                    {
                        "resource_id": resource_id,
                        "kind": "video",
                        "message": str(exc),
                    }
                )
                continue

            result = await self.queue.enqueue_task(
                project_name=project_name,
                task_type=spec.task_type,
                media_type=spec.media_type,
                resource_id=spec.resource_id,
                payload=spec.payload,
                script_file=spec.script_file,
                source="finalize",
                dependency_task_id=dependency_task_id,
                dependency_group=f"{script_file}:finalize-video",
                dependency_index=len(enqueued_videos),
                user_id=user_id,
            )
            enqueued_videos.append(
                {
                    "resource_id": resource_id,
                    "task_id": result["task_id"],
                    "deduped": bool(result.get("deduped")),
                    "dependency_task_id": dependency_task_id,
                }
            )

        return {
            "success": True,
            "mode": "storyboard",
            "project_name": project_name,
            "episode": episode,
            "script_file": script_file,
            "storyboards": enqueued_storyboards,
            "videos": enqueued_videos,
            "issues": issues,
            "summary": {
                "storyboards_enqueued": len(enqueued_storyboards),
                "videos_enqueued": len(enqueued_videos),
                "already_final": already_final,
                "issues": len(issues),
            },
        }

    async def _finalize_reference_video_episode(
        self,
        *,
        project_name: str,
        episode: int,
        script: dict[str, Any],
        script_file: str,
        project_dir: Path,
        project: dict[str, Any],
        user_id: str,
    ) -> dict[str, Any]:
        versions = _load_versions(project_dir)
        target_resolution = _final_reference_video_resolution(project)
        enqueued: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        already_final = 0

        for unit in script.get("video_units") or []:
            unit_id = str(unit.get("unit_id") or "").strip()
            if not unit_id:
                continue
            assets = unit.get("generated_assets") if isinstance(unit.get("generated_assets"), dict) else {}
            meta = _current_version_metadata(versions, "reference_videos", unit_id)
            quality = _quality(meta)
            resolution = _route_resolution(meta)
            clip_exists = _project_path_exists(project_dir, assets.get("video_clip"))
            needs_video = (
                not clip_exists
                or quality != "final"
                or is_video_resolution_below(resolution, target_resolution)
            )
            if not needs_video:
                already_final += 1
                continue
            try:
                extra_payload: dict[str, Any] = {"quality": "final"}
                if unit.get("duration_seconds") is not None:
                    extra_payload["duration_seconds"] = unit.get("duration_seconds")
                spec = TaskSpec.from_request(
                    task_type="reference_video",
                    media_type="video",
                    resource_id=unit_id,
                    prompt=assemble_shots_text(unit.get("shots") or []),
                    script_file=script_file,
                    extra_payload=extra_payload,
                )
            except TaskSpecValidationError as exc:
                issues.append(
                    {
                        "resource_id": unit_id,
                        "kind": "reference_video",
                        "message": str(exc),
                    }
                )
                continue
            result = await self.queue.enqueue_task(
                project_name=project_name,
                task_type=spec.task_type,
                media_type=spec.media_type,
                resource_id=spec.resource_id,
                payload=spec.payload,
                script_file=spec.script_file,
                source="finalize",
                user_id=user_id,
            )
            enqueued.append(
                {
                    "resource_id": unit_id,
                    "task_id": result["task_id"],
                    "deduped": bool(result.get("deduped")),
                }
            )

        return {
            "success": True,
            "mode": "reference_video",
            "project_name": project_name,
            "episode": episode,
            "script_file": script_file,
            "reference_videos": enqueued,
            "issues": issues,
            "summary": {
                "reference_videos_enqueued": len(enqueued),
                "already_final": already_final,
                "issues": len(issues),
            },
        }

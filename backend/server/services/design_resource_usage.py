"""角色/场景/道具项目级设计资源引用检查。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from lib.asset_types import ASSET_SPECS
from lib.project_manager import ProjectManager

logger = logging.getLogger(__name__)


# resource_type（复数，URL 段）→ asset_type（单数，ASSET_SPECS 键）
RESOURCE_TO_ASSET_TYPE: dict[str, str] = {
    "characters": "character",
    "scenes": "scene",
    "props": "prop",
}
DESIGN_RESOURCE_TYPES = frozenset(RESOURCE_TO_ASSET_TYPE)
REFERENCE_VIDEO_TYPE_BY_RESOURCE: dict[str, str] = {
    "characters": "character",
    "scenes": "scene",
    "props": "prop",
}
SCRIPT_REFERENCE_FIELDS: dict[str, tuple[str, ...]] = {
    "characters": ("characters_in_segment", "characters_in_scene"),
    "scenes": ("scenes",),
    "props": ("props", "props_in_scene"),
}


def ensure_design_resource_type(resource_type: str) -> None:
    if resource_type not in DESIGN_RESOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持删除的设计图类型: {resource_type}")


def asset_entry(project: dict, resource_type: str, resource_id: str) -> tuple[str, dict]:
    ensure_design_resource_type(resource_type)
    asset_type = RESOURCE_TO_ASSET_TYPE[resource_type]
    spec = ASSET_SPECS[asset_type]
    bucket = project.get(spec.bucket_key)
    if not isinstance(bucket, dict) or resource_id not in bucket:
        raise HTTPException(status_code=404, detail=f"设计图不存在: {resource_id}")
    entry = bucket.get(resource_id)
    return asset_type, entry if isinstance(entry, dict) else {}


def script_files_for_usage(manager: ProjectManager, project_name: str, project: dict) -> list[str]:
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


def references_resource(item: Any, resource_type: str, resource_id: str) -> bool:
    if not isinstance(item, dict):
        return False
    for field in SCRIPT_REFERENCE_FIELDS[resource_type]:
        value = item.get(field)
        if isinstance(value, list) and resource_id in value:
            return True
    return False


def find_design_resource_usages(
    manager: ProjectManager,
    project_name: str,
    project: dict,
    resource_type: str,
    resource_id: str,
) -> list[dict[str, Any]]:
    ensure_design_resource_type(resource_type)
    usages: list[dict[str, Any]] = []
    reference_video_type = REFERENCE_VIDEO_TYPE_BY_RESOURCE[resource_type]

    for script_file in script_files_for_usage(manager, project_name, project):
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
                if references_resource(segment, resource_type, resource_id):
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
                if references_resource(scene, resource_type, resource_id):
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

"""
Helpers for storyboard sequence ordering and dependency planning.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from lib.script_editor import resolve_items


@dataclass(frozen=True)
class StoryboardTaskPlan:
    resource_id: str
    script_file: str | None
    dependency_resource_id: str | None
    dependency_group: str
    dependency_index: int


PREVIOUS_STORYBOARD_REFERENCE_LABEL = "上一分镜图（镜头衔接参考）"
PREVIOUS_STORYBOARD_REFERENCE_DESCRIPTION = (
    "仅用于延续前一镜头的构图、色调和场景连续性，不是新增角色、服装或道具设定；请以当前 prompt 为准生成当前镜头。"
)


def get_storyboard_items(script: dict) -> tuple[list[dict], str, str, str, str]:
    """返回 storyboard/grid 模式剧本的分镜列表与引用字段名。

    reference_video 模式没有 storyboard 任务，调用方据此跳过。其余 narration/drama
    路径复用 `script_editor.resolve_items`，和 MCP 编辑、结构校验、metadata 重算保持
    同一判别；当 segments/scenes 键存在但不是 list 时让 ScriptEditError 上冒，避免
    脏数据被 `list(None)` 之类的低质量错误掩盖。
    """
    if script.get("generation_mode") == "reference_video":
        return ([], "unit_id", "characters_in_unit", "scenes", "props")

    items, id_field, kind = resolve_items(script)
    char_field = "characters_in_segment" if kind == "segments" else "characters_in_scene"
    return (items, id_field, char_field, "scenes", "props")


def find_storyboard_item(
    items: Sequence[dict],
    id_field: str,
    resource_id: str,
) -> tuple[dict, int] | None:
    for index, item in enumerate(items):
        if str(item.get(id_field)) == str(resource_id):
            return item, index
    return None


def storyboard_path_for_item(project_path: Path, item: dict, id_field: str) -> tuple[str | None, Path | None]:
    resource_id = str(item.get(id_field) or "").strip()
    if not resource_id:
        return None, None
    assets = item.get("generated_assets")
    storyboard_rel = assets.get("storyboard_image") if isinstance(assets, dict) else None
    storyboard_rel_text = str(storyboard_rel).strip() if storyboard_rel else ""
    if storyboard_rel_text:
        return resource_id, project_path / storyboard_rel_text
    return resource_id, project_path / "storyboards" / f"scene_{resource_id}.png"


def resolve_previous_storyboard_path(
    project_path: Path,
    items: Sequence[dict],
    id_field: str,
    resource_id: str,
    *,
    require_exists: bool = True,
) -> Path | None:
    resolved = find_storyboard_item(items, id_field, resource_id)
    if resolved is None:
        raise KeyError(f"scene/segment not found: {resource_id}")

    target_item, index = resolved
    if index == 0 or bool(target_item.get("segment_break")):
        return None

    previous_item = items[index - 1]
    _previous_id, previous_path = storyboard_path_for_item(project_path, previous_item, id_field)
    if not previous_path:
        return None
    if require_exists and not previous_path.exists():
        return None
    return previous_path


def build_previous_storyboard_reference(path: Path) -> dict:
    return {
        "image": path,
        "label": PREVIOUS_STORYBOARD_REFERENCE_LABEL,
        "description": PREVIOUS_STORYBOARD_REFERENCE_DESCRIPTION,
    }


def group_scenes_by_segment_break(items: list[dict], id_field: str) -> list[list[dict]]:
    """Groups consecutive scene dicts, breaking at segment_break=True.

    Args:
        items: List of scene/segment dicts.
        id_field: Key in each dict for the item ID (unused but kept for API consistency).

    Returns:
        List of groups, each a list of consecutive scene dicts.
    """
    groups: list[list[dict]] = []
    current: list[dict] = []
    for item in items:
        if item.get("segment_break", False) and current:
            groups.append(current)
            current = []
        current.append(item)
    if current:
        groups.append(current)
    return groups


def build_storyboard_dependency_plan(
    items: Sequence[dict],
    id_field: str,
    selected_ids: Iterable[str],
    script_file: str | None,
    needs_previous_reference: Callable[[dict], bool] | None = None,
) -> list[StoryboardTaskPlan]:
    selected_set = {str(item_id) for item_id in selected_ids}
    if not selected_set:
        return []

    plans: list[StoryboardTaskPlan] = []
    group_counter = 0
    current_group = ""
    current_group_index = 0

    for index, item in enumerate(items):
        resource_id = str(item.get(id_field) or "").strip()
        if not resource_id or resource_id not in selected_set:
            continue

        previous_resource_id: str | None = None
        if index > 0:
            previous_resource_id = str(items[index - 1].get(id_field) or "").strip() or None

        needs_previous = True if needs_previous_reference is None else bool(needs_previous_reference(item))
        starts_new_group = (
            not needs_previous
            or bool(item.get("segment_break"))
            or not previous_resource_id
            or previous_resource_id not in selected_set
        )

        if starts_new_group:
            group_counter += 1
            current_group = f"{script_file or 'storyboard'}:group:{group_counter}"
            current_group_index = 0
            dependency_resource_id = None
        else:
            current_group_index += 1
            dependency_resource_id = previous_resource_id

        plans.append(
            StoryboardTaskPlan(
                resource_id=resource_id,
                script_file=script_file,
                dependency_resource_id=dependency_resource_id,
                dependency_group=current_group,
                dependency_index=current_group_index,
            )
        )

    return plans

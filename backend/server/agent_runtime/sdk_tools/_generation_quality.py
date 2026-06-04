"""Shared generation quality helpers for agent enqueue tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from lib.version_manager import VersionManager

GenerationQuality = Literal["draft", "final"]
RefineScope = Literal["current_unrefined", "current_all"]

QUALITY_LABELS: dict[str, str] = {
    "draft": "快速版",
    "final": "精修版",
}


QUALITY_SCHEMA: dict[str, Any] = {
    "type": "string",
    "enum": ["draft", "final"],
    "description": "生成质量档位；draft=快速版（批量/Agent 默认），final=精修版（用户明确要求时使用，可单镜头或批量精修）",
}

REFINE_SCOPE_SCHEMA: dict[str, Any] = {
    "type": "string",
    "enum": ["current_unrefined", "current_all"],
    "description": (
        "批量精修范围；current_unrefined=只精修当前不是精修版的已有视频，"
        "current_all=当前已有视频全量重精修（包括已精修项）。只看当前版本，历史版本不参与判断。"
    ),
}


def normalize_quality(args: dict[str, Any], default: GenerationQuality) -> GenerationQuality:
    value = args.get("quality")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"draft", "fast", "quick", "快速", "快速版"}:
            return "draft"
        if normalized in {"final", "refined", "refine", "polish", "精修", "精修版"}:
            return "final"
    return default


def normalize_refine_scope(args: dict[str, Any]) -> RefineScope | None:
    value = args.get("refine_scope")
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("refine_scope 必须是字符串")
    normalized = value.strip().lower()
    if normalized == "current_unrefined":
        return "current_unrefined"
    if normalized == "current_all":
        return "current_all"
    raise ValueError("refine_scope 必须是 current_unrefined 或 current_all")


def current_generation_quality(project_dir: Path, resource_type: str, resource_id: str) -> str:
    try:
        versions = VersionManager(project_dir).get_versions(resource_type, resource_id)
    except Exception:
        return "unknown"
    current_version = versions.get("current_version")
    for item in versions.get("versions") or []:
        if item.get("version") == current_version or item.get("is_current"):
            quality = item.get("generation_quality")
            return str(quality) if quality else "unknown"
    return "unknown"


def is_current_refined(project_dir: Path, resource_type: str, resource_id: str) -> bool:
    return current_generation_quality(project_dir, resource_type, resource_id) == "final"


def route_summary(result: dict[str, Any] | None) -> str:
    if not result:
        return ""
    route = result.get("generation_route")
    if not isinstance(route, dict):
        return ""
    parts: list[str] = []
    quality = result.get("generation_quality")
    if isinstance(quality, str) and quality:
        parts.append(QUALITY_LABELS.get(quality, quality))
    resolution = route.get("resolution")
    if isinstance(resolution, str) and resolution:
        parts.append(resolution)
    duration = route.get("duration_seconds")
    if duration is not None:
        parts.append(f"{duration}s")
    provider = route.get("provider")
    model = route.get("model")
    if isinstance(provider, str) and isinstance(model, str) and provider and model:
        parts.append(f"{provider}/{model}")
    return f" [{' · '.join(parts)}]" if parts else ""

"""Shared generation quality helpers for agent enqueue tools."""

from __future__ import annotations

from typing import Any, Literal

GenerationQuality = Literal["draft", "final"]


QUALITY_SCHEMA: dict[str, Any] = {
    "type": "string",
    "enum": ["draft", "final"],
    "description": "生成质量档位；draft=草稿，final=最终版",
}


def normalize_quality(args: dict[str, Any], default: GenerationQuality) -> GenerationQuality:
    value = args.get("quality")
    if value in ("draft", "final"):
        return value
    return default


def route_summary(result: dict[str, Any] | None) -> str:
    if not result:
        return ""
    route = result.get("generation_route")
    if not isinstance(route, dict):
        return ""
    parts: list[str] = []
    quality = result.get("generation_quality")
    if isinstance(quality, str) and quality:
        parts.append(quality)
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

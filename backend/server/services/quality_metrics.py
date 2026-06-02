"""Project-local manual quality ratings and aggregate statistics."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lib.project_manager import ProjectManager

QUALITY_METRICS_FILENAME = "quality_metrics.json"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _current_version_metadata(project_dir: Path, resource_type: str, resource_id: str, version: object) -> dict[str, Any]:
    versions = _load_json(project_dir / "versions" / "versions.json")
    resource = versions.get(resource_type, {}).get(resource_id)
    if not isinstance(resource, dict):
        return {}
    items = resource.get("versions")
    if not isinstance(items, list):
        return {}
    target_version: int | None = None
    if version is not None:
        try:
            target_version = int(version)
        except (TypeError, ValueError):
            target_version = None
    current_version = resource.get("current_version")
    for item in items:
        if not isinstance(item, dict):
            continue
        if target_version is not None and item.get("version") == target_version:
            return item
        if target_version is None and (item.get("version") == current_version or item.get("is_current")):
            return item
    for item in reversed(items):
        if isinstance(item, dict):
            return item
    return {}


def _metadata_defaults(metadata: dict[str, Any]) -> dict[str, Any]:
    route = metadata.get("generation_route")
    route = route if isinstance(route, dict) else {}
    return {
        "provider": route.get("provider"),
        "model": route.get("model"),
        "generation_quality": metadata.get("generation_quality"),
        "generation_profile_key": metadata.get("generation_profile_key"),
        "shot_tier": metadata.get("shot_tier") or route.get("shot_tier"),
        "resolution": route.get("resolution") or metadata.get("resolution"),
    }


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _normalize_dimensions(dimensions: dict[str, int] | None) -> dict[str, int]:
    normalized: dict[str, int] = {}
    if not isinstance(dimensions, dict):
        return normalized
    for key, value in dimensions.items():
        if not isinstance(key, str) or not key.strip():
            continue
        try:
            score = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= score <= 5:
            normalized[key.strip()] = score
    return normalized


class QualityMetricsService:
    def __init__(self, project_manager: ProjectManager):
        self.pm = project_manager

    def _metrics_path(self, project_name: str) -> Path:
        return self.pm.get_project_path(project_name) / QUALITY_METRICS_FILENAME

    def upsert_rating(
        self,
        *,
        project_name: str,
        resource_type: str,
        resource_id: str,
        rating: int,
        user_id: str,
        version: int | None = None,
        dimensions: dict[str, int] | None = None,
        note: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        generation_quality: str | None = None,
        shot_tier: str | None = None,
    ) -> dict[str, Any]:
        self.pm.load_project(project_name)
        project_dir = self.pm.get_project_path(project_name)
        metadata = _current_version_metadata(project_dir, resource_type, resource_id, version)
        defaults = _metadata_defaults(metadata)

        now = _now_iso()
        path = self._metrics_path(project_name)
        payload = _load_json(path)
        ratings = payload.get("ratings")
        if not isinstance(ratings, list):
            ratings = []

        normalized = {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "version": version,
            "rating": int(rating),
            "dimensions": _normalize_dimensions(dimensions),
            "note": note or "",
            "provider": provider or defaults.get("provider"),
            "model": model or defaults.get("model"),
            "generation_quality": generation_quality or defaults.get("generation_quality"),
            "generation_profile_key": defaults.get("generation_profile_key"),
            "shot_tier": shot_tier or defaults.get("shot_tier"),
            "resolution": defaults.get("resolution"),
            "user_id": user_id,
            "updated_at": now,
        }

        matched = False
        for index, item in enumerate(ratings):
            if not isinstance(item, dict):
                continue
            if (
                item.get("resource_type") == resource_type
                and item.get("resource_id") == resource_id
                and item.get("version") == version
                and item.get("user_id") == user_id
            ):
                ratings[index] = {**item, **normalized, "created_at": item.get("created_at") or now}
                normalized = ratings[index]
                matched = True
                break
        if not matched:
            normalized["created_at"] = now
            ratings.append(normalized)

        payload = {"schema_version": 1, "ratings": ratings, "updated_at": now}
        _write_json(path, payload)
        return {"rating": normalized}

    def get_stats(self, *, project_name: str) -> dict[str, Any]:
        self.pm.load_project(project_name)
        ratings = _load_json(self._metrics_path(project_name)).get("ratings")
        items = [item for item in ratings if isinstance(item, dict)] if isinstance(ratings, list) else []

        scores = [float(item["rating"]) for item in items if isinstance(item.get("rating"), int | float)]
        groups: dict[str, dict[str, list[float]]] = {
            "provider": {},
            "model": {},
            "resource_type": {},
            "generation_quality": {},
            "shot_tier": {},
        }
        dimension_scores: dict[str, list[float]] = {}
        for item in items:
            score = item.get("rating")
            if not isinstance(score, int | float):
                continue
            for key, bucket in groups.items():
                value = item.get(key) or "unknown"
                bucket.setdefault(str(value), []).append(float(score))
            dimensions = item.get("dimensions")
            if isinstance(dimensions, dict):
                for key, value in dimensions.items():
                    if isinstance(value, int | float):
                        dimension_scores.setdefault(str(key), []).append(float(value))

        return {
            "count": len(scores),
            "average_rating": _avg(scores),
            "dimension_averages": [
                {"key": name, "count": len(values), "average_rating": _avg(values)}
                for name, values in sorted(dimension_scores.items())
            ],
            "groups": {
                key: [
                    {"key": name, "count": len(values), "average_rating": _avg(values)}
                    for name, values in sorted(bucket.items())
                ]
                for key, bucket in groups.items()
            },
            "ratings": items[-100:],
        }

    def list_ratings(
        self,
        *,
        project_name: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        version: int | None = None,
    ) -> dict[str, Any]:
        self.pm.load_project(project_name)
        ratings = _load_json(self._metrics_path(project_name)).get("ratings")
        items = [item for item in ratings if isinstance(item, dict)] if isinstance(ratings, list) else []
        if resource_type:
            items = [item for item in items if item.get("resource_type") == resource_type]
        if resource_id:
            items = [item for item in items if item.get("resource_id") == resource_id]
        if version is not None:
            items = [item for item in items if item.get("version") == version]
        return {"ratings": items[-100:]}

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
    video_continuity = metadata.get("video_continuity")
    video_continuity = video_continuity if isinstance(video_continuity, dict) else {}
    reference_policy = metadata.get("provider_image_reference_policy")
    if not isinstance(reference_policy, dict):
        reference_policy = metadata.get("reference_image_policy")
    reference_policy = reference_policy if isinstance(reference_policy, dict) else {}
    requested_video_continuity = (
        video_continuity.get("requested_policy")
        or metadata.get("video_continuity_policy")
    )
    effective_video_continuity = video_continuity.get("effective_policy") or requested_video_continuity
    return {
        "provider": route.get("provider"),
        "model": route.get("model"),
        "generation_quality": metadata.get("generation_quality"),
        "generation_profile_key": metadata.get("generation_profile_key"),
        "resolution": route.get("resolution") or metadata.get("resolution"),
        "task_kind": route.get("task_kind"),
        "media_type": route.get("media_type"),
        "service_tier": route.get("service_tier"),
        "final_generation_mode": metadata.get("final_generation_mode"),
        "source_storyboard_generation_quality": metadata.get("source_storyboard_generation_quality"),
        "source_storyboard_provider": metadata.get("source_storyboard_provider"),
        "source_storyboard_model": metadata.get("source_storyboard_model"),
        "video_continuity_policy": requested_video_continuity,
        "video_continuity_effective_policy": effective_video_continuity,
        "reference_image_count": reference_policy.get("reference_image_count"),
        "reference_image_submitted_count": reference_policy.get("reference_image_submitted_count"),
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


def _score_of(item: dict[str, Any]) -> float | None:
    score = item.get("rating")
    return float(score) if isinstance(score, int | float) else None


def _dimension_average_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dimension_scores: dict[str, list[float]] = {}
    for item in items:
        dimensions = item.get("dimensions")
        if not isinstance(dimensions, dict):
            continue
        for key, value in dimensions.items():
            if isinstance(value, int | float):
                dimension_scores.setdefault(str(key), []).append(float(value))
    return [
        {"key": name, "count": len(values), "average_rating": _avg(values)}
        for name, values in sorted(dimension_scores.items())
    ]


def _group_value(item: dict[str, Any], group_key: str) -> tuple[str, dict[str, Any]]:
    unknown = "unknown"
    if group_key == "project":
        key = str(item.get("project_name") or unknown)
        return key, {
            "project_name": key,
            "project_title": item.get("project_title") or key,
            "label": item.get("project_title") or key,
        }
    if group_key == "provider_model":
        provider = str(item.get("provider") or unknown)
        model = str(item.get("model") or unknown)
        return f"{provider}/{model}", {
            "provider": provider,
            "model": model,
            "label": f"{provider} / {model}",
        }
    if group_key in {"video_continuity_policy", "video_continuity_effective_policy"}:
        value = str(item.get(group_key) or unknown)
        continuity_labels = {
            "auto": "自动",
            "start_only": "仅首帧",
            "end_frame": "首尾帧连续",
            "reference_assisted": "参考图辅助",
            unknown: unknown,
        }
        return value, {"label": continuity_labels.get(value, value), group_key: value}
    if group_key == "final_generation_mode":
        value = str(item.get(group_key) or unknown)
        mode_labels = {
            "draft_locked": "沿当前分镜",
            "fresh_sample": "重新出图",
            unknown: unknown,
        }
        return value, {"label": mode_labels.get(value, value), group_key: value}
    if group_key == "service_tier":
        value = str(item.get(group_key) or unknown)
        service_tier_labels = {
            "default": "默认",
            "flex": "Flex",
            unknown: unknown,
        }
        return value, {"label": service_tier_labels.get(value, value), group_key: value}
    if group_key == "source_storyboard_provider_model":
        provider = str(item.get("source_storyboard_provider") or unknown)
        model = str(item.get("source_storyboard_model") or unknown)
        return f"{provider}/{model}", {
            "source_storyboard_provider": provider,
            "source_storyboard_model": model,
            "label": f"{provider} / {model}",
        }
    if group_key == "reference_image_count":
        value = str(item.get(group_key) or unknown)
        label = f"{value} 张" if value != unknown else unknown
        return value, {"label": label, group_key: value}
    value = str(item.get(group_key) or unknown)
    return value, {"label": value, group_key: value}


def _group_stats(items: list[dict[str, Any]], group_key: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    metadata_by_key: dict[str, dict[str, Any]] = {}
    for item in items:
        if _score_of(item) is None:
            continue
        key, metadata = _group_value(item, group_key)
        buckets.setdefault(key, []).append(item)
        metadata_by_key.setdefault(key, metadata)

    rows: list[dict[str, Any]] = []
    for key, bucket_items in buckets.items():
        scores = [_score_of(item) for item in bucket_items]
        valid_scores = [score for score in scores if score is not None]
        rows.append(
            {
                "key": key,
                **metadata_by_key.get(key, {}),
                "count": len(valid_scores),
                "average_rating": _avg(valid_scores),
                "dimension_averages": _dimension_average_items(bucket_items),
            }
        )

    return sorted(
        rows,
        key=lambda item: (
            -int(item.get("count") or 0),
            -(float(item.get("average_rating")) if item.get("average_rating") is not None else -1),
            str(item.get("label") or item.get("key") or ""),
        ),
    )


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
            "resolution": defaults.get("resolution"),
            "task_kind": defaults.get("task_kind"),
            "media_type": defaults.get("media_type"),
            "service_tier": defaults.get("service_tier"),
            "final_generation_mode": defaults.get("final_generation_mode"),
            "source_storyboard_generation_quality": defaults.get("source_storyboard_generation_quality"),
            "video_continuity_policy": defaults.get("video_continuity_policy"),
            "video_continuity_effective_policy": defaults.get("video_continuity_effective_policy"),
            "reference_image_count": defaults.get("reference_image_count"),
            "reference_image_submitted_count": defaults.get("reference_image_submitted_count"),
            "source_storyboard_provider": defaults.get("source_storyboard_provider"),
            "source_storyboard_model": defaults.get("source_storyboard_model"),
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

    def _enrich_rating(self, project_name: str, project: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        project_dir = self.pm.get_project_path(project_name)
        metadata = _current_version_metadata(
            project_dir,
            str(item.get("resource_type") or ""),
            str(item.get("resource_id") or ""),
            item.get("version"),
        )
        defaults = _metadata_defaults(metadata)
        title = project.get("title")
        enriched = dict(item)
        enriched["project_name"] = project_name
        enriched["project_title"] = str(title).strip() if isinstance(title, str) and title.strip() else project_name
        for key, value in defaults.items():
            if enriched.get(key) in (None, "") and value not in (None, ""):
                enriched[key] = value
        return enriched

    def get_global_analysis(self) -> dict[str, Any]:
        ratings: list[dict[str, Any]] = []
        total_projects = 0

        for project_name in self.pm.list_projects():
            try:
                project = self.pm.load_project(project_name)
            except Exception:
                continue
            total_projects += 1
            raw_ratings = _load_json(self._metrics_path(project_name)).get("ratings")
            if not isinstance(raw_ratings, list):
                continue
            for item in raw_ratings:
                if not isinstance(item, dict) or _score_of(item) is None:
                    continue
                ratings.append(self._enrich_rating(project_name, project, item))

        scores = [_score_of(item) for item in ratings]
        valid_scores = [score for score in scores if score is not None]
        rated_projects = {str(item.get("project_name")) for item in ratings if item.get("project_name")}
        rated_models = {
            f"{item.get('provider') or 'unknown'}/{item.get('model') or 'unknown'}"
            for item in ratings
            if item.get("provider") or item.get("model")
        }

        group_keys = [
            "project",
            "provider",
            "model",
            "provider_model",
            "source_storyboard_provider_model",
            "resource_type",
            "generation_quality",
            "generation_profile_key",
            "service_tier",
            "resolution",
            "video_continuity_policy",
            "video_continuity_effective_policy",
            "final_generation_mode",
            "reference_image_count",
            "source_storyboard_generation_quality",
        ]
        return {
            "count": len(valid_scores),
            "average_rating": _avg(valid_scores),
            "project_count": len(rated_projects),
            "total_projects": total_projects,
            "rated_model_count": len(rated_models),
            "dimension_averages": _dimension_average_items(ratings),
            "groups": {key: _group_stats(ratings, key) for key in group_keys},
            "ratings": ratings[-200:],
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

"""Resolve quick/refined generation routes without breaking legacy draft/final settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from lib.config.registry import PROVIDER_REGISTRY
from lib.config.resolver import ConfigResolver, ProviderModel
from lib.script_splitting_templates import provider_capability_hash
from server.services.resolution_resolver import resolve_resolution

GenerationQuality = Literal["draft", "final", "custom"]
ImageCapability = Literal["t2i", "i2i"]
MediaType = Literal["image", "video"]
ShotTier = Literal["S", "A", "B"]


PROFILED_TASK_KINDS = frozenset({"character", "scene", "prop", "storyboard", "grid", "video", "reference_video"})
SHOT_TIER_TASK_KINDS = frozenset({"storyboard", "video", "reference_video"})
ROUTE_TRIGGER_KEYS = frozenset(
    {
        "quality",
        "generation_quality",
        "generation_profile",
        "resolution",
        "source_version",
        "generate_audio",
        "service_tier",
        "video_backend",
        "shot_tier",
    }
)


def _display_provider_model(provider_id: str, model_id: str) -> tuple[str, str]:
    meta = PROVIDER_REGISTRY.get(provider_id)
    provider_name = meta.display_name if meta else provider_id
    model_info = meta.models.get(model_id) if meta else None
    if model_info and model_info.display_name != model_id:
        model_name = f"{model_info.display_name} ({model_id})"
    else:
        model_name = model_id
    return provider_name, model_name


def _reference_video_model_hint(provider_id: str, model_id: str) -> str:
    provider = provider_id.lower()
    model = model_id.lower()
    if provider in {"ark", "ark-agent-plan"}:
        if "seedance-2" in model or "seedance2" in model:
            return "请确认当前火山方舟端点选择的是 Seedance 2.0 系列，并且没有被自定义端点配置覆盖。"
        return "火山方舟的 Seedance 1.x / 1.5 模型更适合文生、图生或首尾帧视频；参考视频请切换到 Seedance 2.0 或 Seedance 2.0 Fast。"
    if provider == "dashscope":
        return "阿里百炼的 t2v / i2v 模型不接收参考图；参考视频请切换到 happyhorse-1.0-r2v 或 wan2.7-r2v。"
    if provider == "vidu":
        return "Vidu 需要使用 reference2video 能力的模型；请切换到 Vidu Q3 Turbo、Vidu Q3 Reference、Vidu Q3 Mix、Vidu Q2 / Q2 Pro 或 Vidu 2.0。"
    if provider == "newapi":
        return "NewAPI 视频端点当前按不支持参考图处理；请改用支持 reference_images 的视频供应商，或用自定义供应商声明可用的参考图上限。"
    if provider not in PROVIDER_REGISTRY:
        return "自定义供应商当前声明的参考图上限为 0；请确认端点真的支持 reference_images / reference2video，并把 video_max_reference_images 设为大于 0。"
    return "请切换到支持参考图的视频模型，例如火山方舟 Seedance 2.0、Gemini Veo 3.1、Vidu reference2video、OpenAI Sora 2、Grok 视频或阿里百炼 r2v 模型。"


def _reference_video_requires_reference_images_message(
    provider_id: str,
    model_id: str,
    max_reference_images: int | None,
) -> str:
    provider_name, model_name = _display_provider_model(provider_id, model_id)
    limit = "未知" if max_reference_images is None else f"{max_reference_images} 张"
    hint = _reference_video_model_hint(provider_id, model_id)
    return (
        "参考视频模式需要能接收角色、场景、道具参考图的视频模型。"
        f"当前选择：{provider_name} / {model_name}，参考图上限为 {limit}，不能用于参考视频。"
        f"{hint}"
    )


@dataclass(frozen=True)
class GenerationRoute:
    """Resolved generation route passed to task execution."""

    task_kind: str
    media_type: MediaType
    quality: GenerationQuality | None
    profile_key: str | None
    provider_id: str
    model_id: str
    resolution: str | None = None
    duration_seconds: int | None = None
    generate_audio: bool | None = None
    service_tier: str = "default"
    seed: int | None = None
    supported_resolutions: list[str] = field(default_factory=list)
    supported_durations: list[int] = field(default_factory=list)
    duration_resolution_constraints: dict[str, list[int]] = field(default_factory=dict)
    shot_tier: ShotTier | None = None
    shot_tier_strategy: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    effective_payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def default_generation_profiles() -> dict[str, dict[str, Any]]:
    """Return the built-in profile schema used by newly migrated projects."""

    return {
        "asset": {
            "image_provider_t2i": None,
            "image_provider_i2i": None,
            "resolution": "2K",
        },
        "storyboard_draft": {
            "image_provider_t2i": None,
            "image_provider_i2i": None,
            "resolution": "1K",
        },
        "storyboard_final": {
            "image_provider_t2i": None,
            "image_provider_i2i": None,
            "resolution": "2K",
        },
        "grid": {
            "image_provider_t2i": None,
            "image_provider_i2i": None,
            "resolution": "2K",
        },
        "video_draft": {
            "video_backend": None,
            "resolution": "720p",
            "duration_seconds": None,
            "generate_audio": False,
            "service_tier": "default",
        },
        "video_final": {
            "video_backend": None,
            "resolution": "1080p",
            "duration_seconds": None,
            "generate_audio": True,
            "service_tier": "default",
        },
        "reference_video_draft": {
            "video_backend": None,
            "resolution": "720p",
            "duration_seconds": None,
            "generate_audio": False,
            "service_tier": "default",
        },
        "reference_video_final": {
            "video_backend": None,
            "resolution": "1080p",
            "duration_seconds": None,
            "generate_audio": True,
            "service_tier": "default",
        },
    }


def default_shot_tier_profiles() -> dict[str, dict[str, Any]]:
    """Return built-in S/A/B shot strategies.

    The defaults intentionally avoid hard-coding a provider choice. Projects can
    attach per-profile overrides under ``profiles`` when they want a tier to
    force a route field such as resolution, backend, audio, or service tier.
    """

    return {
        "S": {
            "label": "hero",
            "retry_budget": 1,
            "reference_image_policy": "full_context",
            "video_continuity_policy": "auto",
            "prefer_final_storyboard_source": True,
            "profiles": {
                "storyboard_final": {
                    "resolution": "2K",
                },
                "video_final": {
                    "resolution": "1080p",
                    "generate_audio": True,
                    "service_tier": "default",
                },
            },
        },
        "A": {
            "label": "standard",
            "retry_budget": 1,
            "reference_image_policy": "balanced",
            "video_continuity_policy": "auto",
            "prefer_final_storyboard_source": True,
            "profiles": {},
        },
        "B": {
            "label": "utility",
            "retry_budget": 1,
            "reference_image_policy": "lean",
            "video_continuity_policy": "start_only",
            "prefer_final_storyboard_source": False,
            "profiles": {
                "storyboard_final": {
                    "resolution": "1K",
                },
                "video_final": {
                    "resolution": "720p",
                    "generate_audio": False,
                    "service_tier": "default",
                },
            },
        },
    }


def compact_generation_payload(values: dict[str, Any]) -> dict[str, Any]:
    """Drop unset generation override fields before enqueuing."""

    return {key: value for key, value in values.items() if value is not None}


def split_backend_pair(raw: object) -> tuple[str, str] | None:
    """Parse ``provider/model`` style backend values."""

    if not isinstance(raw, str) or "/" not in raw:
        return None
    provider, model = raw.split("/", 1)
    provider = provider.strip()
    model = model.strip()
    if not provider or not model:
        return None
    return provider, model


def normalize_generation_quality(raw: object) -> GenerationQuality | None:
    """Normalize request quality values to the small stable enum."""

    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    if value in {"draft", "fast", "quick", "快速", "快速版"}:
        return "draft"
    if value in {"final", "refined", "refine", "polish", "精修", "精修版"}:
        return "final"
    if value == "custom":
        return value  # type: ignore[return-value]
    return None


def normalize_shot_tier(raw: object) -> ShotTier | None:
    """Normalize shot tier values to S/A/B."""

    if not isinstance(raw, str):
        return None
    value = raw.strip().upper()
    if value in {"S", "A", "B"}:
        return value  # type: ignore[return-value]
    return None


def default_quality_for_task(task_kind: str) -> GenerationQuality:
    """Default profile quality once a project opts into generation_profiles."""

    if task_kind in {"storyboard", "video", "reference_video"}:
        return "draft"
    return "final"


def default_shot_tier_for_task(task_kind: str) -> ShotTier | None:
    """Default shot tier for shot-level generation tasks."""

    if task_kind in SHOT_TIER_TASK_KINDS:
        return "A"
    return None


def profile_key_for(task_kind: str, quality: GenerationQuality | None) -> str | None:
    """Map task + quality to a generation profile key."""

    if quality == "custom":
        return None
    if task_kind in {"character", "scene", "prop"}:
        return "asset"
    if task_kind == "storyboard" and quality in {"draft", "final"}:
        return f"storyboard_{quality}"
    if task_kind == "grid" and quality in {"draft", "final"}:
        return "grid"
    if task_kind == "video" and quality in {"draft", "final"}:
        return f"video_{quality}"
    if task_kind == "reference_video" and quality in {"draft", "final"}:
        return f"reference_video_{quality}"
    return None


def normalize_task_quality(task_kind: str, quality: GenerationQuality | None) -> GenerationQuality | None:
    """Apply task-specific quality semantics."""

    if task_kind == "grid" and quality in {"draft", "final"}:
        return "final"
    return quality


def should_resolve_generation_route(project: dict | None, payload: dict | None) -> bool:
    """Return True only when new routing inputs are present."""

    if project and isinstance(project.get("generation_profiles"), dict):
        return True
    if not payload:
        return False
    return any(key in payload for key in ROUTE_TRIGGER_KEYS)


def merged_generation_profiles(project: dict | None) -> dict[str, dict[str, Any]]:
    """Merge project profiles over the built-in schema."""

    profiles = {key: dict(value) for key, value in default_generation_profiles().items()}
    raw_profiles = project.get("generation_profiles") if isinstance(project, dict) else None
    if isinstance(raw_profiles, dict):
        for key, value in raw_profiles.items():
            if isinstance(value, dict):
                profiles[key] = {**profiles.get(key, {}), **value}
    for key in _VIDEO_PROFILE_KEYS:
        if key in profiles:
            profiles[key] = _drop_quality_duration(key, profiles[key])
    return profiles


def merged_shot_tier_profiles(project: dict | None) -> dict[str, dict[str, Any]]:
    """Merge project S/A/B strategy settings over the built-in schema."""

    profiles = {key: dict(value) for key, value in default_shot_tier_profiles().items()}
    raw_profiles = None
    if isinstance(project, dict):
        raw_profiles = project.get("shot_tier_profiles") or project.get("shot_tiers")
    if isinstance(raw_profiles, dict):
        for key, value in raw_profiles.items():
            tier = normalize_shot_tier(key)
            if tier is None or not isinstance(value, dict):
                continue
            merged = {**profiles.get(tier, {}), **value}
            default_profile_overrides = profiles.get(tier, {}).get("profiles")
            raw_profile_overrides = value.get("profiles")
            if isinstance(default_profile_overrides, dict) or isinstance(raw_profile_overrides, dict):
                merged["profiles"] = {
                    **(default_profile_overrides if isinstance(default_profile_overrides, dict) else {}),
                    **(raw_profile_overrides if isinstance(raw_profile_overrides, dict) else {}),
                }
            profiles[tier] = merged
    return profiles


def _profile_for(
    project: dict | None,
    task_kind: str,
    quality: GenerationQuality | None,
    shot_tier: ShotTier | None = None,
) -> tuple[str | None, dict[str, Any]]:
    if quality is None and project and isinstance(project.get("generation_profiles"), dict):
        quality = default_quality_for_task(task_kind)
    profile_key = profile_key_for(task_kind, quality)
    if profile_key is None:
        return None, {}
    profile = dict(merged_generation_profiles(project).get(profile_key) or {})
    if shot_tier is not None:
        strategy = merged_shot_tier_profiles(project).get(shot_tier) or {}
        overrides = strategy.get("profiles")
        profile_override = overrides.get(profile_key) if isinstance(overrides, dict) else None
        legacy_profile_override = strategy.get(profile_key)
        if isinstance(profile_override, dict):
            profile.update(profile_override)
        elif isinstance(legacy_profile_override, dict):
            profile.update(legacy_profile_override)
    return profile_key, profile


def _shot_tier_strategy(project: dict | None, shot_tier: ShotTier | None) -> dict[str, Any]:
    if shot_tier is None:
        return {}
    strategy = dict(merged_shot_tier_profiles(project).get(shot_tier) or {})
    strategy.pop("profiles", None)
    return compact_generation_payload(strategy)


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


_VIDEO_PROFILE_KEYS = frozenset({"video_draft", "video_final", "reference_video_draft", "reference_video_final"})
_VIDEO_RESOLUTION_RANKS = {
    "360p": 360,
    "480p": 480,
    "540p": 540,
    "720p": 720,
    "1024p": 1024,
    "1080p": 1080,
    "2k": 2000,
    "4k": 4000,
}


def _drop_quality_duration(profile_key: str, profile: dict[str, Any]) -> dict[str, Any]:
    """Draft/final profiles must not override the actual scene/unit duration."""

    normalized = dict(profile)
    if profile_key in _VIDEO_PROFILE_KEYS:
        normalized.pop("duration_seconds", None)
    return normalized


def _merge_payload(profile: dict[str, Any], payload: dict[str, Any] | None) -> dict[str, Any]:
    merged = _without_none(profile)
    if payload:
        merged.update(payload)
    return merged


def _resolution_rank(value: str) -> int | None:
    normalized = value.strip().lower()
    if normalized in _VIDEO_RESOLUTION_RANKS:
        return _VIDEO_RESOLUTION_RANKS[normalized]
    if normalized.endswith("p"):
        try:
            return int(normalized[:-1])
        except ValueError:
            return None
    if normalized.endswith("k"):
        try:
            return int(float(normalized[:-1]) * 1000)
        except ValueError:
            return None
    return None


def video_resolution_rank(value: object) -> int | None:
    """Return a comparable video resolution rank when the value is known."""

    if not isinstance(value, str) or not value.strip():
        return None
    return _resolution_rank(value)


def is_video_resolution_below(actual: object, target: object) -> bool:
    """Return True only when both resolutions are known and actual < target."""

    actual_rank = video_resolution_rank(actual)
    target_rank = video_resolution_rank(target)
    if actual_rank is None or target_rank is None:
        return False
    return actual_rank < target_rank


def coerce_video_resolution_for_options(
    resolution: str | None,
    supported_resolutions: list[str] | tuple[str, ...] | None,
) -> tuple[str | None, dict[str, Any] | None]:
    """Return a provider-supported resolution, preferring the closest non-higher option."""

    supported = [str(item).strip() for item in supported_resolutions or [] if str(item).strip()]
    if not resolution or not supported or resolution in supported:
        return resolution, None

    requested_rank = _resolution_rank(resolution)
    ranked = [(item, _resolution_rank(item)) for item in supported]
    if requested_rank is None:
        resolved = supported[-1]
    else:
        lower_or_equal = [item for item, rank in ranked if rank is not None and rank <= requested_rank]
        if lower_or_equal:
            resolved = max(lower_or_equal, key=lambda item: _resolution_rank(item) or -1)
        else:
            resolved = min(ranked, key=lambda item: item[1] if item[1] is not None else 10**9)[0]

    return resolved, {
        "key": "video_resolution_adjusted",
        "params": {
            "requested": resolution,
            "resolved": resolved,
            "supported": ", ".join(supported),
        },
    }


def coerce_video_duration_for_options(
    duration_seconds: int | None,
    supported_durations: list[int] | tuple[int, ...] | None,
) -> tuple[int | None, dict[str, Any] | None]:
    """Return a provider-supported duration, choosing the nearest non-shorter value when possible."""

    supported = sorted({int(item) for item in supported_durations or []})
    if duration_seconds is None or not supported or duration_seconds in supported:
        return duration_seconds, None

    higher_or_equal = [item for item in supported if item >= duration_seconds]
    resolved = higher_or_equal[0] if higher_or_equal else supported[-1]
    return resolved, {
        "key": "video_duration_adjusted",
        "params": {
            "requested": duration_seconds,
            "resolved": resolved,
            "supported": ", ".join(str(item) for item in supported),
        },
    }


def _payload_resolution(payload: dict[str, Any] | None, profile: dict[str, Any]) -> str | None:
    value = payload.get("resolution") if payload else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    profile_value = profile.get("resolution")
    if isinstance(profile_value, str) and profile_value.strip():
        return profile_value.strip()
    return None


def _to_int_or_none(raw: object) -> int | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not value.is_integer():
        return None
    return int(value)


def _bool_or_none(raw: object) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        value = raw.strip().lower()
        if value in {"true", "1", "yes", "on"}:
            return True
        if value in {"false", "0", "no", "off"}:
            return False
    return None


def _service_tier(payload: dict[str, Any] | None, profile: dict[str, Any]) -> str:
    raw = payload.get("service_tier") if payload else None
    if raw is None and payload:
        settings = payload.get("video_provider_settings")
        raw = settings.get("service_tier") if isinstance(settings, dict) else None
    if raw is None:
        raw = profile.get("service_tier")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return "default"


def _model_default_duration(provider_id: str | None, model_id: str | None) -> int | None:
    if not provider_id or not model_id:
        return None
    meta = PROVIDER_REGISTRY.get(provider_id)
    model_info = meta.models.get(model_id) if meta else None
    if not model_info or not model_info.supported_durations:
        return None
    return int(model_info.supported_durations[0])


def duration_options_for_resolution(
    supported_durations: list[int] | tuple[int, ...] | None,
    duration_resolution_constraints: dict[str, list[int]] | None,
    resolution: str | None,
) -> list[int]:
    """Return durations legal for the selected resolution.

    ``supported_durations`` remains the broad model capability. Some providers
    further restrict a resolution, e.g. Veo 1080p can be limited to 8s. When a
    resolution-specific constraint exists it becomes the effective execution
    guard; otherwise the broad list is kept.
    """

    base = [int(item) for item in supported_durations or []]
    if not resolution or not duration_resolution_constraints:
        return base

    wanted = resolution.strip().lower()
    constrained: list[int] | None = None
    for key, values in duration_resolution_constraints.items():
        if str(key).strip().lower() == wanted:
            constrained = [int(item) for item in values or []]
            break
    if constrained is None:
        return base
    if not base:
        return constrained
    intersection = [item for item in base if item in constrained]
    return intersection or constrained


def _apply_video_backend_override(effective_payload: dict[str, Any], profile: dict[str, Any]) -> None:
    """Translate video_backend into ConfigResolver's payload keys."""

    payload_pair = split_backend_pair(effective_payload.get("video_backend"))
    profile_pair = split_backend_pair(profile.get("video_backend"))
    pair = payload_pair or profile_pair
    if pair is None:
        return
    provider_id, model_id = pair
    if not effective_payload.get("video_provider"):
        effective_payload["video_provider"] = provider_id
    if not effective_payload.get("video_model"):
        effective_payload["video_model"] = model_id


async def resolve_generation_route(
    *,
    project: dict | None,
    payload: dict[str, Any] | None,
    task_kind: str,
    quality: object = None,
    capability: ImageCapability | None = None,
    resolver: ConfigResolver,
    project_name: str | None = None,
) -> GenerationRoute:
    """Resolve provider/model and quality settings for a generation task."""

    normalized_quality = normalize_generation_quality(quality)
    if normalized_quality is None and isinstance(payload, dict):
        normalized_quality = normalize_generation_quality(payload.get("generation_quality"))
        if normalized_quality is None:
            normalized_quality = normalize_generation_quality(payload.get("quality"))
    if normalized_quality is None and project and isinstance(project.get("generation_profiles"), dict):
        normalized_quality = default_quality_for_task(task_kind)
    normalized_quality = normalize_task_quality(task_kind, normalized_quality)
    shot_tier = normalize_shot_tier(payload.get("shot_tier") if isinstance(payload, dict) else None)
    if shot_tier is None:
        shot_tier = default_shot_tier_for_task(task_kind)
    shot_tier_strategy = _shot_tier_strategy(project, shot_tier)
    profile_key, profile = _profile_for(project, task_kind, normalized_quality, shot_tier)
    effective_payload = _merge_payload(profile, payload)

    if task_kind in {"video", "reference_video"}:
        return await _resolve_video_route(
            project=project,
            payload=payload,
            task_kind=task_kind,
            quality=normalized_quality,
            profile_key=profile_key,
            profile=profile,
            effective_payload=effective_payload,
            shot_tier=shot_tier,
            shot_tier_strategy=shot_tier_strategy,
            resolver=resolver,
            project_name=project_name,
        )

    return await _resolve_image_route(
        project=project,
        payload=payload,
        task_kind=task_kind,
        quality=normalized_quality,
        profile_key=profile_key,
        profile=profile,
        effective_payload=effective_payload,
        shot_tier=shot_tier,
        shot_tier_strategy=shot_tier_strategy,
        resolver=resolver,
        capability=capability or "t2i",
    )


async def _resolve_image_route(
    *,
    project: dict | None,
    payload: dict[str, Any] | None,
    task_kind: str,
    quality: GenerationQuality | None,
    profile_key: str | None,
    profile: dict[str, Any],
    effective_payload: dict[str, Any],
    shot_tier: ShotTier | None,
    shot_tier_strategy: dict[str, Any],
    resolver: ConfigResolver,
    capability: ImageCapability,
) -> GenerationRoute:
    resolved = await resolver.resolve_image_backend(project, effective_payload, capability=capability)
    resolution = _payload_resolution(payload, profile)
    if resolution is None:
        resolution = await resolve_resolution(project or {}, resolved.provider_id, resolved.model_id)
    metadata = _build_metadata(
        task_kind=task_kind,
        media_type="image",
        quality=quality,
        profile_key=profile_key,
        resolved=resolved,
        resolution=resolution,
        shot_tier=shot_tier,
        shot_tier_strategy=shot_tier_strategy,
        source_version=payload.get("source_version") if payload else None,
    )
    return GenerationRoute(
        task_kind=task_kind,
        media_type="image",
        quality=quality,
        profile_key=profile_key,
        provider_id=resolved.provider_id,
        model_id=resolved.model_id,
        resolution=resolution,
        shot_tier=shot_tier,
        shot_tier_strategy=shot_tier_strategy,
        effective_payload=effective_payload,
        metadata=metadata,
    )


async def _resolve_video_route(
    *,
    project: dict | None,
    payload: dict[str, Any] | None,
    task_kind: str,
    quality: GenerationQuality | None,
    profile_key: str | None,
    profile: dict[str, Any],
    effective_payload: dict[str, Any],
    shot_tier: ShotTier | None,
    shot_tier_strategy: dict[str, Any],
    resolver: ConfigResolver,
    project_name: str | None,
) -> GenerationRoute:
    _apply_video_backend_override(effective_payload, profile)
    resolved = await resolver.resolve_video_backend(project, effective_payload)

    warnings: list[dict[str, Any]] = []
    supported_resolutions: list[str] = []
    supported_durations: list[int] = []
    duration_resolution_constraints: dict[str, list[int]] = {}
    supports_generate_audio: bool | None = None
    supports_seed: bool | None = None
    service_tiers: list[str] = []
    max_reference_images: int | None = None
    provider_capability_hash_value = ""
    try:
        caps = await resolver.video_capabilities_for_model(resolved.provider_id, resolved.model_id, project)
        caps_for_hash = dict(caps)
        caps_for_hash.setdefault("provider_id", resolved.provider_id)
        caps_for_hash.setdefault("model", resolved.model_id)
        provider_capability_hash_value = provider_capability_hash(caps_for_hash)
        supported_resolutions = [str(item) for item in caps.get("resolutions") or []]
        supported_durations = [int(item) for item in caps.get("supported_durations") or []]
        duration_resolution_constraints = {
            str(key): [int(item) for item in value or []]
            for key, value in (caps.get("duration_resolution_constraints") or {}).items()
        }
        supports_generate_audio = bool(caps["supports_generate_audio"]) if "supports_generate_audio" in caps else None
        supports_seed = bool(caps["supports_seed"]) if "supports_seed" in caps else None
        service_tiers = [str(item) for item in caps.get("service_tiers") or [] if str(item)]
        if caps.get("max_reference_images") is not None:
            max_reference_images = int(caps.get("max_reference_images") or 0)
    except Exception as exc:
        supported_resolutions = []
        supported_durations = []
        duration_resolution_constraints = {}
        supports_generate_audio = None
        supports_seed = None
        service_tiers = []
        max_reference_images = None
        warnings.append(
            {
                "key": "video_capabilities_unavailable",
                "params": {
                    "provider": resolved.provider_id,
                    "model": resolved.model_id,
                    "reason": str(exc),
                },
            }
        )

    if task_kind == "reference_video" and max_reference_images == 0:
        raise ValueError(
            _reference_video_requires_reference_images_message(
                resolved.provider_id,
                resolved.model_id,
                max_reference_images,
            )
        )

    resolution = _payload_resolution(payload, profile)
    if resolution is None:
        resolution = await resolve_resolution(project or {}, resolved.provider_id, resolved.model_id)
    resolution, resolution_warning = coerce_video_resolution_for_options(resolution, supported_resolutions)
    if resolution_warning:
        warnings.append(resolution_warning)
    effective_supported_durations = duration_options_for_resolution(
        supported_durations,
        duration_resolution_constraints,
        resolution,
    )

    duration_seconds = _to_int_or_none(payload.get("duration_seconds") if payload else None)
    if duration_seconds is None:
        duration_seconds = _to_int_or_none(profile.get("duration_seconds"))
    if duration_seconds is None and task_kind != "reference_video" and project:
        duration_seconds = _to_int_or_none(project.get("default_duration"))
    if duration_seconds is None and task_kind != "reference_video":
        duration_seconds = (
            effective_supported_durations[0]
            if effective_supported_durations
            else _model_default_duration(
                resolved.provider_id,
                resolved.model_id,
            )
        )
    if duration_seconds is not None:
        duration_seconds, duration_warning = coerce_video_duration_for_options(
            duration_seconds,
            effective_supported_durations,
        )
        if duration_warning:
            warnings.append(duration_warning)

    generate_audio = _bool_or_none(payload.get("generate_audio") if payload else None)
    if generate_audio is None:
        generate_audio = _bool_or_none(profile.get("generate_audio"))
    if generate_audio is None and project_name:
        generate_audio = await resolver.video_generate_audio(project_name)
    if generate_audio and supports_generate_audio is False:
        warnings.append(
            {
                "key": "video_generate_audio_disabled",
                "params": {
                    "provider": resolved.provider_id,
                    "model": resolved.model_id,
                },
            }
        )
        generate_audio = False

    service_tier = _service_tier(payload, profile)
    if service_tiers and service_tier not in service_tiers:
        resolved_tier = service_tiers[0]
        warnings.append(
            {
                "key": "video_service_tier_adjusted",
                "params": {
                    "requested": service_tier,
                    "resolved": resolved_tier,
                    "supported": ", ".join(service_tiers),
                },
            }
        )
        service_tier = resolved_tier
    seed = _to_int_or_none(payload.get("seed") if payload else None)
    if seed is None:
        seed = _to_int_or_none(profile.get("seed"))
    if seed is not None and supports_seed is False:
        warnings.append(
            {
                "key": "video_seed_ignored",
                "params": {
                    "provider": resolved.provider_id,
                    "model": resolved.model_id,
                },
            }
        )
        seed = None

    metadata = _build_metadata(
        task_kind=task_kind,
        media_type="video",
        quality=quality,
        profile_key=profile_key,
        resolved=resolved,
        resolution=resolution,
        duration_seconds=duration_seconds,
        generate_audio=generate_audio,
        service_tier=service_tier,
        seed=seed,
        shot_tier=shot_tier,
        shot_tier_strategy=shot_tier_strategy,
        supported_resolutions=supported_resolutions,
        supported_durations=effective_supported_durations,
        duration_resolution_constraints=duration_resolution_constraints,
        warnings=warnings,
        source_version=payload.get("source_version") if payload else None,
        provider_capability_hash=provider_capability_hash_value,
    )
    return GenerationRoute(
        task_kind=task_kind,
        media_type="video",
        quality=quality,
        profile_key=profile_key,
        provider_id=resolved.provider_id,
        model_id=resolved.model_id,
        resolution=resolution,
        duration_seconds=duration_seconds,
        generate_audio=generate_audio,
        service_tier=service_tier,
        seed=seed,
        shot_tier=shot_tier,
        shot_tier_strategy=shot_tier_strategy,
        supported_resolutions=supported_resolutions,
        supported_durations=effective_supported_durations,
        duration_resolution_constraints=duration_resolution_constraints,
        warnings=warnings,
        effective_payload=effective_payload,
        metadata=metadata,
    )


def _build_metadata(
    *,
    task_kind: str,
    media_type: MediaType,
    quality: GenerationQuality | None,
    profile_key: str | None,
    resolved: ProviderModel,
    resolution: str | None,
    duration_seconds: int | None = None,
    generate_audio: bool | None = None,
    service_tier: str | None = None,
    seed: int | None = None,
    shot_tier: ShotTier | None = None,
    shot_tier_strategy: dict[str, Any] | None = None,
    supported_resolutions: list[str] | None = None,
    supported_durations: list[int] | None = None,
    duration_resolution_constraints: dict[str, list[int]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    source_version: object = None,
    provider_capability_hash: str | None = None,
) -> dict[str, Any]:
    route = compact_generation_payload(
        {
            "task_kind": task_kind,
            "media_type": media_type,
            "provider": resolved.provider_id,
            "model": resolved.model_id,
            "resolution": resolution,
            "duration_seconds": duration_seconds,
            "generate_audio": generate_audio,
            "service_tier": service_tier,
            "seed": seed,
            "shot_tier": shot_tier,
            "shot_tier_strategy": shot_tier_strategy or None,
            "supported_resolutions": supported_resolutions,
            "supported_durations": supported_durations,
            "duration_resolution_constraints": duration_resolution_constraints,
            "warnings": warnings or None,
            "provider_capability_hash": provider_capability_hash,
        }
    )
    return compact_generation_payload(
        {
            "generation_quality": quality,
            "generation_profile_key": profile_key,
            "generation_route": route,
            "generation_route_warnings": warnings or None,
            "shot_tier": shot_tier,
            "shot_tier_strategy": shot_tier_strategy or None,
            "source_version": source_version,
            "provider_capability_hash": provider_capability_hash,
        }
    )

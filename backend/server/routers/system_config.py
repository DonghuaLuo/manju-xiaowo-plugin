"""
System configuration APIs.

Handles non-provider global settings: default backends, audio, anthropic config.
Provider-specific configuration (API keys, rate limits, credentials, connection test)
is managed by the providers router.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from lib.config.registry import STANDARD_PROVIDER_REGISTRY
from lib.config.repository import mask_secret
from lib.config.resolver import ConfigResolver
from lib.config.service import ConfigService
from lib.db import get_async_session
from lib.i18n import Translator
from server.auth import CurrentUser
from server.dependencies import get_config_service
from server.routers._validators import validate_backend_value

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _OptionsDict(TypedDict):
    video_backends: list[str]
    image_backends: list[str]
    text_backends: list[str]
    provider_names: dict[str, str]


async def _build_options(svc: ConfigService, session: AsyncSession) -> _OptionsDict:
    """Compute available backends from ready providers."""
    statuses = await svc.get_all_providers_status()
    ready_providers = {s.name for s in statuses if s.status == "ready"}

    buckets: dict[str, list[str]] = {
        "video_backends": [],
        "image_backends": [],
        "text_backends": [],
    }
    provider_names: dict[str, str] = {}
    _MEDIA_TO_BUCKET = {"video": "video_backends", "image": "image_backends", "text": "text_backends"}

    for provider_id, meta in STANDARD_PROVIDER_REGISTRY.items():
        if provider_id not in ready_providers:
            continue
        for model_id, model_info in meta.models.items():
            bucket = _MEDIA_TO_BUCKET.get(model_info.media_type)
            if bucket:
                buckets[bucket].append(f"{provider_id}/{model_id}")

    from lib.custom_provider import make_provider_id
    from lib.custom_provider.endpoints import endpoint_to_media_type
    from lib.db.repositories.custom_provider_repo import CustomProviderRepository

    try:
        repo = CustomProviderRepository(session)
        providers = await repo.list_providers()
        provider_name_map = {p.id: p.display_name for p in providers}
        enabled_models = await repo.list_all_enabled_models()
        for model in enabled_models:
            pid = make_provider_id(model.provider_id)
            media_type = endpoint_to_media_type(model.endpoint)
            bucket = _MEDIA_TO_BUCKET.get(media_type)
            if bucket:
                buckets[bucket].append(f"{pid}/{model.model_id}")
            if pid not in provider_names and model.provider_id in provider_name_map:
                provider_names[pid] = provider_name_map[model.provider_id]
    except Exception:
        pass  # Non-fatal: custom providers unavailable shouldn't break the options endpoint

    return {**buckets, "provider_names": provider_names}  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SystemConfigPatchRequest(BaseModel):
    default_video_backend: str | None = None
    default_video_service_tier: str | None = None
    default_image_backend: str | None = None
    default_image_backend_t2i: str | None = None
    default_image_backend_i2i: str | None = None
    default_image_output_format: str | None = None
    default_text_backend: str | None = None
    video_generate_audio: bool | None = None
    anthropic_api_key: str | None = None
    anthropic_base_url: str | None = None
    anthropic_model: str | None = None
    anthropic_default_haiku_model: str | None = None
    anthropic_default_opus_model: str | None = None
    anthropic_default_sonnet_model: str | None = None
    claude_code_subagent_model: str | None = None
    agent_session_cleanup_delay_seconds: int | None = None
    agent_max_concurrent_sessions: int | None = None
    text_backend_script: str | None = None
    text_backend_overview: str | None = None
    text_backend_style: str | None = None


# Setting keys that map directly to string DB settings
#
# DEPRECATED: anthropic_api_key / anthropic_base_url 已迁移至 agent_anthropic_credentials 表
# (spec 2026-05-11-agent-url-config-optimization)。这里保留 anthropic_base_url 读写仅作旧客户端
# 兼容；新 UI 走 /api/v1/agent/credentials/* 接口。计划在 0.14.0 删除 anthropic_api_key /
# anthropic_base_url 字段，anthropic_*_model 系列保留（仍由 Section 2 Model Routing 管理）。
_STRING_SETTINGS = (
    "anthropic_base_url",
    "anthropic_model",
    "anthropic_default_haiku_model",
    "anthropic_default_opus_model",
    "anthropic_default_sonnet_model",
    "claude_code_subagent_model",
    "text_backend_script",
    "text_backend_overview",
    "text_backend_style",
)


# ---------------------------------------------------------------------------
# GET /system/config
# ---------------------------------------------------------------------------


@router.get("/system/config")
async def get_system_config(
    _user: CurrentUser,
    svc: Annotated[ConfigService, Depends(get_config_service)],
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    # Read all settings in a single query
    all_s = await svc.get_all_settings()
    video_generate_audio_raw = all_s.get("video_generate_audio", "")
    video_generate_audio = (
        video_generate_audio_raw.lower() in ("true", "1", "yes")
        if video_generate_audio_raw
        else ConfigResolver._DEFAULT_VIDEO_GENERATE_AUDIO
    )
    anthropic_key = all_s.get("anthropic_api_key", "")
    # 兼容新凭证目录：旧 system_settings 没填但 agent_anthropic_credentials 有 active 时
    # 也算 is_set，避免 dashboard "未配置" 红点误报
    if not anthropic_key:
        from lib.db.repositories.agent_credential_repo import AgentCredentialRepository

        active_cred = await AgentCredentialRepository(session).get_active()
        if active_cred is not None:
            anthropic_key = active_cred.api_key

    settings: dict[str, Any] = {
        "default_video_backend": all_s.get("default_video_backend", ""),
        "default_video_service_tier": all_s.get("default_video_service_tier") or "default",
        "default_image_backend": all_s.get("default_image_backend", ""),
        "default_image_backend_t2i": all_s.get("default_image_backend_t2i", ""),
        "default_image_backend_i2i": all_s.get("default_image_backend_i2i", ""),
        "default_image_output_format": all_s.get("default_image_output_format", "auto") or "auto",
        "default_text_backend": all_s.get("default_text_backend", ""),
        "video_generate_audio": video_generate_audio,
        "anthropic_api_key": {
            "is_set": bool(anthropic_key),
            "masked": mask_secret(anthropic_key) if anthropic_key else None,
        },
        "anthropic_base_url": all_s.get("anthropic_base_url") or None,
        "anthropic_model": all_s.get("anthropic_model") or None,
        "anthropic_default_haiku_model": all_s.get("anthropic_default_haiku_model") or None,
        "anthropic_default_opus_model": all_s.get("anthropic_default_opus_model") or None,
        "anthropic_default_sonnet_model": all_s.get("anthropic_default_sonnet_model") or None,
        "claude_code_subagent_model": all_s.get("claude_code_subagent_model") or None,
        "agent_session_cleanup_delay_seconds": int(all_s.get("agent_session_cleanup_delay_seconds") or "300"),
        "agent_max_concurrent_sessions": int(all_s.get("agent_max_concurrent_sessions") or "5"),
        "text_backend_script": all_s.get("text_backend_script") or "",
        "text_backend_overview": all_s.get("text_backend_overview") or "",
        "text_backend_style": all_s.get("text_backend_style") or "",
    }

    options = await _build_options(svc, session)

    return {"settings": settings, "options": options}


# ---------------------------------------------------------------------------
# PATCH /system/config
# ---------------------------------------------------------------------------


@router.patch("/system/config")
async def patch_system_config(
    req: SystemConfigPatchRequest,
    _user: CurrentUser,
    svc: Annotated[ConfigService, Depends(get_config_service)],
    _t: Translator,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for field_name in req.model_fields_set:
        patch[field_name] = getattr(req, field_name)

    # Validate backend references (empty string = auto-resolve)
    for backend_key in (
        "default_video_backend",
        "default_image_backend",
        "default_image_backend_t2i",
        "default_image_backend_i2i",
        "default_text_backend",
    ):
        if backend_key in patch:
            value = str(patch[backend_key] or "").strip()
            if value:
                validate_backend_value(value, backend_key, _t)
            await svc.set_setting(backend_key, value)

    if "default_video_service_tier" in patch:
        value = str(patch["default_video_service_tier"] or "default").strip().lower()
        if value not in {"default", "flex"}:
            raise HTTPException(status_code=422, detail="default_video_service_tier 只能是 default 或 flex")
        await svc.set_setting("default_video_service_tier", value)

    if "default_image_output_format" in patch:
        value = str(patch["default_image_output_format"] or "auto").strip().lower()
        if value == "jpeg":
            value = "jpg"
        if value not in {"auto", "png", "jpg", "webp"}:
            raise HTTPException(status_code=422, detail="default_image_output_format 只能是 auto/png/jpg/webp")
        await svc.set_setting("default_image_output_format", value)

    # Boolean settings
    if "video_generate_audio" in patch and patch["video_generate_audio"] is not None:
        await svc.set_setting("video_generate_audio", "true" if patch["video_generate_audio"] else "false")

    # Anthropic API key (secret)
    if "anthropic_api_key" in patch:
        value = patch["anthropic_api_key"]
        if value:
            await svc.set_setting("anthropic_api_key", str(value).strip())
        else:
            await svc.set_setting("anthropic_api_key", "")

    # Integer settings with range validation
    _INT_SETTINGS_RANGES = {
        "agent_session_cleanup_delay_seconds": (10, 3600),
        "agent_max_concurrent_sessions": (1, 20),
    }
    for key, (min_val, max_val) in _INT_SETTINGS_RANGES.items():
        if key in patch and patch[key] is not None:
            value = int(patch[key])
            if not (min_val <= value <= max_val):
                raise HTTPException(
                    status_code=422,
                    detail=f"{key} 应在 {min_val}-{max_val} 之间",
                )
            await svc.set_setting(key, str(value))

    # String settings
    for key in _STRING_SETTINGS:
        if key in patch:
            value = patch[key]
            await svc.set_setting(key, str(value).strip() if value else "")

    await session.commit()

    # Return updated config
    return await get_system_config(_user=_user, svc=svc, session=session)

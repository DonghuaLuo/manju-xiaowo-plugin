"""
Task execution service for queued generation jobs.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lib.config.resolver import ConfigResolver, ProviderModel

from lib.app_data_dir import app_data_dir
from lib.asset_types import ASSET_SPECS
from lib.config.registry import ARK_SEEDREAM_MAX_REFERENCE_IMAGES, PROVIDER_REGISTRY
from lib.custom_provider import is_custom_provider
from lib.db.base import DEFAULT_USER_ID
from lib.gemini_shared import get_shared_rate_limiter
from lib.i18n import DEFAULT_LOCALE
from lib.i18n import _ as i18n_translate
from lib.image_backends.base import ImageCapabilityError
from lib.media_generator import MediaGenerator
from lib.project_change_hints import emit_project_change_batch, project_change_source
from lib.project_manager import ProjectManager
from lib.prompt_builders import build_character_prompt, build_prop_prompt, build_scene_prompt
from lib.prompt_utils import (
    VideoPromptPolicy,
    build_speaker_profiles,
    image_prompt_to_yaml,
    is_structured_image_prompt,
    is_structured_video_prompt,
    video_prompt_to_yaml,
)
from lib.providers import (
    PROVIDER_ARK,
    PROVIDER_ARK_AGENT_PLAN,
    PROVIDER_DASHSCOPE,
    PROVIDER_GEMINI,
    PROVIDER_GROK,
    PROVIDER_OPENAI,
    PROVIDER_VIDU,
)
from lib.script_splitting_templates import (
    assert_script_splitting_assets_current,
    check_provider_compatibility,
    current_profile,
    script_splitting_asset_metadata,
)
from lib.storyboard_sequence import (
    build_previous_storyboard_reference,
    find_storyboard_item,
    get_storyboard_items,
    group_scenes_by_segment_break,
    storyboard_path_for_item,
)
from lib.thumbnail import extract_video_thumbnail
from lib.version_manager import VersionManager
from lib.video_backends.base import VideoCapability, VideoCapabilityError
from lib.video_input_preflight import run_video_input_preflight
from server.services.generation_route_resolver import (
    GenerationRoute,
    coerce_video_duration_for_options,
    coerce_video_resolution_for_options,
    default_shot_tier_for_task,
    duration_options_for_resolution,
    merged_shot_tier_profiles,
    normalize_shot_tier,
    resolve_generation_route,
    should_resolve_generation_route,
)
from server.services.resolution_resolver import resolve_resolution

pm = ProjectManager(app_data_dir())
rate_limiter = get_shared_rate_limiter()
logger = logging.getLogger(__name__)

# 按 (channel, provider_name, model) 缓存 Backend 实例，避免每次任务重建 API 客户端
_backend_cache: dict[tuple[str, str, str | None], Any] = {}

# 新 provider_id → 旧 backend registry name 的映射
_PROVIDER_ID_TO_BACKEND: dict[str, str] = {
    "gemini-aistudio": PROVIDER_GEMINI,
    "gemini-vertex": PROVIDER_GEMINI,
    PROVIDER_GEMINI: PROVIDER_GEMINI,
    PROVIDER_ARK: PROVIDER_ARK,
    PROVIDER_GROK: PROVIDER_GROK,
    PROVIDER_OPENAI: PROVIDER_OPENAI,
    PROVIDER_VIDU: PROVIDER_VIDU,
    PROVIDER_DASHSCOPE: PROVIDER_DASHSCOPE,
}

_VIDEO_CONTINUITY_POLICIES = {"auto", "start_only", "end_frame", "reference_assisted"}
_END_FRAME_SKIP_TRANSITIONS = {"fade", "dissolve"}
_IMAGE_MODEL_REFERENCE_LIMITS: dict[str, int] = {
    # 自定义 OpenAI 兼容供应商会使用 custom-* provider_id，只有 model_id 仍是稳定信号。
    "gpt-image-2": 16,
}


def get_project_manager() -> ProjectManager:
    return pm


def _video_backend_caps_payload(
    generator: Any,
    *,
    provider_id: str | None = None,
    model: str | None = None,
    resolved_caps: dict[str, Any] | None = None,
    supported_durations: list[int] | None = None,
    supported_resolutions: list[str] | None = None,
    duration_resolution_constraints: dict[str, list[int]] | None = None,
) -> dict[str, Any]:
    backend = getattr(generator, "_video_backend", None)
    backend_caps = getattr(backend, "video_capabilities", None)
    raw_capabilities = getattr(backend, "capabilities", set())
    capability_set = raw_capabilities() if callable(raw_capabilities) else raw_capabilities
    capability_set = set(capability_set or [])
    if isinstance(resolved_caps, dict):
        capability_set.update(str(item) for item in resolved_caps.get("capabilities") or [])

    resolved_provider_id = provider_id or (resolved_caps or {}).get("provider_id") or getattr(backend, "name", None)
    resolved_model = model or (resolved_caps or {}).get("model") or getattr(backend, "model", None)
    if resolved_provider_id or resolved_model or backend is not None or supported_durations:
        capability_set.add(VideoCapability.IMAGE_TO_VIDEO)

    durations = supported_durations
    if durations is None and isinstance(resolved_caps, dict):
        durations = [int(item) for item in resolved_caps.get("supported_durations") or []]
    resolutions = supported_resolutions
    if resolutions is None and isinstance(resolved_caps, dict):
        resolutions = [
            str(item)
            for item in resolved_caps.get("resolutions") or resolved_caps.get("supported_resolutions") or []
        ]
    duration_constraints = duration_resolution_constraints
    if duration_constraints is None and isinstance(resolved_caps, dict):
        duration_constraints = {
            str(key): [int(item) for item in value or []]
            for key, value in (resolved_caps.get("duration_resolution_constraints") or {}).items()
        }

    def _resolved_bool(*keys: str, backend_value: Any = None) -> bool | None:
        if isinstance(resolved_caps, dict):
            for key in keys:
                if key in resolved_caps:
                    return bool(resolved_caps[key])
        if backend is not None:
            return bool(backend_value)
        return None

    max_reference_images = None
    if isinstance(resolved_caps, dict) and resolved_caps.get("max_reference_images") is not None:
        max_reference_images = resolved_caps.get("max_reference_images")
    elif backend_caps is not None:
        max_reference_images = getattr(backend_caps, "max_reference_images", None)

    supports_generate_audio = None
    if isinstance(resolved_caps, dict) and "supports_generate_audio" in resolved_caps:
        supports_generate_audio = bool(resolved_caps["supports_generate_audio"])
    elif backend is not None or (isinstance(resolved_caps, dict) and "capabilities" in resolved_caps):
        supports_generate_audio = VideoCapability.GENERATE_AUDIO in capability_set
    return {
        "provider_id": resolved_provider_id,
        "model": resolved_model,
        "capabilities": sorted(str(item) for item in capability_set),
        "supported_durations": durations or [],
        "resolutions": resolutions or [],
        "duration_resolution_constraints": duration_constraints or {},
        "max_reference_images": max_reference_images,
        "supports_start_image": _resolved_bool(
            "supports_start_image",
            "supports_first_frame",
            backend_value=getattr(backend_caps, "first_frame", False),
        ),
        "supports_first_frame": _resolved_bool(
            "supports_first_frame",
            "supports_start_image",
            backend_value=getattr(backend_caps, "first_frame", False),
        ),
        "supports_end_image": _resolved_bool(
            "supports_end_image",
            "supports_last_frame",
            backend_value=getattr(backend_caps, "last_frame", False),
        ),
        "supports_last_frame": _resolved_bool(
            "supports_last_frame",
            "supports_end_image",
            backend_value=getattr(backend_caps, "last_frame", False),
        ),
        "supports_reference_images": _resolved_bool(
            "supports_reference_images",
            backend_value=getattr(backend_caps, "reference_images", False),
        ),
        "supports_reference_with_start_image": _resolved_bool(
            "supports_reference_with_start_image",
            backend_value=getattr(backend_caps, "reference_images_with_start_image", False),
        ),
        "supports_generate_audio": supports_generate_audio,
        "constraints": {
            "supported_aspect_ratios": ["9:16", "16:9", "1:1", "4:3", "3:4"],
            "supported_durations": durations or [],
            "supported_resolutions": resolutions or [],
            "duration_resolution_constraints": duration_constraints or {},
            "max_reference_images": max_reference_images,
        },
    }


def _assert_video_preflight_ok(
    *,
    project: dict[str, Any],
    generator: Any,
    aspect_ratio: str,
    duration_seconds: Any,
    reference_images: list[Path] | None = None,
    first_frame_path: Path | str | None = None,
    last_frame_path: Path | str | None = None,
    generate_audio: bool | None = None,
    provider_id: str | None = None,
    model: str | None = None,
    provider_capabilities: dict[str, Any] | None = None,
    supported_durations: list[int] | None = None,
    supported_resolutions: list[str] | None = None,
    duration_resolution_constraints: dict[str, list[int]] | None = None,
) -> dict[str, Any]:
    request = {
        "aspect_ratio": aspect_ratio,
        "duration_seconds": duration_seconds,
        "reference_images_count": len(reference_images or []),
        "reference_images": [str(path) for path in (reference_images or [])],
    }
    if first_frame_path:
        request["first_frame_path"] = str(first_frame_path)
    if last_frame_path:
        request["last_frame_path"] = str(last_frame_path)
    if generate_audio is not None:
        request["generate_audio"] = bool(generate_audio)

    capabilities = _video_backend_caps_payload(
        generator,
        provider_id=provider_id,
        model=model,
        resolved_caps=provider_capabilities,
        supported_durations=supported_durations,
        supported_resolutions=supported_resolutions,
        duration_resolution_constraints=duration_resolution_constraints,
    )
    provider_compatibility = check_provider_compatibility(current_profile(project), capabilities)
    if provider_compatibility.get("status") == "block":
        missing = ", ".join(provider_compatibility.get("missing_required") or [])
        raise ValueError(f"当前视频模型缺少拆分方案必需能力: {missing}")

    result = run_video_input_preflight(
        project=project,
        capabilities=capabilities,
        request=request,
    )
    result["provider_compatibility"] = provider_compatibility
    if result.get("status") == "block":
        messages = [
            str(check.get("message"))
            for check in result.get("checks", [])
            if isinstance(check, dict) and check.get("status") == "block" and check.get("message")
        ]
        raise ValueError("视频生成预检失败：" + "；".join(messages))
    return result


def invalidate_backend_cache() -> None:
    """清空 VideoBackend 实例缓存。在配置变更后调用。"""
    _backend_cache.clear()


async def _resolve_effective_image_backend(
    project: dict,
    payload: dict | None,
    *,
    needs_i2i: bool = False,
) -> ProviderModel:
    """图片 provider 解析的薄投影：委托 ``ConfigResolver.resolve_image_backend``。

    capability 仅在执行层确定（见 ``docs/adr/0001``）：``needs_i2i`` → i2i 槽，否则 t2i 槽。
    与 ``_resolve_video_backend`` 一致不吞解析异常——未配置供应商时让 ``ConfigResolver`` 抛出的
    清晰 ``ValueError``（"未找到可用的 image 供应商..."）直接透传，而非掩盖成空 backend 的通用错误。
    """
    from lib.config.resolver import ConfigResolver
    from lib.db import async_session_factory

    resolver = ConfigResolver(async_session_factory)
    capability = "i2i" if needs_i2i else "t2i"
    return await resolver.resolve_image_backend(project, payload, capability=capability)


async def _maybe_resolve_generation_route(
    *,
    project_name: str,
    project: dict,
    payload: dict[str, Any],
    task_kind: str,
    needs_i2i: bool = False,
) -> GenerationRoute | None:
    """Resolve new draft/final route only when the project/request opts in."""

    if not should_resolve_generation_route(project, payload):
        return None

    from lib.config.resolver import ConfigResolver
    from lib.db import async_session_factory

    resolver = ConfigResolver(async_session_factory)
    capability = "i2i" if needs_i2i else "t2i"
    return await resolve_generation_route(
        project=project,
        payload=payload,
        task_kind=task_kind,
        quality=payload.get("quality"),
        capability=capability,
        resolver=resolver,
        project_name=project_name,
    )


async def _create_custom_backend(provider_name: str, model_id: str | None, media_type: str):
    """自定义供应商的 backend 创建路径。

    media_type 仅用于回退到默认模型时分组（仍接收以兼容调用方调用语义）。
    实际派发以 model.endpoint 为准；若 endpoint 推算 media_type 与 caller 传入不符 → 视为模型不存在并 fallback。
    """
    from lib.custom_provider import parse_provider_id
    from lib.custom_provider.endpoints import endpoint_to_media_type
    from lib.custom_provider.factory import create_custom_backend
    from lib.db import async_session_factory
    from lib.db.repositories.custom_provider_repo import CustomProviderRepository

    async with async_session_factory() as session:
        repo = CustomProviderRepository(session)
        db_id = parse_provider_id(provider_name)
        provider = await repo.get_provider(db_id)
        if provider is None:
            raise ValueError(f"自定义供应商 {provider_name} 不存在")

        model = None
        if model_id:
            from sqlalchemy import select

            from lib.db.models.custom_provider import CustomProviderModel

            stmt = select(CustomProviderModel).where(
                CustomProviderModel.provider_id == db_id,
                CustomProviderModel.model_id == model_id,
                CustomProviderModel.is_enabled == True,  # noqa: E712
            )
            result = await session.execute(stmt)
            candidate = result.scalar_one_or_none()
            if candidate and endpoint_to_media_type(candidate.endpoint) == media_type:
                model = candidate
            else:
                logger.warning(
                    "自定义模型 %s/%s 已不存在 / 已禁用 / 媒体类型不符（期望 %s），回退到默认模型",
                    provider_name,
                    model_id,
                    media_type,
                )
                model_id = None

        if model is None:
            default_model = await repo.get_default_model(db_id, media_type)
            if default_model is None:
                raise ValueError(f"自定义供应商 {provider_name} 没有默认 {media_type} 模型")
            model = default_model
            model_id = default_model.model_id

        assert model_id is not None
        return create_custom_backend(provider=provider, model_id=model_id, endpoint=model.endpoint)


async def _get_or_create_video_backend(
    provider_name: str,
    provider_settings: dict,
    resolver: ConfigResolver,
    *,
    default_video_model: str | None = None,
):
    """获取或创建 VideoBackend 实例（带缓存）。

    provider_name 可以是旧格式（gemini/seedance/grok）或新格式（gemini-aistudio/gemini-vertex）。
    通过 resolver 按需加载供应商配置。
    default_video_model: 全局默认视频模型，当 provider_settings 中无 model 时作为 fallback。
    """
    from lib.video_backends import create_backend

    effective_model = provider_settings.get("model") or default_video_model or None
    cache_key = ("video", provider_name, effective_model)
    if cache_key in _backend_cache:
        return _backend_cache[cache_key]

    # 自定义供应商走独立工厂路径
    if is_custom_provider(provider_name):
        backend = await _create_custom_backend(provider_name, effective_model, "video")
        _backend_cache[cache_key] = backend
        return backend

    # 解析 provider_id → backend registry name
    backend_name = _PROVIDER_ID_TO_BACKEND.get(provider_name, provider_name)

    kwargs: dict = {}
    if backend_name == PROVIDER_GEMINI:
        # 确定 backend_type（aistudio 或 vertex）
        if provider_name == "gemini-vertex":
            kwargs["backend_type"] = "vertex"
        elif provider_name == "gemini-aistudio":
            kwargs["backend_type"] = "aistudio"
        else:
            kwargs["backend_type"] = "aistudio"

        config_provider_id = "gemini-vertex" if kwargs["backend_type"] == "vertex" else "gemini-aistudio"
        db_config = await resolver.provider_config(config_provider_id)
        kwargs["api_key"] = db_config.get("api_key")
        kwargs["rate_limiter"] = rate_limiter
        kwargs["video_model"] = effective_model
    else:
        await _fill_simple_provider_kwargs(backend_name, resolver, kwargs, effective_model)

    backend = create_backend(backend_name, **kwargs)
    _backend_cache[cache_key] = backend
    return backend


async def _fill_simple_provider_kwargs(
    backend_name: str,
    resolver: ConfigResolver,
    kwargs: dict,
    effective_model: str | None,
) -> None:
    """Ark/Grok/OpenAI 等简单供应商的通用配置填充。

    base_url 优先级：用户在 DB 配置中显式填写 > ProviderMeta.default_base_url > 不传。
    """
    from lib.config.registry import PROVIDER_REGISTRY

    db_config = await resolver.provider_config(backend_name)
    kwargs["api_key"] = db_config.get("api_key")
    kwargs["model"] = effective_model
    meta = PROVIDER_REGISTRY.get(backend_name)
    base_url = db_config.get("base_url") or (meta.default_base_url if meta else None)
    if base_url:
        kwargs["base_url"] = base_url


async def _get_or_create_image_backend(
    provider_name: str,
    provider_settings: dict,
    resolver: ConfigResolver,
    *,
    default_image_model: str | None = None,
):
    """获取或创建 ImageBackend 实例（带缓存）。"""
    from lib.image_backends import create_backend

    effective_model = provider_settings.get("model") or default_image_model or None
    cache_key = ("image", provider_name, effective_model)
    if cache_key in _backend_cache:
        return _backend_cache[cache_key]

    # 自定义供应商走独立工厂路径
    if is_custom_provider(provider_name):
        backend = await _create_custom_backend(provider_name, effective_model, "image")
        _backend_cache[cache_key] = backend
        return backend

    backend_name = _PROVIDER_ID_TO_BACKEND.get(provider_name, provider_name)

    kwargs: dict = {}
    if backend_name == PROVIDER_GEMINI:
        if provider_name == "gemini-vertex":
            kwargs["backend_type"] = "vertex"
        else:
            kwargs["backend_type"] = "aistudio"
        config_id = "gemini-vertex" if kwargs["backend_type"] == "vertex" else "gemini-aistudio"
        db_config = await resolver.provider_config(config_id)
        kwargs["api_key"] = db_config.get("api_key")
        kwargs["base_url"] = db_config.get("base_url")
        kwargs["rate_limiter"] = rate_limiter
        kwargs["image_model"] = effective_model
    else:
        await _fill_simple_provider_kwargs(backend_name, resolver, kwargs, effective_model)

    backend = create_backend(backend_name, **kwargs)
    _backend_cache[cache_key] = backend
    return backend


async def _resolve_video_backend(
    project_name: str,
    resolver: ConfigResolver,
    payload: dict | None,
) -> tuple[Any | None, str, str]:
    """解析并构造视频后端，返回 (video_backend, video_backend_type, video_model)。

    provider/model 的**解析**是 ``resolver.resolve_video_backend`` 的薄投影；backend **构造**
    （``_get_or_create_video_backend``）留在原地。仅在 payload 存在时创建 VideoBackend，避免
    图片任务因视频配置缺失而报错。注意：video_backend_type 仅在 video_backend 为 None
    （回退到 GeminiClient）时生效。
    """
    project = await asyncio.to_thread(get_project_manager().load_project, project_name) if payload else None
    resolved = await resolver.resolve_video_backend(project, payload)

    video_backend = None
    video_backend_type = "aistudio"
    mapped = _PROVIDER_ID_TO_BACKEND.get(resolved.provider_id, resolved.provider_id)
    if mapped == PROVIDER_GEMINI:
        video_backend_type = "vertex" if resolved.provider_id == "gemini-vertex" else "aistudio"

    if payload:
        provider_settings: dict = {"model": resolved.model_id} if resolved.model_id else {}
        video_backend = await _get_or_create_video_backend(
            resolved.provider_id,
            provider_settings,
            resolver,
            default_video_model=resolved.model_id or None,
        )

    return video_backend, video_backend_type, resolved.model_id


async def get_media_generator(
    project_name: str,
    payload: dict | None = None,
    *,
    user_id: str = DEFAULT_USER_ID,
    require_image_backend: bool = True,
    needs_i2i: bool = False,
) -> MediaGenerator:
    """创建 MediaGenerator。仅按调用场景初始化所需的 backend。

    needs_i2i: 若调用方知晓本次任务带参考图，传 True 以选 I2I 默认 backend；否则用 T2I。
    """
    from lib.config.resolver import ConfigResolver
    from lib.db import async_session_factory

    project_path = await asyncio.to_thread(get_project_manager().get_project_path, project_name)
    resolver = ConfigResolver(async_session_factory)

    async with resolver.session() as r:
        image_backend = None
        if require_image_backend:
            project = await asyncio.to_thread(get_project_manager().load_project, project_name)
            resolved_image = await _resolve_effective_image_backend(project, payload, needs_i2i=needs_i2i)
            # 解析失败 → provider_id 为空，让 _get_or_create_image_backend 抛出清晰错误
            image_backend = await _get_or_create_image_backend(
                resolved_image.provider_id,
                {},
                r,
                default_image_model=resolved_image.model_id or None,
            )

        # 解析 video backend（保持现有逻辑）
        video_backend, _, _ = await _resolve_video_backend(
            project_name,
            r,
            payload,
        )

    return MediaGenerator(
        project_path,
        rate_limiter=rate_limiter,
        image_backend=image_backend,  # type: ignore[arg-type]
        video_backend=video_backend,  # type: ignore[arg-type]
        config_resolver=resolver,
        user_id=user_id,
    )


def get_aspect_ratio(project: dict, resource_type: str) -> str:
    if resource_type == "characters":
        # 角色采用四视图横版（issue #353）
        return "16:9"
    if resource_type in ("scenes", "props"):
        return "16:9"
    # 优先读顶层字段；缺失时按 content_mode 推导（向后兼容）
    val = project.get("aspect_ratio")
    if isinstance(val, str):
        return val
    if isinstance(val, dict) and resource_type in val:
        return val[resource_type]
    return "9:16" if project.get("content_mode", "narration") == "narration" else "16:9"


def _normalize_storyboard_prompt(prompt: str | dict, style: str) -> str:
    if isinstance(prompt, str):
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        return prompt

    if not isinstance(prompt, dict):
        raise ValueError("prompt must be a string or object")

    if not is_structured_image_prompt(prompt):
        raise ValueError("prompt must be a string or include scene/composition")

    scene_text = str(prompt.get("scene", "")).strip()
    if not scene_text:
        raise ValueError("prompt.scene must not be empty")

    composition_raw = prompt.get("composition")
    composition: dict = composition_raw if isinstance(composition_raw, dict) else {}
    normalized_prompt = {
        "scene": scene_text,
        "composition": {
            "shot_type": str(composition.get("shot_type") or "Medium Shot"),
            "lighting": str(composition.get("lighting", "") or ""),
            "ambiance": str(composition.get("ambiance", "") or ""),
        },
    }
    return image_prompt_to_yaml(normalized_prompt, style)


def _normalize_video_prompt(
    prompt: str | dict,
    *,
    project: dict | None = None,
    target_item: dict | None = None,
    char_field: str | None = None,
    policy: VideoPromptPolicy | None = None,
) -> str:
    """归一化视频 prompt 并在末尾追加统一文本化的反向提示词。"""
    from lib.prompt_builders import append_video_negative_tail

    if isinstance(prompt, str):
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        return append_video_negative_tail(prompt)

    if not isinstance(prompt, dict):
        raise ValueError("prompt must be a string or object")

    if not is_structured_video_prompt(prompt):
        raise ValueError("prompt must be a string or include action/camera_motion")

    action_text = str(prompt.get("action", "")).strip()
    if not action_text:
        raise ValueError("prompt.action must not be empty")

    dialogue = prompt.get("dialogue", [])
    if dialogue is None:
        dialogue = []
    if not isinstance(dialogue, list):
        raise ValueError("prompt.dialogue must be an array")

    normalized_dialogue = []
    for item in dialogue:
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker", "") or "").strip()
        line = str(item.get("line", "") or "").strip()
        emotion = str(item.get("emotion", "") or "").strip()
        screen_position = str(item.get("screen_position", "") or "").strip()
        if speaker or line:
            normalized = {"speaker": speaker, "line": line}
            if emotion:
                normalized["emotion"] = emotion
            if screen_position:
                normalized["screen_position"] = screen_position
            normalized_dialogue.append(normalized)

    normalized_prompt: dict[str, Any] = {
        "action": action_text,
        "camera_motion": str(prompt.get("camera_motion", "") or "") or "Static",
        "ambiance_audio": str(prompt.get("ambiance_audio", "") or ""),
        "dialogue": normalized_dialogue,
    }
    for key in ("subject_motion", "emotion", "environment_motion", "avoid"):
        value = str(prompt.get(key, "") or "").strip()
        if value:
            normalized_prompt[key] = value
    speaker_profiles = build_speaker_profiles(
        project,
        target_item,
        char_field=char_field,
        dialogue=normalized_dialogue,
    )
    return append_video_negative_tail(
        video_prompt_to_yaml(normalized_prompt, speaker_profiles=speaker_profiles, policy=policy)
    )


_GENERATE_AUDIO_CAPABILITY = "generate_audio"
_TRUTHY_VIDEO_AUDIO_VALUES = frozenset({"true", "1", "yes"})


def _is_gemini_aistudio_veo(provider_name: str, model_name: str) -> bool:
    return provider_name == "gemini-aistudio" and model_name.startswith("veo-")


def _video_prompt_policy_with_audio_setting(policy: VideoPromptPolicy, generate_audio_enabled: bool) -> VideoPromptPolicy:
    if generate_audio_enabled or not policy.supports_generated_audio:
        return policy
    return VideoPromptPolicy(
        supports_generated_audio=False,
        compact=policy.compact,
        max_visible_characters=policy.max_visible_characters,
        voice_style_max_chars=policy.voice_style_max_chars,
        mouth_cue_silent_name_limit=policy.mouth_cue_silent_name_limit,
    )


def _video_prompt_policy_from_provider_model(provider_id: str | None, model_id: str | None) -> VideoPromptPolicy:
    provider_key = str(provider_id or "")
    model_key = str(model_id or "")
    provider_name = provider_key.lower()
    model_name = model_key.lower()
    compact = "vidu" in provider_name or "vidu" in model_name

    provider_meta = PROVIDER_REGISTRY.get(provider_key)
    model_info = provider_meta.models.get(model_key) if provider_meta is not None else None
    if model_info is None:
        supports_generated_audio = False
    else:
        capability_values = {str(capability).lower() for capability in model_info.capabilities}
        supports_generated_audio = _GENERATE_AUDIO_CAPABILITY in capability_values

    if _is_gemini_aistudio_veo(provider_name, model_name):
        supports_generated_audio = True

    return VideoPromptPolicy(supports_generated_audio=supports_generated_audio, compact=compact)


async def _video_prompt_policy_from_custom_provider(provider_id: str, model_id: str | None) -> VideoPromptPolicy:
    compact = "vidu" in provider_id.lower() or "vidu" in str(model_id or "").lower()
    try:
        backend = await _create_custom_backend(provider_id, model_id, "video")
    except Exception:
        logger.warning("解析自定义视频 prompt 策略失败，按不支持生成音频处理: %s/%s", provider_id, model_id, exc_info=True)
        return VideoPromptPolicy(supports_generated_audio=False, compact=compact)
    return _video_prompt_policy_from_backend(backend)


def _video_prompt_policy_from_backend(backend: Any | None) -> VideoPromptPolicy:
    if backend is None:
        return VideoPromptPolicy()

    provider_name = str(getattr(backend, "name", "") or "").lower()
    model_name = str(getattr(backend, "model", "") or "").lower()

    try:
        raw_capabilities = getattr(backend, "capabilities")
    except Exception:
        raw_capabilities = None

    if raw_capabilities is None:
        supports_generated_audio = True
    else:
        capability_values = {str(getattr(cap, "value", cap)).lower() for cap in raw_capabilities}
        supports_generated_audio = _GENERATE_AUDIO_CAPABILITY in capability_values

    if _is_gemini_aistudio_veo(provider_name, model_name):
        supports_generated_audio = True

    compact = "vidu" in provider_name or "vidu" in model_name
    return VideoPromptPolicy(supports_generated_audio=supports_generated_audio, compact=compact)


async def resolve_video_prompt_policy(
    project: dict | None,
    payload: dict | None = None,
    *,
    project_name: str | None = None,
) -> VideoPromptPolicy:
    """Resolve the video prompt policy from the same provider/model path used by generation."""
    from lib.config.resolver import ConfigResolver
    from lib.db import async_session_factory

    resolver = ConfigResolver(async_session_factory)
    try:
        resolved = await resolver.resolve_video_backend(project, payload)
    except Exception:
        logger.warning("解析视频 prompt 策略失败，回退默认策略", exc_info=True)
        return VideoPromptPolicy()

    if is_custom_provider(resolved.provider_id):
        policy = await _video_prompt_policy_from_custom_provider(resolved.provider_id, resolved.model_id)
    else:
        policy = _video_prompt_policy_from_provider_model(resolved.provider_id, resolved.model_id)
    if not policy.supports_generated_audio:
        return policy

    raw_project_audio = project.get("video_generate_audio") if isinstance(project, dict) else None
    if raw_project_audio is not None:
        if isinstance(raw_project_audio, str):
            generate_audio_enabled = raw_project_audio.strip().lower() in _TRUTHY_VIDEO_AUDIO_VALUES
        else:
            generate_audio_enabled = bool(raw_project_audio)
    else:
        try:
            generate_audio_enabled = bool(await resolver.video_generate_audio(project_name))
        except Exception:
            generate_audio_enabled = True

    return _video_prompt_policy_with_audio_setting(policy, generate_audio_enabled)


async def _video_prompt_policy_from_generator(generator: MediaGenerator, project_name: str) -> VideoPromptPolicy:
    backend = getattr(generator, "_video_backend", None)
    policy = _video_prompt_policy_from_backend(backend)
    if not policy.supports_generated_audio:
        return policy

    try:
        config = getattr(generator, "_config", None)
        if config is not None:
            generate_audio_enabled = bool(await config.video_generate_audio(project_name))
        else:
            from lib.config.resolver import ConfigResolver

            generate_audio_enabled = ConfigResolver._DEFAULT_VIDEO_GENERATE_AUDIO
    except Exception:
        generate_audio_enabled = True

    if generate_audio_enabled:
        return policy
    return _video_prompt_policy_with_audio_setting(policy, generate_audio_enabled)


def _get_model_default_duration(provider_name: str, model_name: str | None) -> int:
    """从 PROVIDER_REGISTRY 查找模型的 supported_durations[0]，找不到则 fallback 4。"""
    provider_meta = PROVIDER_REGISTRY.get(provider_name)
    if provider_meta and model_name:
        model_info = provider_meta.models.get(model_name)
        if model_info and model_info.supported_durations:
            return model_info.supported_durations[0]
    # 自定义供应商或 registry 中无此模型时 fallback
    return 4


def assert_duration_supported(duration: int | float | str, supported_durations: list[int]) -> None:
    """执行层能力守卫：duration 必须落在已解析 model 的 supported_durations 内。

    这是 `duration ↔ supported_durations` 唯一的权威校验家——provider 在执行时才解析
    （见 ADR-0001），故能力校验只能坐在 provider 解析之后。``supported_durations`` 为空时
    放行（能力不可解析，不更坏：保持既有行为不被本次改动弄坏）。

    duration 可能来自外部配置（payload / project.json），故安全解析字符串 / 浮点：
    可解析为整数秒（如 ``"6"`` / ``6.0``）的归一化后比较；非整数秒（如 ``4.5``）一律
    视为非法而**拒绝**，不做截断式归一化（截断会把本应拒绝的非法值静默修正）。

    校验失败抛 :class:`VideoCapabilityError`（带稳定 code），与 ImageCapabilityError 对称——
    Worker 捕获后渲染为本地化的 task.error_message。
    """
    if not supported_durations:
        return
    try:
        numeric = float(duration)
    except (TypeError, ValueError):
        raise VideoCapabilityError("video_duration_invalid", duration=duration)
    if not numeric.is_integer():
        raise VideoCapabilityError("video_duration_invalid", duration=duration)
    seconds = int(numeric)
    if seconds not in supported_durations:
        raise VideoCapabilityError(
            "video_duration_not_supported",
            duration=seconds,
            supported=", ".join(str(d) for d in supported_durations),
        )


def _current_version_info(versions: Any, resource_type: str, resource_id: str) -> dict[str, Any] | None:
    try:
        info = versions.get_versions(resource_type, resource_id)
    except Exception:
        logger.debug("读取 %s/%s 当前版本失败", resource_type, resource_id, exc_info=True)
        return None
    current = info.get("current_version")
    for item in info.get("versions") or []:
        if item.get("version") == current or item.get("is_current"):
            return item
    return None


def _version_info(versions: Any, resource_type: str, resource_id: str, version: object) -> dict[str, Any] | None:
    try:
        requested = int(version)
        info = versions.get_versions(resource_type, resource_id)
    except Exception:
        logger.debug("读取 %s/%s 指定版本失败 version=%s", resource_type, resource_id, version, exc_info=True)
        return None
    for item in info.get("versions") or []:
        if item.get("version") == requested:
            return item
    return None


def _storyboard_source_quality(versions: Any, resource_id: str, assets: dict[str, Any] | None) -> str:
    current = _current_version_info(versions, "storyboards", resource_id)
    if current:
        quality = current.get("generation_quality")
        if quality in {"draft", "final", "custom", "grid"}:
            return str(quality)
    if isinstance(assets, dict) and assets.get("grid_id"):
        return "grid"
    return "unknown"


def _payload_with_shot_tier(payload: dict[str, Any], item: dict[str, Any] | None) -> dict[str, Any]:
    if payload.get("shot_tier") in {"S", "A", "B"}:
        return payload
    shot_tier = item.get("shot_tier") if isinstance(item, dict) else None
    if shot_tier not in {"S", "A", "B"}:
        return payload
    return {**payload, "shot_tier": shot_tier}


def _storyboard_video_continuity_policy(
    project: dict,
    payload: dict[str, Any],
    item: dict[str, Any] | None,
) -> str:
    raw = payload.get("video_continuity_policy")
    if raw is None:
        raw = payload.get("continuity_policy")
    if raw is None:
        route_payload = _payload_with_shot_tier(payload, item)
        shot_tier = normalize_shot_tier(route_payload.get("shot_tier")) or default_shot_tier_for_task("storyboard")
        strategy = merged_shot_tier_profiles(project).get(shot_tier) if shot_tier else None
        if isinstance(strategy, dict):
            raw = strategy.get("video_continuity_policy")
    if raw is None:
        raw = project.get("video_continuity_policy")
    if raw is None:
        raw = project.get("continuity_policy")
    policy = str(raw or "auto").strip().lower()
    return policy if policy in _VIDEO_CONTINUITY_POLICIES else "auto"


def _storyboard_needs_previous_reference(
    project: dict,
    payload: dict[str, Any],
    item: dict[str, Any] | None,
) -> bool:
    return _storyboard_video_continuity_policy(project, payload, item) != "start_only"


def _wants_final_storyboard(payload: dict[str, Any]) -> bool:
    quality = payload.get("generation_quality")
    if quality is None:
        quality = payload.get("quality")
    return quality == "final" or payload.get("source_version") is not None


_STORYBOARD_FINAL_DRAFT_LOCKED = "draft_locked"
_STORYBOARD_FINAL_FRESH_SAMPLE = "fresh_sample"
_STORYBOARD_SOURCE_QUALITIES = {"draft", "final", "grid", "custom"}


def _storyboard_final_generation_mode(payload: dict[str, Any]) -> str | None:
    if not _wants_final_storyboard(payload):
        return None
    if payload.get("source_version") is not None:
        return _STORYBOARD_FINAL_DRAFT_LOCKED
    raw = payload.get("final_generation_mode") or payload.get("storyboard_final_mode")
    mode = str(raw or _STORYBOARD_FINAL_DRAFT_LOCKED).strip().lower()
    if mode in {_STORYBOARD_FINAL_DRAFT_LOCKED, _STORYBOARD_FINAL_FRESH_SAMPLE}:
        return mode
    return _STORYBOARD_FINAL_DRAFT_LOCKED


def _should_use_storyboard_source(payload: dict[str, Any], final_generation_mode: str | None) -> bool:
    if payload.get("source_version") is not None:
        return True
    return final_generation_mode == _STORYBOARD_FINAL_DRAFT_LOCKED


def _should_use_previous_storyboard_reference(
    project: dict,
    payload: dict[str, Any],
    item: dict[str, Any] | None,
) -> bool:
    return _storyboard_needs_previous_reference(project, payload, item)


def _previous_storyboard_candidate(
    project_path: Path,
    items: list[dict],
    id_field: str,
    resource_id: str,
) -> tuple[str | None, Path | None]:
    resolved = find_storyboard_item(items, id_field, resource_id)
    if resolved is None:
        raise KeyError(f"scene/segment not found: {resource_id}")

    target_item, index = resolved
    if index == 0 or bool(target_item.get("segment_break")):
        return None, None

    previous_item = items[index - 1]
    return storyboard_path_for_item(project_path, previous_item, id_field)


def _resolve_previous_storyboard_reference_path(
    project_path: Path,
    items: list[dict],
    id_field: str,
    resource_id: str,
    *,
    required: bool,
) -> Path | None:
    previous_id, previous_path = _previous_storyboard_candidate(project_path, items, id_field, resource_id)
    if not previous_id or previous_path is None:
        return None
    if previous_path.is_file():
        return previous_path
    if required:
        raise ValueError(f"视频连续性策略需要上一张分镜图，请先生成上一张分镜：{previous_id}")
    return None


def _version_file_exists(project_path: Path, info: dict[str, Any] | None) -> bool:
    rel = str((info or {}).get("file") or "")
    return bool(rel) and (project_path / rel).exists()


def _latest_storyboard_source_version(
    *,
    project_path: Path,
    versions: Any,
    resource_id: str,
) -> dict[str, Any] | None:
    try:
        info = versions.get_versions("storyboards", resource_id)
    except Exception:
        logger.debug("读取 storyboards/%s 版本历史失败", resource_id, exc_info=True)
        return None
    version_items = [item for item in (info.get("versions") or []) if isinstance(item, dict)]
    current_version = info.get("current_version")
    current = next((item for item in version_items if item.get("version") == current_version), None)

    def _usable(item: dict[str, Any] | None) -> bool:
        quality = str((item or {}).get("generation_quality") or "")
        return quality in _STORYBOARD_SOURCE_QUALITIES and _version_file_exists(project_path, item)

    if _usable(current):
        return current
    for item in reversed(version_items):
        if _usable(item):
            return item
    return None


def _storyboard_source_reference(
    *,
    project_path: Path,
    versions: Any,
    resource_id: str,
    assets: dict[str, Any] | None,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    requested_version = payload.get("source_version")
    if requested_version is not None:
        info = _version_info(versions, "storyboards", resource_id, requested_version)
        if info is None:
            raise ValueError(f"storyboard source_version not found: {resource_id} v{requested_version}")
    else:
        info = _latest_storyboard_source_version(
            project_path=project_path,
            versions=versions,
            resource_id=resource_id,
        )
    source_quality = str((info or {}).get("generation_quality") or "unknown")

    source_rel = str((info or {}).get("file") or "")
    source_path = project_path / source_rel if source_rel else None
    if requested_version is not None and (not source_path or not source_path.exists()):
        raise FileNotFoundError(f"storyboard source_version file not found: {source_rel or requested_version}")
    if not source_path or not source_path.exists():
        asset_rel = assets.get("storyboard_image") if isinstance(assets, dict) else None
        source_path = project_path / asset_rel if asset_rel else project_path / "storyboards" / f"scene_{resource_id}.png"
        source_rel = str(asset_rel or f"storyboards/scene_{resource_id}.png")
        if source_quality == "unknown":
            current = _current_version_info(versions, "storyboards", resource_id)
            current_quality = str((current or {}).get("generation_quality") or "")
            if current_quality in _STORYBOARD_SOURCE_QUALITIES:
                source_quality = current_quality
            elif isinstance(assets, dict) and assets.get("grid_id"):
                source_quality = "grid"
    if not source_path.exists():
        return None, {}

    if requested_version is not None:
        label = "指定分镜版本（精修参考）"
    else:
        label = "当前分镜（精修参考）"
    reference = {
        "image": source_path,
        "label": label,
        "description": "用于保持当前分镜构图、角色位置和画面连续性；请按当前 prompt 与已引用资产提升细节。",
    }
    metadata = {
        "source_storyboard_version": (info or {}).get("version"),
        "source_storyboard_file": source_rel,
        "source_storyboard_generation_quality": source_quality,
    }
    return reference, {key: value for key, value in metadata.items() if value is not None}


def _collect_sheet_paths(
    project: dict,
    project_path: Path,
    items: list[dict],
    *,
    char_field: str,
    scene_field: str,
    prop_field: str,
    max_count: int = 0,
) -> tuple[list[Path], set[str]]:
    """Collect character_sheet, scene_sheet and prop_sheet paths from scene/segment items.

    Returns (list of existing Paths, set of relative sheet strings for dedup).
    If *max_count* > 0 collection stops after that many images.
    """
    seen: set[str] = set()
    paths: list[Path] = []

    characters = project.get("characters", {})
    project_scenes = project.get("scenes", {})
    project_props = project.get("props", {})

    for item in items:
        for char_name in item.get(char_field, []):
            sheet = characters.get(char_name, {}).get("character_sheet")
            if sheet and sheet not in seen:
                path = project_path / sheet
                if path.exists():
                    paths.append(path)
                    seen.add(sheet)
        for scene_name in item.get(scene_field, []):
            sheet = project_scenes.get(scene_name, {}).get("scene_sheet")
            if sheet and sheet not in seen:
                path = project_path / sheet
                if path.exists():
                    paths.append(path)
                    seen.add(sheet)
        for prop_name in item.get(prop_field, []):
            sheet = project_props.get(prop_name, {}).get("prop_sheet")
            if sheet and sheet not in seen:
                path = project_path / sheet
                if path.exists():
                    paths.append(path)
                    seen.add(sheet)
        if max_count and len(paths) >= max_count:
            break

    return paths, seen


def _collect_reference_images(
    project: dict,
    project_path: Path,
    target_item: dict,
    *,
    char_field: str,
    scene_field: str,
    prop_field: str,
    previous_storyboard_path: Path | None = None,
) -> list[object] | None:
    sheet_paths, _ = _collect_sheet_paths(
        project, project_path, [target_item], char_field=char_field, scene_field=scene_field, prop_field=prop_field
    )
    reference_images: list[object] = list(sheet_paths)

    if previous_storyboard_path and previous_storyboard_path.is_file():
        reference_images.append(build_previous_storyboard_reference(previous_storyboard_path))

    return reference_images or None


def _image_reference_limit(provider_id: str | None, model_id: str | None) -> int | None:
    provider = str(provider_id or "").strip().lower()
    model = str(model_id or "").strip().lower()
    meta = PROVIDER_REGISTRY.get(provider)
    model_key = str(model_id or "").strip()
    model_info = (meta.models.get(model_key) or meta.models.get(model)) if meta else None
    if model_info and model_info.max_reference_images is not None:
        return int(model_info.max_reference_images)
    if model in _IMAGE_MODEL_REFERENCE_LIMITS:
        return _IMAGE_MODEL_REFERENCE_LIMITS[model]
    if provider == PROVIDER_OPENAI:
        return 16
    if provider == PROVIDER_VIDU:
        return 7
    if provider == PROVIDER_DASHSCOPE:
        return 9 if model.startswith("wan") else 3
    if provider in {PROVIDER_ARK, PROVIDER_ARK_AGENT_PLAN} and "seedream" in model:
        return ARK_SEEDREAM_MAX_REFERENCE_IMAGES
    return None


def _reference_label(ref: object, index: int) -> str:
    if isinstance(ref, dict):
        label = str(ref.get("label") or "").strip()
        if label:
            return label
    return f"参考图{index}"


def _format_image_reference_limit_error(
    *,
    provider_id: str | None,
    model_id: str | None,
    limit: int,
    count: int,
    reference_images: list[object] | None,
) -> str:
    model_label = "/".join(part for part in [provider_id, model_id] if part) or "当前图片模型"
    labels = [_reference_label(ref, index) for index, ref in enumerate(reference_images or [], start=1)]
    detail = "、".join(labels[:8])
    if len(labels) > 8:
        detail += f" 等 {len(labels)} 张"
    if limit <= 0:
        return f"当前图片模型 {model_label} 不支持参考图，但当前分镜需要提交 {count} 张参考图：{detail}"
    return f"当前图片模型 {model_label} 最多支持 {limit} 张参考图，但当前分镜需要提交 {count} 张：{detail}"


def _format_image_reference_unresolved_error(
    *,
    count: int,
    reference_images: list[object] | None,
    route_error: str | None,
) -> str:
    labels = [_reference_label(ref, index) for index, ref in enumerate(reference_images or [], start=1)]
    detail = "、".join(labels[:8])
    if len(labels) > 8:
        detail += f" 等 {len(labels)} 张"
    reason = f" 原因：{route_error}" if route_error else ""
    return f"无法确认当前图片模型的参考图上限，当前分镜需要提交 {count} 张参考图：{detail}。请先检查项目生成质量策略或图片模型配置。{reason}"


def _validate_provider_image_reference_limit(
    reference_images: list[object] | None,
    *,
    provider_id: str | None,
    model_id: str | None,
) -> dict[str, Any]:
    if not reference_images:
        return {}
    limit = _image_reference_limit(provider_id, model_id)
    if limit is None:
        return {}
    if limit <= 0 or len(reference_images) > limit:
        raise ValueError(
            _format_image_reference_limit_error(
                provider_id=provider_id,
                model_id=model_id,
                limit=limit,
                count=len(reference_images),
                reference_images=reference_images,
            )
        )
    return {
        "provider": provider_id,
        "model": model_id,
        "max_reference_images": limit,
        "reference_image_count": len(reference_images),
        "reference_image_submitted_count": len(reference_images),
        "reference_image_dropped_count": 0,
    }


def _asset_reference_sources(
    project: dict,
    project_path: Path,
    target_item: dict,
    *,
    char_field: str,
    scene_field: str,
    prop_field: str,
) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen: set[str] = set()

    def _append(kind: str, name: object, sheet: object) -> None:
        if not isinstance(sheet, str) or not sheet:
            return
        if sheet in seen or not (project_path / sheet).exists():
            return
        seen.add(sheet)
        label_kind = {"character": "角色", "scene": "场景", "prop": "道具"}[kind]
        sources.append({"kind": kind, "name": str(name), "label": f"{label_kind}：{name}", "path": sheet})

    characters = project.get("characters", {})
    scenes = project.get("scenes", {})
    props = project.get("props", {})
    for name in target_item.get(char_field, []):
        asset = characters.get(name) if isinstance(characters, dict) else None
        _append("character", name, asset.get("character_sheet") if isinstance(asset, dict) else None)
    for name in target_item.get(scene_field, []):
        asset = scenes.get(name) if isinstance(scenes, dict) else None
        _append("scene", name, asset.get("scene_sheet") if isinstance(asset, dict) else None)
    for name in target_item.get(prop_field, []):
        asset = props.get(name) if isinstance(props, dict) else None
        _append("prop", name, asset.get("prop_sheet") if isinstance(asset, dict) else None)
    return sources


def _with_candidate_references(
    target_item: dict,
    *,
    char_field: str,
    scene_field: str,
    prop_field: str,
    characters: list[str] | None,
    scenes: list[str] | None,
    props: list[str] | None,
) -> dict:
    candidate = dict(target_item)
    if characters is not None:
        candidate[char_field] = characters
    if scenes is not None:
        candidate[scene_field] = scenes
    if props is not None:
        candidate[prop_field] = props
    return candidate


async def preview_storyboard_reference_usage(
    project_name: str,
    resource_id: str,
    *,
    script_file: str,
    characters: list[str] | None = None,
    scenes: list[str] | None = None,
    props: list[str] | None = None,
    generation_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return whether a candidate reference selection fits current image model limits."""

    payload_overrides = dict(generation_payload or {})

    def _prepare() -> dict[str, Any]:
        manager = get_project_manager()
        project = manager.load_project(project_name)
        project_path = manager.get_project_path(project_name)
        script = manager.load_script(project_name, script_file)
        items, id_field, char_field, scene_field, prop_field = get_storyboard_items(script)
        resolved = find_storyboard_item(items, id_field, resource_id)
        if resolved is None:
            raise ValueError(f"scene/segment not found: {resource_id}")
        target_item, _ = resolved
        target_item = _with_candidate_references(
            target_item,
            char_field=char_field,
            scene_field=scene_field,
            prop_field=prop_field,
            characters=characters,
            scenes=scenes,
            props=props,
        )
        route_payload = _payload_with_shot_tier({"script_file": script_file, **payload_overrides}, target_item)
        asset_sources = _asset_reference_sources(
            project,
            project_path,
            target_item,
            char_field=char_field,
            scene_field=scene_field,
            prop_field=prop_field,
        )

        previous_id, previous_path = _previous_storyboard_candidate(project_path, items, id_field, resource_id)
        needs_previous = _storyboard_needs_previous_reference(project, route_payload, target_item)
        previous_source = None
        if needs_previous and previous_id:
            previous_source = {
                "kind": "previous_storyboard",
                "name": previous_id,
                "label": f"上一张分镜图：{previous_id}",
                "path": str(previous_path) if previous_path else "",
                "exists": bool(previous_path and previous_path.is_file()),
            }

        source_ref = None
        assets = target_item.get("generated_assets") if isinstance(target_item.get("generated_assets"), dict) else {}
        source_ref, _source_meta = _storyboard_source_reference(
            project_path=project_path,
            versions=VersionManager(project_path),
            resource_id=resource_id,
            assets=assets,
            payload={**route_payload, "quality": "final"},
        )
        source_exists = source_ref is not None

        return {
            "project": project,
            "target_item": target_item,
            "route_payload": route_payload,
            "asset_sources": asset_sources,
            "previous_source": previous_source,
            "source_exists": source_exists,
        }

    prepared = await asyncio.to_thread(_prepare)
    project = prepared["project"]
    route_payload = prepared["route_payload"]
    asset_sources = list(prepared["asset_sources"])
    previous_source = prepared["previous_source"]
    source_exists = bool(prepared["source_exists"])

    async def _scenario(payload: dict[str, Any]) -> dict[str, Any]:
        quality = str(payload.get("quality") or "draft")
        final_generation_mode = _storyboard_final_generation_mode(payload)
        include_source = _should_use_storyboard_source(payload, final_generation_mode)
        sources = list(asset_sources)
        if previous_source:
            sources.append(previous_source)
        if include_source and source_exists:
            sources.insert(
                0,
                {
                    "kind": "current_storyboard",
                    "name": resource_id,
                    "label": "当前分镜图（精修参考）",
                    "path": "",
                    "exists": True,
                },
            )
        count = len(sources)
        provider_id = None
        model_id = None
        profile_key = None
        max_reference_images = None
        route_error = None
        try:
            route = await _maybe_resolve_generation_route(
                project_name=project_name,
                project=project,
                payload=payload,
                task_kind="storyboard",
                needs_i2i=count > 0,
            )
            if route is not None:
                provider_id = route.provider_id
                model_id = route.model_id
                profile_key = route.profile_key
            else:
                resolved = await _resolve_effective_image_backend(project, payload, needs_i2i=count > 0)
                provider_id = resolved.provider_id
                model_id = resolved.model_id
        except Exception as exc:  # noqa: BLE001
            route_error = str(exc)

        if provider_id or model_id:
            max_reference_images = _image_reference_limit(provider_id, model_id)

        resolution_failed = route_error is not None and count > 0
        blocking = (
            max_reference_images is not None
            and count > 0
            and (max_reference_images <= 0 or count > max_reference_images)
        )
        message = None
        if resolution_failed:
            message = _format_image_reference_unresolved_error(
                count=count,
                reference_images=[{"label": item["label"]} for item in sources],
                route_error=route_error,
            )
        elif blocking:
            message = _format_image_reference_limit_error(
                provider_id=provider_id,
                model_id=model_id,
                limit=int(max_reference_images or 0),
                count=count,
                reference_images=[{"label": item["label"]} for item in sources],
            )
        return {
            "quality": quality,
            "final_generation_mode": final_generation_mode,
            "profile_key": profile_key,
            "provider_id": provider_id,
            "model_id": model_id,
            "max_reference_images": max_reference_images,
            "reference_image_count": count,
            "sources": sources,
            "ok": not (resolution_failed or blocking),
            "message": message,
            "route_error": route_error,
        }

    if payload_overrides:
        scenario_payloads = [{**route_payload, "quality": payload_overrides.get("quality") or "draft"}]
    else:
        scenario_payloads = [
            {**route_payload, "quality": "draft"},
            {**route_payload, "quality": "final"},
        ]
    scenarios = [await _scenario(payload) for payload in scenario_payloads]
    blocking_scenarios = [item for item in scenarios if not item["ok"]]
    return {
        "ok": not blocking_scenarios,
        "message": blocking_scenarios[0]["message"] if blocking_scenarios else None,
        "scenarios": scenarios,
    }


def _normalize_continuity_policy(project: dict, payload: dict[str, Any]) -> str:
    raw = payload.get("video_continuity_policy")
    if raw is None:
        raw = payload.get("continuity_policy")
    if raw is None:
        raw = project.get("video_continuity_policy")
    if raw is None:
        raw = project.get("continuity_policy")
    policy = str(raw or "auto").strip().lower()
    return policy if policy in _VIDEO_CONTINUITY_POLICIES else "auto"


def _item_reference_values(item: dict, field: str) -> set[str]:
    value = item.get(field)
    if not isinstance(value, list):
        return set()
    return {str(v).strip() for v in value if str(v).strip()}


def _storyboard_path_for_item(project_path: Path, item: dict, id_field: str) -> tuple[str | None, Path | None]:
    return storyboard_path_for_item(project_path, item, id_field)


def _video_backend_caps(generator: Any) -> tuple[Any | None, bool, bool, bool, str | None, str | None]:
    backend = getattr(generator, "_video_backend", None)
    caps = getattr(backend, "video_capabilities", None) if backend is not None else None
    supports_end_image = bool(getattr(caps, "last_frame", False))
    supports_reference_images = bool(getattr(caps, "reference_images", False))
    supports_reference_with_start_image = bool(getattr(caps, "reference_images_with_start_image", False))
    provider = getattr(backend, "name", None)
    model = getattr(backend, "model", None)
    return caps, supports_end_image, supports_reference_images, supports_reference_with_start_image, provider, model


def _resolve_video_end_image(
    *,
    project: dict,
    project_path: Path,
    items: list[dict],
    id_field: str,
    char_field: str,
    item_index: int | None,
    current_item: dict,
    resource_id: str,
    generator: Any,
    payload: dict[str, Any],
) -> tuple[Path | None, list[Path] | None, dict[str, Any]]:
    policy = _normalize_continuity_policy(project, payload)
    (
        caps,
        supports_end_image,
        supports_reference_images,
        supports_reference_with_start_image,
        provider,
        model,
    ) = _video_backend_caps(generator)
    meta: dict[str, Any] = {
        "requested_policy": policy,
        "effective_policy": "start_only",
        "start_storyboard_id": resource_id,
        "provider_supports_end_image": supports_end_image,
        "provider_supports_reference_images": supports_reference_images,
        "provider_supports_reference_with_start_image": supports_reference_with_start_image,
    }
    max_reference_images = getattr(caps, "max_reference_images", None)
    if max_reference_images is not None:
        meta["provider_max_reference_images"] = max_reference_images
    if provider:
        meta["provider"] = provider
    if model:
        meta["model"] = model

    if policy == "start_only":
        meta["skip_reason"] = "policy_start_only"
        return None, None, meta
    if item_index is None:
        meta["skip_reason"] = "storyboard_item_not_found"
        return None, None, meta
    next_index = item_index + 1
    if next_index >= len(items):
        meta["skip_reason"] = "last_storyboard"
        return None, None, meta

    next_item = items[next_index]
    next_id, next_storyboard = _storyboard_path_for_item(project_path, next_item, id_field)
    if next_id:
        meta["end_storyboard_id"] = next_id
    if not next_storyboard or not next_storyboard.is_file():
        meta["skip_reason"] = "next_storyboard_missing"
        return None, None, meta

    transition_to_next = str(current_item.get("transition_to_next") or "cut").strip().lower()
    meta["transition_to_next"] = transition_to_next
    if policy == "auto":
        if transition_to_next in _END_FRAME_SKIP_TRANSITIONS:
            meta["skip_reason"] = f"transition_{transition_to_next}"
            return None, None, meta
        if bool(next_item.get("segment_break")):
            meta["skip_reason"] = "next_segment_break"
            return None, None, meta

        current_scenes = _item_reference_values(current_item, "scenes")
        next_scenes = _item_reference_values(next_item, "scenes")
        if current_scenes and next_scenes and current_scenes.isdisjoint(next_scenes):
            meta["skip_reason"] = "scene_changed"
            return None, None, meta

    if policy == "reference_assisted":
        if not supports_reference_images:
            meta["skip_reason"] = "provider_no_reference_images"
            return None, None, meta
        if not supports_reference_with_start_image:
            meta["skip_reason"] = "provider_no_reference_with_start_image"
            return None, None, meta
        meta["effective_policy"] = "reference_assisted"
        meta["submitted_reference_images"] = [str(next_storyboard)]
        return None, [next_storyboard], meta

    if policy == "auto" and not supports_end_image:
        if supports_reference_images and supports_reference_with_start_image:
            meta["effective_policy"] = "reference_assisted"
            meta["submitted_reference_images"] = [str(next_storyboard)]
            return None, [next_storyboard], meta
        if supports_reference_images:
            meta["skip_reason"] = "provider_no_reference_with_start_image"
            return None, None, meta

    if not supports_end_image:
        meta["skip_reason"] = "provider_no_end_image"
        return None, None, meta

    meta["effective_policy"] = "end_frame"
    meta["submitted_end_image"] = str(next_storyboard)
    return next_storyboard, None, meta


def _resolve_script_episode(project_name: str, script_file: str | None) -> int | None:
    if not script_file:
        return None
    try:
        script = get_project_manager().load_script(project_name, script_file)
    except Exception:
        return None

    episode = script.get("episode")
    if isinstance(episode, int):
        return episode
    return None


def _compute_affected_fingerprints(project_name: str, task_type: str, resource_id: str) -> dict[str, int]:
    """计算受影响文件的 mtime 指纹"""
    try:
        project_path = get_project_manager().get_project_path(project_name)
    except Exception:
        return {}

    paths: list[tuple[str, Path]] = []

    if task_type == "storyboard":
        paths.append(
            (
                f"storyboards/scene_{resource_id}.png",
                project_path / "storyboards" / f"scene_{resource_id}.png",
            )
        )
    elif task_type == "video":
        paths.append(
            (
                f"videos/scene_{resource_id}.mp4",
                project_path / "videos" / f"scene_{resource_id}.mp4",
            )
        )
        paths.append(
            (
                f"thumbnails/scene_{resource_id}.jpg",
                project_path / "thumbnails" / f"scene_{resource_id}.jpg",
            )
        )
    elif task_type == "character":
        paths.append(
            (
                f"characters/{resource_id}.png",
                project_path / "characters" / f"{resource_id}.png",
            )
        )
    elif task_type == "scene":
        paths.append(
            (
                f"scenes/{resource_id}.png",
                project_path / "scenes" / f"{resource_id}.png",
            )
        )
    elif task_type == "prop":
        paths.append(
            (
                f"props/{resource_id}.png",
                project_path / "props" / f"{resource_id}.png",
            )
        )
    elif task_type == "grid":
        paths.append(
            (
                f"grids/{resource_id}.png",
                project_path / "grids" / f"{resource_id}.png",
            )
        )
    elif task_type == "reference_video":
        paths.append(
            (
                f"reference_videos/{resource_id}.mp4",
                project_path / "reference_videos" / f"{resource_id}.mp4",
            )
        )
        paths.append(
            (
                f"reference_videos/thumbnails/{resource_id}.jpg",
                project_path / "reference_videos" / "thumbnails" / f"{resource_id}.jpg",
            )
        )

    result: dict[str, int] = {}
    for rel, abs_path in paths:
        if abs_path.exists():
            result[rel] = abs_path.stat().st_mtime_ns

    return result


# (entity_type, action, label_tpl, include_script_episode)
# 三类项目级资产（character / scene / prop）的 spec 由 lib.asset_types.ASSET_SPECS 派生。
_TASK_CHANGE_SPECS: dict[str, tuple] = {
    "storyboard": ("segment", "storyboard_ready", "分镜「{}」", True),
    "video": ("segment", "video_ready", "分镜「{}」", True),
    "grid": ("grid", "grid_ready", "宫格「{}」", True),
    "reference_video": ("reference_video_unit", "reference_video_ready", "参考视频「{}」", True),
    **{atype: (atype, "updated", f"{spec.label_zh}「{{}}」设计图", False) for atype, spec in ASSET_SPECS.items()},
}


def emit_generation_success_batch(
    *,
    task_type: str,
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
) -> None:
    spec = _TASK_CHANGE_SPECS.get(task_type)
    if spec is None:
        return

    entity_type, action, label_tpl, include_script_episode = spec
    asset_fingerprints = _compute_affected_fingerprints(project_name, task_type, resource_id)

    change: dict[str, Any] = {
        "entity_type": entity_type,
        "action": action,
        "entity_id": resource_id,
        "label": label_tpl.format(resource_id),
        "focus": None,
        "important": True,
        "asset_fingerprints": asset_fingerprints,
    }
    if include_script_episode:
        script_file = str(payload.get("script_file") or "") or None
        change["script_file"] = script_file
        change["episode"] = _resolve_script_episode(project_name, script_file)

    try:
        emit_project_change_batch(project_name, [change], source="worker")
    except Exception:
        logger.exception(
            "发送生成完成项目事件失败 project=%s task_type=%s resource_id=%s",
            project_name,
            task_type,
            resource_id,
        )


async def execute_storyboard_task(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str = DEFAULT_USER_ID,
    task_id: str | None = None,
) -> dict[str, Any]:
    script_file = payload.get("script_file")
    if not script_file:
        raise ValueError("script_file is required for storyboard task")

    prompt = payload.get("prompt")
    if prompt is None:
        raise ValueError("prompt is required for storyboard task")

    def _prepare():
        _project = get_project_manager().load_project(project_name)
        _project_path = get_project_manager().get_project_path(project_name)
        _script = get_project_manager().load_script(project_name, script_file)
        assert_script_splitting_assets_current(
            _project,
            _script,
            script_file=script_file,
            asset_kind="storyboard",
        )
        _items, _id_field, _char_field, _scene_field, _prop_field = get_storyboard_items(_script)

        _resolved = find_storyboard_item(_items, _id_field, resource_id)
        if _resolved is None:
            raise ValueError(f"scene/segment not found: {resource_id}")
        _target_item, _ = _resolved

        _assets = _target_item.get("generated_assets") if isinstance(_target_item.get("generated_assets"), dict) else {}
        _source_meta: dict[str, Any] = {}
        _source_ref: dict[str, Any] | None = None
        _final_generation_mode = _storyboard_final_generation_mode(payload)
        _previous_required = _should_use_previous_storyboard_reference(_project, payload, _target_item)
        _previous_ref_path = _resolve_previous_storyboard_reference_path(
            _project_path,
            _items,
            _id_field,
            resource_id,
            required=_previous_required,
        ) if _previous_required else None
        if _should_use_storyboard_source(payload, _final_generation_mode):
            _source_ref, _source_meta = _storyboard_source_reference(
                project_path=_project_path,
                versions=VersionManager(_project_path),
                resource_id=resource_id,
                assets=_assets,
                payload=payload,
            )
        _prompt_text = _normalize_storyboard_prompt(prompt, _project.get("style", ""))
        _ref_images = _collect_reference_images(
            _project,
            _project_path,
            _target_item,
            char_field=_char_field,
            scene_field=_scene_field,
            prop_field=_prop_field,
            previous_storyboard_path=_previous_ref_path,
        )
        if _source_ref is not None:
            _ref_images = [_source_ref, *(_ref_images or [])]
        return _project, _project_path, _target_item, _prompt_text, _ref_images, _source_meta, _final_generation_mode

    project, project_path, target_item, prompt_text, reference_images, source_storyboard_meta, final_generation_mode = await asyncio.to_thread(
        _prepare
    )
    route_payload = _payload_with_shot_tier(payload, target_item)
    _needs_i2i = bool(reference_images)
    route = await _maybe_resolve_generation_route(
        project_name=project_name,
        project=project,
        payload=route_payload,
        task_kind="storyboard",
        needs_i2i=_needs_i2i,
    )
    effective_payload = route.effective_payload if route else payload
    provider_reference_policy_meta: dict[str, Any] = {}
    if route is not None:
        provider_reference_policy_meta = _validate_provider_image_reference_limit(
            reference_images,
            provider_id=route.provider_id,
            model_id=route.model_id,
        )
    else:
        provider_reference_policy_meta = {}
    effective_needs_i2i = bool(reference_images)

    generator = await get_media_generator(
        project_name,
        payload=effective_payload,
        user_id=user_id,
        needs_i2i=effective_needs_i2i,
    )
    aspect_ratio = get_aspect_ratio(project, "storyboards")

    if route is not None:
        image_size = route.resolution
        version_metadata = dict(route.metadata)
    else:
        resolved_image = await _resolve_effective_image_backend(project, payload, needs_i2i=effective_needs_i2i)
        image_size = await resolve_resolution(project, resolved_image.provider_id, resolved_image.model_id)
        version_metadata = {}
        provider_reference_policy_meta = _validate_provider_image_reference_limit(
            reference_images,
            provider_id=resolved_image.provider_id,
            model_id=resolved_image.model_id,
        )
    for key, value in source_storyboard_meta.items():
        version_metadata.setdefault(key, value)
    if final_generation_mode:
        version_metadata.setdefault("final_generation_mode", final_generation_mode)
    if provider_reference_policy_meta:
        version_metadata.setdefault("provider_image_reference_policy", provider_reference_policy_meta)

    _, version = await generator.generate_image_async(
        prompt=prompt_text,
        resource_type="storyboards",
        resource_id=resource_id,
        reference_images=reference_images,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        **version_metadata,
    )

    def _finalize():
        get_project_manager().update_scene_asset(
            project_name=project_name,
            script_filename=script_file,
            scene_id=resource_id,
            asset_type="storyboard_image",
            asset_path=f"storyboards/scene_{resource_id}.png",
        )
        return generator.versions.get_versions("storyboards", resource_id)["versions"][-1]["created_at"]

    created_at = await asyncio.to_thread(_finalize)

    return {
        "version": version,
        "file_path": f"storyboards/scene_{resource_id}.png",
        "created_at": created_at,
        "resource_type": "storyboards",
        "resource_id": resource_id,
        **version_metadata,
    }


async def execute_video_task(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str = DEFAULT_USER_ID,
    task_id: str | None = None,
) -> dict[str, Any]:
    script_file = payload.get("script_file")
    if not script_file:
        raise ValueError("script_file is required for video task")

    prompt = payload.get("prompt")
    if prompt is None:
        raise ValueError("prompt is required for video task")

    def _load():
        _pm = get_project_manager()
        _project = _pm.load_project(project_name)
        _project_path = _pm.get_project_path(project_name)
        _script = _pm.load_script(project_name, script_file)
        assert_script_splitting_assets_current(
            _project,
            _script,
            script_file=script_file,
            asset_kind="video",
        )
        _items, _id_field, _char_field, _, _ = get_storyboard_items(_script)
        _resolved = find_storyboard_item(_items, _id_field, resource_id)
        _item = _resolved[0] if _resolved else {}
        _item_index = _resolved[1] if _resolved else None
        return _project, _project_path, _items, _id_field, _item, _item_index, _char_field

    project, project_path, items, id_field, item, item_index, char_field = await asyncio.to_thread(_load)
    route_payload = _payload_with_shot_tier(payload, item)
    route = await _maybe_resolve_generation_route(
        project_name=project_name,
        project=project,
        payload=route_payload,
        task_kind="video",
    )
    effective_payload = route.effective_payload if route else payload
    if route is not None and route.shot_tier_strategy.get("video_continuity_policy"):
        effective_payload = {
            **effective_payload,
            "video_continuity_policy": route.shot_tier_strategy["video_continuity_policy"],
        }
    generator = await get_media_generator(project_name, payload=effective_payload, user_id=user_id)

    # 优先读取 generated_assets.storyboard_image，回退默认路径。
    # 旧宫格项目 storyboard_image 指向 scene_{id}_first.png，仍可正常解析。
    assets = item.get("generated_assets", {})
    storyboard_rel = assets.get("storyboard_image") if isinstance(assets, dict) else None
    if storyboard_rel:
        storyboard_file = project_path / storyboard_rel
    else:
        storyboard_file = project_path / "storyboards" / f"scene_{resource_id}.png"
    if not storyboard_file.is_file():
        raise ValueError(f"storyboard not found: {storyboard_file.name}")
    source_storyboard_quality = _storyboard_source_quality(generator.versions, resource_id, assets)

    prompt_policy = await _video_prompt_policy_from_generator(generator, project_name)
    prompt_text = _normalize_video_prompt(
        prompt,
        project=project,
        target_item=item,
        char_field=char_field,
        policy=prompt_policy,
    )
    aspect_ratio = get_aspect_ratio(project, "videos")
    seed = route.seed if route else payload.get("seed")
    service_tier = route.service_tier if route else payload.get("video_provider_settings", {}).get("service_tier", "default")

    if route is not None:
        registry_provider_id = route.provider_id
        model_name = route.model_id or None
        supported_durations = route.supported_durations
        resolution = route.resolution
        duration_seconds = route.duration_seconds
        provider_capabilities = None
        version_metadata = dict(route.metadata)
        if route.generate_audio is not None:
            version_metadata["generate_audio"] = route.generate_audio
    else:
        # 解析 provider / model（薄投影），供 duration fallback 和分辨率查找共用。
        # 与执行层 backend 构造同走 resolve_video_backend，确保限流/分辨率与实际调用对齐。
        from lib.config.resolver import ConfigResolver
        from lib.db import async_session_factory

        _resolver = ConfigResolver(async_session_factory)
        try:
            resolved_video = await _resolver.resolve_video_backend(project, payload)
            registry_provider_id = resolved_video.provider_id
            model_name = resolved_video.model_id or None
        except Exception:
            registry_provider_id, model_name = "gemini-aistudio", "veo-3.1-lite-generate-preview"

        # supported_durations 按上面已解析出的 provider/model 取（而非按 project 二次解析），
        # 确保 duration 守卫所依据的能力与实际要调用的 model 一致——历史任务 payload 携带
        # provider 覆盖时，二者不一致会用「项目默认 model 的能力」误判「payload 解析出的 model」。
        # caps 失败不得丢弃已解析出的 provider/model，否则 resolve_resolution 与默认 duration
        # 会错配。能力不可解析时留空，守卫遇空列表放行（不更坏，见 ADR-0002）。
        supported_resolutions: list[str] = []
        supported_durations: list[int] = []
        duration_resolution_constraints: dict[str, list[int]] = {}
        provider_capabilities: dict[str, Any] | None = None
        try:
            caps = await _resolver.video_capabilities_for_model(registry_provider_id, model_name or "", project)
            provider_capabilities = dict(caps)
            provider_capabilities.setdefault("provider_id", registry_provider_id)
            provider_capabilities.setdefault("model", model_name)
            supported_resolutions = [str(item) for item in caps.get("resolutions") or []]
            supported_durations = [int(d) for d in caps.get("supported_durations") or []]
            duration_resolution_constraints = {
                str(key): [int(item) for item in value or []]
                for key, value in (caps.get("duration_resolution_constraints") or {}).items()
            }
        except Exception:
            supported_resolutions = []
            supported_durations = []
            duration_resolution_constraints = {}
            provider_capabilities = None

        resolution = await resolve_resolution(
            project,
            registry_provider_id,
            model_name or "",
        )
        legacy_route_warnings: list[dict[str, Any]] = []
        resolution, resolution_warning = coerce_video_resolution_for_options(resolution, supported_resolutions)
        if resolution_warning:
            legacy_route_warnings.append(resolution_warning)
        supported_durations = duration_options_for_resolution(
            supported_durations,
            duration_resolution_constraints,
            resolution,
        )

        # duration 解析收口于执行层：payload > project.default_duration > caps 默认。
        # 用 ``is not None`` 而非 ``or`` 取 payload 值，避免显式 falsy 值被当作未设置。
        duration_seconds = payload.get("duration_seconds")
        if duration_seconds is None:
            duration_seconds = project.get("default_duration")
        if not duration_seconds:
            duration_seconds = (
                supported_durations[0]
                if supported_durations
                else _get_model_default_duration(registry_provider_id, model_name)
            )
        duration_seconds, duration_warning = coerce_video_duration_for_options(duration_seconds, supported_durations)
        if duration_warning:
            legacy_route_warnings.append(duration_warning)
        version_metadata = {}
        if legacy_route_warnings:
            version_metadata["generation_route_warnings"] = legacy_route_warnings
    version_metadata["source_storyboard_generation_quality"] = source_storyboard_quality
    # 能力守卫：provider 解析之后的唯一权威家（见 ADR-0001）。安全解析交给守卫，
    # 此处不预先 int() 截断，避免把非整数秒静默修正成「碰巧合法」的值。
    assert_duration_supported(duration_seconds, supported_durations)

    end_image, continuity_reference_images, continuity_meta = _resolve_video_end_image(
        project=project,
        project_path=project_path,
        items=items,
        id_field=id_field,
        char_field=char_field,
        item_index=item_index,
        current_item=item,
        resource_id=resource_id,
        generator=generator,
        payload=effective_payload,
    )
    version_metadata["video_continuity"] = continuity_meta
    version_metadata["video_input_preflight"] = _assert_video_preflight_ok(
        project=project,
        generator=generator,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        reference_images=continuity_reference_images,
        first_frame_path=storyboard_file,
        last_frame_path=end_image,
        generate_audio=version_metadata.get("generate_audio"),
        provider_id=registry_provider_id,
        model=model_name,
        provider_capabilities=provider_capabilities,
        supported_durations=supported_durations,
        supported_resolutions=route.supported_resolutions if route else supported_resolutions,
        duration_resolution_constraints=(
            route.duration_resolution_constraints if route else duration_resolution_constraints
        ),
    )

    _, version, _, video_uri = await generator.generate_video_async(
        prompt=prompt_text,
        resource_type="videos",
        resource_id=resource_id,
        start_image=storyboard_file,
        end_image=end_image,
        reference_images=continuity_reference_images,
        allow_end_image_reference_fallback=False,
        aspect_ratio=aspect_ratio,
        duration_seconds=duration_seconds,
        resolution=resolution,
        task_id=task_id,
        seed=seed,
        service_tier=service_tier,
        **version_metadata,
    )

    return await _finalize_video_task(
        project_name=project_name,
        script_file=script_file,
        project_path=project_path,
        resource_id=resource_id,
        version=version,
        video_uri=video_uri,
        generator=generator,
        version_metadata=version_metadata,
    )


async def _finalize_video_task(
    *,
    project_name: str,
    script_file: str,
    project_path: Path,
    resource_id: str,
    version: int,
    video_uri: str | None,
    generator: Any,
    version_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Normal + resume 共用的 finalize 逻辑：写 scene asset + 抽缩略图 + 返回 result dict。"""

    def _update_video_metadata():
        get_project_manager().update_scene_asset(
            project_name=project_name,
            script_filename=script_file,
            scene_id=resource_id,
            asset_type="video_clip",
            asset_path=f"videos/scene_{resource_id}.mp4",
        )
        if video_uri:
            get_project_manager().update_scene_asset(
                project_name=project_name,
                script_filename=script_file,
                scene_id=resource_id,
                asset_type="video_uri",
                asset_path=video_uri,
            )

    await asyncio.to_thread(_update_video_metadata)

    video_file = project_path / f"videos/scene_{resource_id}.mp4"
    thumbnail_file = project_path / f"thumbnails/scene_{resource_id}.jpg"
    if await extract_video_thumbnail(video_file, thumbnail_file):
        await asyncio.to_thread(
            get_project_manager().update_scene_asset,
            project_name=project_name,
            script_filename=script_file,
            scene_id=resource_id,
            asset_type="video_thumbnail",
            asset_path=f"thumbnails/scene_{resource_id}.jpg",
        )
    else:
        thumbnail_file.unlink(missing_ok=True)

    created_at = await asyncio.to_thread(
        lambda: generator.versions.get_versions("videos", resource_id)["versions"][-1]["created_at"]
    )

    return {
        "version": version,
        "file_path": f"videos/scene_{resource_id}.mp4",
        "created_at": created_at,
        "resource_type": "videos",
        "resource_id": resource_id,
        "video_uri": video_uri,
        **version_metadata,
    }


async def execute_character_task(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str = DEFAULT_USER_ID,
    task_id: str | None = None,
) -> dict[str, Any]:
    prompt = str(payload.get("prompt", "") or "").strip()
    if not prompt:
        raise ValueError("prompt is required for character task")

    def _prepare_char():
        _project = get_project_manager().load_project(project_name)
        _project_path = get_project_manager().get_project_path(project_name)
        if resource_id not in _project.get("characters", {}):
            raise ValueError(f"character not found: {resource_id}")
        _char_data = _project["characters"][resource_id]
        _style = _project.get("style", "")
        _style_desc = _project.get("style_description", "")
        _full_prompt = build_character_prompt(resource_id, prompt, _style, _style_desc)
        _ref_images = None
        _ref_path = _char_data.get("reference_image")
        if _ref_path:
            _full_ref = _project_path / _ref_path
            if _full_ref.exists():
                _ref_images = [_full_ref]
        return _project, _full_prompt, _ref_images

    project, full_prompt, reference_images = await asyncio.to_thread(_prepare_char)
    _needs_i2i = bool(reference_images)
    route = await _maybe_resolve_generation_route(
        project_name=project_name,
        project=project,
        payload=payload,
        task_kind="character",
        needs_i2i=_needs_i2i,
    )
    effective_payload = route.effective_payload if route else payload

    generator = await get_media_generator(project_name, payload=effective_payload, user_id=user_id, needs_i2i=_needs_i2i)
    aspect_ratio = get_aspect_ratio(project, "characters")

    if route is not None:
        image_size = route.resolution
        version_metadata = dict(route.metadata)
    else:
        resolved_image = await _resolve_effective_image_backend(project, payload, needs_i2i=_needs_i2i)
        image_size = await resolve_resolution(project, resolved_image.provider_id, resolved_image.model_id)
        version_metadata = {}

    _, version = await generator.generate_image_async(
        prompt=full_prompt,
        resource_type="characters",
        resource_id=resource_id,
        reference_images=reference_images,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        **version_metadata,
    )

    sheet_path = f"characters/{resource_id}.png"

    def _finalize_char():
        def _set_character_sheet(p: dict) -> None:
            p["characters"][resource_id]["character_sheet"] = sheet_path

        get_project_manager().update_project(project_name, _set_character_sheet)
        return generator.versions.get_versions("characters", resource_id)["versions"][-1]["created_at"]

    created_at = await asyncio.to_thread(_finalize_char)

    return {
        "version": version,
        "file_path": f"characters/{resource_id}.png",
        "created_at": created_at,
        "resource_type": "characters",
        "resource_id": resource_id,
        **version_metadata,
    }


# 仅保留 design 任务的「prompt 构造器」差异；bucket_key 与 sheet 写入由 ASSET_SPECS 与
# ProjectManager._update_asset_sheet 统一派发。
_DESIGN_PROMPT_BUILDERS: dict[str, Any] = {
    "scene": build_scene_prompt,
    "prop": build_prop_prompt,
}


async def execute_design_task(
    kind: str,
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str = DEFAULT_USER_ID,
) -> dict[str, Any]:
    """合并 execute_scene_task / execute_prop_task：按 kind 查表派发。"""
    spec = ASSET_SPECS[kind]
    bucket_key = spec.bucket_key
    prompt_builder = _DESIGN_PROMPT_BUILDERS[kind]

    prompt = str(payload.get("prompt", "") or "").strip()
    if not prompt:
        raise ValueError(f"prompt is required for {kind} task")

    def _prepare():
        project = get_project_manager().load_project(project_name)
        if resource_id not in project.get(bucket_key, {}):
            raise ValueError(f"{kind} not found: {resource_id}")
        style = project.get("style", "")
        style_desc = project.get("style_description", "")
        full_prompt = prompt_builder(resource_id, prompt, style, style_desc)
        return project, full_prompt

    project, full_prompt = await asyncio.to_thread(_prepare)
    route = await _maybe_resolve_generation_route(
        project_name=project_name,
        project=project,
        payload=payload,
        task_kind=kind,
        needs_i2i=False,
    )
    effective_payload = route.effective_payload if route else payload

    generator = await get_media_generator(project_name, payload=effective_payload, user_id=user_id, needs_i2i=False)
    aspect_ratio = get_aspect_ratio(project, bucket_key)

    if route is not None:
        image_size = route.resolution
        version_metadata = dict(route.metadata)
    else:
        resolved_image = await _resolve_effective_image_backend(project, payload, needs_i2i=False)
        image_size = await resolve_resolution(project, resolved_image.provider_id, resolved_image.model_id)
        version_metadata = {}

    _, version = await generator.generate_image_async(
        prompt=full_prompt,
        resource_type=bucket_key,
        resource_id=resource_id,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        **version_metadata,
    )

    sheet_path = f"{bucket_key}/{resource_id}.png"

    def _finalize():
        get_project_manager()._update_asset_sheet(kind, project_name, resource_id, sheet_path)
        return generator.versions.get_versions(bucket_key, resource_id)["versions"][-1]["created_at"]

    created_at = await asyncio.to_thread(_finalize)

    return {
        "version": version,
        "file_path": sheet_path,
        "created_at": created_at,
        "resource_type": bucket_key,
        "resource_id": resource_id,
        **version_metadata,
    }


async def execute_scene_task(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str = DEFAULT_USER_ID,
    task_id: str | None = None,
) -> dict[str, Any]:
    return await execute_design_task("scene", project_name, resource_id, payload, user_id=user_id)


async def execute_prop_task(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str = DEFAULT_USER_ID,
    task_id: str | None = None,
) -> dict[str, Any]:
    return await execute_design_task("prop", project_name, resource_id, payload, user_id=user_id)


def _group_scenes_by_segment_break(items: list[dict], id_field: str) -> list[list[dict]]:
    """Groups consecutive scene dicts, breaking at segment_break=True.

    Delegates to :func:`lib.storyboard_sequence.group_scenes_by_segment_break`.
    """
    return group_scenes_by_segment_break(items, id_field)


def _collect_grid_reference_images(
    project_path: Path,
    payload: dict[str, Any],
    scene_ids: list[str],
) -> tuple[list[object] | None, list[dict]]:
    """Collect character/scene/prop sheet images referenced by grid scenes.

    Returns a tuple of ``(image_paths, metadata)``:
    - *image_paths*: up to 6 :class:`~pathlib.Path` objects for the generation API.
    - *metadata*: list of dicts ``{path, name, ref_type}`` for persisting in
      :class:`~lib.grid.models.GridGeneration`.
    """
    project_json = project_path / "project.json"
    if not project_json.exists():
        return None, []

    import json

    project = json.loads(project_json.read_text(encoding="utf-8"))

    script_file = payload.get("script_file")
    if not script_file:
        return None, []

    script_path = project_path / "scripts" / script_file
    if not script_path.exists():
        return None, []

    script = json.loads(script_path.read_text(encoding="utf-8"))

    items, id_field, char_field, scene_field, prop_field = get_storyboard_items(script)

    scene_id_set = set(scene_ids)
    matched_items = [item for item in items if str(item.get(id_field, "")) in scene_id_set]

    characters = project.get("characters", {})
    project_scenes = project.get("scenes", {})
    project_props = project.get("props", {})

    seen: set[str] = set()
    paths: list[Path] = []
    metadata: list[dict] = []
    max_count = 6

    for item in matched_items:
        for char_name in item.get(char_field, []):
            sheet = characters.get(char_name, {}).get("character_sheet")
            if sheet and sheet not in seen:
                p = project_path / sheet
                if p.exists():
                    paths.append(p)
                    seen.add(sheet)
                    metadata.append({"path": sheet, "name": char_name, "ref_type": "character"})
        for scene_name in item.get(scene_field, []):
            sheet = project_scenes.get(scene_name, {}).get("scene_sheet")
            if sheet and sheet not in seen:
                p = project_path / sheet
                if p.exists():
                    paths.append(p)
                    seen.add(sheet)
                    metadata.append({"path": sheet, "name": scene_name, "ref_type": "scene"})
        for prop_name in item.get(prop_field, []):
            sheet = project_props.get(prop_name, {}).get("prop_sheet")
            if sheet and sheet not in seen:
                p = project_path / sheet
                if p.exists():
                    paths.append(p)
                    seen.add(sheet)
                    metadata.append({"path": sheet, "name": prop_name, "ref_type": "prop"})
        if len(paths) >= max_count:
            break

    return list(paths[:max_count]) or None, metadata[:max_count]


async def execute_grid_task(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str = DEFAULT_USER_ID,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Execute a grid image generation task.

    resource_id is the grid_id. Steps:
    1. Load GridGeneration, set status to generating
    2. Generate image via MediaGenerator
    3. Split grid image into cells
    4. Assign cell images to scenes in the script
    5. Mark completed
    """
    from PIL import Image

    from lib.grid.splitter import split_grid_image
    from lib.grid_manager import GridManager

    project_path = await asyncio.to_thread(get_project_manager().get_project_path, project_name)
    grid_manager = GridManager(project_path)

    # a) Load grid
    grid = grid_manager.get(resource_id)
    if grid is None:
        raise ValueError(f"grid not found: {resource_id}")

    script_file = grid.script_file

    try:
        # b) Set status to generating
        grid.status = "generating"
        grid.error_message = None
        grid_manager.save(grid)

        # c) Build reference images + metadata
        from lib.grid.models import ReferenceImage

        reference_images, ref_metadata = await asyncio.to_thread(
            _collect_grid_reference_images, project_path, payload, grid.scene_ids
        )
        grid.reference_images = [ReferenceImage.from_dict(m) for m in ref_metadata] if ref_metadata else []
        grid_manager.save(grid)

        # d) Generate grid image
        prompt_text = payload.get("prompt") or grid.prompt
        if not prompt_text:
            raise ValueError("prompt is required for grid task")

        _needs_i2i = bool(reference_images)
        project = await asyncio.to_thread(get_project_manager().load_project, project_name)
        script = await asyncio.to_thread(get_project_manager().load_script, project_name, script_file)
        assert_script_splitting_assets_current(
            project,
            script,
            script_file=script_file,
            asset_kind="grid",
        )
        aspect_ratio = payload.get("grid_aspect_ratio") or get_aspect_ratio(project, "storyboards")
        route = await _maybe_resolve_generation_route(
            project_name=project_name,
            project=project,
            payload=payload,
            task_kind="grid",
            needs_i2i=_needs_i2i,
        )
        effective_payload = route.effective_payload if route else payload
        generator = await get_media_generator(
            project_name,
            payload=effective_payload,
            user_id=user_id,
            needs_i2i=_needs_i2i,
        )

        resolved_image = await _resolve_effective_image_backend(project, effective_payload, needs_i2i=_needs_i2i)
        # 回填 grid metadata：route 层创建/重建时无法预知 needs_i2i，由此处补齐
        grid.provider = resolved_image.provider_id
        grid.model = resolved_image.model_id
        grid_manager.save(grid)
        if route is not None:
            image_size = route.resolution or "2K"
            version_metadata = dict(route.metadata)
        else:
            image_size = (
                await resolve_resolution(project, resolved_image.provider_id, resolved_image.model_id) or "2K"
            )  # 宫格图保底高分辨率
            version_metadata = {}

        image_path, version = await generator.generate_image_async(
            prompt=prompt_text,
            resource_type="grids",
            resource_id=resource_id,
            reference_images=reference_images,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            **version_metadata,
        )

        # e) Set grid_image_path, status to splitting
        grid.grid_image_path = f"grids/{resource_id}.png"
        grid.status = "splitting"
        grid_manager.save(grid)

        # f) Split the grid image
        grid_image = Image.open(image_path)
        video_aspect_ratio = get_aspect_ratio(project, "videos")
        cells = split_grid_image(grid_image, grid.rows, grid.cols, video_aspect_ratio)

        # g) Assign cells to scenes
        storyboards_dir = project_path / "storyboards"
        storyboards_dir.mkdir(parents=True, exist_ok=True)

        def _assign_cells():
            from lib.script_editor import resolve_items

            pm = get_project_manager()
            storyboard_versions = VersionManager(project_path)
            script = pm.load_script(project_name, script_file)
            items, id_field, _kind = resolve_items(script)
            valid_ids = {str(item.get(id_field)) for item in items if isinstance(item, dict)}

            asset_updates: list[tuple[str, str, Any]] = []
            missing_ids: list[str] = []

            # 宫格已统一走普通图生视频（不再使用 first_last 模式），cell 仅作为
            # next_scene_id 的起始分镜图，文件名与普通分镜对齐为 scene_{id}.png。
            for cell, frame in zip(cells, grid.frame_chain):
                if frame.frame_type == "placeholder":
                    continue
                if frame.frame_type not in ("first", "transition"):
                    continue
                if not frame.next_scene_id:
                    continue

                if str(frame.next_scene_id) not in valid_ids:
                    missing_ids.append(str(frame.next_scene_id))
                    continue

                cell_rel = f"storyboards/scene_{frame.next_scene_id}.png"
                cell_path = storyboards_dir / f"scene_{frame.next_scene_id}.png"
                cell.save(cell_path, format="PNG")
                cell_metadata = {
                    **version_metadata,
                    **script_splitting_asset_metadata(project),
                    "generation_quality": "grid",
                    "generation_profile_key": "grid",
                    "source_grid_id": resource_id,
                    "source_grid_version": version,
                    "source_grid_file": grid.grid_image_path,
                    "source_grid_cell_index": frame.index,
                    "grid_id": resource_id,
                    "grid_cell_index": frame.index,
                }
                storyboard_versions.add_version(
                    resource_type="storyboards",
                    resource_id=str(frame.next_scene_id),
                    prompt=prompt_text,
                    source_file=cell_path,
                    **cell_metadata,
                )
                frame.image_path = cell_rel
                asset_updates.append((frame.next_scene_id, "storyboard_image", cell_rel))
                asset_updates.append((frame.next_scene_id, "grid_id", resource_id))
                asset_updates.append((frame.next_scene_id, "grid_cell_index", frame.index))

            if missing_ids:
                logger.warning(
                    "grid %s: frame_chain 中以下分镜在剧本 %s 已不存在,跳过 cell 保存: %s",
                    resource_id,
                    script_file,
                    sorted(set(missing_ids)),
                )

            # Batch-write all asset updates in one script read+write pass
            if asset_updates:
                pm.batch_update_scene_assets(
                    project_name=project_name,
                    script_filename=script_file,
                    updates=asset_updates,
                )

        await asyncio.to_thread(_assign_cells)

        # h) Set status to completed
        grid.status = "completed"
        grid_manager.save(grid)

    except Exception as exc:
        grid.status = "failed"
        error_traceback = traceback.format_exc()
        print(error_traceback, flush=True)
        from lib.friendly_errors import summarize_generation_error

        grid.error_message = summarize_generation_error(
            exc,
            provider_id=grid.provider or None,
            task={"payload": payload},
        )
        grid_manager.save(grid)
        raise

    created_at = grid.created_at

    return {
        "version": version,
        "file_path": f"grids/{resource_id}.png",
        "created_at": created_at,
        "resource_type": "grids",
        "resource_id": resource_id,
        **version_metadata,
    }


async def _execute_reference_video_task_proxy(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Lazy proxy to avoid circular import: reference_video_tasks imports from this module."""
    from server.services.reference_video_tasks import execute_reference_video_task

    return await execute_reference_video_task(project_name, resource_id, payload, user_id=user_id, task_id=task_id)


_TASK_EXECUTORS = {
    "storyboard": execute_storyboard_task,
    "video": execute_video_task,
    "character": execute_character_task,
    "scene": execute_scene_task,
    "prop": execute_prop_task,
    "grid": execute_grid_task,
    "reference_video": _execute_reference_video_task_proxy,
}


async def execute_generation_task(task: dict[str, Any]) -> dict[str, Any]:
    task_type = task.get("task_type")
    project_name = task.get("project_name")
    resource_id = str(task.get("resource_id"))
    payload = task.get("payload") or {}
    user_id = task.get("user_id", DEFAULT_USER_ID)
    queue_task_id = task.get("task_id")

    if not project_name:
        raise ValueError("task.project_name is required")
    if not task_type:
        raise ValueError("task.task_type is required")

    executor = _TASK_EXECUTORS.get(task_type)
    if executor is None:
        raise ValueError(f"unsupported task_type: {task_type}")

    with project_change_source("worker"):
        try:
            result = await executor(project_name, resource_id, payload, user_id=user_id, task_id=queue_task_id)
        except (ImageCapabilityError, VideoCapabilityError) as err:
            # Worker 后台无 request 上下文，按 DEFAULT_LOCALE 渲染稳定的 i18n 文案
            # 落到 task.error_message，前端轮询时即可看到本地化提示
            message = i18n_translate(err.code, locale=DEFAULT_LOCALE, **err.params)
            raise RuntimeError(message) from err
        emit_generation_success_batch(
            task_type=task_type,
            project_name=project_name,
            resource_id=resource_id,
            payload=payload,
        )
        return result

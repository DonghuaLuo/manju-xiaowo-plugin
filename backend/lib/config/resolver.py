"""统一运行时配置解析器。

将散落在多个文件中的配置读取和默认值定义集中到一处。
每次调用从 DB 读取，不缓存（本地 SQLite 开销可忽略）。
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import async_sessionmaker

from sqlalchemy.ext.asyncio import AsyncSession

from lib.app_data_dir import app_data_dir
from lib.config.registry import PROVIDER_REGISTRY, is_retired_provider_model
from lib.config.service import (
    _DEFAULT_IMAGE_BACKEND,
    _DEFAULT_TEXT_BACKEND,
    _DEFAULT_VIDEO_BACKEND,
    ConfigService,
)
from lib.custom_provider import is_custom_provider, parse_provider_id
from lib.custom_provider.endpoints import get_endpoint_spec
from lib.db.repositories.credential_repository import CredentialRepository
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from lib.project_manager import ProjectManager
from lib.script_splitting_templates import (
    check_provider_compatibility,
    ensure_project_script_splitting_snapshot,
    provider_capability_hash,
    provider_capability_profile,
)
from lib.text_backends.base import TextTaskType
from lib.video_backends.base import VideoCapabilities

_project_manager: ProjectManager | None = None


def get_project_manager() -> ProjectManager:
    """返回共享的 ProjectManager 单例（使用标准项目根目录）。"""
    global _project_manager
    if _project_manager is None:
        _project_manager = ProjectManager(app_data_dir())
    return _project_manager


logger = logging.getLogger(__name__)

# 布尔字符串解析的 truthy 值集合
_TRUTHY = frozenset({"true", "1", "yes"})


@dataclass(frozen=True)
class ProviderModel:
    """provider 解析结果：规范 provider_id + model_id。"""

    provider_id: str
    model_id: str


def _parse_bool(raw: str) -> bool:
    """将配置字符串解析为布尔值。"""
    return raw.strip().lower() in _TRUTHY


def _split_pair(raw: object) -> tuple[str, str] | None:
    """解析 ``"<provider>/<model>"``；provider 或 model 为空时返回 None。"""
    if not isinstance(raw, str) or "/" not in raw:
        return None
    provider, model = raw.split("/", 1)
    provider, model = provider.strip(), model.strip()
    if not provider or not model:
        return None
    return provider, model


def _default_model_for_provider(provider_id: str, media_type: str) -> str | None:
    """返回 provider 在 registry 中指定 media_type 的默认 model_id。"""
    meta = PROVIDER_REGISTRY.get(provider_id)
    if meta is None:
        return None
    for model_id, model_info in meta.models.items():
        if model_info.media_type == media_type and model_info.default:
            return model_id
    return None


def _parse_project_provider(raw: object, media_type: str) -> tuple[str, str] | None:
    """解析 project.json provider 字段，兼容裸 provider 覆盖。"""
    pair = _split_pair(raw)
    if pair is not None:
        return pair
    if isinstance(raw, str):
        provider = raw.strip().rstrip("/").strip()
        if provider:
            model = _default_model_for_provider(provider, media_type)
            if model is not None:
                return provider, model
    return None


def _seedance_model_family(model_id: str) -> str:
    model = model_id.lower()
    if "seedance-2" in model or "seedance2" in model or "seedance-2.0" in model:
        return "seedance_2"
    if "seedance-1-0" in model or "seedance-1.0" in model:
        return "seedance_1_0"
    return "seedance_1_5"


def _custom_video_capability_strings(endpoint: str, model_id: str) -> list[str]:
    """Best-effort capability flags for custom video endpoints.

    Custom endpoints are usually provider-compatible relays. Keep this conservative:
    expose only flags the delegate backend is known to pass through.
    """

    capabilities = {"text_to_video", "image_to_video"}
    if endpoint == "ark-seedance":
        family = _seedance_model_family(model_id)
        capabilities.add("seed_control")
        if family != "seedance_1_0":
            capabilities.add("generate_audio")
        if family != "seedance_2":
            capabilities.add("flex_tier")
    elif endpoint == "vidu-video":
        capabilities.add("seed_control")
        if "viduq3" in model_id.lower():
            capabilities.add("generate_audio")
    elif endpoint == "v2-video-generations":
        capabilities.add("seed_control")
    elif endpoint == "newapi-video":
        capabilities.add("seed_control")
    return sorted(capabilities)


def _video_capability_fields(capabilities: list[str]) -> dict[str, object]:
    capability_set = set(capabilities)
    supports_service_tier = "flex_tier" in capability_set
    return {
        "capabilities": sorted(capability_set),
        "supports_generate_audio": "generate_audio" in capability_set,
        "supports_seed": "seed_control" in capability_set,
        "supports_service_tier": supports_service_tier,
        "service_tiers": ["default", "flex"] if supports_service_tier else ["default"],
    }


def _recommended_video_continuity_policy(caps: VideoCapabilities) -> str:
    if caps.last_frame:
        return "end_frame"
    if caps.reference_images_with_start_image:
        return "reference_assisted"
    return "start_only"


def _video_continuity_fields(caps: VideoCapabilities) -> dict[str, object]:
    capabilities: list[str] = []
    if caps.first_frame:
        capabilities.append("start_image")
    if caps.last_frame:
        capabilities.append("end_image")
    if caps.reference_images:
        capabilities.append("reference_images")
    if caps.reference_images_with_start_image:
        capabilities.append("reference_images_with_start_image")
    return {
        "supports_start_image": caps.first_frame,
        "supports_end_image": caps.last_frame,
        "supports_reference_images": caps.reference_images,
        "supports_reference_with_start_image": caps.reference_images_with_start_image,
        # Keep raw first/last frame names too, so API consumers can match provider docs directly.
        "supports_first_frame": caps.first_frame,
        "supports_last_frame": caps.last_frame,
        "video_continuity_capabilities": capabilities,
        "recommended_continuity_policy": _recommended_video_continuity_policy(caps),
    }


def _video_caps_for_endpoint(
    endpoint_key: str,
    model_id: str,
    *,
    max_reference_images: int | None,
) -> VideoCapabilities:
    if endpoint_key == "ark-seedance":
        from lib.video_backends.ark import ArkVideoBackend

        return ArkVideoBackend.video_capabilities_for_model(model_id)
    if endpoint_key == "vidu-video":
        from lib.video_backends.vidu import ViduVideoBackend

        return ViduVideoBackend.video_capabilities_for_model(model_id)
    if endpoint_key == "v2-video-generations":
        from lib.video_backends.v2_video_generations import V2VideoGenerationsBackend

        return V2VideoGenerationsBackend.video_capabilities_for_model(model_id)
    if endpoint_key == "dashscope-async-video":
        from lib.video_backends.dashscope import DashScopeVideoBackend

        return DashScopeVideoBackend.video_capabilities_for_model(model_id)
    if endpoint_key == "openai-video":
        return VideoCapabilities(
            reference_images=True,
            max_reference_images=1,
        )
    if endpoint_key == "newapi-video":
        return VideoCapabilities(reference_images=False, max_reference_images=0)
    return VideoCapabilities(
        reference_images=(max_reference_images or 0) > 0,
        max_reference_images=max_reference_images or 0,
    )


def _video_caps_for_provider(provider_id: str, model_id: str) -> VideoCapabilities | None:
    if provider_id in {"gemini-aistudio", "gemini-vertex"}:
        return VideoCapabilities(
            last_frame=True,
            reference_images=True,
            reference_images_with_start_image=True,
            max_reference_images=3,
        )
    if provider_id in {"ark", "ark-agent-plan"}:
        from lib.video_backends.ark import ArkVideoBackend

        return ArkVideoBackend.video_capabilities_for_model(model_id)
    if provider_id == "vidu":
        from lib.video_backends.vidu import ViduVideoBackend

        return ViduVideoBackend.video_capabilities_for_model(model_id)
    if provider_id == "dashscope":
        from lib.video_backends.dashscope import DashScopeVideoBackend

        return DashScopeVideoBackend.video_capabilities_for_model(model_id)
    if provider_id == "openai":
        return VideoCapabilities(
            reference_images=True,
            max_reference_images=1,
        )
    if provider_id == "grok":
        return VideoCapabilities(
            reference_images=True,
            reference_images_with_start_image=True,
            max_reference_images=7,
        )
    if provider_id == "newapi":
        return VideoCapabilities(reference_images=False, max_reference_images=0)
    return None


def _fallback_video_caps(capabilities: list[str], max_reference_images: int | None) -> VideoCapabilities:
    return VideoCapabilities(
        first_frame="image_to_video" in set(capabilities),
        reference_images=(max_reference_images or 0) > 0,
        max_reference_images=max_reference_images or 0,
    )


def _trusted_payload_provider(provider_id: object) -> str | None:
    """仅信任 registry/custom 中存在的 payload provider。"""
    if not isinstance(provider_id, str):
        return None
    provider_id = provider_id.strip()
    if not provider_id:
        return None
    if provider_id in PROVIDER_REGISTRY or is_custom_provider(provider_id):
        return provider_id
    return None


def _payload_model_or_default(raw_model: object, provider_id: str, media_type: str) -> str | None:
    """payload 显式 model 优先；缺失时补 registry 默认 model。"""
    if isinstance(raw_model, str) and raw_model.strip():
        return raw_model.strip()
    return _default_model_for_provider(provider_id, media_type)


_TEXT_TASK_SETTING_KEYS: dict[TextTaskType, str] = {
    TextTaskType.SCRIPT: "text_backend_script",
    TextTaskType.OVERVIEW: "text_backend_overview",
    TextTaskType.STYLE_ANALYSIS: "text_backend_style",
}


class ConfigResolver:
    """运行时配置解析器。

    作为 ConfigService 的上层薄封装，提供：
    - 唯一的默认值定义点
    - 类型化输出（bool / tuple / dict）
    - 内置优先级解析（全局配置 → 项目级覆盖）
    """

    # ── 唯一的默认值定义点 ──
    # 与 Seedance / Grok 默认开启、storyboard 用户期望一致。
    # server/routers/system_config.py 与 lib/media_generator.py 均通过引用此常量读取。
    _DEFAULT_VIDEO_GENERATE_AUDIO = True

    def __init__(
        self,
        session_factory: async_sessionmaker,
        *,
        _bound_session: AsyncSession | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._bound_session = _bound_session

    # ── Session 管理 ──

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ConfigResolver]:
        """打开共享 session，返回绑定到该 session 的 ConfigResolver。"""
        if self._bound_session is not None:
            yield self
        else:
            async with self._session_factory() as sess:
                yield ConfigResolver(self._session_factory, _bound_session=sess)

    @asynccontextmanager
    async def _open_session(self) -> AsyncIterator[tuple[AsyncSession, ConfigService]]:
        """获取 (session, ConfigService)，优先复用 bound session。"""
        if self._bound_session is not None:
            yield self._bound_session, ConfigService(self._bound_session)
        else:
            async with self._session_factory() as session:
                yield session, ConfigService(session)

    # ── 公开 API ──

    async def video_generate_audio(self, project_name: str | None = None) -> bool:
        """解析 video_generate_audio。

        优先级：项目级覆盖 > 全局配置 > 默认值(True)。
        """
        async with self._open_session() as (session, svc):
            return await self._resolve_video_generate_audio(svc, project_name)

    async def default_video_backend(self) -> tuple[str, str]:
        """返回系统级默认 (provider_id, model_id)（不含项目级覆盖）。"""
        async with self._open_session() as (session, svc):
            return await self._resolve_default_video_backend(svc, session)

    async def video_backend(self, project_name: str | None = None) -> tuple[str, str]:
        """解析当前项目应使用的视频 (provider_id, model_id)。

        优先级：项目级 `project.json.video_backend` > 系统设置 `default_video_backend` >
        系统默认 `_DEFAULT_VIDEO_BACKEND` > auto-resolve（按 registry 顺序挑第一个 ready）。
        """
        async with self._open_session() as (session, svc):
            return await self._resolve_video_backend(svc, session, project_name)

    async def resolve_image_backend(
        self,
        project: dict | None,
        payload: dict | None,
        *,
        capability: Literal["t2i", "i2i"],
    ) -> ProviderModel:
        """解析图片任务实际使用的 provider/model。

        优先级：payload > project 的 image_provider_<capability> > 全局默认。
        """
        async with self._open_session() as (session, svc):
            return await self._resolve_image_provider_model(svc, session, project, payload, capability)

    async def resolve_video_backend(
        self,
        project: dict | None,
        payload: dict | None,
    ) -> ProviderModel:
        """解析视频任务实际使用的 provider/model。

        优先级：payload > project 的 video_backend > 全局默认。
        """
        async with self._open_session() as (session, svc):
            return await self._resolve_video_provider_model(svc, session, project, payload)

    async def video_capabilities(self, project_name: str | None = None) -> dict:
        """解析当前项目视频 model 的综合能力 + 用户项目偏好。

        Returns:
            {
              "provider_id": str,
              "model": str,
              "supported_durations": list[int],    # 来自 model (单一真相源)
              "max_duration": int,                 # max(supported_durations) 派生
              "max_reference_images": int | None,  # model/endpoint 粒度；None 表示未知，不做硬裁剪
              "source": "registry" | "custom",
              "default_duration": int | None,      # 用户在 project.json 里设置的偏好
              "content_mode": str | None,
              "generation_mode": str | None,
            }

        Raises:
            ValueError: 当 video_backend 解析失败 / model 找不到 / supported_durations 为空。
        """
        async with self._open_session() as (session, svc):
            return await self._resolve_video_capabilities(svc, session, project_name)

    async def video_capabilities_for_project(self, project: dict) -> dict:
        """同 `video_capabilities`，但使用调用方已加载的 project dict。

        优先用此变体，可避免按名称二次加载、也不依赖 `PROJECT_ROOT/projects/<name>` 目录结构
        （例如 `ScriptGenerator` 在非标准路径实例化、或测试用 tmp_path 时，防止目录名
        与全局项目碰撞读到错误能力）。
        """
        async with self._open_session() as (session, svc):
            return await self._resolve_video_capabilities_from_project(svc, session, project)

    async def video_capabilities_for_model(self, provider_id: str, model_id: str, project: dict | None = None) -> dict:
        """读取指定 provider/model 的视频能力，不再二次解析 provider。"""
        async with self._open_session() as (session, svc):
            return await self._resolve_video_caps_for_model(svc, session, provider_id, model_id, project)

    async def default_image_backend_t2i(self) -> tuple[str, str]:
        """返回 (provider_id, model_id)，T2I 默认。"""
        async with self._open_session() as (session, svc):
            return await self._resolve_default_image_backend(svc, session, "t2i")

    async def default_image_backend_i2i(self) -> tuple[str, str]:
        """返回 (provider_id, model_id)，I2I 默认。"""
        async with self._open_session() as (session, svc):
            return await self._resolve_default_image_backend(svc, session, "i2i")

    async def default_image_backend(self) -> tuple[str, str]:
        """兼容 shim：旧调用方仍可调；返回 T2I 变体。"""
        return await self.default_image_backend_t2i()

    async def provider_config(self, provider_id: str) -> dict[str, str]:
        """获取单个供应商配置。"""
        async with self._open_session() as (session, svc):
            return await self._resolve_provider_config(svc, session, provider_id)

    async def all_provider_configs(self) -> dict[str, dict[str, str]]:
        """批量获取所有供应商配置。"""
        async with self._open_session() as (session, svc):
            return await self._resolve_all_provider_configs(svc, session)

    # ── 内部解析方法（可独立测试，接收已创建的 svc） ──

    async def _resolve_video_generate_audio(
        self,
        svc: ConfigService,
        project_name: str | None,
    ) -> bool:
        raw = await svc.get_setting("video_generate_audio", "")
        value = _parse_bool(raw) if raw else self._DEFAULT_VIDEO_GENERATE_AUDIO

        if project_name:
            project = get_project_manager().load_project(project_name)
            override = project.get("video_generate_audio")
            if override is not None:
                if isinstance(override, str):
                    value = _parse_bool(override)
                else:
                    value = bool(override)

        return value

    async def _resolve_default_video_backend(self, svc: ConfigService, session: AsyncSession) -> tuple[str, str]:
        raw = await svc.get_setting("default_video_backend", "")
        if raw and "/" in raw:
            provider_id, model_id = ConfigService._parse_backend(raw, _DEFAULT_VIDEO_BACKEND)
            if not is_retired_provider_model(provider_id, model_id):
                return provider_id, model_id
            logger.warning("忽略已下线视频模型配置: %s/%s", provider_id, model_id)
        return await self._auto_resolve_backend(svc, session, "video")

    async def _resolve_video_backend(
        self,
        svc: ConfigService,
        session: AsyncSession,
        project_name: str | None,
    ) -> tuple[str, str]:
        """三级解析当前项目应使用的 video backend。

        模式对齐 `_resolve_text_backend`：项目级 > 系统设置 > 系统默认 / auto。
        """
        project = get_project_manager().load_project(project_name) if project_name else None
        return await self._resolve_video_backend_from_project(svc, session, project)

    async def _resolve_video_backend_from_project(
        self,
        svc: ConfigService,
        session: AsyncSession,
        project: dict | None,
    ) -> tuple[str, str]:
        if project is not None:
            parsed = _parse_project_provider(project.get("video_backend"), "video")
            if parsed is not None:
                provider_id, model_id = parsed
                if not is_retired_provider_model(provider_id, model_id):
                    return provider_id, model_id
                logger.warning("忽略项目中的已下线视频模型配置: %s/%s", provider_id, model_id)
        return await self._resolve_default_video_backend(svc, session)

    async def _resolve_image_provider_model(
        self,
        svc: ConfigService,
        session: AsyncSession,
        project: dict | None,
        payload: dict | None,
        capability: Literal["t2i", "i2i"],
    ) -> ProviderModel:
        cap_key = f"image_provider_{capability}"
        if payload:
            pair = _split_pair(payload.get(cap_key))
            if pair is not None and _trusted_payload_provider(pair[0]) is not None:
                return ProviderModel(*pair)
            provider_id = _trusted_payload_provider(payload.get("image_provider"))
            if provider_id is not None:
                model = _payload_model_or_default(payload.get("image_model"), provider_id, "image")
                if model is not None:
                    return ProviderModel(provider_id, model)
        if project:
            parsed = _parse_project_provider(project.get(cap_key), "image")
            if parsed is not None:
                return ProviderModel(*parsed)
        provider_id, model_id = await self._resolve_default_image_backend(svc, session, capability)
        return ProviderModel(provider_id, model_id)

    async def _resolve_video_provider_model(
        self,
        svc: ConfigService,
        session: AsyncSession,
        project: dict | None,
        payload: dict | None,
    ) -> ProviderModel:
        if payload:
            pair = _split_pair(payload.get("video_backend"))
            if pair is not None and _trusted_payload_provider(pair[0]) is not None:
                return ProviderModel(*pair)
            provider_id = _trusted_payload_provider(payload.get("video_provider"))
            if provider_id is not None:
                settings = payload.get("video_provider_settings")
                settings_model = settings.get("model") if isinstance(settings, dict) else None
                model = _payload_model_or_default(payload.get("video_model") or settings_model, provider_id, "video")
                if model is not None:
                    return ProviderModel(provider_id, model)
        provider_id, model_id = await self._resolve_video_backend_from_project(svc, session, project)
        return ProviderModel(provider_id, model_id)

    async def _resolve_video_capabilities(
        self,
        svc: ConfigService,
        session: AsyncSession,
        project_name: str | None,
    ) -> dict:
        """按两步解析：先选 model，再读 model 能力。"""
        project = get_project_manager().load_project(project_name) if project_name else None
        return await self._resolve_video_capabilities_from_project(svc, session, project)

    async def _resolve_video_capabilities_from_project(
        self,
        svc: ConfigService,
        session: AsyncSession,
        project: dict | None,
    ) -> dict:
        provider_id, model_id = await self._resolve_video_backend_from_project(svc, session, project)
        return await self._resolve_video_caps_for_model(svc, session, provider_id, model_id, project)

    async def _resolve_video_caps_for_model(
        self,
        svc: ConfigService,
        session: AsyncSession,
        provider_id: str,
        model_id: str,
        project: dict | None,
    ) -> dict:
        if is_custom_provider(provider_id):
            source = "custom"
            try:
                db_pid = parse_provider_id(provider_id)
            except ValueError as exc:
                raise ValueError(f"invalid custom provider_id: {provider_id}") from exc
            repo = CustomProviderRepository(session)
            model = await repo.get_model_by_ids(db_pid, model_id)
            if model is None:
                raise ValueError(f"custom model not found: {provider_id}/{model_id}")

            endpoint_spec = get_endpoint_spec(model.endpoint)
            if endpoint_spec.media_type != "video":
                raise ValueError(
                    f"endpoint media_type mismatch: {provider_id}/{model_id} endpoint={model.endpoint!r} "
                    f"is {endpoint_spec.media_type}, not video"
                )
            endpoint_key = model.endpoint
            endpoint_family = endpoint_spec.family
            capabilities = _custom_video_capability_strings(model.endpoint, model_id)
            resolutions = [model.resolution] if model.resolution else []
            duration_resolution_constraints: dict[str, list[int]] = {}
            endpoint_cap = endpoint_spec.video_max_reference_images
            if endpoint_cap is not None:
                max_reference_images = endpoint_cap
                video_caps = _video_caps_for_endpoint(
                    endpoint_key,
                    model_id,
                    max_reference_images=endpoint_cap,
                )
            else:
                caps_fn = endpoint_spec.video_caps_for_model
                if caps_fn is None:
                    raise ValueError(
                        f"video endpoint {model.endpoint!r} declares neither video_max_reference_images "
                        f"nor video_caps_for_model: {provider_id}/{model_id}"
                    )
                video_caps = caps_fn(model_id)
                max_reference_images = video_caps.max_reference_images
                if max_reference_images < 0:
                    raise ValueError(
                        f"invalid backend max_reference_images: {provider_id}/{model_id} "
                        f"endpoint={model.endpoint!r} value={max_reference_images!r}"
                    )
            raw_durations = model.supported_durations
            supported_durations: list[int] = []
            if raw_durations:
                try:
                    parsed = json.loads(raw_durations)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"invalid supported_durations JSON on custom model {provider_id}/{model_id}"
                    ) from exc
                if isinstance(parsed, list):
                    supported_durations = [int(d) for d in parsed]
        else:
            source = "registry"
            endpoint_key = None
            endpoint_family = provider_id
            provider_meta = PROVIDER_REGISTRY.get(provider_id)
            if provider_meta is None:
                raise ValueError(f"provider not in PROVIDER_REGISTRY: {provider_id}")
            model_info = provider_meta.models.get(model_id)
            if model_info is None:
                raise ValueError(f"model not found in registry: {provider_id}/{model_id}")
            supported_durations = list(model_info.supported_durations or [])
            capabilities = list(model_info.capabilities or [])
            video_caps = _video_caps_for_provider(provider_id, model_id)
            if video_caps is not None:
                max_reference_images = video_caps.max_reference_images
            else:
                max_reference_images = model_info.max_reference_images
                video_caps = _fallback_video_caps(capabilities, max_reference_images)
            resolutions = list(model_info.resolutions or [])
            duration_resolution_constraints = {
                key: list(value) for key, value in (model_info.duration_resolution_constraints or {}).items()
            }

        if not supported_durations:
            raise ValueError(f"supported_durations is empty for {provider_id}/{model_id}; cannot derive capabilities")

        max_duration = max(supported_durations)

        default_duration: int | None = None
        content_mode: str | None = None
        generation_mode: str | None = None
        if project is not None:
            raw_default = project.get("default_duration")
            if isinstance(raw_default, int):
                default_duration = raw_default
            elif isinstance(raw_default, str) and raw_default.strip().isdigit():
                default_duration = int(raw_default.strip())
            cm = project.get("content_mode")
            if isinstance(cm, str) and cm:
                content_mode = cm
            gm = project.get("generation_mode")
            if isinstance(gm, str) and gm:
                generation_mode = gm

        payload = {
            "provider_id": provider_id,
            "model": model_id,
            "task_kind": "video",
            "supported_durations": supported_durations,
            "max_duration": max_duration,
            "max_reference_images": max_reference_images,
            "resolutions": resolutions,
            "duration_resolution_constraints": duration_resolution_constraints,
            **_video_capability_fields(capabilities),
            **_video_continuity_fields(video_caps),
            "endpoint": endpoint_key,
            "endpoint_family": endpoint_family,
            "source": source,
            "default_duration": default_duration,
            "content_mode": content_mode,
            "generation_mode": generation_mode,
        }
        payload["constraints"] = {
            "supported_aspect_ratios": ["9:16", "16:9", "1:1", "4:3", "3:4"],
            "supported_durations": supported_durations,
            "max_reference_images": max_reference_images,
            "supported_resolutions": resolutions,
            "duration_resolution_constraints": duration_resolution_constraints,
            "supports_native_audio": bool(payload.get("supports_generate_audio")),
        }
        payload["provider_capability_profile"] = provider_capability_profile(payload)
        payload["provider_capability_hash"] = provider_capability_hash(payload)
        if project is not None:
            ensure_project_script_splitting_snapshot(project, provider_capabilities=payload)
            profile = project.get("script_splitting", {}).get("resolved_profile")
            if isinstance(profile, dict):
                payload["script_splitting_template_id"] = profile.get("id")
                payload["script_splitting_hash"] = profile.get("hash")
                payload["provider_compatibility"] = check_provider_compatibility(profile, payload)
        return payload

    async def _resolve_default_image_backend(
        self, svc: ConfigService, session: AsyncSession, capability: Literal["t2i", "i2i"] = "t2i"
    ) -> tuple[str, str]:
        """优先读 default_image_backend_<cap>；新 key **不存在**才回退旧 default_image_backend；都缺则自动解析。

        新 key 存在但值为空字符串 = 用户显式清空 = 跟随自动选择，不再回退 legacy。
        一次 get_all_settings 把候选 key 都拿到，避免迁移期 / 未配置场景两次串行 DB 查询。
        """
        settings = await svc.get_all_settings()
        cap_key = f"default_image_backend_{capability}"
        if cap_key in settings:
            raw = settings[cap_key]
        else:
            raw = settings.get("default_image_backend", "")
        if "/" in raw:
            return ConfigService._parse_backend(raw, _DEFAULT_IMAGE_BACKEND)
        return await self._auto_resolve_backend(svc, session, "image")

    async def _resolve_provider_config(
        self,
        svc: ConfigService,
        session: AsyncSession,
        provider_id: str,
    ) -> dict[str, str]:
        config = await svc.get_provider_config(provider_id)
        cred_repo = CredentialRepository(session)
        active = await cred_repo.get_active(provider_id)
        if active:
            active.overlay_config(config)
        return config

    async def _resolve_all_provider_configs(
        self,
        svc: ConfigService,
        session: AsyncSession,
    ) -> dict[str, dict[str, str]]:
        configs = await svc.get_all_provider_configs()
        cred_repo = CredentialRepository(session)
        active_creds = await cred_repo.get_active_credentials_bulk()
        for provider_id, cred in active_creds.items():
            cfg = configs.setdefault(provider_id, {})
            cred.overlay_config(cfg)
        return configs

    async def default_text_backend(self) -> tuple[str, str]:
        """返回 (provider_id, model_id)。"""
        async with self._open_session() as (session, svc):
            return await svc.get_default_text_backend()

    async def text_backend_for_task(
        self,
        task_type: TextTaskType,
        project_name: str | None = None,
    ) -> tuple[str, str]:
        """解析文本 backend。优先级：项目级任务配置 → 全局任务配置 → 全局默认 → 自动推断"""
        async with self._open_session() as (session, svc):
            return await self._resolve_text_backend(svc, session, task_type, project_name)

    async def _resolve_text_backend(
        self,
        svc: ConfigService,
        session: AsyncSession,
        task_type: TextTaskType,
        project_name: str | None,
    ) -> tuple[str, str]:
        setting_key = _TEXT_TASK_SETTING_KEYS[task_type]

        # 1. Project-level task override
        if project_name:
            project = get_project_manager().load_project(project_name)
            project_val = project.get(setting_key)
            if project_val and "/" in str(project_val):
                return ConfigService._parse_backend(str(project_val), _DEFAULT_TEXT_BACKEND)

        # 2. Global task-type setting
        task_val = await svc.get_setting(setting_key, "")
        if task_val and "/" in task_val:
            return ConfigService._parse_backend(task_val, _DEFAULT_TEXT_BACKEND)

        # 3. Global default text backend
        default_val = await svc.get_setting("default_text_backend", "")
        if default_val and "/" in default_val:
            return ConfigService._parse_backend(default_val, _DEFAULT_TEXT_BACKEND)

        # 4. Auto-resolve
        return await self._auto_resolve_backend(svc, session, "text")

    async def _auto_resolve_backend(
        self,
        svc: ConfigService,
        session: AsyncSession,
        media_type: str,
    ) -> tuple[str, str]:
        """遍历 PROVIDER_REGISTRY（按注册顺序），找到第一个 ready 且支持该 media_type 的供应商。"""
        statuses = await svc.get_all_providers_status()
        ready = {s.name for s in statuses if s.status == "ready"}

        for provider_id, meta in PROVIDER_REGISTRY.items():
            if provider_id not in ready:
                continue
            for model_id, model_info in meta.models.items():
                if model_info.media_type == media_type and model_info.default:
                    return provider_id, model_id

        from lib.custom_provider import make_provider_id
        from lib.db.repositories.custom_provider_repo import CustomProviderRepository

        repo = CustomProviderRepository(session)
        custom_models = await repo.list_enabled_models_by_media_type(media_type)
        for model in custom_models:
            if model.is_default:
                return make_provider_id(model.provider_id), model.model_id

        raise ValueError(f"未找到可用的 {media_type} 供应商。请在「全局设置 → 供应商」页面配置至少一个供应商。")

"""OpenAIVideoBackend — OpenAI Sora 视频生成后端。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from lib.aspect_size import VIDEO_TIER_SHORT_EDGE, parse_aspect_ratio, resolution_to_short_edge
from lib.image_utils import prepare_provider_image_bytes
from lib.logging_utils import format_kwargs_for_log
from lib.openai_shared import OPENAI_RETRYABLE_ERRORS, create_openai_client
from lib.providers import PROVIDER_OPENAI
from lib.retry import DOWNLOAD_BACKOFF_SECONDS, DOWNLOAD_MAX_ATTEMPTS, with_retry_async
from lib.video_backends.base import (
    ResumeExpiredError,
    VideoCapabilities,
    VideoCapability,
    VideoGenerationRequest,
    VideoGenerationResult,
    persist_provider_job_id,
    poll_with_retry,
)

_POLL_INTERVAL_SECONDS = 5.0
_MIN_POLL_TIMEOUT_SECONDS = 600.0
_POLL_TIMEOUT_PER_SECOND = 30.0

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sora-2"

_SORA_SIZES_720P: tuple[str, ...] = ("720x1280", "1280x720")
_SORA_SIZES_1024P: tuple[str, ...] = ("1024x1792", "1792x1024")
_SORA_SIZES_1080P: tuple[str, ...] = ("1080x1920", "1920x1080")
_SORA_LEGAL_SIZES: tuple[str, ...] = _SORA_SIZES_720P + _SORA_SIZES_1024P + _SORA_SIZES_1080P
_SORA_1024P_MIN_SHORT = 1024
_SORA_1080P_MIN_SHORT = 1080


def _resolve_size(model: str, resolution: str | None, aspect_ratio: str) -> str:
    """在 model+分辨率档支持的 Sora 合法尺寸中，选择最接近项目比例的一档。"""
    aw, ah = parse_aspect_ratio(aspect_ratio)
    target = aw / ah
    is_pro = "pro" in model.lower()
    short = resolution_to_short_edge(resolution, tier_map=VIDEO_TIER_SHORT_EDGE)
    supported_shorts = [720, _SORA_1024P_MIN_SHORT, _SORA_1080P_MIN_SHORT] if is_pro else [720]
    achieved_short = min(supported_shorts, key=lambda s: (abs(s - short), -s))
    if achieved_short == _SORA_1080P_MIN_SHORT:
        legal = _SORA_SIZES_1080P
    elif achieved_short == _SORA_1024P_MIN_SHORT:
        legal = _SORA_SIZES_1024P
    else:
        legal = _SORA_SIZES_720P
    if short > achieved_short:
        logger.warning(
            "OpenAI video: model=%s 无法满足分辨率请求 %s（短边 %d），输出封顶到 %dp 档",
            model,
            resolution,
            short,
            achieved_short,
        )

    def _score(size: str) -> tuple[float, int]:
        w, h = (int(x) for x in size.split("x"))
        return abs(w / h - target), -(w * h)

    chosen = min(legal, key=_score)
    cw, ch = (int(x) for x in chosen.split("x"))
    if abs(cw / ch - target) > 0.01:
        logger.warning(
            "OpenAI video: aspect_ratio=%s 无精确 sora 档，吸附到 %s（比例偏差，输出非项目设定比例）",
            aspect_ratio,
            chosen,
        )
    assert chosen in _SORA_LEGAL_SIZES, f"_resolve_size produced illegal sora size: {chosen}"
    return chosen


class OpenAIVideoBackend:
    """OpenAI Sora 视频生成后端。"""

    def __init__(self, *, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        self._client = create_openai_client(api_key=api_key, base_url=base_url)
        self._model = model or DEFAULT_MODEL
        self._capabilities: set[VideoCapability] = {
            VideoCapability.TEXT_TO_VIDEO,
            VideoCapability.IMAGE_TO_VIDEO,
        }

    @property
    def name(self) -> str:
        return PROVIDER_OPENAI

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[VideoCapability]:
        return self._capabilities

    @property
    def video_capabilities(self) -> VideoCapabilities:
        return VideoCapabilities(
            reference_images=True,
            max_reference_images=1,
        )

    async def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        kwargs: dict = {
            "prompt": request.prompt,
            "model": self._model,
            "seconds": str(request.duration_seconds),
        }
        kwargs["size"] = _resolve_size(self._model, request.resolution, request.aspect_ratio)

        input_reference = _resolve_input_reference(request)
        if input_reference is not None:
            kwargs["input_reference"] = input_reference

        logger.info("OpenAI 视频生成开始: model=%s, seconds=%s", self._model, kwargs["seconds"])
        logger.info("调用 %s 视频 SDK kwargs=%s", self.name, format_kwargs_for_log(kwargs))

        video = await self._create_video(**kwargs)
        if request.task_id is not None:
            await persist_provider_job_id(request.task_id, video.id, provider=PROVIDER_OPENAI)
        final = await self._poll_until_complete(video.id, request.duration_seconds)
        if final.status == "expired":
            raise RuntimeError(f"OpenAI Sora job expired during generate: {final.id}")

        return await self._download_and_build_result(final, request, kwargs)

    async def resume_video(self, job_id: str, request: VideoGenerationRequest) -> VideoGenerationResult:
        """Resume a submitted OpenAI job by polling and downloading only."""
        try:
            final = await self._poll_until_complete(job_id, request.duration_seconds)
        except Exception as exc:
            if _is_openai_not_found(exc):
                raise ResumeExpiredError(job_id=job_id, provider=PROVIDER_OPENAI) from exc
            raise
        if final.status == "expired":
            raise ResumeExpiredError(
                job_id=job_id,
                provider=PROVIDER_OPENAI,
                message=f"OpenAI Sora job expired: {final.id}",
            )
        return await self._download_and_build_result(final, request, {"seconds": str(request.duration_seconds)})

    async def _download_and_build_result(
        self, final, request: VideoGenerationRequest, kwargs: dict
    ) -> VideoGenerationResult:
        content = await self._download_content_with_retry(final.id)

        def _write():
            request.output_path.parent.mkdir(parents=True, exist_ok=True)
            request.output_path.write_bytes(content.content)

        await asyncio.to_thread(_write)

        logger.info("OpenAI 视频下载完成: %s", request.output_path)

        return VideoGenerationResult(
            video_path=request.output_path,
            provider=PROVIDER_OPENAI,
            model=self._model,
            duration_seconds=int(
                final.seconds if final.seconds is not None else kwargs.get("seconds") or request.duration_seconds
            ),
            task_id=final.id,
        )

    @with_retry_async(retryable_errors=OPENAI_RETRYABLE_ERRORS)
    async def _create_video(self, **kwargs):
        """仅创建视频任务（带重试）；轮询交由 _poll_until_complete 自管。"""
        return await self._client.videos.create(**kwargs)

    async def _poll_until_complete(self, video_id: str, duration_seconds: int):
        """轮询任务直到 status=='completed'。

        不复用 SDK 的 client.videos.poll：它仅识别 in_progress/queued/completed/failed，
        对接返回非标状态（如 NOT_START）的 OpenAI 兼容网关时会提前退出，导致下载未就绪任务。
        """
        max_wait = max(_MIN_POLL_TIMEOUT_SECONDS, float(duration_seconds) * _POLL_TIMEOUT_PER_SECOND)

        return await poll_with_retry(
            poll_fn=lambda: self._client.videos.retrieve(video_id),
            is_done=lambda v: v.status in ("completed", "failed", "expired"),
            is_failed=lambda v: f"Sora 视频生成失败: {getattr(v, 'error', None)}" if v.status == "failed" else None,
            poll_interval=_POLL_INTERVAL_SECONDS,
            max_wait=max_wait,
            retryable_errors=OPENAI_RETRYABLE_ERRORS,
            label="OpenAI",
            on_progress=lambda v, elapsed: logger.info(
                "OpenAI 视频生成中... 状态: %s, 已等待 %d 秒", v.status, int(elapsed)
            ),
        )

    @with_retry_async(
        max_attempts=DOWNLOAD_MAX_ATTEMPTS,
        backoff_seconds=DOWNLOAD_BACKOFF_SECONDS,
        retryable_errors=OPENAI_RETRYABLE_ERRORS,
    )
    async def _download_content_with_retry(self, video_id: str):
        """单独重试内容下载，避免因下载失败重新触发视频生成。"""
        return await self._client.videos.download_content(video_id)


def _encode_start_image(
    image_path: Path,
    *,
    max_long_edge: int = 2048,
    jpeg_quality: int = 92,
) -> tuple[str, bytes, str]:
    prepared = prepare_provider_image_bytes(
        image_path,
        purpose="openai-video-input",
        max_long_edge=max_long_edge,
        jpeg_quality=jpeg_quality,
    )
    suffix = ".png" if prepared.prepared_mime == "image/png" else ".jpg"
    return (image_path.with_suffix(suffix).name, prepared.data, prepared.prepared_mime)


def _resolve_input_reference(request: VideoGenerationRequest) -> tuple[str, bytes, str] | None:
    """OpenAI Sora accepts one input_reference; prefer the start image when present."""
    if request.start_image and Path(request.start_image).exists():
        if request.reference_images:
            logger.info("OpenAI video: ignoring reference_images because input_reference is already start_image")
        return _encode_start_image(
            Path(request.start_image),
            max_long_edge=request.provider_input_max_long_edge,
            jpeg_quality=request.provider_input_jpeg_quality,
        )

    if not request.reference_images:
        return None

    existing_refs: list[Path] = []
    for ref_path in request.reference_images:
        path = ref_path if isinstance(ref_path, Path) else Path(ref_path)
        if path.exists():
            existing_refs.append(path)
    if not existing_refs:
        return None
    if len(existing_refs) > 1:
        logger.info(
            "OpenAI video: ignoring %d extra reference_images; Sora accepts one input_reference",
            len(existing_refs) - 1,
        )
    return _encode_start_image(
        existing_refs[0],
        max_long_edge=request.provider_input_max_long_edge,
        jpeg_quality=request.provider_input_jpeg_quality,
    )


def _is_openai_not_found(exc: BaseException) -> bool:
    """Detect OpenAI/Sora job missing responses."""
    try:
        from openai import NotFoundError  # pyright: ignore[reportMissingImports]
    except ImportError:
        NotFoundError = None  # noqa: N806

    if NotFoundError is not None and isinstance(exc, NotFoundError):
        return True
    status_code = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    return status_code == 404

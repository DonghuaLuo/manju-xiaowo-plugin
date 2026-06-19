"""OpenAIImageBackend — OpenAI 图片生成后端。"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Literal

from lib.aspect_size import IMAGE_TIER_SHORT_EDGE, aspect_size, resolution_to_short_edge
from lib.image_backends.base import (
    ImageCapability,
    ImageCapabilityError,
    ImageGenerationRequest,
    ImageGenerationResult,
    save_image_from_response_item,
)
from lib.image_utils import prepare_provider_image
from lib.logging_utils import format_kwargs_for_log
from lib.openai_shared import (
    OPENAI_IMAGE_QUALITY_MAP as _QUALITY_MAP,
)
from lib.openai_shared import (
    OPENAI_RETRYABLE_ERRORS,
    create_openai_client,
)
from lib.providers import PROVIDER_OPENAI
from lib.retry import with_retry_async

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-image-2"
_MAX_REFERENCE_IMAGES = 16
ImageBackendMode = Literal["both", "generations_only", "edits_only"]

_GPT_IMAGE_MAX_LONG_EDGE = 3840
_GPT_IMAGE_MAX_TOTAL_PIXELS = 8_294_400
_GPT_IMAGE_STABLE_LONG_EDGE = 2560
_GPT_IMAGE_MAX_RATIO = 3.0

_QUALITY_MAP_CI = {k.lower(): v for k, v in _QUALITY_MAP.items()}


def _quality_for(image_size: str | None) -> str | None:
    return _QUALITY_MAP_CI.get(image_size.strip().lower()) if image_size else None


def _resolve_openai_params(
    image_size: str | None,
    aspect_ratio: str,
) -> dict[str, str]:
    """按「比例优先、清晰度其次」算出 {size, quality}。"""
    short = resolution_to_short_edge(image_size, tier_map=IMAGE_TIER_SHORT_EDGE)
    w, h = aspect_size(
        aspect_ratio,
        short,
        round_to=16,
        max_long_edge=_GPT_IMAGE_MAX_LONG_EDGE,
        max_total_pixels=_GPT_IMAGE_MAX_TOTAL_PIXELS,
        max_ratio=_GPT_IMAGE_MAX_RATIO,
    )
    if max(w, h) > _GPT_IMAGE_STABLE_LONG_EDGE:
        logger.warning(
            "OpenAI image: 尺寸 %dx%d 长边超过稳定区 %d，进入实验性高分辨率区间",
            w,
            h,
            _GPT_IMAGE_STABLE_LONG_EDGE,
        )
    params: dict[str, str] = {"size": f"{w}x{h}"}
    quality = _quality_for(image_size)
    if quality:
        params["quality"] = quality
    return params


def _openai_output_format(output_format: str | None) -> str | None:
    if not output_format:
        return None
    fmt = output_format.strip().lower()
    if fmt == "jpg":
        return "jpeg"
    return fmt if fmt in {"png", "jpeg", "webp"} else None


class OpenAIImageBackend:
    """OpenAI 图片生成后端，按 mode 决定支持 T2I / I2I / 两者。"""

    _MODE_TO_CAPS: dict[str, set[ImageCapability]] = {
        "both": {ImageCapability.TEXT_TO_IMAGE, ImageCapability.IMAGE_TO_IMAGE},
        "generations_only": {ImageCapability.TEXT_TO_IMAGE},
        "edits_only": {ImageCapability.IMAGE_TO_IMAGE},
    }

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        mode: ImageBackendMode = "both",
    ):
        self._client = create_openai_client(api_key=api_key, base_url=base_url)
        self._model = model or DEFAULT_MODEL
        self._capabilities = set(self._MODE_TO_CAPS[mode])

    @property
    def name(self) -> str:
        return PROVIDER_OPENAI

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[ImageCapability]:
        return self._capabilities

    @with_retry_async(retryable_errors=OPENAI_RETRYABLE_ERRORS)
    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        has_refs = bool(request.reference_images)
        if has_refs and ImageCapability.IMAGE_TO_IMAGE not in self._capabilities:
            raise ImageCapabilityError("image_endpoint_mismatch_no_i2i", model=self._model)
        if not has_refs and ImageCapability.TEXT_TO_IMAGE not in self._capabilities:
            raise ImageCapabilityError("image_endpoint_mismatch_no_t2i", model=self._model)
        return await (self._generate_edit(request) if has_refs else self._generate_create(request))

    async def _generate_create(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        kwargs = {
            "model": self._model,
            "prompt": request.prompt,
            "n": 1,
        }
        kwargs.update(_resolve_openai_params(request.image_size, request.aspect_ratio))
        if output_format := _openai_output_format(request.output_format):
            kwargs["output_format"] = output_format
        logger.info("调用 %s 图片 SDK (T2I) kwargs=%s", self.name, format_kwargs_for_log(kwargs))
        response = await self._client.images.generate(**kwargs)
        return await self._save_and_return(response, request)

    async def _generate_edit(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        refs = request.reference_images
        if len(refs) > _MAX_REFERENCE_IMAGES:
            raise ImageCapabilityError(
                "image_reference_images_too_many",
                model=self._model,
                count=len(refs),
                max_reference_images=_MAX_REFERENCE_IMAGES,
            )

        def _open_refs() -> tuple[ExitStack, list, list[Path]]:
            """在 ExitStack 内打开所有参考图，保证部分 open 失败时已打开句柄被释放。"""
            stack = ExitStack()
            prepared_paths: list[Path] = []
            try:
                files = []
                temp_dir = (
                    Path(tempfile.gettempdir())
                    / "manju-provider-inputs"
                    / (request.project_name or "standalone")
                    / "openai-image"
                )
                for ref in refs:
                    ref_path = Path(ref.path)
                    try:
                        if not request.reference_images_prepared:
                            prepared = prepare_provider_image(
                                ref_path,
                                purpose="openai-image-reference",
                                temp_dir=temp_dir,
                            )
                            ref_path = prepared.path
                            prepared_paths.append(prepared.path)
                        files.append(stack.enter_context(open(ref_path, "rb")))
                    except FileNotFoundError:
                        logger.warning("参考图不存在，跳过: %s", ref_path)
                # 把已打开的句柄所有权移交给调用者
                return stack.pop_all(), files, prepared_paths
            except BaseException:
                stack.close()
                for path in prepared_paths:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("清理 OpenAI 图片参考图临时文件失败: %s", path, exc_info=True)
                raise

        stack, image_files, prepared_paths = await asyncio.to_thread(_open_refs)
        try:
            if not image_files:
                # 旧版会回退到 T2I；新语义下若所有 ref 图都打不开，抛错而非降级
                # （等价于用户提交了 i2i 请求但没有有效素材，应该是错误而非默默 fallback）
                raise ImageCapabilityError(
                    "image_endpoint_mismatch_no_i2i",
                    model=self._model,
                    detail="all reference images failed to open",
                )
            edit_kwargs: dict = {
                "model": self._model,
                "image": image_files,
                "prompt": request.prompt,
            }
            edit_kwargs.update(_resolve_openai_params(request.image_size, request.aspect_ratio))
            if output_format := _openai_output_format(request.output_format):
                edit_kwargs["output_format"] = output_format
            logger.info(
                "调用 %s 图片 SDK (I2I) kwargs=%s",
                self.name,
                format_kwargs_for_log({**edit_kwargs, "image": f"<{len(image_files)} files>"}),
            )
            response = await self._client.images.edit(**edit_kwargs)
        finally:
            stack.close()
            for path in prepared_paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("清理 OpenAI 图片参考图临时文件失败: %s", path, exc_info=True)
        return await self._save_and_return(response, request)

    async def _save_and_return(self, response, request: ImageGenerationRequest) -> ImageGenerationResult:
        data = getattr(response, "data", None) or []
        if not data:
            # 空 data 通常是内容安全过滤命中或上游网关异常，给出清晰错误便于排查
            raise RuntimeError(
                f"OpenAI 图片生成响应 data 为空 (model={self._model})，可能触发内容安全过滤或上游服务异常"
            )
        image_path = await save_image_from_response_item(data[0], request.output_path)
        logger.info("OpenAI 图片生成完成: %s", image_path)
        quality = _quality_for(request.image_size)

        img_in = img_out = txt_in = txt_out = None
        usage = getattr(response, "usage", None)
        if usage is not None:
            try:
                in_details = getattr(usage, "input_tokens_details", None)
                # 必须拿到 input 拆分（image_tokens / text_tokens 至少一项有值），否则保留 None
                # 让 cost_calculator 走静态 fallback，避免部分字段缺失场景下漏算 input 费用
                in_image = getattr(in_details, "image_tokens", None) if in_details is not None else None
                in_text = getattr(in_details, "text_tokens", None) if in_details is not None else None
                if in_image is not None or in_text is not None:
                    img_in = in_image
                    txt_in = in_text
                    out_details = getattr(usage, "output_tokens_details", None)
                    if out_details is not None:
                        img_out = getattr(out_details, "image_tokens", None)
                        txt_out = getattr(out_details, "text_tokens", None)
                    if img_out is None:
                        # 部分模型只在顶层暴露 output_tokens（GPT Image 输出基本为 image token）
                        img_out = getattr(usage, "output_tokens", None)
                    # 输入拆分到手但输出完全拿不到 → 数据残缺，撤回让上层走静态 fallback
                    if img_out is None and txt_out is None:
                        img_in = txt_in = None
            except Exception:
                logger.warning("OpenAI image usage 解析失败", exc_info=True)
                img_in = img_out = txt_in = txt_out = None

        return ImageGenerationResult(
            image_path=image_path,
            provider=PROVIDER_OPENAI,
            model=self._model,
            quality=quality,
            image_input_tokens=img_in,
            image_output_tokens=img_out,
            text_input_tokens=txt_in,
            text_output_tokens=txt_out,
        )

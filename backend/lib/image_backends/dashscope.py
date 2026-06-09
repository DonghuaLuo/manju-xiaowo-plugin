"""DashScopeImageBackend — 阿里百炼 Qwen-Image / 万相图像生成后端（同步）。

走原生 multimodal-generation/generation 同步端点，T2I 与 I2I 共用同一请求体，
只差 content 是否含 image 元素。覆盖 qwen-image-2.0 融合系列、qwen-image-edit
编辑系列与 wan2.7-image 系列。schema 依据 docs/dashscope-docs/ 一手核实快照。
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from lib.aspect_size import IMAGE_TIER_SHORT_EDGE, aspect_size, resolution_to_short_edge
from lib.dashscope_shared import (
    DASHSCOPE_RETRYABLE_ERRORS,
    dashscope_headers,
    dashscope_native_base_url,
    extract_image_url,
    image_to_data_uri,
    resolve_dashscope_api_key,
    safe_body_for_log,
)
from lib.image_backends.base import (
    ImageCapability,
    ImageCapabilityError,
    ImageGenerationRequest,
    ImageGenerationResult,
    download_image_to_path,
)
from lib.logging_utils import format_kwargs_for_log
from lib.providers import PROVIDER_DASHSCOPE
from lib.retry import with_retry_async

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen-image-2.0"

_IMAGE_ENDPOINT = "/services/aigc/multimodal-generation/generation"

# 编辑系列仅图生图（无文生图能力）；子串覆盖 qwen-image-edit / -edit-plus / -edit-max
_I2I_ONLY_MARKERS = ("qwen-image-edit",)

# 参考图上限：qwen 系 1~3 张、wan 系 0~9 张（docs 确权）
_QWEN_REF_LIMIT = 3
_WAN_REF_LIMIT = 9

_DEFAULT_WAN_BUDGET = "2K"
_DEFAULT_SHORT_FUSION = 2048
_DEFAULT_SHORT_WAN = 1440
_DEFAULT_SHORT_EDIT = 2048

# 标准档总像素预算（非 pro / 非文生图上限）= 2048×2048；超出须 wan2.7-image-pro 文生图（4K=4096×4096）
_STANDARD_PIXEL_BUDGET = 2048 * 2048
_FOURK_PIXEL_BUDGET = 4096 * 4096
_EDIT_MAX_LONG_EDGE = 2048
_DASHSCOPE_MAX_RATIO = 8.0
_EDIT_MAX_RATIO = 4.0


class DashScopeImageBackend:
    """阿里百炼图像后端（同步 multimodal 端点）。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        http_timeout: float = 120.0,
    ) -> None:
        self._api_key = resolve_dashscope_api_key(api_key)
        self._base_url = dashscope_native_base_url(base_url)
        self._model = model or DEFAULT_MODEL
        self._http_timeout = http_timeout
        mid = self._model.lower()
        self._is_wan = mid.startswith("wan")
        self._is_edit = "qwen-image-edit" in mid
        self._capabilities = self._resolve_caps(self._model)

    @staticmethod
    def _resolve_caps(model: str) -> set[ImageCapability]:
        mid = model.lower()
        if any(marker in mid for marker in _I2I_ONLY_MARKERS):
            return {ImageCapability.IMAGE_TO_IMAGE}
        return {ImageCapability.TEXT_TO_IMAGE, ImageCapability.IMAGE_TO_IMAGE}

    @staticmethod
    def _exceeds_standard_budget(size: str) -> bool:
        """size 是否超出标准档总像素预算（2048×2048）。

        docs 口径：超出 2048×2048 的输出仅 wan2.7-image-pro 文生图支持（4K 档=4096×4096）。
        档位 "1K"/"2K" 在预算内、"4K" 超预算；像素值按"总像素 > 预算"判定，避免只认 "4K"
        字面而让 "4096*4096" / "3000*3000" 等数字写法绕过门控（这是按比例算总像素，
        故 "4096*512" 这类窄幅合法尺寸不会被误拒）。
        """
        normalized = size.strip().upper()
        if normalized in ("1K", "2K"):
            return False
        if normalized == "4K":
            return True
        for sep in ("*", "X", "×"):
            if sep in normalized:
                parts = normalized.split(sep, 1)
                try:
                    return int(parts[0]) * int(parts[1]) > _STANDARD_PIXEL_BUDGET
                except ValueError:
                    return False
        return False

    @property
    def name(self) -> str:
        return PROVIDER_DASHSCOPE

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[ImageCapability]:
        return self._capabilities

    @property
    def _ref_limit(self) -> int:
        return _WAN_REF_LIMIT if self._is_wan else _QWEN_REF_LIMIT

    @with_retry_async(retryable_errors=DASHSCOPE_RETRYABLE_ERRORS)
    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        has_refs = bool(request.reference_images)
        if has_refs and ImageCapability.IMAGE_TO_IMAGE not in self._capabilities:
            raise ImageCapabilityError("image_endpoint_mismatch_no_i2i", model=self._model)
        if not has_refs and ImageCapability.TEXT_TO_IMAGE not in self._capabilities:
            raise ImageCapabilityError("image_endpoint_mismatch_no_t2i", model=self._model)

        size = self._resolve_size(request, has_refs)
        content = self._build_content(request, has_refs)

        parameters: dict = {
            "n": 1,
            "watermark": False,
            # ArcReel 剧本 prompt 已是 LLM 精炼描述，关闭智能改写保留原意
            "prompt_extend": False,
            "size": size,
        }
        if request.seed is not None:
            parameters["seed"] = request.seed

        payload = {
            "model": self._model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": parameters,
        }

        logger.info(
            "调用 %s 图片 API model=%s body=%s",
            self.name,
            self._model,
            format_kwargs_for_log(safe_body_for_log(payload)),
        )
        async with httpx.AsyncClient(timeout=self._http_timeout) as client:
            resp = await client.post(
                f"{self._base_url}{_IMAGE_ENDPOINT}",
                json=payload,
                headers=dashscope_headers(self._api_key),
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"DashScope 图像接口返回 {resp.status_code}: {resp.text[:500]}")
            data = resp.json()

        url = extract_image_url(data)
        image_path = await download_image_to_path(url, request.output_path)
        logger.info("DashScope 图片生成完成: %s", image_path)

        return ImageGenerationResult(
            image_path=image_path,
            provider=PROVIDER_DASHSCOPE,
            model=self._model,
            image_uri=url,
        )

    def _resolve_size(self, request: ImageGenerationRequest, has_refs: bool) -> str:
        """比例来自项目 aspect_ratio；image_size 只贡献清晰度短边。"""
        explicit = (request.image_size or "").strip()
        aspect = request.aspect_ratio

        if self._is_wan:
            budget_word = explicit or _DEFAULT_WAN_BUDGET
            exceeds = self._exceeds_standard_budget(budget_word)
            if exceeds and ("pro" not in self._model.lower() or has_refs):
                raise ImageCapabilityError("image_dashscope_4k_t2i_only", model=self._model)
            max_total = _FOURK_PIXEL_BUDGET if exceeds else _STANDARD_PIXEL_BUDGET
            short = resolution_to_short_edge(
                explicit or None, tier_map=IMAGE_TIER_SHORT_EDGE, default_short=_DEFAULT_SHORT_WAN
            )
            w, h = aspect_size(aspect, short, round_to=16, max_total_pixels=max_total, max_ratio=_DASHSCOPE_MAX_RATIO)
            return f"{w}*{h}"

        if self._is_edit:
            short = resolution_to_short_edge(
                explicit or None, tier_map=IMAGE_TIER_SHORT_EDGE, default_short=_DEFAULT_SHORT_EDIT
            )
            w, h = aspect_size(aspect, short, round_to=16, max_long_edge=_EDIT_MAX_LONG_EDGE, max_ratio=_EDIT_MAX_RATIO)
            return f"{w}*{h}"

        short = resolution_to_short_edge(
            explicit or None, tier_map=IMAGE_TIER_SHORT_EDGE, default_short=_DEFAULT_SHORT_FUSION
        )
        w, h = aspect_size(
            aspect, short, round_to=16, max_total_pixels=_STANDARD_PIXEL_BUDGET, max_ratio=_DASHSCOPE_MAX_RATIO
        )
        return f"{w}*{h}"

    def _build_content(self, request: ImageGenerationRequest, has_refs: bool) -> list[dict]:
        content: list[dict] = []
        if has_refs:
            # fail-loud：任一声明的参考图缺失（含目录/空串解析出的 "."）或读取失败（权限/并发删除
            # → OSError）即中止生成并报错列出文件名，让用户感知到有图未被使用，而非静默丢弃、用子集
            # 生成出错误结果还照常计费。
            data_uris: list[str] = []
            unreadable: list[str] = []
            # names 进多语言错误模板（en/vi 也渲染），分隔符与占位用 locale 中性形式：
            # 空路径无文件名可显示，用序号 #N 标识第几张参考图，避免中文占位漏进非中文报错。
            for idx, ref in enumerate(request.reference_images, start=1):
                path = Path(ref.path) if ref.path else None
                if path is None or not path.is_file():
                    unreadable.append(path.name if path else f"#{idx}")
                    continue
                try:
                    data_uris.append(image_to_data_uri(path))
                except (OSError, ValueError) as exc:
                    logger.warning("DashScope 参考图读取失败: %s (%s)", path, exc)
                    unreadable.append(path.name)
            if unreadable:
                raise ImageCapabilityError(
                    "image_reference_images_unreadable", model=self._model, names=", ".join(unreadable)
                )
            if len(data_uris) > self._ref_limit:
                raise ImageCapabilityError(
                    "image_reference_images_too_many",
                    model=self._model,
                    count=len(data_uris),
                    max_reference_images=self._ref_limit,
                )
            content.extend({"image": uri} for uri in data_uris)
        content.append({"text": request.prompt})
        return content

"""费用计算器。

统一入口 ``calculate_cost`` 按 ``lookup_pricing`` 查出模型定价声明（``ModelInfo.pricing``，
单一真相源），再交 ``lib.pricing.strategies`` 按定价形状 ``kind`` 派发计算。新增内置模型只需在
其 ``ModelInfo.pricing`` 写一条声明并复用已有 kind，无需改动本文件。
"""

from __future__ import annotations

from lib.custom_provider import is_custom_provider
from lib.pricing.lookup import lookup_pricing
from lib.pricing.strategies import PricingParams, calculate_pricing
from lib.pricing.types import PerSecondMatrix, PerTokenVideo
from lib.providers import (
    PROVIDER_ARK,
    PROVIDER_GROK,
    PROVIDER_OPENAI,
    CallType,
)


class CostCalculator:
    """费用计算器：按定价声明的 ``kind`` 派发，不含 provider 分支。"""

    # 外部依赖常量（lib.gemini_shared / lib.video_backends.gemini 直接读取）。
    DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image-preview"
    DEFAULT_VIDEO_MODEL = "veo-3.1-lite-generate-preview"
    DEFAULT_OPENAI_IMAGE_MODEL = "gpt-image-2"
    DEFAULT_OPENAI_VIDEO_MODEL = "sora-2"

    # Ark 生成视频的 token/s 近似常量（用于参考模式成本估算，实际 token 由生成回调覆盖）。
    _ARK_TOKENS_PER_SECOND_ESTIMATE = 60_000

    def calculate_text_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        provider: str,
        model: str | None = None,
    ) -> tuple[float, str]:
        """兼容旧入口：文本 token 计费。"""
        return self.calculate_cost(
            provider,
            "text",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def calculate_image_cost(self, resolution: str = "1K", model: str | None = None) -> float:
        """兼容旧入口：Gemini 图片按分辨率计费，返回 USD 金额。"""
        amount, _ = calculate_pricing(
            lookup_pricing("gemini-aistudio", model, "image"),
            PricingParams(call_type="image", model=model, resolution=resolution),
        )
        return amount

    def calculate_video_cost(
        self,
        duration_seconds: int,
        resolution: str = "1080p",
        generate_audio: bool = True,
        model: str | None = None,
    ) -> float:
        """兼容旧入口：Gemini/Veo 视频按秒计费，返回 USD 金额。"""
        amount, _ = calculate_pricing(
            lookup_pricing("gemini-aistudio", model, "video"),
            PricingParams(
                call_type="video",
                model=model,
                duration_seconds=duration_seconds,
                resolution=resolution,
                generate_audio=generate_audio,
            ),
        )
        return amount

    def calculate_ark_video_cost(
        self,
        usage_tokens: int,
        service_tier: str = "default",
        generate_audio: bool = True,
        model: str | None = None,
    ) -> tuple[float, str]:
        """兼容旧入口：Ark 视频按 usage token 计费。"""
        return self.calculate_cost(
            PROVIDER_ARK,
            "video",
            model=model,
            usage_tokens=usage_tokens,
            service_tier=service_tier,
            generate_audio=generate_audio,
        )

    def calculate_ark_image_cost(self, model: str | None = None, n: int = 1) -> tuple[float, str]:
        """兼容旧入口：Ark 图片按张计费。"""
        return self.calculate_cost(PROVIDER_ARK, "image", model=model, n=n)

    def calculate_grok_image_cost(self, model: str | None = None, n: int = 1) -> tuple[float, str]:
        """兼容旧入口：Grok 图片按张计费。"""
        return self.calculate_cost(PROVIDER_GROK, "image", model=model, n=n)

    def calculate_grok_video_cost(self, duration_seconds: int, model: str | None = None) -> tuple[float, str]:
        """兼容旧入口：Grok 视频按秒计费。"""
        return calculate_pricing(
            lookup_pricing(PROVIDER_GROK, model, "video"),
            PricingParams(call_type="video", model=model, duration_seconds=duration_seconds),
        )

    def calculate_openai_image_cost(
        self,
        *,
        model: str | None = None,
        image_input_tokens: int | None = None,
        image_output_tokens: int | None = None,
        text_input_tokens: int | None = None,
        text_output_tokens: int | None = None,
        quality: str | None = None,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
        size: str | None = None,
        n: int = 1,
    ) -> tuple[float, str]:
        """兼容旧入口：OpenAI 图片 token 主路径 + fallback 表。"""
        return self.calculate_cost(
            PROVIDER_OPENAI,
            "image",
            model=model,
            image_input_tokens=image_input_tokens,
            image_output_tokens=image_output_tokens,
            text_input_tokens=text_input_tokens,
            text_output_tokens=text_output_tokens,
            quality=quality,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            size=size,
            n=n,
        )

    def calculate_openai_video_cost(
        self,
        duration_seconds: int,
        model: str | None = None,
        resolution: str | None = None,
    ) -> tuple[float, str]:
        """兼容旧入口：OpenAI Sora 视频按秒计费。"""
        return calculate_pricing(
            lookup_pricing(PROVIDER_OPENAI, model, "video"),
            PricingParams(call_type="video", model=model, duration_seconds=duration_seconds, resolution=resolution),
        )

    def calculate_cost(
        self,
        provider: str,
        call_type: CallType,
        *,
        model: str | None = None,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
        duration_seconds: int | None = None,
        generate_audio: bool = True,
        usage_tokens: int | None = None,
        service_tier: str = "default",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        quality: str | None = None,
        size: str | None = None,
        image_input_tokens: int | None = None,
        image_output_tokens: int | None = None,
        text_input_tokens: int | None = None,
        text_output_tokens: int | None = None,
        custom_price_input: float | None = None,
        custom_price_output: float | None = None,
        custom_currency: str | None = None,
        n: int = 1,
    ) -> tuple[float, str]:
        """统一费用计算入口。返回 ``(amount, currency)``。

        自定义供应商的价格信息通过 ``custom_price_*`` 参数传入（调用方需预先查询 DB）。
        """
        if is_custom_provider(provider):
            return self._calculate_custom_cost(
                call_type,
                price_input=custom_price_input,
                price_output=custom_price_output,
                currency=custom_currency,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_seconds=duration_seconds,
            )

        # 文本无 token 数据时无从计费，保留早返回。
        if call_type == "text" and input_tokens is None:
            return 0.0, "USD"

        pricing = lookup_pricing(provider, model, call_type)
        # 按秒计费的视频：单次实时调用无/0 时长时按默认 8 秒计（历史行为）。
        # 参考模式聚合走 estimate_reference_video_cost，传真实累计时长（可为 0），不经此默认。
        if isinstance(pricing, PerSecondMatrix):
            duration_seconds = duration_seconds or 8
        params = PricingParams(
            call_type=call_type,
            model=model,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            duration_seconds=duration_seconds,
            generate_audio=generate_audio,
            usage_tokens=usage_tokens,
            service_tier=service_tier,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            quality=quality,
            size=size,
            image_input_tokens=image_input_tokens,
            image_output_tokens=image_output_tokens,
            text_input_tokens=text_input_tokens,
            text_output_tokens=text_output_tokens,
            n=n,
        )
        return calculate_pricing(pricing, params)

    def estimate_reference_video_cost(
        self,
        *,
        unit_durations_seconds: list[int],
        provider: str,
        model: str | None = None,
        resolution: str | None = None,
        generate_audio: bool = True,
        service_tier: str = "default",
    ) -> tuple[float, str]:
        """聚合参考模式一集的视频费用：sum over units of (duration × 单价)。

        token 计费的视频（Ark）按 duration × ``_ARK_TOKENS_PER_SECOND_ESTIMATE`` 近似换算 token；
        其余按秒计费的模型直接用累计时长。空列表返回该定价声明自带的币种。
        """
        pricing = lookup_pricing(provider, model, "video")
        if not unit_durations_seconds:
            return 0.0, pricing.currency

        total_duration = sum(max(0, int(d)) for d in unit_durations_seconds)
        usage_tokens = (
            total_duration * self._ARK_TOKENS_PER_SECOND_ESTIMATE if isinstance(pricing, PerTokenVideo) else None
        )
        params = PricingParams(
            call_type="video",
            model=model,
            resolution=resolution,
            duration_seconds=total_duration,
            generate_audio=generate_audio,
            usage_tokens=usage_tokens,
            service_tier=service_tier,
        )
        return calculate_pricing(pricing, params)

    @staticmethod
    def _calculate_custom_cost(
        call_type: str,
        *,
        price_input: float | None = None,
        price_output: float | None = None,
        currency: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        duration_seconds: int | None = None,
    ) -> tuple[float, str]:
        """根据调用方预查的价格信息计算自定义供应商费用。"""
        if price_input is None:
            return 0.0, "USD"

        cur = currency or "USD"

        if call_type == "text":
            inp = (input_tokens or 0) * price_input
            out = (output_tokens or 0) * (price_output or 0)
            return (inp + out) / 1_000_000, cur
        if call_type == "image":
            return price_input, cur
        if call_type == "video":
            return (duration_seconds or 8) * price_input, cur
        return 0.0, cur


# 单例实例，方便使用
cost_calculator = CostCalculator()

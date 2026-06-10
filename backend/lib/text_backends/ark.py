"""ArkTextBackend — 火山方舟文本生成后端。"""

from __future__ import annotations

import asyncio
import logging

from lib.ark_shared import ARK_BASE_URL, create_ark_client, resolve_ark_api_key
from lib.logging_utils import format_kwargs_for_log
from lib.providers import PROVIDER_ARK
from lib.retry import with_retry_async
from lib.text_backends.base import (
    TextCapability,
    TextGenerationRequest,
    TextGenerationResult,
    structured_output_error,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "doubao-seed-2-0-lite-260215"


class ArkTextBackend:
    """Ark (火山方舟) 文本生成后端。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ):
        resolved_key = resolve_ark_api_key(api_key)
        effective_base_url = base_url or ARK_BASE_URL
        self._client = create_ark_client(api_key=resolved_key, base_url=effective_base_url)
        self._model = model or DEFAULT_MODEL
        self._capabilities: set[TextCapability] = self._resolve_capabilities()

    def _resolve_capabilities(self) -> set[TextCapability]:
        """根据 PROVIDER_REGISTRY 中的模型声明构建能力集合。"""
        from lib.config.registry import PROVIDER_REGISTRY

        base = {TextCapability.TEXT_GENERATION, TextCapability.VISION}
        # 同一 backend 类同时服务 ark 与 ark-agent-plan，模型 ID 命名格式不同，
        # 任一 provider 命中即可解析 STRUCTURED_OUTPUT。
        for provider_id in ("ark", "ark-agent-plan"):
            provider_meta = PROVIDER_REGISTRY.get(provider_id)
            if provider_meta is None:
                continue
            model_info = provider_meta.models.get(self._model)
            if model_info and TextCapability.STRUCTURED_OUTPUT in model_info.capabilities:
                base.add(TextCapability.STRUCTURED_OUTPUT)
                break
        # 未注册模型不加 STRUCTURED_OUTPUT：不要把 json_object/Instructor 当成 strict schema。
        return base

    @property
    def name(self) -> str:
        return PROVIDER_ARK

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[TextCapability]:
        return self._capabilities

    @with_retry_async()
    async def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        if request.response_schema:
            return await self._generate_structured(request)
        return await self._generate_plain(request)

    async def _generate_plain(self, request: TextGenerationRequest) -> TextGenerationResult:
        messages = self._build_messages(request)
        kwargs: dict = {"model": self._model, "messages": messages}
        if request.max_output_tokens is not None:
            kwargs["max_tokens"] = request.max_output_tokens
        logger.info("调用 %s 文本 SDK kwargs=%s", self.name, format_kwargs_for_log(kwargs))
        response = await asyncio.to_thread(
            self._client.chat.completions.create,
            **kwargs,
        )
        return self._parse_chat_response(response)

    async def _generate_structured(self, request: TextGenerationRequest) -> TextGenerationResult:
        messages = self._build_messages(request)

        if TextCapability.STRUCTURED_OUTPUT not in self._capabilities:
            raise ValueError(
                _strict_structured_output_failure(
                    self._model,
                    "当前 Ark 模型未声明已验证的原生 json_schema 结构化输出能力",
                )
            )

        from lib.text_backends.base import resolve_schema

        if request.response_schema is None:
            raise ValueError("structured 模式要求 response_schema 非空")
        schema = resolve_schema(request.response_schema)
        kwargs: dict = {
            "model": self._model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": schema},
            },
        }
        if request.max_output_tokens is not None:
            kwargs["max_tokens"] = request.max_output_tokens
        logger.info("调用 %s 文本 SDK kwargs=%s", self.name, format_kwargs_for_log(kwargs))
        try:
            response = await asyncio.to_thread(self._client.chat.completions.create, **kwargs)
        except Exception as exc:
            logger.warning("Ark 原生 response_format.json_schema 失败，不降级到 Instructor/json_object：%s", exc)
            raise ValueError(_strict_structured_output_failure(self._model, f"接口拒绝 json_schema 请求: {exc}")) from exc

        result = self._parse_chat_response(response)
        if error := structured_output_error(result.text, request.response_schema):
            raise ValueError(_strict_structured_output_failure(self._model, error))
        return result

    def _build_messages(self, request: TextGenerationRequest) -> list[dict]:
        messages: list[dict] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})

        if request.images:
            from lib.image_backends.base import image_to_base64_data_uri

            content: list[dict] = []
            for img in request.images:
                if img.path:
                    data_uri = image_to_base64_data_uri(img.path)
                    content.append({"type": "image_url", "image_url": {"url": data_uri}})
                elif img.url:
                    content.append({"type": "image_url", "image_url": {"url": img.url}})
            content.append({"type": "text", "text": request.prompt})
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": request.prompt})

        return messages

    def _parse_chat_response(self, response) -> TextGenerationResult:
        from lib.text_backends.base import warn_if_truncated

        choice = response.choices[0]
        text = choice.message.content
        input_tokens = getattr(getattr(response, "usage", None), "prompt_tokens", None)
        output_tokens = getattr(getattr(response, "usage", None), "completion_tokens", None)
        warn_if_truncated(
            getattr(choice, "finish_reason", None),
            provider=PROVIDER_ARK,
            model=self._model,
            output_tokens=output_tokens,
        )
        return TextGenerationResult(
            text=text.strip() if isinstance(text, str) else str(text),
            provider=PROVIDER_ARK,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def _strict_structured_output_failure(model: str, detail: str) -> str:
    return (
        f"{PROVIDER_ARK}/{model} strict JSON Schema 结构化输出失败：{detail}。"
        "根据 provider-api-evidence 资料，不能降级到 json_object/Instructor 后继续当作 strict schema；"
        "请改用已验证支持 json_schema 的 endpoint/供应商，或为该模型配置独立的非 strict 纠错流程。"
    )

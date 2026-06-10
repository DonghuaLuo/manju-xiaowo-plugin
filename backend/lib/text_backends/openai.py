"""OpenAITextBackend — OpenAI 文本生成后端。"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI, BadRequestError
from pydantic import BaseModel, ValidationError

from lib.logging_utils import format_kwargs_for_log
from lib.openai_shared import OPENAI_RETRYABLE_ERRORS, create_openai_client
from lib.providers import PROVIDER_OPENAI
from lib.retry import with_retry_async
from lib.text_backends.base import (
    TextCapability,
    TextGenerationRequest,
    TextGenerationResult,
    resolve_schema,
    warn_if_truncated,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5.4-mini"

OPENAI_RESPONSES_BACKEND = "openai-responses"
DEFAULT_RESPONSES_INSTRUCTIONS = "Follow the user's instructions and produce the requested output."
_RESPONSES_PREFERRED_MODEL_RE = r"(^|[/:\s_-])gpt[-_]?5(?:[.\s_-]|$)"


def is_responses_preferred_model(model: str | None) -> bool:
    """Return True for OpenAI-family models that should avoid Chat Completions."""
    if not model:
        return False
    import re

    return bool(re.search(_RESPONSES_PREFERRED_MODEL_RE, model.strip().lower()))


class OpenAITextBackend:
    """OpenAI 文本生成后端，支持 Chat Completions API。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        provider_name: str = PROVIDER_OPENAI,
        prefer_native_structured_output: bool = True,
    ):
        # 禁用 SDK 内置重试，由本层 generate() 统一管理重试策略
        self._client = create_openai_client(api_key=api_key, base_url=base_url, max_retries=0)
        self._model = model or DEFAULT_MODEL
        # 复用 OpenAI 兼容协议的 provider（如 dashscope）须用真实 provider 记账，
        # 否则计费查表会命中 OpenAI 的 USD 费率而非自身定价。
        self._provider_name = provider_name
        self._prefer_native_structured_output = prefer_native_structured_output
        self._capabilities: set[TextCapability] = {
            TextCapability.TEXT_GENERATION,
            TextCapability.STRUCTURED_OUTPUT,
            TextCapability.VISION,
        }

    @property
    def name(self) -> str:
        return self._provider_name

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[TextCapability]:
        return self._capabilities

    @with_retry_async(max_attempts=4, backoff_seconds=(2, 4, 8), retryable_errors=OPENAI_RETRYABLE_ERRORS)
    async def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        """生成文本回复。

        单一重试循环包裹整个流程：
        1. 尝试原生 response_format 调用
        2. 若遇 schema 不兼容错误 → 本次 attempt 内降级到 Instructor
        3. 若遇瞬态错误（429/500/503/网络）→ 由装饰器自动重试整个流程

        这样无论是原生调用还是降级路径遇到瞬态错误，都统一由外层重试处理。
        """
        messages = _build_messages(request)
        if request.response_schema and not self._prefer_native_structured_output:
            logger.info("跳过原生 response_format，直接使用 Instructor/json_object 路径")
            return await _instructor_fallback(
                self._client, self._model, request, messages, provider=self._provider_name
            )

        kwargs: dict = {"model": self._model, "messages": messages}
        if request.max_output_tokens is not None:
            kwargs["max_tokens"] = request.max_output_tokens

        if request.response_schema:
            schema = resolve_schema(request.response_schema)
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": schema,
                },
            }

        logger.info("调用 %s 文本 SDK kwargs=%s", self.name, format_kwargs_for_log(kwargs))
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            if request.response_schema and _is_schema_error(exc):
                logger.warning(
                    "原生 response_format 失败 (%s)，降级到 Instructor 路径",
                    exc,
                )
                return await _instructor_fallback(
                    self._client, self._model, request, messages, provider=self._provider_name
                )
            raise

        usage = response.usage
        choice = response.choices[0]
        output_tokens = usage.completion_tokens if usage else None
        text = choice.message.content or ""

        if request.response_schema and not _is_valid_json(text):
            logger.warning(
                "原生 response_format 返回非 JSON 内容（代理可能未支持 response_format），降级到 Instructor 路径",
            )
            return await _instructor_fallback(
                self._client, self._model, request, messages, provider=self._provider_name
            )
        if request.response_schema and _pydantic_validation_error(text, request.response_schema):
            logger.warning(
                "原生 response_format 返回 JSON 但不符合 Pydantic schema（代理可能未支持 json_schema），"
                "降级到 Instructor 路径",
            )
            return await _instructor_fallback(
                self._client, self._model, request, messages, provider=self._provider_name
            )

        warn_if_truncated(
            getattr(choice, "finish_reason", None),
            provider=self._provider_name,
            model=self._model,
            output_tokens=output_tokens,
        )
        return TextGenerationResult(
            text=text,
            provider=self._provider_name,
            model=self._model,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=output_tokens,
        )


class OpenAIResponsesTextBackend:
    """OpenAI 文本生成后端，使用 Responses API。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        provider_name: str = PROVIDER_OPENAI,
        send_max_output_tokens: bool = True,
        use_input_item_list: bool = False,
        stream_response: bool = False,
    ):
        self._client = create_openai_client(api_key=api_key, base_url=base_url, max_retries=0)
        self._model = model or DEFAULT_MODEL
        self._provider_name = provider_name
        self._send_max_output_tokens = send_max_output_tokens
        self._use_input_item_list = use_input_item_list
        self._stream_response = stream_response
        self._capabilities: set[TextCapability] = {
            TextCapability.TEXT_GENERATION,
            TextCapability.STRUCTURED_OUTPUT,
            TextCapability.VISION,
        }

    @property
    def name(self) -> str:
        return self._provider_name

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[TextCapability]:
        return self._capabilities

    @with_retry_async(max_attempts=4, backoff_seconds=(2, 4, 8), retryable_errors=OPENAI_RETRYABLE_ERRORS)
    async def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        format_mode = "json_schema" if request.response_schema else None
        return await self._generate_with_format(request, format_mode=format_mode)

    async def _generate_with_format(
        self,
        request: TextGenerationRequest,
        *,
        format_mode: str | None,
    ) -> TextGenerationResult:
        kwargs = _build_responses_kwargs(
            self._model,
            request,
            format_mode=format_mode,
            send_max_output_tokens=self._send_max_output_tokens,
            use_input_item_list=self._use_input_item_list,
        )
        logger.info("调用 %s Responses SDK kwargs=%s", self.name, format_kwargs_for_log(kwargs))
        try:
            if self._stream_response:
                response = await _create_streamed_response(self._client, kwargs)
            else:
                response = await self._client.responses.create(**kwargs)
        except Exception as exc:
            if request.response_schema and format_mode == "json_schema" and _is_schema_error(exc):
                logger.warning(
                    "Responses 原生 json_schema 失败 (%s)，降级到 Responses json_object 路径",
                    exc,
                )
                return await self._generate_with_format(request, format_mode="json_object")
            raise

        text = _extract_responses_text(response)
        if request.response_schema and format_mode == "json_schema" and not _is_valid_json(text):
            logger.warning("Responses json_schema 返回非 JSON 内容，降级到 Responses json_object 路径")
            return await self._generate_with_format(request, format_mode="json_object")
        if request.response_schema and format_mode == "json_schema" and _pydantic_validation_error(
            text, request.response_schema
        ):
            logger.warning("Responses json_schema 返回 JSON 但不符合 Pydantic schema，降级到 Responses json_object 路径")
            return await self._generate_with_format(request, format_mode="json_object")

        usage = _read_attr_or_key(response, "usage")
        input_tokens = _read_int_attr_or_key(usage, "input_tokens", "prompt_tokens")
        output_tokens = _read_int_attr_or_key(usage, "output_tokens", "completion_tokens")
        warn_if_truncated(
            _extract_responses_finish_reason(response),
            provider=self._provider_name,
            model=self._model,
            output_tokens=output_tokens,
            truncation_values=("length", "MAX_TOKENS", "max_tokens", "max_output_tokens"),
        )

        return TextGenerationResult(
            text=text,
            provider=self._provider_name,
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def _build_messages(request: TextGenerationRequest) -> list[dict]:
    """将 TextGenerationRequest 转为 OpenAI messages 格式。"""
    messages: list[dict] = []

    if request.system_prompt:
        messages.append({"role": "system", "content": request.system_prompt})

    # 构建 user message
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


def _build_responses_kwargs(
    model: str,
    request: TextGenerationRequest,
    *,
    format_mode: str | None,
    send_max_output_tokens: bool = True,
    use_input_item_list: bool = False,
) -> dict:
    """将 TextGenerationRequest 转为 OpenAI Responses API kwargs。"""
    kwargs: dict[str, Any] = {
        "model": model,
        "input": _build_responses_input(request, use_input_item_list=use_input_item_list),
        "instructions": _responses_instructions(request),
    }
    if send_max_output_tokens and request.max_output_tokens is not None:
        kwargs["max_output_tokens"] = request.max_output_tokens
    if format_mode == "json_schema" and request.response_schema:
        kwargs["text"] = {
            "format": {
                "type": "json_schema",
                "name": "response",
                "strict": True,
                "schema": resolve_schema(request.response_schema),
            }
        }
    elif format_mode == "json_object":
        kwargs["text"] = {"format": {"type": "json_object"}}
    return kwargs


def _responses_instructions(request: TextGenerationRequest) -> str:
    if request.system_prompt and request.system_prompt.strip():
        return request.system_prompt
    return DEFAULT_RESPONSES_INSTRUCTIONS


def _build_responses_input(
    request: TextGenerationRequest,
    *,
    use_input_item_list: bool = False,
) -> str | list[dict]:
    if not request.images:
        if use_input_item_list:
            return [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": request.prompt}],
                }
            ]
        return request.prompt

    from lib.image_backends.base import image_to_base64_data_uri

    content: list[dict] = [{"type": "input_text", "text": request.prompt}]
    for img in request.images:
        image_url: str | None = None
        if img.path:
            image_url = image_to_base64_data_uri(img.path)
        elif img.url:
            image_url = img.url
        if image_url:
            content.append({"type": "input_image", "image_url": image_url})
    message = {"role": "user", "content": content}
    if use_input_item_list:
        message["type"] = "message"
    return [message]


async def _create_streamed_response(client: AsyncOpenAI, kwargs: dict[str, Any]) -> Any:
    """Call Responses with stream=true and return an accumulated Response-like object."""
    stream = await client.responses.create(**kwargs, stream=True)
    chunks: list[str] = []
    final_response: Any | None = None
    try:
        async for event in stream:
            event_type = _read_attr_or_key(event, "type")
            if event_type == "response.output_text.delta":
                delta = _read_attr_or_key(event, "delta")
                if isinstance(delta, str):
                    chunks.append(delta)
            elif event_type == "response.output_text.done":
                text = _read_attr_or_key(event, "text")
                if isinstance(text, str):
                    chunks = [text]
            elif event_type == "response.completed":
                final_response = _read_attr_or_key(event, "response")
                if final_response is not None:
                    return final_response
            elif event_type == "response.failed":
                response = _read_attr_or_key(event, "response")
                error = _read_attr_or_key(response, "error")
                message = _read_attr_or_key(error, "message") or _read_attr_or_key(response, "error")
                raise RuntimeError(f"Responses stream failed: {message or response or 'unknown error'}")
    finally:
        close = getattr(stream, "close", None) or getattr(stream, "aclose", None)
        if close:
            result = close()
            if hasattr(result, "__await__"):
                await result

    if final_response is not None:
        return final_response
    return {
        "output_text": "".join(chunks),
        "usage": None,
        "status": "completed",
        "incomplete_details": None,
    }


def _extract_responses_text(response: Any) -> str:
    output_text = _read_attr_or_key(response, "output_text")
    if isinstance(output_text, str):
        return output_text

    chunks: list[str] = []
    output = _read_attr_or_key(response, "output")
    if not isinstance(output, (list, tuple)):
        return ""
    for item in output:
        content = _read_attr_or_key(item, "content")
        if not isinstance(content, (list, tuple)):
            continue
        for part in content:
            text = _read_attr_or_key(part, "text")
            if isinstance(text, str):
                chunks.append(text)
    return "".join(chunks)


def _extract_responses_finish_reason(response: Any) -> str | None:
    incomplete_details = _read_attr_or_key(response, "incomplete_details")
    reason = _read_attr_or_key(incomplete_details, "reason")
    if isinstance(reason, str) and reason:
        return reason
    status = _read_attr_or_key(response, "status")
    return status if isinstance(status, str) else None


def _read_attr_or_key(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _read_int_attr_or_key(obj: Any, *keys: str) -> int | None:
    for key in keys:
        value = _read_attr_or_key(obj, key)
        if isinstance(value, int):
            return value
    return None


_SCHEMA_ERROR_KEYWORDS = (
    "response_schema",
    "json_schema",
    "Unknown name",
    "Cannot find field",
    "Invalid JSON payload",
)


def _is_valid_json(text: str) -> bool:
    """判断字符串是否为合法 JSON。

    一些 OpenAI 兼容代理（自定义供应商常见情况）会静默忽略 response_format
    参数并返回纯文本/markdown，需要据此触发 Instructor 降级。
    """
    if not text or not text.strip():
        return False
    try:
        json.loads(text)
        return True
    except (ValueError, TypeError):
        return False


def _pydantic_validation_error(text: str, schema: dict | type | None) -> bool:
    """判断 Pydantic schema 的原生 JSON 响应是否结构不匹配。

    一些 OpenAI 兼容代理会返回合法 JSON，但忽略 json_schema 的必填字段约束；
    如果这里不拦截，错误会延迟到业务层的 model_validate_json 才暴露。
    """
    if not isinstance(schema, type) or not issubclass(schema, BaseModel):
        return False
    try:
        schema.model_validate_json(text)
    except ValidationError:
        return True
    return False


def _is_schema_error(exc: BaseException) -> bool:
    """判断异常是否为 JSON Schema 不兼容导致的错误。

    除了标准的 400 BadRequestError，一些 OpenAI 兼容代理（如 Gemini
    兼容端点）会将上游 schema 错误包装成其他状态码（如 429），
    因此也检查错误信息中是否包含 schema 相关关键字。
    """
    if isinstance(exc, BadRequestError):
        return True
    # 代理可能把上游 schema 错误包装成非 400 状态码
    error_str = str(exc)
    return any(kw in error_str for kw in _SCHEMA_ERROR_KEYWORDS)


async def _instructor_fallback(
    client: AsyncOpenAI,
    model: str,
    request: TextGenerationRequest,
    messages: list[dict],
    *,
    provider: str = PROVIDER_OPENAI,
) -> TextGenerationResult:
    """Instructor 降级：当原生 response_format 不可用时的备选路径。"""
    from lib.text_backends.instructor_support import instructor_fallback_async

    return await instructor_fallback_async(
        client=client,
        model=model,
        messages=messages,
        response_schema=request.response_schema,
        provider=provider,
        max_tokens=request.max_output_tokens,
    )

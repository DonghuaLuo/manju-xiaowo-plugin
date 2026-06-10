"""OpenAITextBackend 单元测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from openai import BadRequestError
from PIL import Image
from pydantic import BaseModel

from lib.providers import PROVIDER_OPENAI
from lib.text_backends.base import (
    ImageInput,
    TextCapability,
    TextGenerationRequest,
    ensure_structured_output,
    structured_output_error,
)


def _make_mock_response(content="Hello", input_tokens=10, output_tokens=5):
    """构造 mock ChatCompletion 响应。"""
    usage = MagicMock()
    usage.prompt_tokens = input_tokens
    usage.completion_tokens = output_tokens

    message = MagicMock()
    message.content = content

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def _make_mock_responses_response(content="Hello", input_tokens=10, output_tokens=5):
    """构造 mock Responses API 响应。"""
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens

    response = MagicMock()
    response.output_text = content
    response.usage = usage
    response.status = "completed"
    response.incomplete_details = None
    return response


class _FakeAsyncStream:
    def __init__(self, events):
        self._events = list(events)
        self.closed = False

    def __aiter__(self):
        self._iter = iter(self._events)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def close(self):
        self.closed = True


def test_ensure_structured_output_wraps_pydantic_schema_mismatch():
    class ResponseModel(BaseModel):
        key: str

    with pytest.raises(ValueError, match="custom-42/gpt-5.5 结构化输出无效"):
        ensure_structured_output(
            '{"wrong": "field"}',
            ResponseModel,
            provider="custom-42",
            model="gpt-5.5",
        )


def test_ensure_structured_output_validates_dict_schema_mismatch():
    schema = {
        "type": "object",
        "required": ["title", "scenes"],
        "properties": {
            "title": {"type": "string"},
            "scenes": {"type": "array"},
        },
    }

    with pytest.raises(ValueError, match="custom-42/gpt-5.5 结构化输出无效"):
        ensure_structured_output(
            '{"episode": 1}',
            schema,
            provider="custom-42",
            model="gpt-5.5",
        )


def test_structured_output_error_validates_dict_schema_type_mismatch():
    schema = {"type": "object", "required": ["age"], "properties": {"age": {"type": "integer"}}}

    assert structured_output_error('{"age": "old"}', schema)


class TestOpenAITextBackend:
    def test_name_and_model(self):
        with patch("lib.openai_shared.AsyncOpenAI"):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key")
            assert backend.name == PROVIDER_OPENAI
            assert backend.model == "gpt-5.4-mini"

    def test_custom_model(self):
        with patch("lib.openai_shared.AsyncOpenAI"):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key", model="gpt-5.4")
            assert backend.model == "gpt-5.4"

    def test_capabilities(self):
        with patch("lib.openai_shared.AsyncOpenAI"):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key")
            assert TextCapability.TEXT_GENERATION in backend.capabilities
            assert TextCapability.STRUCTURED_OUTPUT in backend.capabilities
            assert TextCapability.VISION in backend.capabilities

    def test_compatible_chat_without_native_schema_does_not_advertise_structured_output(self):
        with patch("lib.openai_shared.AsyncOpenAI"):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key", prefer_native_structured_output=False)
            assert TextCapability.TEXT_GENERATION in backend.capabilities
            assert TextCapability.STRUCTURED_OUTPUT not in backend.capabilities
            assert TextCapability.VISION in backend.capabilities

    async def test_generate_plain_text(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_make_mock_response("Test output", 15, 8))

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key")
            request = TextGenerationRequest(prompt="Say hello")
            result = await backend.generate(request)

        assert result.text == "Test output"
        assert result.provider == PROVIDER_OPENAI
        assert result.model == "gpt-5.4-mini"
        assert result.input_tokens == 15
        assert result.output_tokens == 8

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-5.4-mini"
        assert len(call_kwargs["messages"]) == 1
        assert call_kwargs["messages"][0]["role"] == "user"
        assert call_kwargs["messages"][0]["content"] == "Say hello"

    async def test_generate_with_system_prompt(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_make_mock_response("Response"))

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key")
            request = TextGenerationRequest(
                prompt="Do something",
                system_prompt="You are helpful",
            )
            await backend.generate(request)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["messages"][0]["role"] == "system"
        assert call_kwargs["messages"][0]["content"] == "You are helpful"
        assert call_kwargs["messages"][1]["role"] == "user"

    async def test_generate_with_vision(self, tmp_path):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_make_mock_response("I see a cat"))

        img_path = tmp_path / "test.png"
        Image.new("RGB", (8, 8), color="blue").save(img_path, format="PNG")

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key")
            request = TextGenerationRequest(
                prompt="What is this?",
                images=[ImageInput(path=img_path)],
            )
            result = await backend.generate(request)

        assert result.text == "I see a cat"
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        user_msg = call_kwargs["messages"][-1]
        assert isinstance(user_msg["content"], list)
        types = [part["type"] for part in user_msg["content"]]
        assert "image_url" in types
        assert "text" in types

    async def test_generate_structured_output(self):
        schema_response = json.dumps({"name": "Alice", "age": 30})
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_make_mock_response(schema_response))

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key")
            request = TextGenerationRequest(
                prompt="Extract info",
                response_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                },
            )
            result = await backend.generate(request)

        assert result.text == schema_response
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert "response_format" in call_kwargs

    async def test_generate_usage_none_tolerant(self):
        """usage 为 None 时不应崩溃。"""
        response = _make_mock_response("OK")
        response.usage = None

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=response)

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key")
            request = TextGenerationRequest(prompt="Hi")
            result = await backend.generate(request)

        assert result.text == "OK"
        assert result.input_tokens is None
        assert result.output_tokens is None


class TestOpenAIResponsesTextBackend:
    def test_compatible_responses_without_native_schema_does_not_advertise_structured_output(self):
        with patch("lib.openai_shared.AsyncOpenAI"):
            from lib.text_backends.openai import OpenAIResponsesTextBackend

            backend = OpenAIResponsesTextBackend(
                api_key="test-key",
                provider_name="custom-42",
                prefer_native_structured_output=False,
            )
            assert TextCapability.TEXT_GENERATION in backend.capabilities
            assert TextCapability.STRUCTURED_OUTPUT not in backend.capabilities
            assert TextCapability.VISION in backend.capabilities

    async def test_generate_without_system_prompt_sends_default_instructions(self):
        mock_client = AsyncMock()
        mock_client.responses.create = AsyncMock(return_value=_make_mock_responses_response("Test output"))

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import DEFAULT_RESPONSES_INSTRUCTIONS, OpenAIResponsesTextBackend

            backend = OpenAIResponsesTextBackend(api_key="test-key", model="gpt-5.5")
            await backend.generate(TextGenerationRequest(prompt="Normalize this script"))

        call_kwargs = mock_client.responses.create.call_args[1]
        assert call_kwargs["input"] == "Normalize this script"
        assert call_kwargs["instructions"] == DEFAULT_RESPONSES_INSTRUCTIONS

    async def test_generate_plain_text_uses_responses_api(self):
        mock_client = AsyncMock()
        mock_client.responses.create = AsyncMock(return_value=_make_mock_responses_response("Test output", 15, 8))
        mock_client.chat.completions.create = AsyncMock()

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAIResponsesTextBackend

            backend = OpenAIResponsesTextBackend(api_key="test-key", model="gpt-5.5")
            request = TextGenerationRequest(
                prompt="Say hello",
                system_prompt="You are helpful",
                max_output_tokens=1234,
            )
            result = await backend.generate(request)

        assert result.text == "Test output"
        assert result.provider == PROVIDER_OPENAI
        assert result.model == "gpt-5.5"
        assert result.input_tokens == 15
        assert result.output_tokens == 8

        call_kwargs = mock_client.responses.create.call_args[1]
        assert call_kwargs["model"] == "gpt-5.5"
        assert call_kwargs["input"] == "Say hello"
        assert call_kwargs["instructions"] == "You are helpful"
        assert call_kwargs["max_output_tokens"] == 1234
        mock_client.chat.completions.create.assert_not_called()

    async def test_custom_responses_backend_uses_relay_compatible_stream_shape(self):
        final_response = _make_mock_responses_response("Test output", 15, 8)
        stream = _FakeAsyncStream(
            [
                SimpleNamespace(type="response.output_text.delta", delta="Test "),
                SimpleNamespace(type="response.output_text.delta", delta="output"),
                SimpleNamespace(type="response.completed", response=final_response),
            ]
        )
        mock_client = AsyncMock()
        mock_client.responses.create = AsyncMock(return_value=stream)

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import DEFAULT_RESPONSES_INSTRUCTIONS, OpenAIResponsesTextBackend

            backend = OpenAIResponsesTextBackend(
                api_key="test-key",
                model="gpt-5.5",
                provider_name="custom-42",
                send_max_output_tokens=False,
                use_input_item_list=True,
                stream_response=True,
                prefer_native_structured_output=False,
            )
            result = await backend.generate(TextGenerationRequest(prompt="Normalize this script", max_output_tokens=16000))

        call_kwargs = mock_client.responses.create.call_args[1]
        assert result.text == "Test output"
        assert result.input_tokens == 15
        assert result.output_tokens == 8
        assert call_kwargs["stream"] is True
        assert call_kwargs["input"] == [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Normalize this script"}],
            }
        ]
        assert call_kwargs["instructions"] == DEFAULT_RESPONSES_INSTRUCTIONS
        assert "max_output_tokens" not in call_kwargs
        assert stream.closed is True

    async def test_custom_responses_stream_keeps_delta_when_completed_response_has_no_text(self):
        usage = SimpleNamespace(input_tokens=15, output_tokens=8)
        final_response = SimpleNamespace(output=[], usage=usage, status="completed", incomplete_details=None)
        stream = _FakeAsyncStream(
            [
                SimpleNamespace(type="response.output_text.delta", delta='{"ok": '),
                SimpleNamespace(type="response.output_text.delta", delta="true}"),
                SimpleNamespace(type="response.completed", response=final_response),
            ]
        )
        mock_client = AsyncMock()
        mock_client.responses.create = AsyncMock(return_value=stream)

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAIResponsesTextBackend

            backend = OpenAIResponsesTextBackend(
                api_key="test-key",
                model="gpt-5.5",
                provider_name="custom-42",
                send_max_output_tokens=False,
                use_input_item_list=True,
                stream_response=True,
                prefer_native_structured_output=False,
            )
            result = await backend.generate(TextGenerationRequest(prompt="Return JSON"))

        assert result.text == '{"ok": true}'
        assert result.input_tokens == 15
        assert result.output_tokens == 8
        assert stream.closed is True

    async def test_generate_structured_output_uses_responses_text_format(self):
        schema_response = json.dumps({"name": "Alice", "age": 30})
        mock_client = AsyncMock()
        mock_client.responses.create = AsyncMock(return_value=_make_mock_responses_response(schema_response))

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAIResponsesTextBackend

            backend = OpenAIResponsesTextBackend(api_key="test-key", model="gpt-5.5")
            request = TextGenerationRequest(
                prompt="Extract info",
                response_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                },
            )
            result = await backend.generate(request)

        assert result.text == schema_response
        call_kwargs = mock_client.responses.create.call_args[1]
        assert call_kwargs["text"]["format"]["type"] == "json_schema"
        assert call_kwargs["text"]["format"]["name"] == "response"
        assert call_kwargs["text"]["format"]["strict"] is True

    async def test_responses_without_native_structured_output_raises_before_request(self):
        mock_client = AsyncMock()
        mock_client.responses.create = AsyncMock()

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAIResponsesTextBackend

            backend = OpenAIResponsesTextBackend(
                api_key="test-key",
                model="gpt-5.5",
                provider_name="custom-42",
                prefer_native_structured_output=False,
            )
            with pytest.raises(ValueError, match="未发送原生 text.format.json_schema 请求"):
                await backend.generate(TextGenerationRequest(prompt="Extract info", response_schema=_PersonSchema))

        mock_client.responses.create.assert_not_called()

    async def test_responses_schema_mismatch_raises_without_json_object_fallback(self):
        wrong_schema_json = json.dumps({"title": "Wrong shape", "language": "zh"})
        mock_client = AsyncMock()
        mock_client.responses.create = AsyncMock(return_value=_make_mock_responses_response(wrong_schema_json))

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAIResponsesTextBackend

            backend = OpenAIResponsesTextBackend(api_key="test-key", model="gpt-5.5")
            with pytest.raises(ValueError, match="不能降级到 json_object/Instructor"):
                await backend.generate(TextGenerationRequest(prompt="Extract info", response_schema=_PersonSchema))

        assert mock_client.responses.create.await_count == 1
        call_kwargs = mock_client.responses.create.call_args[1]
        assert call_kwargs["text"]["format"]["type"] == "json_schema"

    async def test_responses_schema_error_raises_without_json_object_fallback(self):
        mock_client = AsyncMock()
        mock_client.responses.create = AsyncMock(side_effect=_make_bad_request_error())

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAIResponsesTextBackend

            backend = OpenAIResponsesTextBackend(api_key="test-key", model="gpt-5.5")
            with pytest.raises(ValueError, match="接口拒绝 json_schema 请求"):
                await backend.generate(TextGenerationRequest(prompt="Extract info", response_schema=_PersonSchema))

        assert mock_client.responses.create.await_count == 1


def _make_bad_request_error(message: str = "Invalid schema") -> BadRequestError:
    """构造 OpenAI BadRequestError。"""
    return BadRequestError(
        message=message,
        response=httpx.Response(400, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")),
        body={"error": {"message": message}},
    )


class _PersonSchema(BaseModel):
    name: str
    age: int


class TestStrictStructuredOutput:
    """Strict schema 路径不能降级到 Instructor/json_object。"""

    async def test_native_structured_output_success_no_fallback(self):
        """原生 response_format 成功时，不走降级路径。"""
        schema_response = json.dumps({"name": "Alice", "age": 30})
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_make_mock_response(schema_response))

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key")
            request = TextGenerationRequest(
                prompt="Extract info",
                response_schema=_PersonSchema,
            )
            result = await backend.generate(request)

        assert result.text == schema_response
        assert mock_client.chat.completions.create.await_count == 1

    async def test_skip_native_structured_output_raises_without_fallback(self):
        """OpenAI 兼容代理不能跳过原生 json_schema 后继续声称 strict schema。"""
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock()

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(
                api_key="test-key",
                model="gpt-4o",
                prefer_native_structured_output=False,
            )
            with pytest.raises(ValueError, match="未发送原生 json_schema 请求"):
                await backend.generate(TextGenerationRequest(prompt="Extract info", response_schema=_PersonSchema))

        mock_client.chat.completions.create.assert_not_called()

    async def test_non_json_response_raises_without_fallback(self):
        """原生返回 200 但内容非 JSON 时，不能降级到 Instructor。"""
        markdown_text = "## 小说关键信息提取\n\n- 主角: 张三\n- 题材: 都市悬疑\n开放式续集铺垫"
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_make_mock_response(markdown_text, 100, 60))

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key")
            request = TextGenerationRequest(
                prompt="Extract info",
                response_schema=_PersonSchema,
            )
            with pytest.raises(ValueError, match="模型返回非 JSON 内容"):
                await backend.generate(request)

        assert mock_client.chat.completions.create.await_count == 1

    async def test_valid_json_wrong_schema_raises_without_fallback(self):
        """原生返回可解析 JSON 但不符合 Pydantic schema 时，不能降级到 Instructor。"""
        wrong_schema_json = json.dumps({"title": "Wrong shape", "language": "zh"})

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_mock_response(wrong_schema_json, 100, 60)
        )

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key")
            request = TextGenerationRequest(
                prompt="Extract info",
                response_schema=_PersonSchema,
            )
            with pytest.raises(ValueError, match="模型返回 JSON 但不符合 schema"):
                await backend.generate(request)

        assert mock_client.chat.completions.create.await_count == 1

    async def test_bad_request_error_raises_without_fallback_pydantic(self):
        """原生 response_format 抛 BadRequestError 且 schema 为 Pydantic 类时，不做降级。"""
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=_make_bad_request_error())

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key")
            request = TextGenerationRequest(
                prompt="Extract info",
                response_schema=_PersonSchema,
            )
            with pytest.raises(ValueError, match="接口拒绝 json_schema 请求"):
                await backend.generate(request)

        assert mock_client.chat.completions.create.await_count == 1

    async def test_bad_request_error_with_dict_schema_raises_without_json_object(self):
        """原生 response_format 抛 BadRequestError 且 schema 为 dict 时，不降级到 json_object。"""
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=_make_bad_request_error())

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key")
            request = TextGenerationRequest(
                prompt="Extract info",
                response_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                },
            )
            with pytest.raises(ValueError, match="不能降级到 json_object/Instructor"):
                await backend.generate(request)

        assert mock_client.chat.completions.create.await_count == 1

    async def test_bad_request_error_without_schema_propagates(self):
        """没有 response_schema 时，BadRequestError 应原样抛出，不做降级。"""
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=_make_bad_request_error())

        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="test-key")
            request = TextGenerationRequest(prompt="Just chat")
            with pytest.raises(BadRequestError):
                await backend.generate(request)

    async def test_is_schema_error_recognizes_bad_request(self):
        """_is_schema_error 正确识别 BadRequestError。"""
        from lib.text_backends.openai import _is_schema_error

        assert _is_schema_error(_make_bad_request_error()) is True
        assert _is_schema_error(ValueError("other")) is False
        assert _is_schema_error(RuntimeError("test")) is False


class TestMaxOutputTokens:
    async def test_plain_path_passes_max_tokens(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_make_mock_response("ok"))
        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="k")
            await backend.generate(TextGenerationRequest(prompt="hi", max_output_tokens=32000))

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_tokens"] == 32000

    async def test_structured_path_passes_max_tokens(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_make_mock_response(json.dumps({"name": "x"})))
        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            class MyModel(BaseModel):
                name: str

            backend = OpenAITextBackend(api_key="k")
            await backend.generate(TextGenerationRequest(prompt="hi", response_schema=MyModel, max_output_tokens=24000))

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["max_tokens"] == 24000

    async def test_no_max_tokens_means_key_absent(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_make_mock_response("ok"))
        with patch("lib.openai_shared.AsyncOpenAI", return_value=mock_client):
            from lib.text_backends.openai import OpenAITextBackend

            backend = OpenAITextBackend(api_key="k")
            await backend.generate(TextGenerationRequest(prompt="hi"))

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert "max_tokens" not in call_kwargs

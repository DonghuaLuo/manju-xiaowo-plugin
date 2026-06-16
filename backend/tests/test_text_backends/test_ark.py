"""ArkTextBackend tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lib.text_backends.ark import ArkTextBackend
from lib.text_backends.base import TextCapability, TextGenerationRequest, TextGenerationResult
from lib.text_backends.structured_probe import probe_text_structured_output_backend


@pytest.fixture
def mock_ark():
    mock_client = MagicMock()
    with patch("lib.text_backends.ark.create_ark_client", return_value=mock_client) as mock_create:
        yield mock_create, mock_client


class TestProperties:
    def test_name(self, mock_ark):
        b = ArkTextBackend(api_key="k")
        assert b.name == "ark"

    def test_default_model(self, mock_ark):
        b = ArkTextBackend(api_key="k")
        assert b.model == "doubao-seed-2-0-lite-260215"

    def test_capabilities(self, mock_ark):
        b = ArkTextBackend(api_key="k")
        assert b.capabilities == {
            TextCapability.TEXT_GENERATION,
            TextCapability.STRUCTURED_OUTPUT,
            TextCapability.VISION,
        }

    def test_no_api_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="API Key"):
                ArkTextBackend()


class TestGenerate:
    @pytest.fixture
    def backend(self, mock_ark):
        _, mock_client = mock_ark
        b = ArkTextBackend(api_key="k")
        b._test_client = mock_client
        return b

    async def test_plain_text(self, backend, sync_to_thread):
        mock_resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="  ark output  "))],
            usage=SimpleNamespace(prompt_tokens=15, completion_tokens=8),
        )
        backend._test_client.chat.completions.create = MagicMock(return_value=mock_resp)

        result = await backend.generate(TextGenerationRequest(prompt="hello"))

        assert isinstance(result, TextGenerationResult)
        assert result.text == "ark output"
        assert result.provider == "ark"
        assert result.input_tokens == 15
        assert result.output_tokens == 8


class TestVision:
    async def test_vision_uses_chat_completions(self, mock_ark, sync_to_thread):
        """vision 路径走 chat.completions.create，与 plain 共用响应解析。"""
        from lib.text_backends.base import ImageInput

        _, mock_client = mock_ark
        b = ArkTextBackend(api_key="k")

        mock_resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="  style description  "))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        )
        mock_client.chat.completions.create = MagicMock(return_value=mock_resp)

        result = await b.generate(
            TextGenerationRequest(prompt="describe style", images=[ImageInput(url="https://example.com/img.jpg")])
        )

        assert result.text == "style description"
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        # 确认走的是 chat.completions 而不是 responses API
        mock_client.chat.completions.create.assert_called_once()

    async def test_vision_message_format(self, mock_ark, sync_to_thread):
        """vision 请求构建 image_url 格式的多模态消息。"""
        from lib.text_backends.base import ImageInput

        _, mock_client = mock_ark
        b = ArkTextBackend(api_key="k")

        mock_resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
        mock_client.chat.completions.create = MagicMock(return_value=mock_resp)

        await b.generate(
            TextGenerationRequest(
                prompt="describe",
                system_prompt="you are helpful",
                images=[ImageInput(url="https://example.com/img.jpg")],
            )
        )

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        assert messages[0] == {"role": "system", "content": "you are helpful"}
        user_content = messages[1]["content"]
        assert user_content[0] == {"type": "image_url", "image_url": {"url": "https://example.com/img.jpg"}}
        assert user_content[1] == {"type": "text", "text": "describe"}


class TestCapabilityAwareStructured:
    """测试基于模型能力的结构化输出路径选择。"""

    @pytest.fixture
    def backend_no_structured(self, mock_ark):
        """创建一个模型不支持原生 structured_output 的 backend。"""
        _, mock_client = mock_ark
        b = ArkTextBackend(api_key="k", model="unknown-model-xyz")
        b._test_client = mock_client
        return b

    @pytest.fixture
    def backend_with_structured(self, mock_ark):
        """创建一个模型支持原生 structured_output 的 backend。"""
        _, mock_client = mock_ark
        b = ArkTextBackend(api_key="k", model="doubao-seed-2-0-pro-260215")
        b._test_client = mock_client
        return b

    async def test_default_model_supports_native_structured(self, mock_ark):
        """默认豆包 Seed 2.0 模型声明原生结构化输出。"""
        b = ArkTextBackend(api_key="k")
        assert TextCapability.STRUCTURED_OUTPUT in b.capabilities

    async def test_seed_2_pro_supports_native_structured(self, backend_with_structured):
        """用户常用的 doubao-seed-2-0-pro-260215 可进入 strict schema probe。"""
        assert TextCapability.STRUCTURED_OUTPUT in backend_with_structured.capabilities

    async def test_agent_plan_seed_2_pro_supports_native_structured(self, mock_ark):
        """Agent Plan 命名格式的 Seed 2.0 Pro 同样声明 strict schema 能力。"""
        b = ArkTextBackend(api_key="k", model="doubao-seed-2.0-pro")
        assert TextCapability.STRUCTURED_OUTPUT in b.capabilities

    async def test_unknown_model_does_not_support_native_structured(self, backend_no_structured):
        """未知模型不声明原生结构化输出。"""
        assert TextCapability.STRUCTURED_OUTPUT not in backend_no_structured.capabilities

    async def test_without_native_structured_raises(self, backend_no_structured):
        """模型不支持原生 json_schema 时不降级到 Instructor。"""
        from pydantic import BaseModel

        class TestModel(BaseModel):
            key: str

        with pytest.raises(ValueError, match="strict JSON Schema"):
            await backend_no_structured.generate(TextGenerationRequest(prompt="gen", response_schema=TestModel))

        backend_no_structured._test_client.chat.completions.create.assert_not_called()

    async def test_native_path_when_supported(self, backend_with_structured, sync_to_thread):
        """模型支持原生时走 response_format 路径。"""
        mock_resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"key": "value"}'))],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10),
        )
        backend_with_structured._test_client.chat.completions.create = MagicMock(return_value=mock_resp)

        schema = {"type": "object", "properties": {"key": {"type": "string"}}}
        result = await backend_with_structured.generate(TextGenerationRequest(prompt="gen", response_schema=schema))

        assert result.text == '{"key": "value"}'
        call_args = backend_with_structured._test_client.chat.completions.create.call_args
        assert "response_format" in call_args.kwargs
        assert call_args.kwargs["response_format"]["json_schema"]["strict"] is True

    async def test_structured_probe_sends_request_for_seed_2_pro(self, backend_with_structured, sync_to_thread):
        """Seed 2.0 Pro 不再在 capabilities 阶段被 probe 拦截。"""
        mock_resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"title":"probe","scenes":[]}'))],
            usage=SimpleNamespace(prompt_tokens=8, completion_tokens=6),
        )
        backend_with_structured._test_client.chat.completions.create = MagicMock(return_value=mock_resp)

        result = await probe_text_structured_output_backend(backend_with_structured)

        assert result.ok is True
        assert result.status == "supported"
        backend_with_structured._test_client.chat.completions.create.assert_called_once()

    async def test_unknown_model_does_not_claim_structured(self, mock_ark):
        """未注册模型不声明 strict schema 能力。"""
        b = ArkTextBackend(api_key="k", model="unknown-model-xyz")
        assert TextCapability.STRUCTURED_OUTPUT not in b.capabilities

    async def test_dict_schema_without_native_structured_raises(self, backend_no_structured):
        """dict schema 也不能降级成 json_object 后当作 strict schema。"""
        with pytest.raises(ValueError, match="不能降级到 json_object/Instructor"):
            await backend_no_structured.generate(TextGenerationRequest(prompt="gen", response_schema={"type": "object"}))

    async def test_truncation_warning_logged_on_finish_reason_length(
        self, backend_no_structured, sync_to_thread, caplog
    ):
        """当 Ark 返回 finish_reason=length 时应记录 WARNING。"""
        import logging

        mock_resp = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="partial"),
                    finish_reason="length",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=8192),
        )
        backend_no_structured._test_client.chat.completions.create = MagicMock(return_value=mock_resp)

        with caplog.at_level(logging.WARNING, logger="lib.text_backends.base"):
            await backend_no_structured.generate(TextGenerationRequest(prompt="hi"))

        assert any("被截断" in r.message for r in caplog.records)

    async def test_max_output_tokens_plain(self, backend_no_structured, sync_to_thread):
        """plain 路径透传 max_tokens。"""
        mock_resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="x"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )
        backend_no_structured._test_client.chat.completions.create = MagicMock(return_value=mock_resp)
        await backend_no_structured.generate(TextGenerationRequest(prompt="hi", max_output_tokens=16000))
        call_kwargs = backend_no_structured._test_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 16000

    async def test_max_output_tokens_structured_native(self, backend_with_structured, sync_to_thread):
        """原生 structured 路径透传 max_tokens。"""
        mock_resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"a":1}'))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )
        backend_with_structured._test_client.chat.completions.create = MagicMock(return_value=mock_resp)
        await backend_with_structured.generate(
            TextGenerationRequest(prompt="g", response_schema={"type": "object"}, max_output_tokens=20000)
        )
        call_kwargs = backend_with_structured._test_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 20000

    async def test_max_output_tokens_without_native_structured_raises_before_request(self, backend_no_structured):
        """模型未声明 strict schema 能力时不会发起降级请求。"""
        from pydantic import BaseModel

        class M(BaseModel):
            k: str

        with pytest.raises(ValueError, match="strict JSON Schema"):
            await backend_no_structured.generate(
                TextGenerationRequest(prompt="g", response_schema=M, max_output_tokens=24000)
            )
        backend_no_structured._test_client.chat.completions.create.assert_not_called()

    async def test_native_failure_raises_without_fallback(self, backend_with_structured, sync_to_thread):
        """原生 json_schema 运行时失败后直接暴露能力错误。"""
        backend_with_structured._test_client.chat.completions.create = MagicMock(
            side_effect=Exception("schema not supported")
        )

        with pytest.raises(ValueError, match="接口拒绝 json_schema 请求"):
            await backend_with_structured.generate(TextGenerationRequest(prompt="gen", response_schema={"type": "object"}))

        backend_with_structured._test_client.chat.completions.create.assert_called_once()

    async def test_native_invalid_structured_content_raises(self, backend_with_structured, sync_to_thread):
        """原生 response_format 被代理忽略返回非 JSON 时直接报 strict schema 错误。"""
        native_resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
        backend_with_structured._test_client.chat.completions.create = MagicMock(return_value=native_resp)

        with pytest.raises(ValueError, match="strict JSON Schema"):
            await backend_with_structured.generate(TextGenerationRequest(prompt="gen", response_schema={"type": "object"}))

        backend_with_structured._test_client.chat.completions.create.assert_called_once()


class TestBaseUrl:
    def test_custom_base_url_passes_to_both_clients(self):
        with patch("lib.text_backends.ark.create_ark_client") as mock_ark_create:
            ArkTextBackend(api_key="k", base_url="https://ark.cn-beijing.volces.com/api/plan/v3")
            mock_ark_create.assert_called_once_with(
                api_key="k",
                base_url="https://ark.cn-beijing.volces.com/api/plan/v3",
            )

    def test_default_base_url_keeps_ark_v3(self):
        from lib.ark_shared import ARK_BASE_URL

        with patch("lib.text_backends.ark.create_ark_client") as mock_ark_create:
            ArkTextBackend(api_key="k")
            mock_ark_create.assert_called_once_with(api_key="k", base_url=ARK_BASE_URL)

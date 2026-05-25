"""Tests for TextGenerator wrapper."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lib.db.base import Base
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult
from lib.text_generator import TextGenerator
from lib.usage_tracker import UsageTracker


@pytest.fixture
async def tracker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    t = UsageTracker(session_factory=factory)
    yield t
    await engine.dispose()


def _make_backend(provider="gemini", model="gemini-3-flash-preview"):
    backend = AsyncMock()
    backend.name = provider
    backend.model = model
    backend.generate = AsyncMock(
        return_value=TextGenerationResult(
            text="生成的文本",
            provider=provider,
            model=model,
            input_tokens=100,
            output_tokens=50,
        )
    )
    return backend


class TestTextGenerator:
    async def test_generate_records_usage_on_success(self, tracker):
        backend = _make_backend()
        gen = TextGenerator(backend, tracker)

        result = await gen.generate(
            TextGenerationRequest(prompt="测试"),
            project_name="demo",
        )

        assert result.text == "生成的文本"
        assert result.input_tokens == 100
        assert result.output_tokens == 50

        calls = await tracker.get_calls(project_name="demo")
        assert calls["total"] == 1
        item = calls["items"][0]
        assert item["call_type"] == "text"
        assert item["status"] == "success"
        assert item["input_tokens"] == 100
        assert item["output_tokens"] == 50
        assert item["provider"] == "gemini"
        assert item["cost_amount"] == pytest.approx((100 * 0.50 + 50 * 3.00) / 1_000_000)

    async def test_generate_records_usage_on_failure(self, tracker):
        backend = _make_backend()
        backend.generate = AsyncMock(side_effect=RuntimeError("API 超时"))
        gen = TextGenerator(backend, tracker)

        with pytest.raises(RuntimeError, match="API 超时"):
            await gen.generate(
                TextGenerationRequest(prompt="测试"),
                project_name="demo",
            )

        calls = await tracker.get_calls(project_name="demo")
        assert calls["total"] == 1
        item = calls["items"][0]
        assert item["status"] == "failed"
        assert item["cost_amount"] == 0.0
        assert "API 超时" in item["error_message"]

    async def test_generate_raises_friendly_quota_error(self, tracker):
        backend = _make_backend(provider="openai", model="gpt-image-1")
        backend.generate = AsyncMock(side_effect=RuntimeError("Error code: insufficient_quota - billing quota exceeded"))
        gen = TextGenerator(backend, tracker)

        with pytest.raises(RuntimeError, match="用量、余额或配额已达上限"):
            await gen.generate(
                TextGenerationRequest(prompt="测试"),
                project_name="demo",
            )

        calls = await tracker.get_calls(project_name="demo")
        item = calls["items"][0]
        assert "用量、余额或配额已达上限" in item["error_message"]
        assert "供应商：openai" in item["error_message"]
        assert "模型：gpt-image-1" in item["error_message"]

    async def test_generate_keeps_model_not_found_error(self, tracker):
        raw = "InvalidEndpointOrModel.NotFound: 模型不存在，或当前账号没有访问权限"
        backend = _make_backend(provider="ark", model="doubao-seedance-1-0-lite-i2v-250428")
        backend.generate = AsyncMock(side_effect=RuntimeError(raw))
        gen = TextGenerator(backend, tracker)

        with pytest.raises(RuntimeError, match="InvalidEndpointOrModel"):
            await gen.generate(
                TextGenerationRequest(prompt="测试"),
                project_name="demo",
            )

        calls = await tracker.get_calls(project_name="demo")
        item = calls["items"][0]
        assert item["error_message"] == raw

    async def test_generate_without_project_name(self, tracker):
        backend = _make_backend()
        gen = TextGenerator(backend, tracker)

        result = await gen.generate(TextGenerationRequest(prompt="工具箱调用"))

        assert result.text == "生成的文本"
        calls = await tracker.get_calls()
        assert calls["total"] == 1
        item = calls["items"][0]
        assert item["project_name"] == ""

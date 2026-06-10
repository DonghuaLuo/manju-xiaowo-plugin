"""文本 backend 工厂的运行时路由回归测试。"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lib.config.service import ConfigService
from lib.custom_provider import make_provider_id
from lib.custom_provider.backends import CustomTextBackend
from lib.db.base import Base
from lib.db.models.custom_provider import CustomProvider, CustomProviderModel
from lib.text_backends.base import TextTaskType
from lib.text_backends.factory import _runtime_custom_text_endpoint, create_text_backend_for_task


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return factory, engine


def _make_mock_resolver(**async_methods):
    mock = MagicMock()
    for name, return_value in async_methods.items():
        setattr(mock, name, AsyncMock(return_value=return_value))

    @contextlib.asynccontextmanager
    async def _session():
        yield mock

    mock.session = _session
    return mock


def test_runtime_custom_text_endpoint_keeps_saved_endpoint():
    assert _runtime_custom_text_endpoint("openai-chat", "gpt-5.5") == "openai-chat"
    assert _runtime_custom_text_endpoint("openai-responses", "gpt-5.5") == "openai-responses"
    assert _runtime_custom_text_endpoint("openai-chat", "gpt-4o") == "openai-chat"


@pytest.mark.asyncio
async def test_custom_gpt5_saved_as_openai_chat_keeps_chat_endpoint(monkeypatch):
    """自定义供应商必须尊重用户保存的 endpoint，不能按模型名偷换 Responses。"""

    factory, engine = await _make_session()
    try:
        async with factory() as session:
            provider = CustomProvider(
                display_name="Sub2API",
                discovery_format="openai",
                base_url="https://sub2api.example.com",
                api_key="sk-test",
            )
            session.add(provider)
            await session.flush()
            provider_runtime_id = make_provider_id(provider.id)
            session.add(
                CustomProviderModel(
                    provider_id=provider.id,
                    model_id="gpt-5.5",
                    display_name="GPT 5.5",
                    endpoint="openai-chat",
                    is_default=True,
                    is_enabled=True,
                )
            )
            await ConfigService(session).set_setting("default_text_backend", f"{provider_runtime_id}/gpt-5.5")
            await session.commit()

        monkeypatch.setattr("lib.text_backends.factory.async_session_factory", factory)
        with (
            patch("lib.custom_provider.endpoints.OpenAIResponsesTextBackend") as mock_responses,
            patch("lib.custom_provider.endpoints.OpenAITextBackend") as mock_chat,
        ):
            mock_chat.return_value.capabilities = set()

            backend = await create_text_backend_for_task(TextTaskType.SCRIPT)

        assert isinstance(backend, CustomTextBackend)
        mock_chat.assert_called_once_with(
            api_key="sk-test",
            base_url="https://sub2api.example.com/v1",
            model="gpt-5.5",
            provider_name=provider_runtime_id,
            prefer_native_structured_output=False,
        )
        mock_responses.assert_not_called()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dashscope_text_backend_disables_native_structured_output():
    """DashScope 复用 OpenAI-compatible 后端，但不能继续宣称原生 strict json_schema。"""

    resolver = _make_mock_resolver(
        text_backend_for_task=("dashscope", "qwen-plus"),
        provider_config={"api_key": "dash-key", "base_url": "https://dashscope.aliyuncs.com/api/v1"},
    )

    with (
        patch("lib.text_backends.factory.ConfigResolver", return_value=resolver),
        patch("lib.text_backends.factory.create_backend") as mock_create,
    ):
        mock_create.return_value = MagicMock()
        await create_text_backend_for_task(TextTaskType.SCRIPT)

    mock_create.assert_called_once_with(
        "openai",
        api_key="dash-key",
        model="qwen-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_name="dashscope",
        prefer_native_structured_output=False,
    )

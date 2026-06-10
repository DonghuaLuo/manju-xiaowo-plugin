"""文本 backend 工厂的运行时路由回归测试。"""

from __future__ import annotations

from unittest.mock import patch

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


def test_runtime_custom_text_endpoint_upgrades_stale_gpt5_chat_endpoint():
    assert _runtime_custom_text_endpoint("openai-chat", "gpt-5.5") == "openai-responses"
    assert _runtime_custom_text_endpoint("openai-chat", "gpt-4o") == "openai-chat"


@pytest.mark.asyncio
async def test_custom_gpt5_saved_as_openai_chat_routes_to_responses(monkeypatch):
    """旧自定义供应商模型无需重新发现，也应避开 /v1/chat/completions 慢路径。"""

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
            mock_responses.return_value.capabilities = set()

            backend = await create_text_backend_for_task(TextTaskType.SCRIPT)

        assert isinstance(backend, CustomTextBackend)
        mock_responses.assert_called_once_with(
            api_key="sk-test",
            base_url="https://sub2api.example.com/v1",
            model="gpt-5.5",
            provider_name=provider_runtime_id,
            send_max_output_tokens=False,
            use_input_item_list=True,
            stream_response=True,
        )
        mock_chat.assert_not_called()
    finally:
        await engine.dispose()

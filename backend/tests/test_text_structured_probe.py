from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.script_generator import ScriptGenerator
from lib.text_backends.base import TextCapability, TextGenerationResult
from lib.text_backends.structured_probe import (
    StructuredOutputProbePayload,
    ensure_text_structured_output_ready,
    probe_text_structured_output_backend,
)


class _FakeBackend:
    def __init__(
        self,
        *,
        capabilities: set[TextCapability],
        text: str = '{"title":"probe","scenes":[]}',
    ) -> None:
        self.name = "custom-1"
        self.model = "gpt-5.5"
        self.endpoint = "openai-chat"
        self.capabilities = capabilities
        self.text = text
        self.calls = 0
        self.last_request = None

    async def generate(self, request):
        self.calls += 1
        self.last_request = request
        assert request.response_schema is StructuredOutputProbePayload
        return TextGenerationResult(text=self.text, provider=self.name, model=self.model, input_tokens=8, output_tokens=6)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    _write(path, json.dumps(payload, ensure_ascii=False, indent=2))


class _PreflightFailsGenerator:
    model = "fake-model"

    async def ensure_structured_output_ready(self):
        raise ValueError("probe failed before script generation")

    async def generate(self, request, project_name=None):
        raise AssertionError("generate must not run when preflight fails")


async def test_probe_skips_request_when_capability_missing() -> None:
    backend = _FakeBackend(capabilities={TextCapability.TEXT_GENERATION})

    result = await probe_text_structured_output_backend(backend)

    assert result.ok is False
    assert result.status == "unsupported"
    assert backend.calls == 0
    assert "未声明 structured_output" in result.detail


async def test_probe_succeeds_with_minimal_strict_schema() -> None:
    backend = _FakeBackend(
        capabilities={TextCapability.TEXT_GENERATION, TextCapability.STRUCTURED_OUTPUT},
        text=json.dumps({"title": "probe", "scenes": []}),
    )

    result = await probe_text_structured_output_backend(backend)

    assert result.ok is True
    assert result.status == "supported"
    assert result.endpoint == "openai-chat"
    assert result.input_tokens == 8
    assert backend.calls == 1


async def test_probe_reports_schema_mismatch() -> None:
    backend = _FakeBackend(
        capabilities={TextCapability.TEXT_GENERATION, TextCapability.STRUCTURED_OUTPUT},
        text=json.dumps({"episode": 1}),
    )

    result = await probe_text_structured_output_backend(backend)

    assert result.ok is False
    assert result.status == "schema_not_enforced"
    assert "结构化输出无效" in result.detail
    assert backend.last_request is not None
    assert '{"episode":1}' in backend.last_request.prompt
    assert "Do not include title or scenes" in backend.last_request.prompt


async def test_ensure_raises_concise_failure() -> None:
    backend = _FakeBackend(capabilities={TextCapability.TEXT_GENERATION})

    try:
        await ensure_text_structured_output_ready(backend)
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ValueError")

    assert "custom-1/gpt-5.5" in message
    assert "capability probe" in message
    assert "endpoint=openai-chat" in message


async def test_script_generator_runs_preflight_before_model_call(tmp_path: Path) -> None:
    project_path = tmp_path / "demo"
    _write_json(
        project_path / "project.json",
        {
            "title": "项目",
            "content_mode": "drama",
            "overview": {},
            "characters": {},
            "scenes": {},
            "props": {},
            "style": "写实",
            "style_description": "cinematic",
            "_supported_durations": [4, 6, 8],
        },
    )
    _write(project_path / "drafts" / "episode_1" / "step1_normalized_script.md", "E1S01 | 场景")

    generator = ScriptGenerator(project_path, generator=_PreflightFailsGenerator())
    with pytest.raises(ValueError, match="probe failed before script generation"):
        await generator.generate(1)


async def test_project_overview_runs_preflight_before_model_call(tmp_path: Path, monkeypatch) -> None:
    from lib.project_manager import ProjectManager

    class _PreflightFailsBackend:
        name = "fake"
        model = "fake-model"
        capabilities = set()

        async def generate(self, request):
            raise AssertionError("overview generation must not run when preflight fails")

    pm = ProjectManager(tmp_path / "projects")
    pm.create_project("demo")
    pm.create_project_metadata("demo", "Demo")
    _write(pm.get_project_path("demo") / "source" / "1.txt", "source body")

    async def _fake_create_backend(*args, **kwargs):
        return _PreflightFailsBackend()

    monkeypatch.setattr("lib.text_generator.create_text_backend_for_task", _fake_create_backend)
    with pytest.raises(ValueError, match="capability probe"):
        await pm.generate_overview("demo")


async def test_ipc_dispatcher_maps_text_structured_output_probe(monkeypatch) -> None:
    from server.routers import providers as providers_router
    from utils.manju_ipc_dispatcher import dispatch_ipc_command

    async def fake_probe(body):
        return {
            "ok": True,
            "status": "supported",
            "provider": "custom-1",
            "model": "gpt-5.5",
            "detail": "strict JSON Schema probe 通过",
            "capabilities": ["structured_output", "text_generation"],
            "endpoint": "openai-chat",
            "backend_type": "CustomTextBackend",
            "delegate_type": "OpenAITextBackend",
            "input_tokens": 8,
            "output_tokens": 6,
        }

    monkeypatch.setattr(providers_router, "probe_text_structured_output", fake_probe)

    result = await dispatch_ipc_command(
        "manju_api_probe_text_structured_output",
        {
            "body": {"kind": "json", "value": {"task_type": "script", "project_name": "demo"}},
        },
    )

    assert result["success"] is True
    value = result["content"]["value"]
    assert value["ok"] is True
    assert value["endpoint"] == "openai-chat"

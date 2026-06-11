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


def _write_basic_drama_project(project_path: Path) -> None:
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
    _write(
        project_path / "drafts" / "episode_1" / "step1_normalized_script.md",
        "| scene_id | scene_description | duration_seconds | segment_break |\n"
        "| --- | --- | --- | --- |\n"
        "| E1S01 | 场景 | 4 | 是 |\n",
    )


def _valid_drama_script_payload() -> dict:
    return {
        "title": "第一集",
        "content_mode": "drama",
        "scenes": [
            {
                "scene_id": "E1S01",
                "duration_seconds": 4,
                "segment_break": True,
                "characters_in_scene": [],
                "scenes": [],
                "props": [],
                "image_prompt": {
                    "scene": "林清站在雨夜巷口，路灯从左侧打出冷白光，地面积水倒映她的身影。",
                    "composition": {
                        "shot_type": "Medium Shot",
                        "lighting": "左侧冷白路灯照亮半身，背景保持暗部层次",
                        "ambiance": "雨丝和薄雾在路灯下可见",
                    },
                },
                "video_prompt": {
                    "action": "林清缓慢抬头，手指收紧伞柄，雨水沿伞缘滴落。",
                    "camera_motion": "Static",
                    "ambiance_audio": "雨声和远处脚步声",
                    "dialogue": [],
                },
            }
        ],
    }


class _PreflightFailsGenerator:
    model = "fake-model"

    def __init__(self, responses: list[str] | None = None) -> None:
        self.requests = []
        self._responses = responses or [json.dumps(_valid_drama_script_payload(), ensure_ascii=False)]

    @property
    def last_request(self):
        return self.requests[-1] if self.requests else None

    async def ensure_structured_output_ready(self):
        raise ValueError("probe failed before script generation")

    async def generate(self, request, project_name=None):
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self._responses) - 1)
        return TextGenerationResult(
            text=self._responses[index],
            provider="fake",
            model="fake-model",
        )


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


async def test_script_generator_falls_back_when_preflight_fails(tmp_path: Path) -> None:
    project_path = tmp_path / "demo"
    _write_basic_drama_project(project_path)

    fake = _PreflightFailsGenerator()
    generator = ScriptGenerator(project_path, generator=fake)
    output = await generator.generate(1)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["scenes"][0]["scene_id"] == "E1S01"
    assert payload["metadata"]["structured_output_mode"] == "non_strict_validated"
    assert payload["metadata"]["structured_output_attempts"] == 1
    assert fake.last_request is not None
    assert fake.last_request.response_schema is None
    assert "<json_schema>" in fake.last_request.prompt


async def test_script_generator_retries_non_strict_until_local_validation_passes(tmp_path: Path) -> None:
    project_path = tmp_path / "demo"
    _write_basic_drama_project(project_path)

    fake = _PreflightFailsGenerator(
        responses=[
            "not json",
            json.dumps(_valid_drama_script_payload(), ensure_ascii=False),
        ]
    )
    generator = ScriptGenerator(project_path, generator=fake)
    output = await generator.generate(1)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["scenes"][0]["scene_id"] == "E1S01"
    assert payload["metadata"]["structured_output_attempts"] == 2
    assert len(fake.requests) == 2
    assert all(request.response_schema is None for request in fake.requests)
    assert "上一次输出未通过本地校验" in fake.requests[1].prompt


async def test_script_generator_does_not_write_invalid_non_strict_output(tmp_path: Path) -> None:
    project_path = tmp_path / "demo"
    _write_basic_drama_project(project_path)

    fake = _PreflightFailsGenerator(responses=["not json", "[]", '{"title":"bad","scenes":[]}'])
    generator = ScriptGenerator(project_path, generator=fake)

    with pytest.raises(ValueError, match="JSON 解析失败|剧本结构校验失败|剧本条目数与 Step 1 不一致"):
        await generator.generate(1)

    assert len(fake.requests) == 3
    assert not (project_path / "scripts" / "episode_1.json").exists()


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


async def test_run_agent_ops_accepts_raw_ipc_payload(monkeypatch) -> None:
    from utils import manju_agent_ops_ipc
    from utils.manju_ipc_api import handle_manju_api_command

    seen: list[dict] = []

    async def fake_run_agent_ops(body):
        seen.append(body)
        return {"success": True, "action": body["action"]}

    monkeypatch.setattr(manju_agent_ops_ipc, "run_agent_ops", fake_run_agent_ops)

    result = await handle_manju_api_command("manju_api_run_agent_ops", {"action": "list"}, sdk=None)

    assert result == {"success": True, "action": "list"}
    assert seen == [{"action": "list"}]


async def test_run_agent_ops_accepts_wrapped_json_body(monkeypatch) -> None:
    from utils import manju_agent_ops_ipc
    from utils.manju_ipc_api import handle_manju_api_command

    seen: list[dict] = []

    async def fake_run_agent_ops(body):
        seen.append(body)
        return {"success": True, "script_id": body["script_id"], "dry_run": body["dry_run"]}

    monkeypatch.setattr(manju_agent_ops_ipc, "run_agent_ops", fake_run_agent_ops)

    result = await handle_manju_api_command(
        "manju_api_run_agent_ops",
        {
            "body": {
                "kind": "json",
                "value": {
                    "action": "run",
                    "script_id": "text_structured_output_probe",
                    "dry_run": True,
                },
            }
        },
        sdk=None,
    )

    assert result == {"success": True, "script_id": "text_structured_output_probe", "dry_run": True}
    assert seen == [
        {
            "action": "run",
            "script_id": "text_structured_output_probe",
            "dry_run": True,
        }
    ]


async def test_agent_ops_autofix_writes_runtime_repair_task(tmp_path: Path, monkeypatch) -> None:
    from utils import agent_ops_autofix

    repair_dir = tmp_path / "repair-runs"
    monkeypatch.setattr(agent_ops_autofix, "REPAIR_RUNS_DIR", repair_dir)
    monkeypatch.delenv("MANJU_AGENT_OPS_AGENT_COMMAND", raising=False)
    monkeypatch.setenv("MANJU_AGENT_OPS_AUTO_REPAIR", "1")
    monkeypatch.setattr(
        agent_ops_autofix,
        "_run_default_sdk_agent_repair",
        lambda **_kwargs: {
            "success": True,
            "returncode": 0,
            "timed_out": False,
            "mode": "default_sdk",
            "command": "claude_agent_sdk.query",
            "stdout": "repaired",
            "stderr": "",
            "error": None,
        },
    )
    monkeypatch.setattr(
        agent_ops_autofix,
        "_run_registry_check",
        lambda script_id, timeout_seconds: {
            "success": True,
            "returncode": 0,
            "timed_out": False,
            "stdout": "OK",
            "stderr": "",
            "error": None,
        },
    )

    result = await agent_ops_autofix.auto_repair_runtime_failure(
        script_id="text_structured_output_probe",
        tool_name="generate_episode_script",
        failure_stage="episode_script_json_generation",
        exc=RuntimeError("strict schema blocked"),
        context={"episode": 1},
    )

    assert result["enabled"] is True
    assert result["agent_command_configured"] is False
    assert result["agent_repair_attempted"] is True
    assert result["agent_repair_mode"] == "default_sdk"
    assert result["repaired"] is True
    task_path = repair_dir / Path(result["repair_task"]).name
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    assert payload["trigger"] == "runtime_failure"
    assert payload["script_id"] == "text_structured_output_probe"
    assert payload["tool_name"] == "generate_episode_script"
    assert payload["context"]["episode"] == 1

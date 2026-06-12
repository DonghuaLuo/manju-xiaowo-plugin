"""Tests for ArcReel SDK in-process MCP tools.

Each tool: 1 happy-path and 1 error-path. Heavy plumbing
(``batch_enqueue_and_wait`` / ``enqueue_and_wait`` / ``ScriptGenerator`` etc.)
is monkeypatched, so the tests exercise schema wiring + error envelope
behavior without hitting the real queue or providers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from server.agent_runtime.sdk_tools import build_arcreel_mcp_server
from server.agent_runtime.sdk_tools._context import ToolContext
from server.agent_runtime.sdk_tools._generation_quality import route_summary
from server.agent_runtime.sdk_tools.enqueue_assets import (
    generate_assets_tool,
    list_pending_assets_tool,
)
from server.agent_runtime.sdk_tools.enqueue_grid import generate_grid_tool
from server.agent_runtime.sdk_tools.enqueue_storyboards import generate_storyboards_tool
from server.agent_runtime.sdk_tools.enqueue_videos import (
    generate_video_all_tool,
    generate_video_episode_tool,
    generate_video_scene_tool,
    generate_video_selected_tool,
)
from server.agent_runtime.sdk_tools.project_sources import (
    list_source_files_tool,
    peek_split_point_tool,
    reset_episode_artifacts_tool,
    source_info_tool,
    split_episode_tool,
)
from server.agent_runtime.sdk_tools.text_generation import (
    generate_episode_script_tool,
    get_video_capabilities_tool,
    normalize_drama_script_tool,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakePM:
    def __init__(self, project_name: str, project_dir: Path):
        self._project_name = project_name
        self._project_dir = project_dir
        self.project_payload: dict[str, Any] = {
            "characters": {"张三": {"description": "主角"}, "李四": {"description": ""}},
            "scenes": {"村口": {"description": "黄昏的村口"}},
            "props": {},
            "style": "anime",
            "style_description": "soft pastel",
        }
        self.script_payload: dict[str, Any] = {
            "content_mode": "narration",
            "episode": 1,
            "segments": [
                {
                    "segment_id": "E1S01",
                    "image_prompt": "村口黄昏",
                    "video_prompt": "镜头平移",
                    "duration_seconds": 4,
                    "generated_assets": {"storyboard_image": "storyboards/scene_E1S01.png"},
                },
            ],
        }

    def get_project_path(self, _name: str) -> Path:
        return self._project_dir

    def load_project(self, _name: str) -> dict[str, Any]:
        return self.project_payload

    def load_script(self, _name: str, _filename: str) -> dict[str, Any]:
        return self.script_payload

    def project_exists(self, _name: str) -> bool:
        return True

    def get_pending_characters(self, _name: str) -> list[dict[str, Any]]:
        return [
            {"name": "张三", "description": "主角描述"},
            {"name": "李四", "description": ""},
        ]

    def get_pending_project_scenes(self, _name: str) -> list[dict[str, Any]]:
        return [{"name": "村口", "description": "黄昏村口"}]

    def get_pending_project_props(self, _name: str) -> list[dict[str, Any]]:
        return []


@pytest.fixture
def fake_ctx(tmp_path: Path) -> ToolContext:
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    # Build a storyboard image so video tools can find it.
    (project_dir / "storyboards").mkdir()
    (project_dir / "storyboards" / "scene_E1S01.png").write_bytes(b"")

    return ToolContext(
        project_name="demo",
        projects_root=tmp_path,
        pm=_FakePM("demo", project_dir),  # type: ignore[arg-type]
    )


async def _call(tool_obj, args: dict[str, Any]) -> dict[str, Any]:
    return await tool_obj.handler(args)


# ---------------------------------------------------------------------------
# build_arcreel_mcp_server
# ---------------------------------------------------------------------------


def test_build_arcreel_mcp_server_contains_all_tools(tmp_path: Path) -> None:
    srv = build_arcreel_mcp_server(project_name="demo", projects_root=tmp_path)
    assert srv["name"] == "arcreel"
    # SDK exposes the registered tools on srv["instance"]; we just sanity-check
    # the type returned matches the spec contract.
    assert "instance" in srv


# ---------------------------------------------------------------------------
# validate_script_filename — shared guard for all enqueue tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "scripts/episode_1.json",  # 任何分隔符都拒（包括 scripts/ 前缀）
        "../etc/passwd",
        "sub/dir/file.json",
        "a\\b.json",
        ".",
        "..",
    ],
)
def test_validate_script_filename_rejects_paths(bad: str) -> None:
    from server.agent_runtime.sdk_tools._context import validate_script_filename

    with pytest.raises(ValueError):
        validate_script_filename(bad)


def test_validate_script_filename_accepts_basename() -> None:
    from server.agent_runtime.sdk_tools._context import validate_script_filename

    assert validate_script_filename("episode_1.json") == "episode_1.json"


async def test_generate_storyboards_rejects_path_in_script_arg(fake_ctx: ToolContext) -> None:
    """Agent 传带路径分隔符的 script 名必须被 handler 拒绝（共享 validate_script_filename 防御）。"""
    tool_obj = generate_storyboards_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "../etc/passwd"})
    assert out.get("is_error") is True
    assert "路径分隔符" in out["content"][0]["text"]


# ---------------------------------------------------------------------------
# project_sources — shell-free source inspection / split / reset
# ---------------------------------------------------------------------------


async def test_project_source_tools_split_and_reset_episode(fake_ctx: ToolContext) -> None:
    """分集规划不再依赖 shell：MCP 工具完成统计、peek、split 和固定产物清理。"""
    project_path = fake_ctx.project_path
    source_dir = project_path / "source"
    source_dir.mkdir()
    (source_dir / "novel.txt").write_text("一二三四五。六七八九十。十一十二十三。", encoding="utf-8")

    list_out = await _call(list_source_files_tool(fake_ctx), {})
    assert list_out.get("is_error") is not True
    list_payload = json.loads(list_out["content"][0]["text"])
    assert list_payload["preferred_source"] == "source/novel.txt"

    info_out = await _call(source_info_tool(fake_ctx), {"source": "source/novel.txt"})
    assert info_out.get("is_error") is not True
    info_payload = json.loads(info_out["content"][0]["text"])
    assert info_payload["reading_units"] > 10
    assert "context_before" not in info_out["content"][0]["text"]

    peek_out = await _call(peek_split_point_tool(fake_ctx), {"source": "source/novel.txt", "target": 6})
    assert peek_out.get("is_error") is not True
    peek_payload = json.loads(peek_out["content"][0]["text"])
    assert peek_payload["split_target_chars"] >= 1
    assert peek_payload["nearby_breakpoints"]

    split_args = {
        "source": "source/novel.txt",
        "episode": 1,
        "target": peek_payload["split_target_chars"],
        "anchor": "一二三四五。",
    }
    dry_out = await _call(split_episode_tool(fake_ctx), {**split_args, "dry_run": True})
    assert dry_out.get("is_error") is not True
    assert not (source_dir / "episode_1.txt").exists()

    split_out = await _call(split_episode_tool(fake_ctx), split_args)
    assert split_out.get("is_error") is not True
    assert (source_dir / "episode_1.txt").read_text(encoding="utf-8") == "一二三四五。"
    assert (source_dir / "_remaining.txt").read_text(encoding="utf-8").startswith("六七八九十")

    scripts_dir = project_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "episode_1.json").write_text("{}", encoding="utf-8")
    draft_dir = project_path / "drafts" / "episode_1"
    draft_dir.mkdir(parents=True)
    (draft_dir / "step1_segments.md").write_text("draft", encoding="utf-8")

    reset_out = await _call(reset_episode_artifacts_tool(fake_ctx), {"episode": 1})
    assert reset_out.get("is_error") is not True
    assert (source_dir / "episode_1.txt").exists()
    assert not (scripts_dir / "episode_1.json").exists()
    assert not draft_dir.exists()
    assert (source_dir / "_remaining.txt").exists()

    reset_source_out = await _call(reset_episode_artifacts_tool(fake_ctx), {"episode": 1, "include_source": True})
    assert reset_source_out.get("is_error") is not True
    assert not (source_dir / "episode_1.txt").exists()


async def test_project_source_tools_reject_path_escape(fake_ctx: ToolContext) -> None:
    source_dir = fake_ctx.project_path / "source"
    source_dir.mkdir()
    (source_dir / "novel.txt").write_text("正文", encoding="utf-8")

    out = await _call(source_info_tool(fake_ctx), {"source": "../outside.txt"})

    assert out.get("is_error") is True
    assert "源文件必须位于" in out["content"][0]["text"]


# ---------------------------------------------------------------------------
# enqueue_assets
# ---------------------------------------------------------------------------


async def test_list_pending_assets_happy(fake_ctx: ToolContext) -> None:
    tool_obj = list_pending_assets_tool(fake_ctx)
    out = await _call(tool_obj, {})
    assert out.get("is_error") is not True
    text = out["content"][0]["text"]
    assert "张三" in text
    assert "村口" in text


async def test_list_pending_assets_error(fake_ctx: ToolContext, monkeypatch) -> None:
    def boom(_name):
        raise RuntimeError("db down")

    fake_ctx.pm.get_pending_characters = boom  # type: ignore[attr-defined]
    tool_obj = list_pending_assets_tool(fake_ctx)
    out = await _call(tool_obj, {"type": "character"})
    assert out.get("is_error") is True


async def test_generate_assets_happy(fake_ctx: ToolContext, monkeypatch) -> None:
    from server.agent_runtime.sdk_tools import enqueue_assets as mod

    captured_quality: list[str] = []

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        from lib.generation_queue_client import BatchTaskResult

        captured_quality.extend(s.payload["quality"] for s in specs)
        succ = [
            BatchTaskResult(
                resource_id=s.resource_id,
                task_id="t1",
                status="succeeded",
                result={"file_path": f"characters/{s.resource_id}.png", "version": 1},
            )
            for s in specs
        ]
        return succ, []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    tool_obj = generate_assets_tool(fake_ctx)
    out = await _call(tool_obj, {"type": "character"})
    assert out.get("is_error") is not True
    text = out["content"][0]["text"]
    assert "1 succeeded" in text
    assert "张三" in text
    assert captured_quality == ["final"]


async def test_generate_assets_names_without_type(fake_ctx: ToolContext) -> None:
    tool_obj = generate_assets_tool(fake_ctx)
    out = await _call(tool_obj, {"names": ["张三"]})
    assert out.get("is_error") is True


# ---------------------------------------------------------------------------
# enqueue_storyboards
# ---------------------------------------------------------------------------


async def test_generate_storyboards_happy(fake_ctx: ToolContext, monkeypatch) -> None:
    from server.agent_runtime.sdk_tools import enqueue_storyboards as mod

    captured_quality: list[str] = []
    captured_ids: list[str] = []

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        from lib.generation_queue_client import BatchTaskResult

        captured_quality.extend(s.payload["quality"] for s in specs)
        captured_ids.extend(s.resource_id for s in specs)
        succ = [
            BatchTaskResult(
                resource_id=s.resource_id,
                task_id="t1",
                status="succeeded",
                result={"file_path": f"storyboards/scene_{s.resource_id}.png"},
            )
            for s in specs
        ]
        return succ, []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    # Strip storyboard_image to force selection
    fake_ctx.pm.script_payload["segments"][0]["generated_assets"] = {}  # type: ignore[attr-defined]
    tool_obj = generate_storyboards_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json"})
    assert out.get("is_error") is not True
    assert captured_quality == ["draft"]
    assert captured_ids == ["E1S01"]


async def test_generate_storyboards_final_requires_explicit_selection_mode(fake_ctx: ToolContext) -> None:
    tool_obj = generate_storyboards_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json", "quality": "final"})

    assert out.get("is_error") is True
    assert "selection_mode" in out["content"][0]["text"]


async def test_generate_storyboards_refine_current_all_requires_explicit_mode(
    fake_ctx: ToolContext,
    monkeypatch,
) -> None:
    from server.agent_runtime.sdk_tools import enqueue_storyboards as mod

    captured: list[tuple[str, str]] = []

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        from lib.generation_queue_client import BatchTaskResult

        captured.extend((s.resource_id, s.payload["quality"]) for s in specs)
        succ = [
            BatchTaskResult(
                resource_id=s.resource_id,
                task_id=f"task-{s.resource_id}",
                status="succeeded",
                result={"file_path": f"storyboards/scene_{s.resource_id}.png"},
            )
            for s in specs
        ]
        return succ, []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    tool_obj = generate_storyboards_tool(fake_ctx)
    out = await _call(
        tool_obj,
        {"script": "episode_1.json", "quality": "final", "selection_mode": "current_all"},
    )

    assert out.get("is_error") is not True
    assert captured == [("E1S01", "final")]


async def test_generate_storyboards_refine_current_unrefined_uses_current_version_only(
    fake_ctx: ToolContext,
    monkeypatch,
) -> None:
    from lib.version_manager import VersionManager
    from server.agent_runtime.sdk_tools import enqueue_storyboards as mod

    project_dir = fake_ctx.project_path
    storyboard_dir = project_dir / "storyboards"
    (storyboard_dir / "scene_E1S02.png").write_bytes(b"draft")
    fake_ctx.pm.script_payload["segments"].append(  # type: ignore[attr-defined]
        {
            "segment_id": "E1S02",
            "image_prompt": "村口夜色",
            "video_prompt": "镜头推进",
            "generated_assets": {"storyboard_image": "storyboards/scene_E1S02.png"},
        }
    )
    versions = VersionManager(project_dir)
    versions.backup_current(
        "storyboards",
        "E1S01",
        storyboard_dir / "scene_E1S01.png",
        "prompt",
        generation_quality="final",
    )
    versions.backup_current(
        "storyboards",
        "E1S02",
        storyboard_dir / "scene_E1S02.png",
        "prompt",
        generation_quality="draft",
    )

    captured: list[str] = []

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        from lib.generation_queue_client import BatchTaskResult

        captured.extend(s.resource_id for s in specs)
        return [
            BatchTaskResult(
                resource_id=s.resource_id,
                task_id=f"task-{s.resource_id}",
                status="succeeded",
                result={"file_path": f"storyboards/scene_{s.resource_id}.png"},
            )
            for s in specs
        ], []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    tool_obj = generate_storyboards_tool(fake_ctx)
    out = await _call(
        tool_obj,
        {"script": "episode_1.json", "quality": "final", "selection_mode": "current_unrefined"},
    )

    assert out.get("is_error") is not True
    assert captured == ["E1S02"]


async def test_generate_storyboards_refine_selected_requires_existing_source(fake_ctx: ToolContext) -> None:
    fake_ctx.pm.script_payload["segments"][0]["generated_assets"] = {}  # type: ignore[attr-defined]
    tool_obj = generate_storyboards_tool(fake_ctx)
    out = await _call(
        tool_obj,
        {
            "script": "episode_1.json",
            "selection_mode": "selected",
            "segment_ids": ["E1S01"],
            "quality": "final",
        },
    )

    assert out.get("is_error") is True
    assert "缺少可精修源图" in out["content"][0]["text"]


async def test_generate_storyboards_missing_treats_missing_file_as_missing(
    fake_ctx: ToolContext,
    monkeypatch,
) -> None:
    from server.agent_runtime.sdk_tools import enqueue_storyboards as mod

    fake_ctx.pm.script_payload["segments"][0]["generated_assets"]["storyboard_image"] = "storyboards/missing.png"  # type: ignore[attr-defined]
    captured: list[str] = []

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        captured.extend(spec.resource_id for spec in specs)
        return [], []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    tool_obj = generate_storyboards_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json"})

    assert out.get("is_error") is not True
    assert captured == ["E1S01"]


async def test_generate_storyboards_error(fake_ctx: ToolContext, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise ValueError("bad script")

    fake_ctx.pm.load_script = boom  # type: ignore[attr-defined]
    tool_obj = generate_storyboards_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json"})
    assert out.get("is_error") is True


# ---------------------------------------------------------------------------
# enqueue_grid
# ---------------------------------------------------------------------------


async def test_generate_grid_list_only(fake_ctx: ToolContext) -> None:
    fake_ctx.pm.project_payload["generation_mode"] = "grid"  # type: ignore[attr-defined]
    # Need enough segments to form a group with valid layout
    fake_ctx.pm.script_payload["segments"] = [  # type: ignore[attr-defined]
        {"segment_id": f"E1S0{i}", "image_prompt": "p", "segment_break": False} for i in range(1, 5)
    ]
    tool_obj = generate_grid_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json", "list_only": True})
    assert out.get("is_error") is not True
    assert "分组" in out["content"][0]["text"]


async def test_generate_grid_scene_ids_filters_to_matching_chunk(fake_ctx: ToolContext, monkeypatch) -> None:
    from server.agent_runtime.sdk_tools import enqueue_grid as mod

    fake_ctx.pm.project_payload["generation_mode"] = "grid"  # type: ignore[attr-defined]
    fake_ctx.pm.script_payload["segments"] = [  # type: ignore[attr-defined]
        {
            "segment_id": f"E1S0{i}",
            "image_prompt": f"prompt {i}",
            "video_prompt": f"video {i}",
            "duration_seconds": 4,
            "segment_break": False,
        }
        for i in range(1, 6)
    ]
    captured_scene_ids: list[list[str]] = []

    async def fake_enqueue_task_only(**kwargs):
        captured_scene_ids.append(kwargs["payload"]["scene_ids"])
        return {"task_id": f"task-{len(captured_scene_ids)}"}

    async def fake_wait_for_task(_task_id: str) -> dict[str, str]:
        return {"status": "succeeded"}

    monkeypatch.setattr(mod, "enqueue_task_only", fake_enqueue_task_only)
    monkeypatch.setattr(mod, "wait_for_task", fake_wait_for_task)

    tool_obj = generate_grid_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json", "scene_ids": ["E1S05"]})

    assert out.get("is_error") is not True
    assert captured_scene_ids == [["E1S05"]]


async def test_generate_grid_wrong_mode(fake_ctx: ToolContext) -> None:
    # project doesn't have generation_mode='grid' → error
    tool_obj = generate_grid_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json"})
    assert out.get("is_error") is True


# ---------------------------------------------------------------------------
# enqueue_videos
# ---------------------------------------------------------------------------


async def test_generate_video_episode_happy(fake_ctx: ToolContext, monkeypatch) -> None:
    from server.agent_runtime.sdk_tools import enqueue_videos as mod

    captured_quality: list[str] = []
    project_dir = fake_ctx.project_path
    (project_dir / "videos").mkdir()
    (project_dir / "videos" / "scene_E1S01.mp4").write_bytes(b"draft-video")
    fake_ctx.pm.script_payload["segments"][0]["generated_assets"]["video_clip"] = "videos/scene_E1S01.mp4"  # type: ignore[attr-defined]

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        from lib.generation_queue_client import BatchTaskResult

        for spec in specs:
            captured_quality.append(spec.payload["quality"])
            br = BatchTaskResult(
                resource_id=spec.resource_id,
                task_id="t1",
                status="succeeded",
                result={"file_path": f"videos/scene_{spec.resource_id}.mp4"},
            )
            if on_success:
                on_success(br)
        return [], []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    tool_obj = generate_video_episode_tool(fake_ctx)
    out = await _call(
        tool_obj,
        {"script": "episode_1.json", "quality": "final", "refine_scope": "current_all"},
    )
    assert out.get("is_error") is not True
    assert captured_quality == ["final"]


async def test_generate_video_episode_final_requires_refine_scope(fake_ctx: ToolContext) -> None:
    tool_obj = generate_video_episode_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json", "quality": "final"})

    assert out.get("is_error") is True
    assert "refine_scope" in out["content"][0]["text"]


async def test_generate_video_episode_default_skips_existing_current_video(
    fake_ctx: ToolContext,
    monkeypatch,
) -> None:
    from server.agent_runtime.sdk_tools import enqueue_videos as mod

    project_dir = fake_ctx.project_path
    (project_dir / "videos").mkdir()
    (project_dir / "videos" / "scene_E1S01.mp4").write_bytes(b"existing-video")
    (project_dir / "storyboards" / "scene_E1S02.png").write_bytes(b"storyboard")
    fake_ctx.pm.script_payload["segments"][0]["generated_assets"]["video_clip"] = "videos/scene_E1S01.mp4"  # type: ignore[attr-defined]
    fake_ctx.pm.script_payload["segments"].append(  # type: ignore[attr-defined]
        {
            "segment_id": "E1S02",
            "image_prompt": "夜色",
            "video_prompt": "镜头推进",
            "generated_assets": {"storyboard_image": "storyboards/scene_E1S02.png"},
        }
    )
    captured: list[str] = []

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        from lib.generation_queue_client import BatchTaskResult

        for spec in specs:
            captured.append(spec.resource_id)
            if on_success:
                on_success(
                    BatchTaskResult(
                        resource_id=spec.resource_id,
                        task_id=f"task-{spec.resource_id}",
                        status="succeeded",
                        result={"file_path": f"videos/scene_{spec.resource_id}.mp4"},
                    )
                )
        return [], []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    tool_obj = generate_video_episode_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json"})

    assert out.get("is_error") is not True
    assert captured == ["E1S02"]


async def test_generate_video_episode_regenerate_existing_is_explicit(
    fake_ctx: ToolContext,
    monkeypatch,
) -> None:
    from server.agent_runtime.sdk_tools import enqueue_videos as mod

    project_dir = fake_ctx.project_path
    (project_dir / "videos").mkdir()
    (project_dir / "videos" / "scene_E1S01.mp4").write_bytes(b"existing-video")
    fake_ctx.pm.script_payload["segments"][0]["generated_assets"]["video_clip"] = "videos/scene_E1S01.mp4"  # type: ignore[attr-defined]
    captured: list[str] = []

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        from lib.generation_queue_client import BatchTaskResult

        for spec in specs:
            captured.append(spec.resource_id)
            if on_success:
                on_success(
                    BatchTaskResult(
                        resource_id=spec.resource_id,
                        task_id=f"task-{spec.resource_id}",
                        status="succeeded",
                        result={"file_path": f"videos/scene_{spec.resource_id}.mp4"},
                    )
                )
        return [], []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    tool_obj = generate_video_episode_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json", "regenerate_existing": True})

    assert out.get("is_error") is not True
    assert captured == ["E1S01"]


async def test_generate_video_episode_error(fake_ctx: ToolContext) -> None:
    fake_ctx.pm.script_payload = {"content_mode": "narration", "segments": [], "episode": 1}  # type: ignore[attr-defined]
    tool_obj = generate_video_episode_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json"})
    assert out.get("is_error") is True


async def test_generate_video_scene_happy(fake_ctx: ToolContext, monkeypatch) -> None:
    from server.agent_runtime.sdk_tools import enqueue_videos as mod

    async def fake_enqueue(**kwargs):
        return {"task": {}, "result": {"file_path": "videos/scene_E1S01.mp4"}}

    monkeypatch.setattr(mod, "enqueue_and_wait", fake_enqueue)
    tool_obj = generate_video_scene_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json", "scene_id": "E1S01"})
    assert out.get("is_error") is not True


async def test_generate_video_scene_missing(fake_ctx: ToolContext) -> None:
    tool_obj = generate_video_scene_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json", "scene_id": "NO_SUCH"})
    assert out.get("is_error") is True


async def test_generate_video_all_happy(fake_ctx: ToolContext, monkeypatch) -> None:
    from server.agent_runtime.sdk_tools import enqueue_videos as mod

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        from lib.generation_queue_client import BatchTaskResult

        succ = [
            BatchTaskResult(
                resource_id=s.resource_id, task_id="t1", status="succeeded", result={"file_path": "videos/x.mp4"}
            )
            for s in specs
        ]
        return succ, []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    tool_obj = generate_video_all_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json"})
    assert out.get("is_error") is not True


async def test_generate_video_all_refine_current_unrefined_uses_current_version_only(
    fake_ctx: ToolContext,
    monkeypatch,
) -> None:
    from lib.version_manager import VersionManager
    from server.agent_runtime.sdk_tools import enqueue_videos as mod

    project_dir = fake_ctx.project_path
    (project_dir / "videos").mkdir()
    (project_dir / "videos" / "scene_E1S01.mp4").write_bytes(b"final-video")
    (project_dir / "storyboards" / "scene_E1S02.png").write_bytes(b"storyboard")
    (project_dir / "videos" / "scene_E1S02.mp4").write_bytes(b"draft-video")
    fake_ctx.pm.script_payload["segments"][0]["generated_assets"]["video_clip"] = "videos/scene_E1S01.mp4"  # type: ignore[attr-defined]
    fake_ctx.pm.script_payload["segments"].append(  # type: ignore[attr-defined]
        {
            "segment_id": "E1S02",
            "image_prompt": "夜色",
            "video_prompt": "镜头推进",
            "generated_assets": {
                "storyboard_image": "storyboards/scene_E1S02.png",
                "video_clip": "videos/scene_E1S02.mp4",
            },
        }
    )
    versions = VersionManager(project_dir)
    versions.backup_current(
        "videos",
        "E1S01",
        project_dir / "videos" / "scene_E1S01.mp4",
        "prompt",
        generation_quality="final",
    )
    versions.backup_current(
        "videos",
        "E1S02",
        project_dir / "videos" / "scene_E1S02.mp4",
        "prompt",
        generation_quality="draft",
    )

    captured: list[str] = []

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        from lib.generation_queue_client import BatchTaskResult

        captured.extend(s.resource_id for s in specs)
        return [
            BatchTaskResult(
                resource_id=s.resource_id,
                task_id=f"task-{s.resource_id}",
                status="succeeded",
                result={"file_path": f"videos/scene_{s.resource_id}.mp4"},
            )
            for s in specs
        ], []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    tool_obj = generate_video_all_tool(fake_ctx)
    out = await _call(
        tool_obj,
        {"script": "episode_1.json", "quality": "final", "refine_scope": "current_unrefined"},
    )

    assert out.get("is_error") is not True
    assert captured == ["E1S02"]


async def test_generate_video_all_treats_missing_file_as_pending(
    fake_ctx: ToolContext,
    monkeypatch,
) -> None:
    from server.agent_runtime.sdk_tools import enqueue_videos as mod

    fake_ctx.pm.script_payload["segments"][0]["generated_assets"]["video_clip"] = "videos/missing.mp4"  # type: ignore[attr-defined]
    captured: list[str] = []

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        from lib.generation_queue_client import BatchTaskResult

        for spec in specs:
            captured.append(spec.resource_id)
            if on_success:
                on_success(
                    BatchTaskResult(
                        resource_id=spec.resource_id,
                        task_id=f"task-{spec.resource_id}",
                        status="succeeded",
                        result={"file_path": f"videos/scene_{spec.resource_id}.mp4"},
                    )
                )
        return [], []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    tool_obj = generate_video_all_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json"})

    assert out.get("is_error") is not True
    assert captured == ["E1S01"]


async def test_generate_video_all_treats_video_clip_directory_as_pending(
    fake_ctx: ToolContext,
    monkeypatch,
) -> None:
    from server.agent_runtime.sdk_tools import enqueue_videos as mod

    video_dir = fake_ctx.project_path / "videos" / "scene_E1S01.mp4"
    video_dir.mkdir(parents=True)
    fake_ctx.pm.script_payload["segments"][0]["generated_assets"]["video_clip"] = "videos/scene_E1S01.mp4"  # type: ignore[attr-defined]
    captured: list[str] = []

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        from lib.generation_queue_client import BatchTaskResult

        for spec in specs:
            captured.append(spec.resource_id)
            if on_success:
                on_success(
                    BatchTaskResult(
                        resource_id=spec.resource_id,
                        task_id=f"task-{spec.resource_id}",
                        status="succeeded",
                        result={"file_path": f"videos/scene_{spec.resource_id}.mp4"},
                    )
                )
        return [], []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    tool_obj = generate_video_all_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json"})

    assert out.get("is_error") is not True
    assert captured == ["E1S01"]


async def test_generate_video_all_error(fake_ctx: ToolContext) -> None:
    def boom(*a, **kw):
        raise RuntimeError("broken")

    fake_ctx.pm.load_script = boom  # type: ignore[attr-defined]
    tool_obj = generate_video_all_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json"})
    assert out.get("is_error") is True


async def test_generate_video_selected_happy(fake_ctx: ToolContext, monkeypatch) -> None:
    from server.agent_runtime.sdk_tools import enqueue_videos as mod

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        from lib.generation_queue_client import BatchTaskResult

        for s in specs:
            if on_success:
                on_success(
                    BatchTaskResult(
                        resource_id=s.resource_id,
                        task_id="t1",
                        status="succeeded",
                        result={"file_path": f"videos/scene_{s.resource_id}.mp4"},
                    )
                )
        return [], []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    tool_obj = generate_video_selected_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json", "scene_ids": ["E1S01"]})
    assert out.get("is_error") is not True


async def test_generate_video_selected_no_match(fake_ctx: ToolContext) -> None:
    tool_obj = generate_video_selected_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json", "scene_ids": ["NO_SUCH"]})
    assert out.get("is_error") is True


async def test_generate_video_scene_reference_mode_targets_single_unit(
    fake_ctx: ToolContext,
    monkeypatch,
) -> None:
    from server.agent_runtime.sdk_tools import enqueue_videos as mod

    fake_ctx.pm.script_payload = {  # type: ignore[attr-defined]
        "generation_mode": "reference_video",
        "episode": 1,
        "video_units": [
            {"unit_id": "E1U1", "duration_seconds": 4, "shots": [{"duration": 4, "text": "@张三 起身"}]},
            {"unit_id": "E1U2", "duration_seconds": 7, "shots": [{"duration": 7, "text": "@李四 转身"}]},
        ],
    }
    captured: list[tuple[str, int | None, str]] = []

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        from lib.generation_queue_client import BatchTaskResult

        for spec in specs:
            captured.append(
                (
                    spec.resource_id,
                    spec.payload.get("duration_seconds"),
                    spec.payload.get("quality"),
                )
            )
            if on_success:
                on_success(
                    BatchTaskResult(
                        resource_id=spec.resource_id,
                        task_id=f"task-{spec.resource_id}",
                        status="succeeded",
                        result={"file_path": f"reference_videos/{spec.resource_id}.mp4"},
                    )
                )
        return [], []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    tool_obj = generate_video_scene_tool(fake_ctx)
    out = await _call(tool_obj, {"script": "episode_1.json", "scene_id": "E1U2", "quality": "final"})

    assert out.get("is_error") is not True
    assert captured == [("E1U2", 7, "final")]
    assert "共 1 个 unit" in out["content"][0]["text"]


async def test_generate_video_selected_reference_mode_targets_requested_units(
    fake_ctx: ToolContext,
    monkeypatch,
) -> None:
    from server.agent_runtime.sdk_tools import enqueue_videos as mod

    fake_ctx.pm.script_payload = {  # type: ignore[attr-defined]
        "generation_mode": "reference_video",
        "episode": 1,
        "video_units": [
            {"unit_id": "E1U1", "duration_seconds": 4, "shots": [{"duration": 4, "text": "@张三 起身"}]},
            {"unit_id": "E1U2", "duration_seconds": 8, "shots": [{"duration": 8, "text": "@李四 转身"}]},
            {"unit_id": "E1U3", "duration_seconds": 6, "shots": [{"duration": 6, "text": "@王五 看向远处"}]},
        ],
    }
    captured: list[str] = []

    async def fake_batch(*, project_name, specs, on_success=None, on_failure=None):
        from lib.generation_queue_client import BatchTaskResult

        for spec in specs:
            captured.append(spec.resource_id)
            if on_success:
                on_success(
                    BatchTaskResult(
                        resource_id=spec.resource_id,
                        task_id=f"task-{spec.resource_id}",
                        status="succeeded",
                        result={"file_path": f"reference_videos/{spec.resource_id}.mp4"},
                    )
                )
        return [], []

    monkeypatch.setattr(mod, "batch_enqueue_and_wait", fake_batch)
    tool_obj = generate_video_selected_tool(fake_ctx)
    out = await _call(
        tool_obj,
        {"script": "episode_1.json", "scene_ids": ["E1U3", "NO_SUCH", "E1U1", "E1U3"]},
    )

    assert out.get("is_error") is not True
    assert captured == ["E1U3", "E1U1"]
    assert "NO_SUCH" in out["content"][0]["text"]


def test_build_asset_specs_skips_invalid_description(monkeypatch) -> None:
    """空白 / 非字符串描述都被跳过并告警，不应抛错（.strip()）或漏到 from_request 而中断整批。"""
    from lib.asset_types import ASSET_SPECS
    from server.agent_runtime.sdk_tools.enqueue_assets import _build_specs

    bucket = ASSET_SPECS["character"].bucket_key

    class _PM:
        def load_project(self, _name):
            return {
                bucket: {
                    "Alice": {"description": "   "},  # 空白
                    "Carol": {"description": {"x": 1}},  # 非字符串，.strip() 会抛 AttributeError
                    "Bob": {"description": "勇士"},
                }
            }

    warnings: list[str] = []
    specs = _build_specs(_PM(), "demo", "character", ["Alice", "Carol", "Bob"], warnings)  # type: ignore[arg-type]
    assert [s.resource_id for s in specs] == ["Bob"]
    assert any("Alice" in w for w in warnings)
    assert any("Carol" in w for w in warnings)


def test_build_video_specs_does_not_validate_duration_at_enqueue(tmp_path) -> None:
    """duration 是能力维度，入队侧不再校验——任意 duration 都透传给执行层（见 ADR-0001）。"""
    from server.agent_runtime.sdk_tools.enqueue_videos import _build_video_specs

    (tmp_path / "storyboards").mkdir()
    (tmp_path / "storyboards" / "scene_S01.png").write_bytes(b"png")
    items = [
        {
            "segment_id": "S01",
            "video_prompt": "一个奔跑的镜头",
            "duration_seconds": 7,  # 不属于任何典型 supported_durations
            "generated_assets": {"storyboard_image": "storyboards/scene_S01.png"},
        }
    ]
    log: list[str] = []
    specs, order_map = _build_video_specs(
        items=items,
        id_field="segment_id",
        content_mode="narration",
        script_filename="episode_1.json",
        project_dir=tmp_path,
        skip_ids=None,
        log=log,
    )
    assert len(specs) == 1
    assert specs[0].payload["quality"] == "draft"
    assert specs[0].payload["duration_seconds"] == 7

    # 未显式指定 duration 时不携带该键，留给执行层按 caps 收口默认。
    items[0].pop("duration_seconds")
    specs2, _ = _build_video_specs(
        items=items,
        id_field="segment_id",
        content_mode="narration",
        script_filename="episode_1.json",
        project_dir=tmp_path,
        skip_ids=None,
        log=[],
    )
    assert specs2[0].payload["quality"] == "draft"
    assert "duration_seconds" not in specs2[0].payload


def test_route_summary_formats_actual_generation_route() -> None:
    result = {
        "generation_quality": "final",
        "generation_route": {
            "resolution": "1080p",
            "duration_seconds": 6,
            "provider": "doubao",
            "model": "seedance",
        },
    }

    assert route_summary(result) == " [精修版 · 1080p · 6s · doubao/seedance]"


def test_build_reference_specs_routes_through_guard(tmp_path) -> None:
    """参考生视频入队经统一守卫点：prompt 由 shots 拼接后随 payload 入队（见 ADR-0001）。"""
    from server.agent_runtime.sdk_tools.enqueue_videos import _build_reference_specs

    # production 的 shots[*].text 由 parse_prompt 产出、已剥离 "Shot N (Xs):" header，
    # fixture 用同样的 header-stripped 形态以贴近真实数据。
    units = [
        {
            "unit_id": "E1U1",
            "duration_seconds": 7,
            "shots": [{"duration": 3, "text": "@张三 推门"}],
            "references": [{"type": "character", "name": "张三"}],
        }
    ]
    log: list[str] = []
    specs, order_map = _build_reference_specs(units=units, script_filename="episode_1.json", skip_ids=None, log=log)
    assert len(specs) == 1
    assert specs[0].task_type == "reference_video"
    assert specs[0].resource_id == "E1U1"
    # 拼接出的 prompt 经守卫点校验后落入 payload。
    assert specs[0].payload["prompt"] == "@张三 推门"
    assert specs[0].payload["script_file"] == "episode_1.json"
    assert specs[0].payload["quality"] == "draft"
    assert specs[0].payload["duration_seconds"] == 7

    specs_final, _ = _build_reference_specs(
        units=units,
        script_filename="episode_1.json",
        skip_ids=None,
        log=[],
        quality="final",
    )
    assert specs_final[0].payload["quality"] == "final"


def test_build_reference_specs_skips_blank_prompt(tmp_path) -> None:
    """shots 存在但文本全空白的 unit 被跳过并告警，不漏到执行层（结构校验上移到守卫点）。"""
    from server.agent_runtime.sdk_tools.enqueue_videos import _build_reference_specs

    units = [
        {"unit_id": "E1U1", "shots": [{"duration": 3, "text": "   "}, {"duration": 2, "text": ""}]},
        {"unit_id": "E1U2", "shots": [{"duration": 3, "text": "@李四 转身"}]},
    ]
    log: list[str] = []
    specs, order_map = _build_reference_specs(units=units, script_filename="episode_1.json", skip_ids=None, log=log)
    assert [s.resource_id for s in specs] == ["E1U2"]
    assert any("E1U1" in w for w in log)


def test_build_reference_specs_skips_bad_unit_id_without_aborting_batch(tmp_path) -> None:
    """unit_id 为空或键缺失（Agent 裸写 JSON 可致）都跳过该 unit 而非中断整批：
    空串经 from_request 抛 ValueError 被捕获，缺键经 .get 归一化为空串后同样被拒。"""
    from server.agent_runtime.sdk_tools.enqueue_videos import _build_reference_specs

    units = [
        {"unit_id": "", "shots": [{"duration": 3, "text": "@张三 推门"}]},  # 空串
        {"shots": [{"duration": 3, "text": "@王五 起身"}]},  # 缺 unit_id 键 → 不应抛 KeyError
        {"unit_id": "E1U2", "shots": [{"duration": 3, "text": "@李四 转身"}]},
    ]
    log: list[str] = []
    specs, _ = _build_reference_specs(units=units, script_filename="episode_1.json", skip_ids=None, log=log)
    assert [s.resource_id for s in specs] == ["E1U2"]


def test_build_reference_specs_handles_malformed_shots(tmp_path) -> None:
    """畸形 shots（显式 null text / 非 dict 元素）不应崩溃整批，且不得把 'None' 注入 prompt。"""
    from server.agent_runtime.sdk_tools.enqueue_videos import _build_reference_specs

    units = [
        # text 显式 null + 一个非 dict 元素 → 拼接后为空 → 被守卫点判空跳过（不注入 'None'）。
        {"unit_id": "E1U1", "shots": [{"duration": 3, "text": None}, "garbage"]},
        {"unit_id": "E1U2", "shots": [{"duration": 3, "text": "@李四 转身"}]},
    ]
    log: list[str] = []
    specs, _ = _build_reference_specs(units=units, script_filename="episode_1.json", skip_ids=None, log=log)
    assert [s.resource_id for s in specs] == ["E1U2"]
    assert all("None" not in (s.payload.get("prompt") or "") for s in specs)


# ---------------------------------------------------------------------------
# text_generation
# ---------------------------------------------------------------------------


async def test_get_video_capabilities_happy(fake_ctx: ToolContext, monkeypatch) -> None:
    from server.agent_runtime.sdk_tools import text_generation as mod

    class FakeResolver:
        def __init__(self, *_args, **_kwargs):
            pass

        async def video_capabilities_for_project(self, _project):
            return {"provider_id": "fake", "supported_durations": [4, 6, 8]}

    async def fake_recommendations(**_kwargs):
        return {"video": {"draft": {"provider_id": "fake"}}}

    monkeypatch.setattr(mod, "ConfigResolver", FakeResolver)
    monkeypatch.setattr(mod, "_build_video_quality_recommendations", fake_recommendations)
    tool_obj = get_video_capabilities_tool(fake_ctx)
    out = await _call(tool_obj, {})
    assert out.get("is_error") is not True
    assert json.loads(out["content"][0]["text"])["provider_id"] == "fake"


async def test_get_video_capabilities_error(fake_ctx: ToolContext, monkeypatch) -> None:
    def fake_load_project(_project_name):
        raise FileNotFoundError("missing project.json")

    fake_ctx.pm.load_project = fake_load_project  # type: ignore[method-assign]
    tool_obj = get_video_capabilities_tool(fake_ctx)
    out = await _call(tool_obj, {})
    assert out.get("is_error") is True


async def test_generate_episode_script_dry_run(fake_ctx: ToolContext, monkeypatch) -> None:
    from server.agent_runtime.sdk_tools import text_generation as mod

    project_path = fake_ctx.project_path
    drafts = project_path / "drafts" / "episode_1"
    drafts.mkdir(parents=True)
    (drafts / "step1_segments.md").write_text("step1 content", encoding="utf-8")
    (project_path / "project.json").write_text(json.dumps({"content_mode": "narration"}), encoding="utf-8")

    class _FakeGenerator:
        def __init__(self, _path):
            pass

        async def build_prompt(self, _episode):
            return "fake prompt"

    monkeypatch.setattr(mod, "ScriptGenerator", _FakeGenerator)
    tool_obj = generate_episode_script_tool(fake_ctx)
    out = await _call(tool_obj, {"episode": 1, "dry_run": True})
    assert out.get("is_error") is not True
    assert "fake prompt" in out["content"][0]["text"]


async def test_generate_episode_script_missing_step1(fake_ctx: ToolContext) -> None:
    tool_obj = generate_episode_script_tool(fake_ctx)
    out = await _call(tool_obj, {"episode": 99})
    assert out.get("is_error") is True


async def test_generate_episode_script_writes_to_default_project_scripts(fake_ctx: ToolContext, monkeypatch) -> None:
    """output 参数已下线；写出路径必须由 ScriptGenerator 内部决定，handler 不应让 agent 控制。"""
    from server.agent_runtime.sdk_tools import text_generation as mod

    project_path = fake_ctx.project_path
    drafts = project_path / "drafts" / "episode_1"
    drafts.mkdir(parents=True)
    (drafts / "step1_segments.md").write_text("step1", encoding="utf-8")
    (project_path / "project.json").write_text(json.dumps({"content_mode": "narration"}), encoding="utf-8")

    captured: dict[str, dict[str, Any]] = {"calls": {}}

    class _FakeGenerator:
        @classmethod
        async def create(cls, _path):
            return cls()

        async def generate(self, **kwargs) -> Path:
            captured["calls"] = kwargs
            script_path = project_path / "scripts" / "episode_1.json"
            script_path.parent.mkdir(parents=True)
            script_path.write_text(
                json.dumps(
                    {
                        "episode": 1,
                        "content_mode": "narration",
                        "generation_mode": "storyboard",
                        "script_splitting_template_id": "tpl",
                        "script_splitting_hash": "sha256:abc",
                        "duration_seconds": 8,
                        "segments": [{"segment_id": "E1S01"}, {"segment_id": "E1S02"}],
                        "metadata": {"generator": "fake-model"},
                    }
                ),
                encoding="utf-8",
            )
            return script_path

    monkeypatch.setattr(mod, "ScriptGenerator", _FakeGenerator)
    tool_obj = generate_episode_script_tool(fake_ctx)

    out = await _call(tool_obj, {"episode": 1})
    assert out.get("is_error") is not True
    # handler 不再传 output_path —— ScriptGenerator 自己决定写到哪里
    assert "output_path" not in captured["calls"]
    text = out["content"][0]["text"]
    assert "segments_count: 2" in text
    assert "duration_seconds: 8" in text
    assert "model: fake-model" in text


async def test_generate_episode_script_failure_returns_direct_error(fake_ctx: ToolContext, monkeypatch) -> None:
    from server.agent_runtime.sdk_tools import text_generation as mod

    project_path = fake_ctx.project_path
    drafts = project_path / "drafts" / "episode_1"
    drafts.mkdir(parents=True)
    (drafts / "step1_segments.md").write_text("step1", encoding="utf-8")
    (project_path / "project.json").write_text(json.dumps({"content_mode": "narration"}), encoding="utf-8")

    class _FakeGenerator:
        @classmethod
        async def create(cls, _path):
            return cls()

        async def generate(self, **_kwargs) -> Path:
            raise RuntimeError("strict schema blocked")

    monkeypatch.setattr(mod, "ScriptGenerator", _FakeGenerator)

    out = await _call(generate_episode_script_tool(fake_ctx), {"episode": 1})

    assert out.get("is_error") is True
    text = out["content"][0]["text"]
    assert "generate_episode_script 失败" in text
    assert "strict schema blocked" in text
    assert "agent_ops" not in text


async def test_normalize_drama_script_dry_run(fake_ctx: ToolContext, monkeypatch) -> None:
    from server.agent_runtime.sdk_tools import text_generation as mod

    project_path = fake_ctx.project_path
    src = project_path / "source"
    src.mkdir(parents=True)
    (src / "chapter1.txt").write_text("从前有座山", encoding="utf-8")

    async def fake_caps(_p):
        return 4, [4, 6, 8]

    monkeypatch.setattr(mod, "_fetch_caps_with_fallback", fake_caps)
    tool_obj = normalize_drama_script_tool(fake_ctx)
    out = await _call(tool_obj, {"episode": 1, "dry_run": True})
    assert out.get("is_error") is not True
    assert "DRY RUN" in out["content"][0]["text"]


async def test_normalize_drama_script_injects_episode_into_prompt(fake_ctx: ToolContext, monkeypatch) -> None:
    """工具必须把 episode 注入 build_normalize_prompt，避免 LLM 写错 E\\d+ 前缀（#574）。"""
    from server.agent_runtime.sdk_tools import text_generation as mod

    project_path = fake_ctx.project_path
    src = project_path / "source"
    src.mkdir(parents=True)
    (src / "chapter2.txt").write_text("第二集开场", encoding="utf-8")

    async def fake_caps(_p):
        return 4, [4, 6, 8]

    monkeypatch.setattr(mod, "_fetch_caps_with_fallback", fake_caps)
    tool_obj = normalize_drama_script_tool(fake_ctx)
    out = await _call(tool_obj, {"episode": 2, "dry_run": True, "source": "source/chapter2.txt"})
    assert out.get("is_error") is not True, out
    prompt_text = out["content"][0]["text"]
    assert "E2S01" in prompt_text
    assert "第 2 集" in prompt_text or "E2S{两位序号}" in prompt_text
    assert "E1S01" not in prompt_text


async def test_normalize_drama_script_passes_project_name_to_backend(fake_ctx: ToolContext, monkeypatch) -> None:
    """工具必须把 ctx.project_name 传给 TextGenerator.create/generate，
    否则项目级 text_backend_script 覆盖被跳过，且 usage tracking 会丢 project_name。"""
    from server.agent_runtime.sdk_tools import text_generation as mod

    project_path = fake_ctx.project_path
    src = project_path / "source"
    src.mkdir(parents=True)
    (src / "chapter1.txt").write_text("从前有座山", encoding="utf-8")

    async def fake_caps(_p):
        return 4, [4, 6, 8]

    captured: dict[str, Any] = {}

    class _FakeGenerator:
        async def generate(self, _request, project_name=None):
            captured["generate_project_name"] = project_name

            class _R:
                text = "| 场景 ID | 场景描述 | 时长 | segment_break |\n|---|---|---|---|\n| E1S01 | 山中 | 4 | 是 |"

            return _R()

    async def fake_create(task_type, project_name=None):
        captured["task_type"] = task_type
        captured["create_project_name"] = project_name
        return _FakeGenerator()

    monkeypatch.setattr(mod, "_fetch_caps_with_fallback", fake_caps)
    monkeypatch.setattr(mod.TextGenerator, "create", fake_create)

    tool_obj = normalize_drama_script_tool(fake_ctx)
    out = await _call(tool_obj, {"episode": 1})

    assert out.get("is_error") is not True, out
    assert captured["task_type"] is mod.TextTaskType.SCRIPT
    assert captured["create_project_name"] == "demo", (
        f"normalize_drama_script 必须向 TextGenerator.create 传入 project_name，"
        f"实际传入: {captured.get('create_project_name')!r}"
    )
    assert captured["generate_project_name"] == "demo", (
        f"normalize_drama_script 必须向 TextGenerator.generate 传入 project_name，"
        f"实际传入: {captured.get('generate_project_name')!r}"
    )


async def test_normalize_drama_script_ignores_cached_narration_profile(
    fake_ctx: ToolContext, monkeypatch
) -> None:
    from lib.script_splitting_templates import ensure_project_script_splitting_snapshot
    from server.agent_runtime.sdk_tools import text_generation as mod

    project_path = fake_ctx.project_path
    src = project_path / "source"
    src.mkdir(parents=True)
    (src / "episode_1.txt").write_text("第一集文本", encoding="utf-8")

    project_payload = fake_ctx.pm.project_payload
    project_payload["content_mode"] = "narration"
    ensure_project_script_splitting_snapshot(project_payload)

    async def fake_caps(_p):
        return 4, [4, 6, 8]

    class _FakeGenerator:
        async def generate(self, request, project_name=None):
            assert "segment_label" not in request.prompt
            assert "场景描述" in request.prompt

            class _R:
                text = "| 场景 ID | 场景描述 | 时长 | segment_break |\n|---|---|---|---|\n| E1S01 | 山中 | 4 | 是 |"

            return _R()

    async def fake_create(task_type, project_name=None):
        return _FakeGenerator()

    monkeypatch.setattr(mod, "_fetch_caps_with_fallback", fake_caps)
    monkeypatch.setattr(mod.TextGenerator, "create", fake_create)

    out = await _call(normalize_drama_script_tool(fake_ctx), {"episode": 1})

    assert out.get("is_error") is not True, out


async def test_normalize_drama_script_prefers_episode_source_file(fake_ctx: ToolContext, monkeypatch) -> None:
    from server.agent_runtime.sdk_tools import text_generation as mod

    project_path = fake_ctx.project_path
    src = project_path / "source"
    src.mkdir(parents=True)
    (src / "episode_1.txt").write_text("第一集文本", encoding="utf-8")
    (src / "episode_2.txt").write_text("第二集文本不应混入", encoding="utf-8")

    async def fake_caps(_p):
        return 4, [4, 6, 8]

    captured: dict[str, str] = {}

    class _FakeGenerator:
        async def generate(self, request, project_name=None):
            captured["prompt"] = request.prompt

            class _R:
                text = "| 场景 ID | 场景描述 | 时长 | segment_break |\n|---|---|---|---|\n| E1S01 | 开场 | 4 | 是 |"

            return _R()

    async def fake_create(task_type, project_name=None):
        return _FakeGenerator()

    monkeypatch.setattr(mod, "_fetch_caps_with_fallback", fake_caps)
    monkeypatch.setattr(mod.TextGenerator, "create", fake_create)

    out = await _call(normalize_drama_script_tool(fake_ctx), {"episode": 1})

    assert out.get("is_error") is not True, out
    assert "第一集文本" in captured["prompt"]
    assert "第二集文本不应混入" not in captured["prompt"]
    assert "source/episode_1.txt" in out["content"][0]["text"]


async def test_normalize_drama_script_rejects_invalid_step1_table(fake_ctx: ToolContext, monkeypatch) -> None:
    from server.agent_runtime.sdk_tools import text_generation as mod

    project_path = fake_ctx.project_path
    src = project_path / "source"
    src.mkdir(parents=True)
    (src / "episode_1.txt").write_text("第一集文本", encoding="utf-8")

    async def fake_caps(_p):
        return 4, [4, 6, 8]

    class _FakeGenerator:
        async def generate(self, request, project_name=None):
            class _R:
                text = "| 场景 ID | 场景描述 | 时长 | segment_break |\n|---|---|---|---|\n| E2S01 | 错集 | 4 | 是 |"

            return _R()

    async def fake_create(task_type, project_name=None):
        return _FakeGenerator()

    monkeypatch.setattr(mod, "_fetch_caps_with_fallback", fake_caps)
    monkeypatch.setattr(mod.TextGenerator, "create", fake_create)

    out = await _call(normalize_drama_script_tool(fake_ctx), {"episode": 1})

    assert out.get("is_error") is True
    assert "scene_id 集号错误" in out["content"][0]["text"]
    assert not (project_path / "drafts" / "episode_1" / "step1_normalized_script.md").exists()


async def test_normalize_drama_script_no_source(fake_ctx: ToolContext) -> None:
    tool_obj = normalize_drama_script_tool(fake_ctx)
    out = await _call(tool_obj, {"episode": 1})
    assert out.get("is_error") is True

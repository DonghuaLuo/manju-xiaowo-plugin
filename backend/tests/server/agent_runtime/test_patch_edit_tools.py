"""项目/剧本 JSON 编辑 MCP 工具的真实写盘路径测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lib.project_manager import ProjectManager
from server.agent_runtime.sdk_tools._context import ToolContext
from server.agent_runtime.sdk_tools.patch_project import patch_project_tool
from server.agent_runtime.sdk_tools.patch_script import (
    insert_segment_tool,
    patch_episode_script_tool,
    remove_segment_tool,
    split_segment_tool,
)


def _segment(segment_id: str, duration: int = 4) -> dict[str, Any]:
    return {
        "segment_id": segment_id,
        "duration_seconds": duration,
        "segment_break": False,
        "novel_text": "原文",
        "characters_in_segment": ["角色A"],
        "clues_in_segment": ["玉佩"],
        "image_prompt": {
            "scene": "场景描述",
            "composition": {"shot_type": "Medium Shot", "lighting": "暖光", "ambiance": "薄雾"},
        },
        "video_prompt": {"action": "转身", "camera_motion": "Static", "ambiance_audio": "风声", "dialogue": []},
    }


def _script() -> dict[str, Any]:
    return {
        "episode": 1,
        "title": "标题",
        "content_mode": "narration",
        "summary": "摘要",
        "novel": {"title": "小说", "chapter": "第一章"},
        "segments": [_segment("E1S01"), _segment("E1S02")],
    }


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    pm = ProjectManager(str(tmp_path))
    pm.create_project("demo")
    pm.create_project_metadata("demo", "Demo", "Anime", "narration")
    pm.save_script("demo", _script(), "episode_1.json")
    return ToolContext(project_name="demo", projects_root=tmp_path, pm=pm)


async def _call(tool_obj, args: dict[str, Any]) -> dict[str, Any]:
    return await tool_obj.handler(args)


def _load(ctx: ToolContext) -> dict[str, Any]:
    return ctx.pm.load_script("demo", "episode_1.json")


def _text(out: dict[str, Any]) -> str:
    blocks = out.get("content") or []
    return "\n".join(block.get("text", "") for block in blocks if isinstance(block, dict))


async def test_patch_project_settings_set_clear_and_validate(ctx: ToolContext) -> None:
    tool_obj = patch_project_tool(ctx)

    out = await _call(tool_obj, {"settings": {"episode_target_units": 1200, "source_language": "vi"}})
    assert out.get("is_error") is not True
    project = ctx.pm.load_project("demo")
    assert project["episode_target_units"] == 1200
    assert project["source_language"] == "vi"

    out = await _call(tool_obj, {"settings": {"source_language": None}})
    assert out.get("is_error") is not True
    assert "source_language" not in ctx.pm.load_project("demo")

    out = await _call(tool_obj, {"settings": {"source_language": "english"}})
    assert out.get("is_error") is True

    out = await _call(tool_obj, {"settings": {"episode_target_units": 0}})
    assert out.get("is_error") is True


@pytest.mark.parametrize("bad_lang", ["english", "ja", "ZH", "", 1, True, ["en"]])
async def test_patch_project_invalid_source_language_rejected(ctx: ToolContext, bad_lang: Any) -> None:
    before = ctx.pm.load_project("demo").get("source_language")

    out = await _call(patch_project_tool(ctx), {"settings": {"source_language": bad_lang}})

    assert out.get("is_error") is True
    assert ctx.pm.load_project("demo").get("source_language") == before


@pytest.mark.parametrize("bad_value", ["1000", 0, -5, 1.5, True])
async def test_patch_project_invalid_episode_target_units_rejected(ctx: ToolContext, bad_value: Any) -> None:
    before = ctx.pm.load_project("demo").get("episode_target_units")

    out = await _call(patch_project_tool(ctx), {"settings": {"episode_target_units": bad_value}})

    assert out.get("is_error") is True
    assert ctx.pm.load_project("demo").get("episode_target_units") == before


async def test_patch_project_rejects_ambiguous_or_empty_modes(ctx: ToolContext) -> None:
    tool_obj = patch_project_tool(ctx)

    out = await _call(
        tool_obj,
        {"table": "characters", "entries": {"x": {"description": "y"}}, "settings": {"episode_target_units": 1}},
    )
    assert out.get("is_error") is True

    out = await _call(tool_obj, {})
    assert out.get("is_error") is True

    out = await _call(tool_obj, {"settings": {}})
    assert out.get("is_error") is True


async def test_patch_project_drops_system_and_legacy_fields(ctx: ToolContext) -> None:
    tool_obj = patch_project_tool(ctx)

    await _call(tool_obj, {"table": "characters", "entries": {"李白": {"description": "白衣剑客"}}})
    ctx.pm.update_character_reference_image("demo", "李白", "characters/refs/li_bai.jpg")

    out = await _call(
        tool_obj,
        {
            "table": "characters",
            "entries": {
                "李白": {
                    "description": "改后描述",
                    "voice_style": "沉稳",
                    "reference_image": "agent-overwrite.jpg",
                    "character_sheet": "agent-overwrite.png",
                    "type": "主角",
                    "importance": "high",
                }
            },
        },
    )

    assert out.get("is_error") is not True
    char = ctx.pm.load_project("demo")["characters"]["李白"]
    assert char["description"] == "改后描述"
    assert char["voice_style"] == "沉稳"
    assert char["reference_image"] == "characters/refs/li_bai.jpg"
    assert char["character_sheet"] == ""
    assert "type" not in char
    assert "importance" not in char
    text = _text(out)
    assert "reference_image" in text
    assert "character_sheet" in text
    assert "type" in text
    assert "importance" in text


async def test_patch_project_invalid_entry_rejected_and_not_written(ctx: ToolContext) -> None:
    out = await _call(
        patch_project_tool(ctx),
        {"table": "scenes", "entries": {"空场景": {"voice_style": "x"}}},
    )

    assert out.get("is_error") is True
    assert "空场景" not in ctx.pm.load_project("demo").get("scenes", {})


async def test_patch_episode_script_updates_nested_field(ctx: ToolContext) -> None:
    out = await _call(
        patch_episode_script_tool(ctx),
        {"script": "episode_1.json", "id": "E1S02", "field": "image_prompt.scene", "value": "新场景"},
    )
    assert out.get("is_error") is not True
    assert _load(ctx)["segments"][1]["image_prompt"]["scene"] == "新场景"


async def test_patch_episode_script_rejects_paths_and_invalid_structure(ctx: ToolContext) -> None:
    out = await _call(
        patch_episode_script_tool(ctx),
        {"script": "../x.json", "id": "E1S01", "field": "duration_seconds", "value": 5},
    )
    assert out.get("is_error") is True

    out = await _call(
        patch_episode_script_tool(ctx),
        {"script": "episode_1.json", "id": "E1S01", "field": "duration_seconds", "value": 999},
    )
    assert out.get("is_error") is True
    assert _load(ctx)["segments"][0]["duration_seconds"] == 4


async def test_patch_episode_script_hallucinated_leaf_blocked_by_write_funnel(ctx: ToolContext) -> None:
    out = await _call(
        patch_episode_script_tool(ctx),
        {
            "script": "episode_1.json",
            "id": "E1S01",
            "field": "video_prompt.hallucinated_key",
            "value": "stray",
        },
    )

    assert out.get("is_error") is True
    assert "hallucinated_key" not in _load(ctx)["segments"][0]["video_prompt"]


async def test_patch_episode_script_image_prompt_typo_blocked_by_write_funnel(ctx: ToolContext) -> None:
    out = await _call(
        patch_episode_script_tool(ctx),
        {"script": "episode_1.json", "id": "E1S01", "field": "image_prompt.scen", "value": "x"},
    )

    assert out.get("is_error") is True
    assert "scen" not in _load(ctx)["segments"][0]["image_prompt"]


async def test_insert_remove_and_split_segment(ctx: ToolContext) -> None:
    out = await _call(
        insert_segment_tool(ctx),
        {"script": "episode_1.json", "after_id": "E1S01", "item": _segment("ignored")},
    )
    assert out.get("is_error") is not True
    assert [s["segment_id"] for s in _load(ctx)["segments"]] == ["E1S01", "E1S01_1", "E1S02"]

    out = await _call(remove_segment_tool(ctx), {"script": "episode_1.json", "id": "E1S01_1"})
    assert out.get("is_error") is not True
    assert [s["segment_id"] for s in _load(ctx)["segments"]] == ["E1S01", "E1S02"]

    script = _load(ctx)
    script["segments"][0]["generated_assets"] = {"storyboard_image": "storyboards/old.png"}
    ctx.pm.save_script("demo", script, "episode_1.json")
    out = await _call(
        split_segment_tool(ctx),
        {"script": "episode_1.json", "id": "E1S01", "parts": [_segment("a"), _segment("b")]},
    )
    assert out.get("is_error") is not True
    saved = _load(ctx)["segments"]
    assert [s["segment_id"] for s in saved] == ["E1S01", "E1S01_1", "E1S02"]
    assert saved[0]["generated_assets"]["storyboard_image"] == "storyboards/old.png"
    assert saved[1]["generated_assets"] == {}

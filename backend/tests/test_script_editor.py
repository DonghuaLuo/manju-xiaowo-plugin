"""剧本编辑核心纯函数测试。"""

from __future__ import annotations

import logging

import pytest

from lib.script_editor import (
    ScriptEditError,
    insert_segment,
    patch_field,
    remove_segment,
    resolve_items,
    split_segment,
)


def _segment(segment_id: str = "E1S01", duration: int = 4) -> dict:
    return {
        "segment_id": segment_id,
        "duration_seconds": duration,
        "novel_text": "原文",
        "characters_in_segment": ["角色A"],
        "clues_in_segment": ["玉佩"],
        "image_prompt": {
            "scene": "场景描述",
            "composition": {"shot_type": "Medium Shot", "lighting": "暖光", "ambiance": "薄雾"},
        },
        "video_prompt": {"action": "转身", "camera_motion": "Static", "ambiance_audio": "风声", "dialogue": []},
        "generated_assets": {"storyboard_image": "scripts/x.png", "status": "completed"},
    }


def _narration(segments: list[dict] | None = None) -> dict:
    return {
        "title": "标题",
        "content_mode": "narration",
        "episode": 1,
        "summary": "摘要",
        "novel": {"title": "小说", "chapter": "第一章"},
        "segments": segments if segments is not None else [_segment("E1S01"), _segment("E1S02")],
    }


def _scene(scene_id: str = "E1S01", duration: int = 8) -> dict:
    return {
        "scene_id": scene_id,
        "duration_seconds": duration,
        "scene_type": "剧情",
        "characters_in_scene": ["角色A"],
        "image_prompt": {
            "scene": "场景描述",
            "composition": {"shot_type": "Medium Shot", "lighting": "暖光", "ambiance": "薄雾"},
        },
        "video_prompt": {"action": "转身", "camera_motion": "Static", "ambiance_audio": "风声"},
        "generated_assets": {"storyboard_image": "scripts/y.png"},
    }


def _drama(scenes: list[dict] | None = None) -> dict:
    return {
        "title": "标题",
        "content_mode": "drama",
        "episode": 1,
        "summary": "摘要",
        "novel": {"title": "小说", "chapter": "第一章"},
        "scenes": scenes if scenes is not None else [_scene("E1S01"), _scene("E1S02")],
    }


def _unit(unit_id: str = "E1U1", shots: list[dict] | None = None) -> dict:
    shots = shots if shots is not None else [{"duration": 3, "text": "镜头1"}, {"duration": 4, "text": "镜头2"}]
    return {
        "unit_id": unit_id,
        "shots": shots,
        "references": [],
        "duration_seconds": sum(s["duration"] for s in shots),
        "transition_to_next": "cut",
        "generated_assets": {"video_clip": "scripts/z.mp4"},
    }


def _reference(units: list[dict] | None = None) -> dict:
    return {
        "title": "标题",
        "content_mode": "narration",
        "generation_mode": "reference_video",
        "episode": 1,
        "summary": "摘要",
        "novel": {"title": "小说", "chapter": "第一章"},
        "video_units": units if units is not None else [_unit("E1U1"), _unit("E1U2")],
    }


class TestResolveItems:
    def test_narration(self) -> None:
        items, id_field, kind = resolve_items(_narration())
        assert id_field == "segment_id"
        assert kind == "segments"
        assert len(items) == 2

    def test_drama(self) -> None:
        _items, id_field, kind = resolve_items(_drama())
        assert id_field == "scene_id"
        assert kind == "scenes"

    def test_reference_data_shape_picks_video_units(self) -> None:
        _items, id_field, kind = resolve_items(_reference())
        assert id_field == "unit_id"
        assert kind == "video_units"

    def test_partial_migration_data_shape_wins_over_generation_mode(self) -> None:
        script = {
            "title": "标题",
            "content_mode": "narration",
            "generation_mode": "reference_video",
            "episode": 1,
            "summary": "摘要",
            "novel": {"title": "小说", "chapter": "第一章"},
            "segments": [_segment("E1S01")],
        }
        items, id_field, kind = resolve_items(script)
        assert kind == "segments"
        assert id_field == "segment_id"
        assert len(items) == 1

    def test_returned_list_is_live_reference(self) -> None:
        script = _narration()
        items, _id, _kind = resolve_items(script)
        items.append(_segment("E1S03"))
        assert len(script["segments"]) == 3

    def test_stray_video_units_do_not_hijack_storyboard_script(self) -> None:
        script = {
            "segments": [_segment("E1S01"), _segment("E1S02")],
            "video_units": [{"unit_id": "E1U1", "generated_assets": {"status": "pending"}}],
        }
        items, id_field, kind = resolve_items(script)
        assert kind == "segments"
        assert id_field == "segment_id"
        assert len(items) == 2

    def test_bare_video_units_without_segments_is_reference(self) -> None:
        _items, id_field, kind = resolve_items({"video_units": [{"unit_id": "E1U1"}]})
        assert kind == "video_units"
        assert id_field == "unit_id"

    def test_missing_key_is_empty_list(self) -> None:
        items, _id, kind = resolve_items({"content_mode": "narration"})
        assert kind == "segments"
        assert items == []

    @pytest.mark.parametrize("bad_items", ["oops", None])
    def test_present_non_list_items_fail_loud(self, bad_items: object) -> None:
        with pytest.raises(ScriptEditError):
            resolve_items({"content_mode": "narration", "segments": bad_items})


class TestPatchField:
    def test_patch_top_level_field(self) -> None:
        script = patch_field(_narration(), "E1S02", "duration_seconds", 9)
        assert script["segments"][1]["duration_seconds"] == 9

    def test_patch_nested_field(self) -> None:
        script = patch_field(_narration(), "E1S01", "image_prompt.scene", "新场景")
        assert script["segments"][0]["image_prompt"]["scene"] == "新场景"

    def test_patch_drama_by_scene_id(self) -> None:
        script = patch_field(_drama(), "E1S02", "scene_type", "空镜")
        assert script["scenes"][1]["scene_type"] == "空镜"

    def test_patch_reference_unit_field(self) -> None:
        script = patch_field(_reference(), "E1U2", "transition_to_next", "fade")
        assert script["video_units"][1]["transition_to_next"] == "fade"

    def test_patch_optional_leaf_present_in_schema_succeeds(self) -> None:
        script = _narration()
        for seg in script["segments"]:
            seg.pop("note", None)
        script = patch_field(script, "E1S01", "note", "补全的备注")
        assert script["segments"][0]["note"] == "补全的备注"

    def test_patch_unknown_id_raises(self) -> None:
        with pytest.raises(ScriptEditError):
            patch_field(_narration(), "E9S99", "duration_seconds", 9)

    def test_patch_generated_assets_rejected(self) -> None:
        with pytest.raises(ScriptEditError):
            patch_field(_narration(), "E1S01", "generated_assets.status", "completed")

    @pytest.mark.parametrize("id_field", ["segment_id", "scene_id", "unit_id"])
    def test_patch_id_field_rejected(self, id_field: str) -> None:
        with pytest.raises(ScriptEditError, match="不可改分镜 id"):
            patch_field(_narration(), "E1S01", id_field, "X")

    def test_patch_does_not_touch_generated_assets(self) -> None:
        script = patch_field(_narration(), "E1S01", "duration_seconds", 7)
        assert script["segments"][0]["generated_assets"]["status"] == "completed"

    def test_patch_missing_parent_path_raises(self) -> None:
        with pytest.raises(ScriptEditError):
            patch_field(_narration(), "E1S01", "no_such.deep", 1)


class TestInsertSegment:
    def test_insert_after_assigns_unique_suffixed_id_at_right_position(self) -> None:
        script = insert_segment(_narration(), "E1S01", _segment("IGNORED"))
        assert [s["segment_id"] for s in script["segments"]] == ["E1S01", "E1S01_1", "E1S02"]

    def test_insert_clears_generated_assets(self) -> None:
        script = insert_segment(_narration(), "E1S01", _segment("X"))
        assert script["segments"][1]["generated_assets"] == {}

    def test_insert_anchor_already_suffixed_flattens_subindex(self) -> None:
        script = insert_segment(_narration([_segment("E1S01"), _segment("E1S01_1")]), "E1S01_1", _segment("X"))
        assert [s["segment_id"] for s in script["segments"]] == ["E1S01", "E1S01_1", "E1S01_2"]

    def test_insert_unknown_anchor_raises(self) -> None:
        with pytest.raises(ScriptEditError):
            insert_segment(_narration(), "E9S99", _segment("X"))

    def test_insert_reference_unit(self) -> None:
        script = insert_segment(_reference(), "E1U1", _unit("X"))
        assert [u["unit_id"] for u in script["video_units"]] == ["E1U1", "E1U1_1", "E1U2"]


class TestRemoveSegment:
    def test_remove_by_id(self) -> None:
        script = remove_segment(_narration(), "E1S01")
        assert [s["segment_id"] for s in script["segments"]] == ["E1S02"]

    def test_remove_does_not_renumber_others(self) -> None:
        script = remove_segment(_narration([_segment("E1S01"), _segment("E1S02"), _segment("E1S03")]), "E1S02")
        assert [s["segment_id"] for s in script["segments"]] == ["E1S01", "E1S03"]

    def test_remove_unknown_id_raises(self) -> None:
        with pytest.raises(ScriptEditError):
            remove_segment(_narration(), "E9S99")


class TestSplitSegment:
    def test_split_keeps_first_id_and_suffixes_rest(self) -> None:
        script = split_segment(_narration(), "E1S01", [_segment("a"), _segment("b"), _segment("c")])
        assert [s["segment_id"] for s in script["segments"]] == ["E1S01", "E1S01_1", "E1S01_2", "E1S02"]

    def test_split_keeps_anchor_assets_clears_new_parts(self) -> None:
        anchor_assets = _narration()["segments"][0]["generated_assets"]
        script = split_segment(_narration(), "E1S01", [_segment("a"), _segment("b")])
        assert script["segments"][0]["generated_assets"] == anchor_assets
        assert script["segments"][1]["generated_assets"] == {}

    def test_split_requires_at_least_two_parts(self) -> None:
        with pytest.raises(ScriptEditError):
            split_segment(_narration(), "E1S01", [_segment("a")])

    def test_split_unknown_id_raises(self) -> None:
        with pytest.raises(ScriptEditError):
            split_segment(_narration(), "E9S99", [_segment("a"), _segment("b")])

    def test_split_reference_units_act_on_video_units(self) -> None:
        anchor_assets = _reference()["video_units"][0]["generated_assets"]
        script = split_segment(_reference(), "E1U1", [_unit("a"), _unit("b")])
        assert [u["unit_id"] for u in script["video_units"]] == ["E1U1", "E1U1_1", "E1U2"]
        assert script["video_units"][0]["generated_assets"] == anchor_assets
        assert script["video_units"][1]["generated_assets"] == {}

    def test_split_warns_when_anchor_assets_dirty_non_dict(self, caplog: pytest.LogCaptureFixture) -> None:
        script = _narration([_segment("E1S01"), _segment("E1S02")])
        script["segments"][0]["generated_assets"] = ["unexpected_list_form"]

        with caplog.at_level(logging.WARNING, logger="lib.script_editor"):
            split_segment(script, "E1S01", [_segment("a"), _segment("b")])

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("E1S01" in m and "list" in m for m in warnings), warnings

    def test_split_no_warn_when_anchor_assets_none(self, caplog: pytest.LogCaptureFixture) -> None:
        script = _narration([_segment("E1S01"), _segment("E1S02")])
        script["segments"][0].pop("generated_assets", None)

        with caplog.at_level(logging.WARNING, logger="lib.script_editor"):
            split_segment(script, "E1S01", [_segment("a"), _segment("b")])

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert not warnings

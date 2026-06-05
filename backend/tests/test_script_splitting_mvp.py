from __future__ import annotations

import json

import pytest

from lib.script_splitting_templates import (
    assert_script_splitting_assets_current,
    delete_custom_script_splitting_template,
    export_script_splitting_template,
    current_hash,
    ensure_project_script_splitting_snapshot,
    list_script_splitting_templates,
    mark_template_change_stale_assets,
    preview_template_change,
    resolve_script_splitting_profile,
    script_splitting_staleness_for_script,
    snapshot_from_profile,
    upsert_custom_script_splitting_template,
)
from lib.video_input_preflight import run_video_input_preflight


def test_template_change_preview_and_apply_is_future_only_for_existing_scripts():
    project = {
        "content_mode": "narration",
        "generation_mode": "storyboard",
        "episodes": [{"episode": 1, "script_file": "episode_1.json"}],
    }
    ensure_project_script_splitting_snapshot(project)
    old_hash = current_hash(project)

    preview = preview_template_change(project, "narration_suspense_hook")
    next_profile = resolve_script_splitting_profile("narration", "storyboard", "narration_suspense_hook")
    project["script_splitting_template_id"] = next_profile["id"]
    project["script_splitting"] = snapshot_from_profile(next_profile)
    mark_template_change_stale_assets(project, preview=preview, mode="apply_keep_drafts")

    marker = project["script_splitting"]["asset_staleness"]
    assert marker["status"] == "current"
    assert marker["reason"] == "template_changed_future_only"
    assert marker["previous_hash"] == old_hash
    assert marker["current_hash"] == next_profile["hash"]
    assert marker["affected_assets"] == []
    assert marker["rebuild_required_assets"] == []

    old_script = {"script_splitting_hash": old_hash}
    stale = script_splitting_staleness_for_script(project, old_script, script_file="episode_1.json")
    assert stale["status"] == "current"
    assert stale["reason"] == "template_changed_future_only"
    assert stale["template_hash_differs"] is True
    assert stale["suggested_action"] == "continue"
    assert_script_splitting_assets_current(project, old_script, script_file="episode_1.json")

    regenerated_script = {"script_splitting_hash": next_profile["hash"]}
    current = script_splitting_staleness_for_script(project, regenerated_script, script_file="episode_1.json")
    assert current["status"] == "current"


def test_template_change_apply_rebuild_step1_is_kept_as_future_only_compat_mode():
    project = {
        "content_mode": "narration",
        "generation_mode": "storyboard",
        "episodes": [{"episode": 1, "script_file": "episode_1.json"}],
    }
    ensure_project_script_splitting_snapshot(project)
    preview = preview_template_change(project, "narration_suspense_hook")
    next_profile = resolve_script_splitting_profile("narration", "storyboard", "narration_suspense_hook")
    project["script_splitting_template_id"] = next_profile["id"]
    project["script_splitting"] = snapshot_from_profile(next_profile)

    mark_template_change_stale_assets(project, preview=preview, mode="apply_rebuild_step1")

    marker = project["script_splitting"]["asset_staleness"]
    assert marker["status"] == "current"
    assert marker["reason"] == "template_changed_future_only"
    assert marker["mode"] == "apply_rebuild_step1"
    assert marker["rebuild_required_assets"] == []
    assert marker["future_generation_policy"] == "use_current_template_for_ungenerated_episodes"


def test_template_change_preview_reports_existing_outputs_as_preserved(tmp_path):
    project = {
        "content_mode": "narration",
        "generation_mode": "storyboard",
        "episodes": [{"episode": 1, "script_file": "scripts/episode_1.json"}],
    }
    ensure_project_script_splitting_snapshot(project)
    (tmp_path / "drafts" / "episode_1").mkdir(parents=True)
    (tmp_path / "drafts" / "episode_1" / "step1_segments.md").write_text("E1S01 | 片段", encoding="utf-8")
    (tmp_path / "storyboards").mkdir()
    (tmp_path / "storyboards" / "scene_E1S01.png").write_bytes(b"png")
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / "scene_E1S01.mp4").write_bytes(b"mp4")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "episode_1.json").write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "segment_id": "E1S01",
                        "generated_assets": {
                            "storyboard_image": "storyboards/scene_E1S01.png",
                            "video_clip": "videos/scene_E1S01.mp4",
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    preview = preview_template_change(project, "narration_suspense_hook", project_path=tmp_path)

    assert preview["affected_asset_count"] == 0
    assert preview["affected_assets"] == []
    assert preview["requires_confirmation"] is False
    assert preview["regeneration_chain"] == []
    assert preview["preserved_existing_asset_count"] == 4
    assert preview["preserved_existing_assets"] == ["step1", "scripts", "storyboards", "videos", "jianying_draft"]
    assert preview["existing_assets_policy"] == "preserve_existing"
    assert preview["existing_outputs"]["videos"]["exists"] is True
    assert preview["has_generated_videos"] is True
    assert preview["has_jianying_draft"] is None
    assert preview["jianying_draft_tracking"] == "external_path_required"
    assert preview["suggested_action"] == "future_episodes_only"


def test_custom_template_lifecycle(tmp_path):
    template = upsert_custom_script_splitting_template(
        {
            "base_template_id": "narration_storytelling_classic",
            "id": "user_narration_fast",
            "name": "快节奏说书",
            "description": "更快进入冲突。",
            "recommended_generation_modes": ["storyboard"],
            "intent_brief": "开头更快抛出冲突。",
            "extra_split_rules": ["每集前 3 个片段必须有明确推进。"],
            "extra_forbidden_patterns": ["不要连续两个片段都只做背景介绍。"],
        },
        data_root=tmp_path,
    )

    assert template["id"] == "user_narration_fast"
    assert template["source"] == "user_generated"
    assert template["base_template_id"] == "narration_storytelling_classic"
    assert template["hash"].startswith("sha256:")
    assert "每集前 3 个片段必须有明确推进。" in template["split_rules"]

    listed = list_script_splitting_templates("narration", data_root=tmp_path)
    assert "user_narration_fast" in {item["id"] for item in listed}

    exported = export_script_splitting_template("user_narration_fast", data_root=tmp_path)
    assert exported["schema"] == "manju.script_splitting_template.v1"
    assert exported["template"]["id"] == "user_narration_fast"

    assert delete_custom_script_splitting_template("user_narration_fast", data_root=tmp_path) is True


def test_custom_template_from_universal_does_not_inherit_legacy_passthrough_fragments(tmp_path):
    template = upsert_custom_script_splitting_template(
        {
            "base_template_id": "narration_legacy_reading_default",
            "id": "user_narration_legacy_variant",
            "name": "旧版通用变体",
            "description": "保持旧骨架但增加开头钩子。",
            "supported_generation_modes": ["storyboard"],
            "extra_split_rules": ["前两个片段优先保留可见冲突。"],
        },
        data_root=tmp_path,
    )

    assert template["base_template_id"] == "narration_legacy_reading_default"
    assert template.get("legacy_passthrough") is None
    assert "prompt_fragments" not in template
    assert "前两个片段优先保留可见冲突。" in template["split_rules"]


def test_custom_template_can_improve_existing_custom_template(tmp_path):
    base_custom = upsert_custom_script_splitting_template(
        {
            "base_template_id": "drama_web_short_hook",
            "id": "user_drama_hook",
            "name": "强钩子短剧",
            "description": "前三秒更强。",
            "supported_generation_modes": ["storyboard"],
            "extra_split_rules": ["前三个镜头必须连续推进冲突。"],
        },
        data_root=tmp_path,
    )

    improved = upsert_custom_script_splitting_template(
        {
            "base_template_id": "user_drama_hook",
            "derived_from_template_id": "user_drama_hook",
            "creation_mode": "improve",
            "name": "强钩子短剧 · 改进版 1",
            "description": "继续加强反转。",
            "supported_generation_modes": ["storyboard"],
            "derivation_note": "加重反转节奏。",
            "extra_split_rules": ["结尾镜头必须留下下一集悬念。"],
        },
        data_root=tmp_path,
    )

    assert base_custom["base_template_id"] == "drama_web_short_hook"
    assert improved["base_template_id"] == "drama_web_short_hook"
    assert improved["derived_from_template_id"] == "user_drama_hook"
    assert improved["creation_mode"] == "improve"
    assert "前三个镜头必须连续推进冲突。" in improved["split_rules"]
    assert "结尾镜头必须留下下一集悬念。" in improved["split_rules"]
    assert improved["user_overlay"]["derivation_note"] == "加重反转节奏。"


def test_custom_template_rejects_duplicate_name(tmp_path):
    upsert_custom_script_splitting_template(
        {
            "base_template_id": "narration_storytelling_classic",
            "id": "user_narration_a",
            "name": "重复标题",
            "description": "第一份。",
            "supported_generation_modes": ["storyboard"],
            "extra_split_rules": ["按冲突拆分。"],
        },
        data_root=tmp_path,
    )

    with pytest.raises(ValueError, match="标题已存在"):
        upsert_custom_script_splitting_template(
            {
                "base_template_id": "narration_storytelling_classic",
                "id": "user_narration_b",
                "name": "重复标题",
                "description": "第二份。",
                "supported_generation_modes": ["storyboard"],
                "extra_split_rules": ["按悬念拆分。"],
            },
            data_root=tmp_path,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "", "标题不能为空"),
        ("description", "", "描述不能为空"),
        ("extra_split_rules", [], "拆分规则不能为空"),
    ],
)
def test_custom_template_rejects_missing_required_ai_fields(tmp_path, field, value, message):
    payload = {
        "base_template_id": "narration_storytelling_classic",
        "id": f"user_missing_{field}",
        "name": "完整标题",
        "description": "完整描述。",
        "supported_generation_modes": ["storyboard"],
        "extra_split_rules": ["按冲突拆分。"],
    }
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        upsert_custom_script_splitting_template(payload, data_root=tmp_path)


def test_video_input_preflight_blocks_requested_audio_when_model_does_not_support_it():
    result = run_video_input_preflight(
        project={"aspect_ratio": "9:16"},
        capabilities={
            "supported_durations": [5],
            "max_reference_images": 1,
            "supports_generate_audio": False,
            "constraints": {"supported_aspect_ratios": ["9:16"]},
        },
        request={
            "aspect_ratio": "9:16",
            "duration_seconds": 5,
            "reference_images_count": 0,
            "generate_audio": True,
        },
    )

    checks = {check["id"]: check for check in result["checks"]}
    assert result["status"] == "block"
    assert checks["generate_audio_supported"]["status"] == "block"
    assert checks["generate_audio_supported"]["autofix_available"] is True

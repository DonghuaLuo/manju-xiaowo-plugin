"""Script splitting template registry and project snapshot helpers."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

VALID_CONTENT_MODES = {"narration", "drama"}
GENERATION_MODE_ORDER = ("storyboard", "reference_video", "grid")
VALID_GENERATION_MODES = set(GENERATION_MODE_ORDER)
VALID_TEMPLATE_SOURCES = {"builtin", "user_generated", "imported"}
VALID_TEMPLATE_CAPABILITIES = {
    "single_shot_video",
    "multi_shot",
    "subject_reference",
    "reference_image",
    "element_reference",
    "first_frame",
    "first_last_frame",
    "native_audio",
    "dialogue_audio",
    "camera_command",
    "reference_video",
}

DEFAULT_TEMPLATE_BY_MODE = {
    "narration": "narration_legacy_reading_default",
    "drama": "drama_legacy_scene_default",
}

_HASH_EXCLUDED_KEYS = {
    "hash",
    "provider_compatibility",
    "generation_mode_compatibility",
    "created_at",
    "updated_at",
    "last_used_at",
}
_SNAPSHOT_RUNTIME_KEYS = ("asset_staleness", "last_template_change")
_CUSTOM_TEMPLATES_DIR = "_script_splitting_templates"
_CUSTOM_TEMPLATES_FILE = "templates.json"
_TEMPLATE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,79}$")
_custom_templates_lock = threading.RLock()
_STEP1_DRAFT_FILES = (
    "step1_segments.md",
    "step1_normalized_script.md",
    "step1_reference_units.md",
)
_SCRIPT_ITEM_LIST_KEYS = ("segments", "scenes", "video_units")
_REGENERATION_ORDER = (
    "step1",
    "scripts",
    "asset_bindings",
    "storyboards",
    "grids",
    "videos",
    "reference_videos",
    "jianying_draft",
)
_PROVIDER_CAPABILITY_HASH_KEYS = {
    "provider_id",
    "model",
    "task_kind",
    "supported_durations",
    "max_duration",
    "max_reference_images",
    "resolutions",
    "duration_resolution_constraints",
    "capabilities",
    "supports_generate_audio",
    "supports_seed",
    "supports_service_tier",
    "service_tiers",
    "supports_start_image",
    "supports_end_image",
    "supports_reference_images",
    "supports_reference_with_start_image",
    "supports_first_frame",
    "supports_last_frame",
    "video_continuity_capabilities",
    "recommended_continuity_policy",
    "endpoint",
    "endpoint_family",
    "source",
    "provider_capability_profile",
}


def _normalize_generation_modes(values: Any) -> list[str]:
    raw_values = values if isinstance(values, list) else []
    seen: set[str] = set()
    modes: list[str] = []
    for raw in raw_values:
        mode = str(raw or "").strip()
        if mode in VALID_GENERATION_MODES and mode not in seen:
            seen.add(mode)
            modes.append(mode)
    return modes


def _template_supported_generation_modes(profile: dict[str, Any]) -> list[str]:
    modes = _normalize_generation_modes(profile.get("supported_generation_modes"))
    if not modes:
        modes = _normalize_generation_modes(profile.get("recommended_generation_modes"))
    return modes or ["storyboard"]


def _template_default_generation_mode(profile: dict[str, Any], supported_modes: list[str] | None = None) -> str:
    modes = supported_modes if supported_modes is not None else _template_supported_generation_modes(profile)
    default_mode = str(profile.get("default_generation_mode") or "").strip()
    if default_mode in modes:
        return default_mode
    return modes[0] if modes else "storyboard"


def _ensure_generation_mode_fields(profile: dict[str, Any]) -> dict[str, Any]:
    supported = _template_supported_generation_modes(profile)
    profile["supported_generation_modes"] = supported
    # The legacy field is kept for API compatibility, but product semantics now
    # treat it as the same selectable support range.
    profile["recommended_generation_modes"] = supported
    profile["default_generation_mode"] = _template_default_generation_mode(profile, supported)
    return profile


def _template(
    *,
    template_id: str,
    content_mode: str,
    name: str,
    description: str,
    recommended_generation_modes: list[str],
    required_capabilities: list[str],
    preferred_capabilities: list[str],
    locked_contract: dict[str, Any],
    output_fields: list[str],
    split_rules: list[str],
    forbidden_patterns: list[str],
    few_shot_examples: list[dict[str, str]],
    quality_gates: list[dict[str, str]],
    supported_generation_modes: list[str] | None = None,
    default_generation_mode: str | None = None,
    legacy_passthrough: bool = False,
    prompt_fragments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    supported_modes = _normalize_generation_modes(
        supported_generation_modes if supported_generation_modes is not None else recommended_generation_modes
    )
    if not supported_modes:
        supported_modes = ["storyboard"]
    default_mode = default_generation_mode if default_generation_mode in supported_modes else supported_modes[0]
    template = {
        "id": template_id,
        "version": 1,
        "source": "builtin",
        "content_mode": content_mode,
        "name": name,
        "description": description,
        "supported_generation_modes": supported_modes,
        "recommended_generation_modes": supported_modes,
        "default_generation_mode": default_mode,
        "required_capabilities": required_capabilities,
        "preferred_capabilities": preferred_capabilities,
        "locked_contract": locked_contract,
        "output_fields": output_fields,
        "split_rules": split_rules,
        "forbidden_patterns": forbidden_patterns,
        "few_shot_examples": few_shot_examples,
        "quality_gates": quality_gates,
        "user_overlay": {
            "intent_brief": "",
            "tone_preferences": [],
            "extra_split_rules": [],
            "extra_forbidden_patterns": [],
            "example_source": "",
            "example_expected_output": "",
        },
    }
    if legacy_passthrough:
        template["legacy_passthrough"] = True
    if prompt_fragments:
        template["prompt_fragments"] = copy.deepcopy(prompt_fragments)
    return template


_NARRATION_CONTRACT = {
    "unit_name": "segment",
    "display_unit_name": "片段",
    "required_fields": [
        "segment_id",
        "novel_text",
        "duration_seconds",
        "segment_break",
    ],
    "id_format": "E{episode}S{two_digit_index}",
    "allowed_variables": [
        "project_overview",
        "episode",
        "source_text",
        "characters",
        "scenes",
        "props",
        "supported_durations",
        "default_duration",
    ],
}

_NARRATION_LEGACY_CONTRACT = {
    "unit_name": "segment",
    "display_unit_name": "片段",
    "required_fields": [
        "segment_id",
        "novel_text",
        "character_count",
        "duration_seconds",
        "has_dialogue",
        "segment_break",
    ],
    "id_format": "E{episode}S{two_digit_index}",
    "allowed_variables": [
        "project_overview",
        "episode",
        "source_text",
        "characters",
        "scenes",
        "props",
        "supported_durations",
        "default_duration",
    ],
}

_DRAMA_CONTRACT = {
    "unit_name": "scene",
    "display_unit_name": "镜头",
    "required_fields": [
        "scene_id",
        "dramatic_purpose",
        "start_state",
        "visible_action",
        "end_state",
        "duration_seconds",
        "segment_break",
        "transition_to_next",
    ],
    "id_format": "E{episode}S{two_digit_index}",
    "allowed_variables": [
        "project_overview",
        "episode",
        "source_text",
        "characters",
        "scenes",
        "props",
        "supported_durations",
        "default_duration",
    ],
}

_DRAMA_LEGACY_CONTRACT = {
    "unit_name": "scene",
    "display_unit_name": "场景",
    "required_fields": [
        "scene_id",
        "scene_description",
        "duration_seconds",
        "segment_break",
    ],
    "id_format": "E{episode}S{two_digit_index}",
    "allowed_variables": [
        "project_overview",
        "episode",
        "source_text",
        "characters",
        "scenes",
        "props",
        "supported_durations",
        "default_duration",
    ],
}

_REFERENCE_CONTRACT = {
    "unit_name": "video_unit",
    "display_unit_name": "视频单元",
    "required_fields": [
        "unit_id",
        "shots",
        "references",
        "duration_seconds",
    ],
    "id_format": "E{episode}U{two_digit_index}",
    "allowed_variables": [
        "project_overview",
        "episode",
        "source_text",
        "characters",
        "scenes",
        "props",
        "supported_durations",
        "default_duration",
        "max_reference_images",
        "max_duration",
    ],
}


_DRAMA_PRODUCTION_FIELDS = [
    "scene_id",
    "beat_type",
    "dramatic_purpose",
    "coverage_role",
    "start_state",
    "visible_action",
    "dialogue_core",
    "emotion_turn",
    "reaction_target",
    "end_state",
    "shot_size",
    "camera_angle",
    "camera_motion",
    "screen_direction",
    "eyeline_match",
    "match_action",
    "continuity_anchor",
    "reference_assets",
    "asset_binding_requirements",
    "first_frame_intent",
    "lighting_palette",
    "sound_cue",
    "provider_hints",
    "duration_seconds",
    "segment_break",
    "transition_to_next",
    "production_note",
]

_DRAMA_PRODUCTION_SPLIT_RULES = [
    "先把原文拆成可拍摄的视觉节拍，再按 establishing / action / reaction / insert / reveal / transition 选择 coverage_role。",
    "每个镜头只安排一个清楚主体动作和一种镜头运动；复杂动作、多人调度或大场面必须拆成连续短镜头。",
    "相邻镜头必须写明 end_state、start_state、screen_direction、eyeline_match 或 match_action 中至少一个衔接依据。",
    "对白场面要保留视线匹配、反应镜头或插入镜头，不让关键情绪只停留在台词里。",
    "图生视频、参考视频和宫格分镜都要写 first_frame_intent、reference_assets、provider_hints，让下游生成能直接接住首帧、主体和动作。",
]

_DRAMA_PRODUCTION_FORBIDDEN_PATTERNS = [
    "一个镜头同时换时空、换场景、换主动作或塞入多个反转。",
    "只写高级、震撼、压迫、唯美等抽象风格词，没有主体动作、镜头运动或可见线索。",
    "相邻镜头没有站位、视线、动作或道具状态衔接，导致剪辑时只能硬切。",
    "为了追求炫技而安排 360 度旋转、快速变焦、多主体复杂运动等高失控镜头。",
]

_DRAMA_PRODUCTION_QUALITY_GATES = [
    {"id": "single_shot_intent", "severity": "block", "description": "每个镜头必须只有一个主要动作或一个情绪转折。"},
    {"id": "continuity_match", "severity": "warn", "description": "相邻镜头必须可通过视线、方向、动作或道具状态接上。"},
    {"id": "generation_ready", "severity": "warn", "description": "first_frame_intent、reference_assets、provider_hints 应能直接服务图生视频/参考视频/宫格。"},
]


def _production_drama_fields(*style_fields: str) -> list[str]:
    fields = list(_DRAMA_PRODUCTION_FIELDS)
    insert_at = fields.index("provider_hints")
    for field in reversed([item for item in style_fields if item and item not in fields]):
        fields.insert(insert_at, field)
    return fields


BUILTIN_TEMPLATES: dict[str, dict[str, Any]] = {
    "narration_legacy_reading_default": _template(
        template_id="narration_legacy_reading_default",
        content_mode="narration",
        name="旧版默认：朗读节奏拆分",
        description="完整保留改版前的默认旁白方案：按朗读节奏、自然标点和段落边界拆片段，保留原文，segment_break 只标真正的时间、空间或情节切换。",
        recommended_generation_modes=list(GENERATION_MODE_ORDER),
        default_generation_mode="storyboard",
        required_capabilities=["single_shot_video"],
        preferred_capabilities=["first_frame"],
        locked_contract=_NARRATION_LEGACY_CONTRACT,
        output_fields=[
            "segment_id",
            "novel_text",
            "character_count",
            "duration_seconds",
            "has_dialogue",
            "segment_break",
        ],
        split_rules=[
            "片段 ID 统一使用 E{episode}S01、E{episode}S02 格式，从当前集第 1 个片段开始按顺序递增。",
            "默认单片段时长 = 项目的 default_duration（按朗读速度每秒约 5-6 字估算字数上限）。",
            "长句、情绪铺陈、关键对话可选用 supported_durations 中更长的值（如 2× / 3× default_duration）。",
            "保持语义完整性，不拆断完整的语义单元。",
            "优先在句号、问号、感叹号、省略号等标点处拆分，也可以在段落结束处拆分。",
            "识别包含角色对话的片段（如“XXX说道”、引号对白、「XXX」），并在“有对话”列标记“是”。",
            "segment_break 在重要场景切换点标记“是”（时间跳跃、空间转换、情节转折）；同一连续场景内标记“否”或“-”。",
            "原文字段保留完整标点；对话片段的原文包含完整说话内容和引导语。",
        ],
        forbidden_patterns=[
            "按固定字数机械切断完整语义单元。",
            "在连续同一场景内滥用 segment_break。",
            "删改原文标点、对白内容或对白引导语。",
        ],
        few_shot_examples=[
            {
                "source": "裴与出征后的第二年，千里加急给我送回一个襁褓中的婴儿。\n我站在府门口，看着信使远去的背影，心中五味杂陈。\n“夫人，这是侯爷的亲笔信。”老管家递上一封火漆封印的书信。\n三年过去了。",
                "good": "E1S01 | “裴与出征后的第二年，千里加急给我送回一个襁褓中的婴儿。” | 25 | <default_duration>s | 否 | -\nE1S02 | “我站在府门口，看着信使远去的背影，心中五味杂陈。” | 21 | <default_duration>s | 否 | -\nE1S03 | “夫人，这是侯爷的亲笔信。”老管家递上一封火漆封印的书信。 | 24 | <default_duration>s | 是 | -\nE1S04 | “三年过去了。” | 6 | <default_duration>s | 否 | 是",
            }
        ],
        quality_gates=[
            {"id": "source_text_preserved", "severity": "block", "description": "原文字段必须保留小说原文。"},
            {"id": "reading_boundary", "severity": "warn", "description": "片段边界应贴合朗读自然停顿。"},
        ],
        legacy_passthrough=True,
        prompt_fragments={
            "agent_output_table": """## 片段拆分结果

| 片段 ID | 原文 | 字数 | 时长 | 有对话 | segment_break |
|------|------|------|------|--------|---------------|
| E1S01 | "裴与出征后的第二年，千里加急给我送回一个襁褓中的婴儿。" | 25 | <default_duration>s | 否 | - |
| E1S02 | "我站在府门口，看着信使远去的背影，心中五味杂陈。" | 21 | <default_duration>s | 否 | - |
| E1S03 | ""夫人，这是侯爷的亲笔信。"老管家递上一封火漆封印的书信。" | 24 | <default_duration>s | 是 | - |
| E1S04 | "三年过去了。" | 6 | <default_duration>s | 否 | 是 |""",
        },
    ),
    "narration_storytelling_classic": _template(
        template_id="narration_storytelling_classic",
        content_mode="narration",
        name="经典说书节奏",
        description="按叙事信息点拆分，保留原文感，适合连载小说说书。",
        recommended_generation_modes=["storyboard", "grid"],
        required_capabilities=["single_shot_video"],
        preferred_capabilities=["first_frame"],
        locked_contract=_NARRATION_CONTRACT,
        output_fields=[
            "segment_id",
            "narrative_purpose",
            "novel_text",
            "visual_focus",
            "duration_seconds",
            "has_dialogue",
            "segment_break",
            "transition_to_next",
        ],
        split_rules=[
            "旁白是主信息通道；一个 segment 只表达一个明确叙事信息点。",
            "保留小说原文，不改写事实，不把所有内心戏强行转成对白。",
            "优先在自然标点、段落边界和单一信息点结束处拆分。",
            "画面只服务一个主视觉焦点，避免在同一片段内塞入多个时空。",
        ],
        forbidden_patterns=[
            "按朗读字数机械切断完整语义。",
            "把不可见心理活动直接写成画面动作。",
            "一个片段同时承载铺垫、反转和新场景切换。",
        ],
        few_shot_examples=[
            {
                "source": "她推开尘封的木门，发现父亲留下的旧匣子。",
                "good": "E1S01 表达发现线索：保留原句，视觉聚焦木门与旧匣子，segment_break=是。",
            },
            {
                "source": "他终于明白这一切都是骗局。",
                "bad": "只写他明白骗局。",
                "fixed": "用旁白承载明白真相，画面聚焦他攥皱账本、抬眼看向门外。",
            },
        ],
        quality_gates=[
            {"id": "single_information_point", "severity": "warn", "description": "单片段只承载一个叙事信息点。"},
            {"id": "novel_text_preserved", "severity": "block", "description": "novel_text 不得删改原文事实。"},
        ],
    ),
    "narration_suspense_hook": _template(
        template_id="narration_suspense_hook",
        content_mode="narration",
        name="悬疑钩子节奏",
        description="更重首段钩子、段尾悬念和信息延迟释放，适合悬疑/复仇/反转短视频。",
        recommended_generation_modes=["storyboard", "grid"],
        required_capabilities=["single_shot_video"],
        preferred_capabilities=["first_frame", "camera_command"],
        locked_contract=_NARRATION_CONTRACT,
        output_fields=[
            "segment_id",
            "hook_role",
            "narrative_purpose",
            "novel_text",
            "visual_focus",
            "suspense_question",
            "duration_seconds",
            "has_dialogue",
            "segment_break",
            "transition_to_next",
        ],
        split_rules=[
            "开篇优先保留异常、危机或强反差画面，不先平铺世界观。",
            "段尾可在信息尚未完全解释时断开，形成下一段追问。",
            "每个 segment 只揭示一个线索或一个情绪反转。",
            "悬念来自信息顺序和画面焦点，不靠虚构原文没有的事件。",
        ],
        forbidden_patterns=[
            "把悬念写成空泛形容词，例如诡异、震撼、惊天秘密但无可见线索。",
            "一段内连续解释多个谜底。",
            "为制造钩子而改写原文事实。",
        ],
        few_shot_examples=[
            {
                "source": "棺材里空无一人，只压着半枚玉佩。",
                "good": "E1S01 作为强钩子：视觉聚焦空棺与半枚玉佩，suspense_question=棺中人去了哪里。",
            },
            {
                "source": "门外传来第三个人的脚步声。",
                "good": "段尾悬念：只揭示脚步声和角色反应，不提前说明来者身份。",
            },
        ],
        quality_gates=[
            {"id": "hook_visible_signal", "severity": "warn", "description": "悬念片段必须有可见线索或可听事件。"},
            {"id": "source_fidelity", "severity": "block", "description": "不得虚构原文没有的反转。"},
        ],
    ),
    "narration_cinematic_manga_drama": _template(
        template_id="narration_cinematic_manga_drama",
        content_mode="narration",
        name="旁白漫剧镜头流",
        description="保留小说旁白原文，同时把每段拆成可生成的影视化画面节拍，适合说书、漫剧和轻剧情旁白视频。",
        recommended_generation_modes=list(GENERATION_MODE_ORDER),
        default_generation_mode="storyboard",
        required_capabilities=["single_shot_video"],
        preferred_capabilities=["subject_reference", "first_frame", "camera_command"],
        locked_contract=_NARRATION_CONTRACT,
        output_fields=[
            "segment_id",
            "narrative_purpose",
            "novel_text",
            "visual_focus",
            "shot_size",
            "camera_motion",
            "continuity_anchor",
            "first_frame_intent",
            "sound_cue",
            "duration_seconds",
            "has_dialogue",
            "segment_break",
            "transition_to_next",
        ],
        split_rules=[
            "novel_text 必须保留原文；影视化只写在 visual_focus、camera_motion、first_frame_intent 等字段中。",
            "每个 segment 只承载一个旁白信息点和一个主视觉焦点，避免把长段心理活动拆成空泛氛围图。",
            "不可见心理必须通过旁白保留，画面只补充可见动作、道具、光线、视线或环境动态。",
            "连续同一场景内要写 continuity_anchor；segment_break=是时才允许重新建立空间和首帧构图。",
            "camera_motion 以固定镜头、慢推、轻微跟随为主，只有动作明确时才使用更强运镜。",
        ],
        forbidden_patterns=[
            "删改小说原文以适配画面。",
            "把一整段旁白压成一个静态氛围词，例如孤独、绝望、震撼。",
            "连续片段中角色服装、道具状态或空间方位无理由跳变。",
        ],
        few_shot_examples=[
            {
                "source": "她终于在母亲的旧箱底找到那封被烧过一角的信。",
                "good": "E1S01 novel_text=原句；visual_focus=旧木箱、烧角信纸和她停住的手；first_frame_intent=手电光照在箱底信纸上；transition_to_next=match cut to letter close-up。",
            },
            {
                "source": "我这才知道，原来所有人都在骗我。",
                "bad": "画面写我震惊地知道真相。",
                "fixed": "旁白保留原句；画面聚焦她攥皱名单、目光扫过门外几道人影。",
            },
        ],
        quality_gates=[
            {"id": "novel_text_preserved", "severity": "block", "description": "novel_text 不得删改原文。"},
            {"id": "visual_focus_actionable", "severity": "warn", "description": "visual_focus 必须能转成单帧画面或单镜头动作。"},
            {"id": "narration_continuity", "severity": "warn", "description": "同场连续旁白片段应保留连续性锚点。"},
        ],
    ),
    "drama_legacy_scene_default": _template(
        template_id="drama_legacy_scene_default",
        content_mode="drama",
        name="旧版默认：结构化场景表",
        description="完整保留改版前的默认剧情方案：把小说改编为 Markdown 场景表，每个场景是一个独立视觉画面，使用 E{集}Sxx 编号并标注时长与 segment_break。",
        recommended_generation_modes=list(GENERATION_MODE_ORDER),
        default_generation_mode="storyboard",
        required_capabilities=["single_shot_video"],
        preferred_capabilities=["first_frame"],
        locked_contract=_DRAMA_LEGACY_CONTRACT,
        output_fields=[
            "scene_id",
            "scene_description",
            "duration_seconds",
            "segment_break",
        ],
        split_rules=[
            "将小说改编为结构化场景列表，而不是逐字保留原文。",
            "所有场景 ID 必须使用 E{episode}S{两位序号} 格式，不得使用其他集号前缀。",
            "场景描述是改编后的剧本化描述，包含角色动作、对话、环境，适合视觉化呈现。",
            "时长只能取当前视频模型支持的秒数集合；不要默认挑最短值。",
            "打斗、大场面、情绪铺陈等画面可取更长值至模型上限。",
            "segment_break 标记场景切换点，同一连续场景标“否”。",
            "每个场景应为一个独立视觉画面，可以在指定时长内完成。",
        ],
        forbidden_patterns=[
            "一个场景包含多个不同动作或画面切换。",
            "时长使用模型不支持的秒数。",
            "使用非当前集号的场景 ID 前缀。",
        ],
        few_shot_examples=[
            {
                "source": "竹林深处，晨雾弥漫。青年剑客李明手持长剑，缓缓踏入林间。",
                "good": "E1S01 | 竹林深处，晨雾弥漫。青年剑客李明手持长剑，缓缓踏入林间，目光坚定。 | <duration> | 是",
            }
        ],
        quality_gates=[
            {"id": "scene_table_shape", "severity": "block", "description": "输出必须是场景 ID、场景描述、时长、segment_break 表格。"},
            {"id": "single_visual_scene", "severity": "warn", "description": "每个场景应能作为单个视觉画面生成。"},
        ],
        legacy_passthrough=True,
        prompt_fragments={
            "normalize_table_template": """| 场景 ID | 场景描述 | 时长 | segment_break |
|---------|---------|------|---------------|
| E{episode}S01 | 详细的场景描述... | <duration> | 是 |
| E{episode}S02 | 详细的场景描述... | <duration> | 否 |""",
            "normalize_field_rule": "- 场景描述：改编后的剧本化描述，包含角色动作、对话、环境，适合视觉化呈现",
        },
    ),
    "drama_web_short_hook": _template(
        template_id="drama_web_short_hook",
        content_mode="drama",
        name="短剧爽点节奏",
        description="高密度冲突、强钩子、强反转；同时补齐反应镜头、视线衔接和首帧锚点，适合短剧爽点内容。",
        recommended_generation_modes=["storyboard", "reference_video"],
        required_capabilities=["single_shot_video"],
        preferred_capabilities=["subject_reference", "first_last_frame", "multi_shot", "camera_command"],
        locked_contract=_DRAMA_CONTRACT,
        output_fields=_production_drama_fields("payoff_hook"),
        split_rules=[
            *_DRAMA_PRODUCTION_SPLIT_RULES,
            "一个镜头只承担一个主要动作或一个明确情绪转折。",
            "首镜优先建立冲突、羞辱、危险、误会或强反差，不从背景介绍开始。",
            "每 3-5 个镜头至少形成一次小 payoff：反击、打脸、身份露出、众人见证、证据翻出或情绪压倒。",
            "payoff_hook 写下一镜观众期待看到的爽点兑现，不提前把后续反转解释完。",
        ],
        forbidden_patterns=[
            *_DRAMA_PRODUCTION_FORBIDDEN_PATTERNS,
            "用决定、意识到、回忆起、感到绝望等不可见动词替代可见表演。",
            "把爽点写成口号式总结，没有证据、反应镜头或可见行动承接。",
        ],
        few_shot_examples=[
            {
                "source": "她看见丈夫牵着陌生女人进门，手里的汤碗摔碎。",
                "good": "E1S01 coverage_role=hook/action；start_state=她端汤站在门内；visible_action=目光定住、汤碗坠地；end_state=碎瓷散开，丈夫回头；reaction_target=丈夫与陌生女人；payoff_hook=下一镜看丈夫反应。",
            },
            {
                "source": "他心里决定反击。",
                "bad": "他下定决心反击。",
                "fixed": "他沉默合上账本，把证据推入抽屉，抬头直视对方。",
            },
        ],
        quality_gates=[
            *_DRAMA_PRODUCTION_QUALITY_GATES,
            {"id": "state_fields_present", "severity": "block", "description": "start_state/end_state/transition_to_next 必须存在。"},
            {"id": "visible_action_only", "severity": "warn", "description": "visible_action 不应只写不可见心理。"},
            {"id": "payoff_visible", "severity": "warn", "description": "爽点兑现需要有可见证据、行动或反应镜头。"},
        ],
    ),
    "drama_reference_continuity_lite": _template(
        template_id="drama_reference_continuity_lite",
        content_mode="drama",
        name="轻量参考连续性",
        description="适合剧情视频需要角色、场景、道具前后一致：保留普通分镜拆分方式，同时补充连续性锚点和首帧意图。",
        recommended_generation_modes=["storyboard", "reference_video"],
        required_capabilities=["single_shot_video"],
        preferred_capabilities=["subject_reference", "element_reference", "first_last_frame", "multi_shot"],
        locked_contract=_DRAMA_CONTRACT,
        output_fields=[
            "scene_id",
            "dramatic_purpose",
            "start_state",
            "visible_action",
            "end_state",
            "continuity_anchor",
            "reference_assets",
            "asset_binding_requirements",
            "first_frame_intent",
            "shot_sequence",
            "provider_hints",
            "duration_seconds",
            "segment_break",
            "transition_to_next",
        ],
        split_rules=[
            "每个镜头必须声明角色、场景、道具的连续性锚点。",
            "reference_assets 只引用项目中已有资产；缺资产时写需求，不发明名称。",
            "first_frame_intent 描述首帧应固定的主体位置、视线和关键道具。",
            "相邻镜头 end_state 与下一个 start_state 必须能接上。",
        ],
        forbidden_patterns=[
            "同一角色在相邻镜头中无理由换服装、换位置或换道具状态。",
            "reference_assets 写成泛泛描述而非项目资产引用。",
            "把完整 reference_video 阶段 2 的多 unit 设计塞进普通 storyboard Step 1。",
        ],
        few_shot_examples=[
            {
                "source": "她从门口退到桌边，抓起玉佩挡在胸前。",
                "good": "continuity_anchor=角色站位从门口到桌边；reference_assets=只填项目资产表中能精确命中的角色/道具/场景名称，不确定项写入 asset_binding_requirements；first_frame_intent=她半身在画面左侧，关键道具位于胸前。",
            }
        ],
        quality_gates=[
            {"id": "asset_refs_known", "severity": "warn", "description": "reference_assets 应尽量来自项目资产表。"},
            {"id": "first_frame_intent_present", "severity": "warn", "description": "需要首帧意图描述。"},
        ],
    ),
    "drama_cinematic_shot_flow": _template(
        template_id="drama_cinematic_shot_flow",
        content_mode="drama",
        name="影视镜头流",
        description="通用制作型预设：用建立镜头、动作镜头、反应镜头、插入镜头和匹配剪辑组织剧情，适合真人感和动漫感短剧。",
        recommended_generation_modes=list(GENERATION_MODE_ORDER),
        default_generation_mode="storyboard",
        required_capabilities=["single_shot_video"],
        preferred_capabilities=["subject_reference", "first_last_frame", "multi_shot", "camera_command"],
        locked_contract=_DRAMA_CONTRACT,
        output_fields=_production_drama_fields(),
        split_rules=[
            *_DRAMA_PRODUCTION_SPLIT_RULES,
            "重要动作优先拆成“动作开始 -> 动作中段 -> 反应/结果”三类镜头，而不是一个长镜头讲完。",
            "每场开头先建立空间、人物站位或冲突关系；每场结束保留能剪到下一场的动作、视线、道具或声音。",
        ],
        forbidden_patterns=[
            *_DRAMA_PRODUCTION_FORBIDDEN_PATTERNS,
            "只有连续中景对白，没有反应、插入、特写或空间建立镜头。",
        ],
        few_shot_examples=[
            {
                "source": "他推门进来，所有人都安静了。",
                "good": "E1S01 coverage_role=establishing/action；visible_action=门被推开，屋内众人动作停住；reaction_target=桌边众人；screen_direction=他从画面右侧进入；match_action=推门动作接下一镜众人回头。",
            }
        ],
        quality_gates=[
            *_DRAMA_PRODUCTION_QUALITY_GATES,
            {"id": "coverage_variety", "severity": "warn", "description": "连续 4 个以上镜头不应全部是同一景别和同一 coverage_role。"},
        ],
    ),
    "drama_suspense_clue_chain": _template(
        template_id="drama_suspense_clue_chain",
        content_mode="drama",
        name="悬疑线索推进",
        description="适合悬疑、复仇、刑侦和反转：按异常信号、线索特写、人物反应和延迟揭示来拆镜。",
        recommended_generation_modes=list(GENERATION_MODE_ORDER),
        default_generation_mode="storyboard",
        required_capabilities=["single_shot_video"],
        preferred_capabilities=["first_frame", "camera_command", "native_audio", "subject_reference"],
        locked_contract=_DRAMA_CONTRACT,
        output_fields=_production_drama_fields("clue_state", "reveal_boundary"),
        split_rules=[
            *_DRAMA_PRODUCTION_SPLIT_RULES,
            "每个镜头只推进一个线索：异常物件、可疑动作、证词矛盾、空间痕迹或人物反应。",
            "clue_state 写清线索处于“发现 / 遮挡 / 被误读 / 被验证 / 暂不揭示”的哪一阶段。",
            "reveal_boundary 写本镜头允许观众知道什么、必须保留什么；谜底不要提前解释完。",
            "声音线索可以作为转场：脚步、门轴、钟声、手机震动等必须写入 sound_cue。",
        ],
        forbidden_patterns=[
            *_DRAMA_PRODUCTION_FORBIDDEN_PATTERNS,
            "用旁白直接揭露凶手、真相或幕后身份，跳过线索和反应镜头。",
            "每个镜头都只写阴森氛围，没有可见线索或可听事件。",
        ],
        few_shot_examples=[
            {
                "source": "她打开衣柜，发现里面挂着一件不属于自己的湿外套。",
                "good": "E1S01 coverage_role=insert/reaction；clue_state=发现异常物件；visible_action=柜门打开，湿外套滴水；reaction_target=她的手停在门把上；reveal_boundary=只暴露外套来源异常，不说明来者是谁。",
            }
        ],
        quality_gates=[
            *_DRAMA_PRODUCTION_QUALITY_GATES,
            {"id": "clue_visible_or_audible", "severity": "warn", "description": "悬疑镜头必须有可见线索或可听线索。"},
            {"id": "reveal_control", "severity": "warn", "description": "每个镜头只揭示一层信息，不提前解完谜底。"},
        ],
    ),
    "drama_xuanhuan_xianxia_spectacle": _template(
        template_id="drama_xuanhuan_xianxia_spectacle",
        content_mode="drama",
        name="玄幻修仙奇观",
        description="适合玄幻、修仙、异能和国风战斗：用力量锚点、动作段落和反应镜头控制奇观，不把大场面写散。",
        recommended_generation_modes=["storyboard", "reference_video", "grid"],
        default_generation_mode="storyboard",
        required_capabilities=["single_shot_video"],
        preferred_capabilities=["subject_reference", "element_reference", "first_last_frame", "multi_shot", "camera_command"],
        locked_contract=_DRAMA_CONTRACT,
        output_fields=_production_drama_fields("power_anchor", "scale_control"),
        split_rules=[
            *_DRAMA_PRODUCTION_SPLIT_RULES,
            "先建立角色、法器、阵法、灵光或环境破坏的 power_anchor，再写动作爆发。",
            "大场面按“起势 / 交锋 / 影响 / 反应 / 余波”拆成短镜头，避免单镜头同时写满天法术和多人战斗。",
            "scale_control 写本镜头奇观尺度：近身细节、单人法术、双人交锋、场景级冲击或天地异象。",
            "动漫风可写衣摆、发丝、灵光粒子、符文、尘土等细节，但动作仍必须物理可见。",
        ],
        forbidden_patterns=[
            *_DRAMA_PRODUCTION_FORBIDDEN_PATTERNS,
            "一镜同时写多人乱战、法术变化、场景坍塌和角色心理转折。",
            "只写恢弘、燃、炸裂，没有明确法器、动作方向或环境影响。",
        ],
        few_shot_examples=[
            {
                "source": "少年拔剑，剑身亮起青色符文，山门前的石阶寸寸裂开。",
                "good": "E1S01 coverage_role=action/insert；power_anchor=青色符文长剑；visible_action=剑身亮起，石阶从剑尖方向裂开；scale_control=单人法术影响近景环境；sound_cue=石阶碎裂声。",
            }
        ],
        quality_gates=[
            *_DRAMA_PRODUCTION_QUALITY_GATES,
            {"id": "spectacle_anchor", "severity": "warn", "description": "奇观必须绑定角色、法器、阵法、场景破坏或明确能量锚点。"},
            {"id": "scale_not_overloaded", "severity": "warn", "description": "单镜头奇观尺度不能同时跨越多个动作阶段。"},
        ],
    ),
    "drama_apocalypse_survival_pressure": _template(
        template_id="drama_apocalypse_survival_pressure",
        content_mode="drama",
        name="末世压迫逃生",
        description="适合末世、生存、灾变和怪物压迫：按威胁距离、资源状态、空间出口和角色决策动作来拆镜。",
        recommended_generation_modes=["storyboard", "reference_video"],
        default_generation_mode="storyboard",
        required_capabilities=["single_shot_video"],
        preferred_capabilities=["subject_reference", "first_last_frame", "camera_command", "native_audio"],
        locked_contract=_DRAMA_CONTRACT,
        output_fields=_production_drama_fields("threat_vector", "survival_resource", "escape_route"),
        split_rules=[
            *_DRAMA_PRODUCTION_SPLIT_RULES,
            "每个镜头写清威胁从哪里来、离角色多远、角色能看见或听见什么。",
            "survival_resource 写当前可用资源：武器、药品、燃料、食物、门锁、车辆、通讯或同伴状态。",
            "escape_route 写角色可走的空间路径或被封锁的出口，保证追逐和逃生方向能接上。",
            "压迫感来自可见限制：低光、狭窄空间、门缝、倒计时、脚步声、失效设备，而不是空泛恐慌。",
        ],
        forbidden_patterns=[
            *_DRAMA_PRODUCTION_FORBIDDEN_PATTERNS,
            "没有空间出口、威胁方向或资源状态，只写末世很危险。",
            "同一镜头里既逃跑、战斗、找物资又完成情绪反转。",
        ],
        few_shot_examples=[
            {
                "source": "走廊尽头传来撞门声，她只剩最后一发子弹。",
                "good": "E1S01 coverage_role=establishing/insert；threat_vector=走廊尽头门后撞击；survival_resource=手枪仅一发子弹；escape_route=右侧消防门半掩；sound_cue=连续撞门声。",
            }
        ],
        quality_gates=[
            *_DRAMA_PRODUCTION_QUALITY_GATES,
            {"id": "threat_direction_present", "severity": "warn", "description": "末世压迫镜头应写清威胁方向和距离。"},
            {"id": "survival_state_visible", "severity": "warn", "description": "资源、出口或同伴状态需要可见化。"},
        ],
    ),
    "drama_folk_horror_ritual_dread": _template(
        template_id="drama_folk_horror_ritual_dread",
        content_mode="drama",
        name="民俗鬼怪氛围",
        description="适合民俗、怪谈、灵异和乡土恐怖：用禁忌、仪式物、空间声响和延迟露出来制造真实压迫。",
        recommended_generation_modes=list(GENERATION_MODE_ORDER),
        default_generation_mode="storyboard",
        required_capabilities=["single_shot_video"],
        preferred_capabilities=["first_frame", "camera_command", "native_audio", "element_reference"],
        locked_contract=_DRAMA_CONTRACT,
        output_fields=_production_drama_fields("folklore_taboo", "ritual_symbol", "unseen_presence"),
        split_rules=[
            *_DRAMA_PRODUCTION_SPLIT_RULES,
            "每个恐怖镜头先写可见民俗物或空间异常：红绳、纸钱、牌位、香灰、门槛、水缸、戏台、祠堂等。",
            "folklore_taboo 写本镜头触犯或接近的禁忌，ritual_symbol 写承载禁忌的具体物件。",
            "鬼怪不必频繁正面出现；可用影子、脚步、风铃、香灰、门缝、视线反应建立 unseen_presence。",
            "恐怖衔接优先使用声音、视线、物件状态变化和慢推近景，不靠突兀跳吓堆叠。",
        ],
        forbidden_patterns=[
            *_DRAMA_PRODUCTION_FORBIDDEN_PATTERNS,
            "只写恐怖、诡异、阴森，没有民俗物件、空间异常或声音线索。",
            "每个镜头都让鬼怪正面露出，导致悬念和真实感失效。",
        ],
        few_shot_examples=[
            {
                "source": "她跨过门槛时，脚边的红绳自己断了。",
                "good": "E1S01 coverage_role=insert/reaction；folklore_taboo=夜里不可跨祠堂门槛；ritual_symbol=门槛红绳；visible_action=红绳在脚边绷断；unseen_presence=门内烛火同时偏向同一侧。",
            }
        ],
        quality_gates=[
            *_DRAMA_PRODUCTION_QUALITY_GATES,
            {"id": "folk_anchor_visible", "severity": "warn", "description": "民俗恐怖镜头必须有可见仪式物、禁忌物或空间异常。"},
            {"id": "horror_reveal_delayed", "severity": "warn", "description": "鬼怪露出要有延迟和反应，不应连续硬露。"},
        ],
    ),
    "drama_emotional_conflict_performance": _template(
        template_id="drama_emotional_conflict_performance",
        content_mode="drama",
        name="情感冲突表演",
        description="适合婚恋、家庭、虐恋、职场和关系修罗场：用视线、停顿、微表情、反应镜头和物件细节承接情绪。",
        recommended_generation_modes=list(GENERATION_MODE_ORDER),
        default_generation_mode="storyboard",
        required_capabilities=["single_shot_video"],
        preferred_capabilities=["subject_reference", "first_last_frame", "dialogue_audio", "camera_command"],
        locked_contract=_DRAMA_CONTRACT,
        output_fields=_production_drama_fields("subtext", "acting_detail", "dialogue_timing"),
        split_rules=[
            *_DRAMA_PRODUCTION_SPLIT_RULES,
            "情绪变化要拆成可拍表演：停顿、视线闪避、手部动作、呼吸、吞咽、笑容消失、拿起或放下物件。",
            "subtext 写台词背后的真实意图；acting_detail 写可见表演细节，不能只写伤心、愤怒、崩溃。",
            "dialogue_timing 写台词与动作的时间关系：先看见证据再开口、沉默后开口、打断对方、说完后反应。",
            "冲突镜头要给对手反应或旁观者反应，尤其是羞辱、误会、摊牌和选择时刻。",
        ],
        forbidden_patterns=[
            *_DRAMA_PRODUCTION_FORBIDDEN_PATTERNS,
            "连续对白没有停顿、反应、视线或手部动作。",
            "把情绪写成抽象总结，没有可见表演或物件互动。",
        ],
        few_shot_examples=[
            {
                "source": "她把离婚协议推到他面前，笑着说不用解释了。",
                "good": "E1S01 coverage_role=action/reaction；visible_action=她把协议推过桌面，笑容停在嘴角；subtext=她已知道真相但压住情绪；acting_detail=指尖压住纸角微微发白；dialogue_timing=推纸后停一拍再说台词。",
            }
        ],
        quality_gates=[
            *_DRAMA_PRODUCTION_QUALITY_GATES,
            {"id": "emotion_visible", "severity": "warn", "description": "情绪必须通过表演细节、停顿、视线或物件互动呈现。"},
            {"id": "reaction_present", "severity": "warn", "description": "关键冲突需要对方或旁观者反应镜头。"},
        ],
    ),
    "drama_reference_continuity": _template(
        template_id="drama_reference_continuity",
        content_mode="drama",
        name="高一致性参考视频",
        description="适合以参考图/参考视频保持高一致性：把连续动作拆成可生成的视频单元，明确角色、场景、道具参考和镜头衔接。",
        recommended_generation_modes=["reference_video"],
        required_capabilities=["single_shot_video", "subject_reference"],
        preferred_capabilities=["reference_video", "native_audio", "multi_shot", "first_last_frame"],
        locked_contract=_REFERENCE_CONTRACT,
        output_fields=[
            "unit_id",
            "shots",
            "references",
            "shot_sequence",
            "audio_plan",
            "provider_hints",
            "duration_seconds",
            "transition_to_next",
        ],
        split_rules=[
            "每个 video_unit 对应一次参考视频生成调用，包含 1-4 个连续 shot。",
            "references 必须覆盖 unit 中出现的关键角色、场景和道具。",
            "按 provider 能力把 2-4 个连续镜头合并为短任务，不把整集塞入一个 prompt。",
            "每个 shot 只写一个主体动作和一种镜头运动；多动作、多反应或跨空间内容拆成多个 shot 或多个 unit。",
            "同一 unit 内的 shot 必须共享连续空间、连续角色状态和可接上的动作方向；跨场景时开启新 unit。",
            "shot_sequence 写清建立镜头、动作镜头、反应镜头、插入镜头或转场镜头的顺序。",
            "audio_plan 只写本 unit 内可执行的对白、环境声和关键物体声，不把整集 BGM 或后期包装塞入生成任务。",
        ],
        forbidden_patterns=[
            "跨时空、跨场景或动作状态不连续的 shot 合并进同一 unit。",
            "忽略参考素材数量和时长上限。",
            "shot text 复述参考图外貌、服装和场景细节，导致参考一致性被文本冲突覆盖。",
            "一个 unit 承担完整一场戏或多个情绪转折，导致生成时动作和口型失控。",
        ],
        few_shot_examples=[
            {
                "source": "他从门口走到桌边，拿起账本，抬头看向对面的人。",
                "good": "E1U01 shots=Shot1 @[他] 从门口走向 @[桌边]；Shot2 @[他] 拿起 @[账本] 并抬头；references=character:他, scene:房间, prop:账本；shot_sequence=动作镜头接反应镜头。",
            }
        ],
        quality_gates=[
            {"id": "reference_count_limit", "severity": "block", "description": "references 数量不得超过 provider 上限。"},
            {"id": "unit_duration_limit", "severity": "block", "description": "unit 总时长不得超过 provider 上限。"},
            {"id": "unit_continuity", "severity": "warn", "description": "同一 unit 内镜头必须动作和空间连续。"},
        ],
    ),
}


def _resolve_data_root(data_root: str | Path | None = None) -> Path:
    if data_root is not None:
        return Path(data_root)
    try:
        from lib.app_data_dir import app_data_dir

        return app_data_dir()
    except Exception:
        for env_key in ("ARCREEL_DATA_DIR", "AI_ANIME_PROJECTS"):
            raw = os.environ.get(env_key, "").strip()
            if raw:
                path = Path(raw)
                if not path.is_absolute():
                    path = Path(__file__).resolve().parents[1] / path
                path.mkdir(parents=True, exist_ok=True)
                return path.resolve()
        fallback = Path(__file__).resolve().parents[1] / "projects"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def script_splitting_templates_root(data_root: str | Path | None = None) -> Path:
    root = _resolve_data_root(data_root) / _CUSTOM_TEMPLATES_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _custom_templates_file_path(data_root: str | Path | None = None) -> Path:
    return script_splitting_templates_root(data_root) / _CUSTOM_TEMPLATES_FILE


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    return []


def _validation_issue(
    issue_id: str,
    *,
    check_type: str,
    severity: str,
    field: str,
    message: str,
    repair_hint: str | None = None,
    autofix_allowed: bool = False,
) -> dict[str, Any]:
    issue = {
        "id": issue_id,
        "check_type": check_type,
        "severity": severity,
        "field": field,
        "message": message,
        "autofix_allowed": autofix_allowed,
    }
    if repair_hint:
        issue["repair_hint"] = repair_hint
    return issue


def _base_template_for_profile(profile: dict[str, Any]) -> dict[str, Any] | None:
    base_id = str(profile.get("base_template_id") or "")
    if base_id:
        return BUILTIN_TEMPLATES.get(base_id)
    contract = profile.get("locked_contract")
    for template in BUILTIN_TEMPLATES.values():
        if template.get("content_mode") == profile.get("content_mode") and template.get("locked_contract") == contract:
            return template
    return None


def validate_script_splitting_template(
    profile: dict[str, Any],
    *,
    autofix: bool = True,
) -> dict[str, Any]:
    """Validate a user/imported splitting template and return diagnostics plus normalized profile."""
    normalized = copy.deepcopy(profile) if isinstance(profile, dict) else {}
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    tpl_id = str(normalized.get("id") or "").strip()
    if not _TEMPLATE_ID_RE.fullmatch(tpl_id):
        errors.append(
            _validation_issue(
                "invalid_template_id",
                check_type="schema",
                severity="block",
                field="id",
                message="模板 ID 只能使用小写字母、数字和下划线，并以字母开头。",
                repair_hint="使用形如 user_short_hook 的模板 ID。",
            )
        )
    normalized["id"] = tpl_id

    source = str(normalized.get("source") or "user_generated")
    if source not in VALID_TEMPLATE_SOURCES or source == "builtin":
        if autofix:
            source = "user_generated"
        else:
            errors.append(
                _validation_issue(
                    "invalid_source",
                    check_type="schema",
                    severity="block",
                    field="source",
                    message="用户模板 source 必须是 user_generated 或 imported。",
                )
            )
    normalized["source"] = source
    normalized.pop("legacy_passthrough", None)

    content_mode = str(normalized.get("content_mode") or "")
    if content_mode not in VALID_CONTENT_MODES:
        errors.append(
            _validation_issue(
                "invalid_content_mode",
                check_type="schema",
                severity="block",
                field="content_mode",
                message="content_mode 必须是 narration 或 drama。",
            )
        )

    base_template = _base_template_for_profile(normalized)
    if base_template is None:
        errors.append(
            _validation_issue(
                "missing_base_template",
                check_type="contract",
                severity="block",
                field="base_template_id",
                message="用户模板必须继承一个内置模板契约。",
                repair_hint="从内置模板复制后再定制。",
            )
        )
        fallback_mode = content_mode if content_mode in VALID_CONTENT_MODES else "narration"
        base_template = BUILTIN_TEMPLATES.get(DEFAULT_TEMPLATE_BY_MODE[fallback_mode])
    if base_template is not None:
        normalized["base_template_id"] = base_template["id"]
        if normalized.get("content_mode") != base_template.get("content_mode"):
            errors.append(
                _validation_issue(
                    "content_mode_mismatch",
                    check_type="contract",
                    severity="block",
                    field="content_mode",
                    message="用户模板 content_mode 必须与来源模板一致。",
                )
            )
        normalized["content_mode"] = base_template["content_mode"]
        if normalized.get("locked_contract") != base_template.get("locked_contract"):
            errors.append(
                _validation_issue(
                    "locked_contract_changed",
                    check_type="contract",
                    severity="block",
                    field="locked_contract",
                    message="用户模板不能修改来源模板的固定契约。",
                )
            )
            if autofix:
                normalized["locked_contract"] = copy.deepcopy(base_template["locked_contract"])

        required_fields = list(base_template.get("locked_contract", {}).get("required_fields") or [])
        output_fields = _string_list(normalized.get("output_fields"))
        missing_fields = [field for field in required_fields if field not in output_fields]
        if missing_fields and autofix:
            output_fields.extend(missing_fields)
            warnings.append(
                _validation_issue(
                    "missing_required_field_autofixed",
                    check_type="contract",
                    severity="warn",
                    field="output_fields",
                    message="已补回来源模板必填字段。",
                    repair_hint=", ".join(missing_fields),
                    autofix_allowed=True,
                )
            )
        elif missing_fields:
            errors.append(
                _validation_issue(
                    "missing_required_field",
                    check_type="contract",
                    severity="block",
                    field="output_fields",
                    message="output_fields 缺少来源模板必填字段。",
                    repair_hint=", ".join(missing_fields),
                    autofix_allowed=True,
                )
            )
        normalized["output_fields"] = output_fields

        base_gate_map = {gate.get("id"): gate for gate in base_template.get("quality_gates") or [] if isinstance(gate, dict)}
        gate_map = {gate.get("id"): gate for gate in normalized.get("quality_gates") or [] if isinstance(gate, dict)}
        for gate_id, base_gate in base_gate_map.items():
            gate = gate_map.get(gate_id)
            if gate is None or gate.get("severity") != base_gate.get("severity"):
                errors.append(
                    _validation_issue(
                        "quality_gate_changed",
                        check_type="contract",
                        severity="block",
                        field="quality_gates",
                        message="用户模板不能删除或降级来源模板质检规则。",
                        repair_hint=str(gate_id),
                    )
                )
        if errors and autofix:
            existing_extra = [
                gate for gate in normalized.get("quality_gates") or []
                if isinstance(gate, dict) and gate.get("id") not in base_gate_map
            ]
            normalized["quality_gates"] = copy.deepcopy(base_template.get("quality_gates") or []) + existing_extra

        base_forbidden = [str(item) for item in base_template.get("forbidden_patterns") or []]
        forbidden = _string_list(normalized.get("forbidden_patterns"))
        missing_forbidden = [item for item in base_forbidden if item not in forbidden]
        if missing_forbidden:
            errors.append(
                _validation_issue(
                    "forbidden_pattern_removed",
                    check_type="contract",
                    severity="block",
                    field="forbidden_patterns",
                    message="用户模板不能删除来源模板禁止写法。",
                )
            )
            if autofix:
                forbidden = base_forbidden + [item for item in forbidden if item not in base_forbidden]
        normalized["forbidden_patterns"] = forbidden

    modes = _normalize_generation_modes(
        normalized.get("supported_generation_modes")
        if "supported_generation_modes" in normalized
        else normalized.get("recommended_generation_modes")
    )
    if not modes and base_template is not None:
        modes = _template_supported_generation_modes(base_template)
    if not modes:
        modes = ["storyboard"]
    normalized["supported_generation_modes"] = modes
    normalized["recommended_generation_modes"] = modes
    normalized["default_generation_mode"] = _template_default_generation_mode(normalized, modes)

    required_caps = _string_list(normalized.get("required_capabilities"))
    invalid_required = [cap for cap in required_caps if cap not in VALID_TEMPLATE_CAPABILITIES]
    if invalid_required:
        errors.append(
            _validation_issue(
                "invalid_required_capability",
                check_type="compatibility",
                severity="block",
                field="required_capabilities",
                message="required_capabilities 包含未知能力。",
                repair_hint=", ".join(invalid_required),
            )
        )
    if base_template is not None:
        base_required = list(base_template.get("required_capabilities") or [])
        required_caps = base_required + [cap for cap in required_caps if cap not in base_required]
    normalized["required_capabilities"] = [cap for cap in required_caps if cap in VALID_TEMPLATE_CAPABILITIES]

    preferred_caps = _string_list(normalized.get("preferred_capabilities"))
    filtered_preferred = [cap for cap in preferred_caps if cap in VALID_TEMPLATE_CAPABILITIES]
    if len(filtered_preferred) != len(preferred_caps):
        warnings.append(
            _validation_issue(
                "invalid_preferred_capability_filtered",
                check_type="compatibility",
                severity="warn",
                field="preferred_capabilities",
                message="已过滤未知推荐能力。",
                autofix_allowed=True,
            )
        )
    normalized["preferred_capabilities"] = filtered_preferred

    normalized["name"] = str(normalized.get("name") or "").strip()
    if not normalized["name"]:
        errors.append(
            _validation_issue(
                "missing_name",
                check_type="schema",
                severity="block",
                field="name",
                message="拆分方案标题不能为空。",
            )
        )
    normalized["description"] = str(normalized.get("description") or "").strip()
    if not normalized["description"]:
        errors.append(
            _validation_issue(
                "missing_description",
                check_type="schema",
                severity="block",
                field="description",
                message="拆分方案描述不能为空。",
            )
        )
    normalized["version"] = int(normalized.get("version") or 1)
    normalized["split_rules"] = _string_list(normalized.get("split_rules"))
    if not normalized["split_rules"]:
        errors.append(
            _validation_issue(
                "missing_split_rules",
                check_type="schema",
                severity="block",
                field="split_rules",
                message="拆分规则不能为空。",
            )
        )
    normalized["few_shot_examples"] = [
        item for item in normalized.get("few_shot_examples") or [] if isinstance(item, dict)
    ]
    normalized.setdefault("user_overlay", {})
    normalized["hash"] = script_splitting_hash(normalized)
    return {"ok": not errors, "errors": errors, "warnings": warnings, "profile": normalized}


def _normalize_custom_template_item(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    validation = validate_script_splitting_template(raw, autofix=True)
    if not validation["ok"]:
        return None
    return validation["profile"]


def _load_custom_templates(data_root: str | Path | None = None) -> list[dict[str, Any]]:
    path = _custom_templates_file_path(data_root)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_items = raw.get("templates", []) if isinstance(raw, dict) else raw
    if not isinstance(raw_items, list):
        return []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item = _normalize_custom_template_item(raw_item)
        if item is None or item["id"] in seen or item["id"] in BUILTIN_TEMPLATES:
            continue
        seen.add(item["id"])
        items.append(item)
    return items


def _save_custom_templates(items: list[dict[str, Any]], data_root: str | Path | None = None) -> None:
    _atomic_write_json(_custom_templates_file_path(data_root), {"templates": items})


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _canonicalize(v) for k, v in sorted(value.items()) if k not in _HASH_EXCLUDED_KEYS}
    if isinstance(value, list):
        return [_canonicalize(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_canonicalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def script_splitting_hash(profile: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(profile).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _normalize_script_splitting_hash(value: Any) -> str:
    text = str(value or "")
    if text.startswith("sha256:"):
        return text
    if len(text) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in text):
        return f"sha256:{text.lower()}"
    return ""


def normalize_script_splitting_hash(value: Any) -> str:
    """Normalize stored script-splitting hashes to the canonical ``sha256:`` shape."""
    return _normalize_script_splitting_hash(value)


def default_template_id(content_mode: str | None, data_root: str | Path | None = None) -> str:
    del data_root
    mode = content_mode if content_mode in VALID_CONTENT_MODES else "narration"
    return DEFAULT_TEMPLATE_BY_MODE[mode]


def get_script_splitting_template(template_id: str, data_root: str | Path | None = None) -> dict[str, Any]:
    template = BUILTIN_TEMPLATES.get(template_id)
    if template is not None:
        return _ensure_generation_mode_fields(copy.deepcopy(template))
    for custom_template in _load_custom_templates(data_root):
        if custom_template.get("id") == template_id:
            return _ensure_generation_mode_fields(copy.deepcopy(custom_template))
    raise ValueError(f"未知拆分方案模板: {template_id}")


def list_script_splitting_templates(
    content_mode: str | None = None,
    *,
    data_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    templates = []
    builtin_order = {tpl_id: index for index, tpl_id in enumerate(BUILTIN_TEMPLATES.keys())}
    for template in [*BUILTIN_TEMPLATES.values(), *_load_custom_templates(data_root)]:
        if content_mode is not None and template.get("content_mode") != content_mode:
            continue
        item = _ensure_generation_mode_fields(copy.deepcopy(template))
        item["hash"] = script_splitting_hash(item)
        templates.append(item)
    return sorted(
        templates,
        key=lambda t: (
            t["content_mode"],
            t.get("source") != "builtin",
            builtin_order.get(t["id"], 9999),
            t["id"],
        ),
    )


def new_custom_script_splitting_template_id(base_template_id: str) -> str:
    base_slug = re.sub(r"[^a-z0-9_]+", "_", base_template_id.lower()).strip("_") or "template"
    return f"user_{base_slug}_{uuid4().hex[:8]}"


def build_custom_template_from_base(
    *,
    base_template_id: str,
    template_id: str | None = None,
    derived_from_template_id: str | None = None,
    creation_mode: str | None = None,
    name: str | None = None,
    description: str | None = None,
    recommended_generation_modes: list[str] | None = None,
    intent_brief: str | None = None,
    derivation_note: str | None = None,
    tone_preferences: list[str] | None = None,
    extra_split_rules: list[str] | None = None,
    extra_forbidden_patterns: list[str] | None = None,
    example_source: str | None = None,
    example_expected_output: str | None = None,
    source: str = "user_generated",
    data_root: str | Path | None = None,
) -> dict[str, Any]:
    base = get_script_splitting_template(base_template_id, data_root=data_root)
    root_base_template_id = (
        base_template_id
        if base.get("source") == "builtin"
        else str(base.get("base_template_id") or base_template_id)
    )
    now = _now_iso()
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("拆分方案标题不能为空")
    clean_description = str(description or "").strip()
    if not clean_description:
        raise ValueError("拆分方案描述不能为空")
    clean_extra_split_rules = _string_list(extra_split_rules or [])
    if not clean_extra_split_rules:
        raise ValueError("拆分规则不能为空")
    overlay = {
        "intent_brief": str(intent_brief or "").strip(),
        "derivation_note": str(derivation_note or "").strip(),
        "tone_preferences": _string_list(tone_preferences or []),
        "extra_split_rules": clean_extra_split_rules,
        "extra_forbidden_patterns": _string_list(extra_forbidden_patterns or []),
        "example_source": str(example_source or "").strip(),
        "example_expected_output": str(example_expected_output or "").strip(),
    }
    template = copy.deepcopy(base)
    template["id"] = template_id or new_custom_script_splitting_template_id(base_template_id)
    template["source"] = source if source in {"user_generated", "imported"} else "user_generated"
    template["base_template_id"] = root_base_template_id
    normalized_creation_mode = creation_mode if creation_mode in {"improve", "new_style"} else "improve"
    template["creation_mode"] = normalized_creation_mode
    if normalized_creation_mode == "new_style":
        template["derived_from_template_id"] = None
    else:
        template["derived_from_template_id"] = str(derived_from_template_id or base_template_id).strip() or base_template_id
    template["name"] = clean_name
    template["description"] = clean_description
    modes = (
        _normalize_generation_modes(recommended_generation_modes)
        if recommended_generation_modes is not None
        else _template_supported_generation_modes(base)
    )
    if not modes:
        modes = ["storyboard"]
    template["supported_generation_modes"] = modes
    template["recommended_generation_modes"] = modes
    template["default_generation_mode"] = _template_default_generation_mode(base, modes)
    template.pop("legacy_passthrough", None)
    template.pop("prompt_fragments", None)
    template["split_rules"] = list(base.get("split_rules") or []) + overlay["extra_split_rules"]
    template["forbidden_patterns"] = list(base.get("forbidden_patterns") or []) + overlay["extra_forbidden_patterns"]
    template["user_overlay"] = overlay
    template["version"] = 1
    template["created_at"] = now
    template["updated_at"] = now
    if overlay["example_source"] or overlay["example_expected_output"]:
        template["few_shot_examples"] = list(base.get("few_shot_examples") or []) + [
            {
                "source": overlay["example_source"],
                "good": overlay["example_expected_output"],
            }
        ]
    return template


def save_custom_script_splitting_template(
    template: dict[str, Any],
    *,
    data_root: str | Path | None = None,
) -> dict[str, Any]:
    validation = validate_script_splitting_template(template, autofix=True)
    if not validation["ok"]:
        raise ValueError(json.dumps(validation, ensure_ascii=False))
    profile = validation["profile"]
    if profile["id"] in BUILTIN_TEMPLATES:
        raise ValueError("不能覆盖内置拆分方案模板")
    now = _now_iso()
    with _custom_templates_lock:
        items = _load_custom_templates(data_root)
        profile_name = str(profile.get("name") or "").strip().casefold()
        if profile_name:
            for item in [*BUILTIN_TEMPLATES.values(), *items]:
                item_name = str(item.get("name") or "").strip().casefold()
                if item_name and item_name == profile_name and item.get("id") != profile["id"]:
                    raise ValueError("拆分方案标题已存在，请换一个标题")
        existing = next((item for item in items if item["id"] == profile["id"]), None)
        if existing and existing.get("created_at"):
            profile["created_at"] = existing["created_at"]
        else:
            profile.setdefault("created_at", now)
        profile["updated_at"] = now
        items = [item for item in items if item["id"] != profile["id"]]
        items.append(profile)
        _save_custom_templates(sorted(items, key=lambda t: (t["content_mode"], t["id"])), data_root)
    profile["hash"] = script_splitting_hash(profile)
    return profile


def upsert_custom_script_splitting_template(
    payload: dict[str, Any],
    *,
    data_root: str | Path | None = None,
    source: str = "user_generated",
) -> dict[str, Any]:
    if "locked_contract" in payload:
        template = copy.deepcopy(payload)
        if source == "imported":
            template["source"] = "imported"
    else:
        template = build_custom_template_from_base(
            base_template_id=str(payload.get("base_template_id") or ""),
            template_id=str(payload.get("id") or "").strip() or None,
            derived_from_template_id=payload.get("derived_from_template_id"),
            creation_mode=payload.get("creation_mode"),
            name=payload.get("name"),
            description=payload.get("description"),
            recommended_generation_modes=payload.get("supported_generation_modes") or payload.get("recommended_generation_modes"),
            intent_brief=payload.get("intent_brief"),
            derivation_note=payload.get("derivation_note"),
            tone_preferences=payload.get("tone_preferences"),
            extra_split_rules=payload.get("extra_split_rules"),
            extra_forbidden_patterns=payload.get("extra_forbidden_patterns"),
            example_source=payload.get("example_source"),
            example_expected_output=payload.get("example_expected_output"),
            source=source,
            data_root=data_root,
        )
    return save_custom_script_splitting_template(template, data_root=data_root)


def delete_custom_script_splitting_template(
    template_id: str,
    *,
    data_root: str | Path | None = None,
) -> bool:
    if template_id in BUILTIN_TEMPLATES:
        raise ValueError("内置拆分方案模板不能删除")
    with _custom_templates_lock:
        items = _load_custom_templates(data_root)
        next_items = [item for item in items if item["id"] != template_id]
        if len(next_items) == len(items):
            return False
        _save_custom_templates(next_items, data_root)
    return True


def export_script_splitting_template(
    template_id: str,
    *,
    data_root: str | Path | None = None,
) -> dict[str, Any]:
    template = get_script_splitting_template(template_id, data_root=data_root)
    template["hash"] = script_splitting_hash(template)
    return {
        "schema": "manju.script_splitting_template.v1",
        "template": template,
    }


def _provider_capability_hash_payload(caps: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(caps, dict) or not caps:
        return {}
    payload = {
        key: caps[key]
        for key in sorted(_PROVIDER_CAPABILITY_HASH_KEYS)
        if key in caps and caps[key] is not None
    }
    payload["provider_capability_profile"] = provider_capability_profile(caps)
    return _canonicalize(payload)


def provider_capability_hash(caps: dict[str, Any] | None) -> str:
    """Return a stable hash for the provider/model capability snapshot used by video versions."""
    payload = _provider_capability_hash_payload(caps)
    if not payload:
        return ""
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def provider_capability_profile(caps: dict[str, Any] | None) -> list[str]:
    """Map current backend capability payload to template-level capability names."""
    if not caps:
        return []
    raw = {str(c) for c in caps.get("capabilities") or []}
    mapped = set(raw)

    if caps.get("supported_durations") or raw.intersection({"text_to_video", "image_to_video"}):
        mapped.add("single_shot_video")
    if caps.get("supports_first_frame") or caps.get("supports_start_image"):
        mapped.add("first_frame")
    if caps.get("supports_last_frame") or caps.get("supports_end_image"):
        mapped.add("first_last_frame")
    if caps.get("supports_reference_images") or int(caps.get("max_reference_images") or 0) > 0:
        mapped.update({"reference_image", "reference_video", "subject_reference"})
    if caps.get("supports_reference_with_start_image"):
        mapped.add("element_reference")
    if caps.get("supports_generate_audio"):
        mapped.update({"native_audio", "dialogue_audio"})

    provider_id = str(caps.get("provider_id") or "")
    model = str(caps.get("model") or "").lower()
    endpoint_family = str(caps.get("endpoint_family") or "")
    if provider_id in {"ark", "vidu", "dashscope"} or endpoint_family in {"ark-seedance", "vidu-video"}:
        mapped.update({"camera_command", "multi_shot"})
    if "seedance" in model or "kling" in model or "wan" in model or "vidu" in model:
        mapped.update({"camera_command", "multi_shot"})
    return sorted(mapped)


def check_provider_compatibility(profile: dict[str, Any], caps: dict[str, Any] | None) -> dict[str, Any]:
    if not caps:
        return {
            "status": "unknown",
            "provider_id": None,
            "model": None,
            "capabilities": [],
            "missing_required": list(profile.get("required_capabilities") or []),
            "missing_preferred": list(profile.get("preferred_capabilities") or []),
            "warnings": ["当前未解析视频模型能力，稍后在生成前重新校验。"],
        }

    available = set(provider_capability_profile(caps))
    required = set(profile.get("required_capabilities") or [])
    preferred = set(profile.get("preferred_capabilities") or [])
    missing_required = sorted(required - available)
    missing_preferred = sorted(preferred - available)
    status = "block" if missing_required else ("warn" if missing_preferred else "ok")
    warnings = []
    if missing_required:
        warnings.append("当前视频模型缺少模板必需能力，建议切换 provider 或更换兼容拆分方案。")
    if missing_preferred:
        warnings.append("当前视频模型缺少部分推荐能力，可继续但连续性或镜头控制会降低。")
    return {
        "status": status,
        "provider_id": caps.get("provider_id"),
        "model": caps.get("model"),
        "capabilities": sorted(available),
        "missing_required": missing_required,
        "missing_preferred": missing_preferred,
        "warnings": warnings,
    }


def _generation_mode_compatibility(profile: dict[str, Any], generation_mode: str | None) -> dict[str, Any]:
    supported = _template_supported_generation_modes(profile)
    mode = generation_mode if generation_mode in VALID_GENERATION_MODES else "storyboard"
    if mode in supported:
        return {"status": "ok", "generation_mode": mode, "warnings": []}
    return {
        "status": "block",
        "generation_mode": mode,
        "warnings": [f"拆分方案支持的生成方式为 {supported or '未声明'}，当前项目为 {mode}。"],
    }


def resolve_script_splitting_profile(
    content_mode: str | None,
    generation_mode: str | None,
    template_id: str | None = None,
    *,
    provider_capabilities: dict[str, Any] | None = None,
    data_root: str | Path | None = None,
) -> dict[str, Any]:
    mode = content_mode if content_mode in VALID_CONTENT_MODES else "narration"
    gen_mode = generation_mode if generation_mode in VALID_GENERATION_MODES else "storyboard"
    chosen_id = template_id or default_template_id(mode, data_root=data_root)
    profile = get_script_splitting_template(chosen_id, data_root=data_root)
    if profile.get("content_mode") != mode:
        raise ValueError(f"拆分方案 {chosen_id} 属于 {profile.get('content_mode')}，不能用于 {mode} 项目")

    profile = _ensure_generation_mode_fields(profile)
    profile["hash"] = script_splitting_hash(profile)
    generation_mode_compatibility = _generation_mode_compatibility(profile, gen_mode)
    if generation_mode_compatibility.get("status") == "block":
        supported = ", ".join(_template_supported_generation_modes(profile))
        raise ValueError(f"拆分方案 {chosen_id} 不支持生成方式 {gen_mode}，支持范围：{supported}")
    profile["generation_mode_compatibility"] = generation_mode_compatibility
    profile["provider_compatibility"] = check_provider_compatibility(profile, provider_capabilities)
    return profile


def snapshot_from_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "template_id": profile["id"],
        "resolved_profile_hash": profile["hash"],
        "resolved_profile": copy.deepcopy(profile),
        "provider_compatibility": copy.deepcopy(profile.get("provider_compatibility")),
    }


def _copy_snapshot_runtime_state(source: Any, target: dict[str, Any]) -> None:
    if not isinstance(source, dict):
        return
    for key in _SNAPSHOT_RUNTIME_KEYS:
        value = source.get(key)
        if isinstance(value, dict):
            target[key] = copy.deepcopy(value)


def _is_stale_legacy_narration_profile(profile: dict[str, Any]) -> bool:
    if profile.get("id") != "narration_legacy_reading_default":
        return False
    if str(profile.get("source") or "builtin") != "builtin":
        return False
    locked_contract = profile.get("locked_contract") if isinstance(profile.get("locked_contract"), dict) else {}
    required_fields = locked_contract.get("required_fields") if isinstance(locked_contract, dict) else []
    output_fields = profile.get("output_fields") if isinstance(profile.get("output_fields"), list) else []
    prompt_fragments = profile.get("prompt_fragments") if isinstance(profile.get("prompt_fragments"), dict) else {}
    agent_output_table = str(prompt_fragments.get("agent_output_table") or "")
    split_rules = "\n".join(str(rule) for rule in profile.get("split_rules") or [])
    return (
        locked_contract.get("id_format") == "G{two_digit_index}"
        or "segment_label" in required_fields
        or "segment_label" in output_fields
        or "片段编号从 G01" in split_rules
        or "| G01 |" in agent_output_table
    )


def _normalize_cached_builtin_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if not _is_stale_legacy_narration_profile(profile):
        return profile
    normalized = copy.deepcopy(BUILTIN_TEMPLATES["narration_legacy_reading_default"])
    user_overlay = profile.get("user_overlay")
    if isinstance(user_overlay, dict):
        normalized["user_overlay"] = copy.deepcopy(user_overlay)
    return normalized


def script_splitting_asset_metadata(project: dict[str, Any] | None) -> dict[str, Any]:
    """Return stable script-splitting metadata for downstream generated assets."""
    if not isinstance(project, dict):
        return {}
    ensure_project_script_splitting_snapshot(project)
    snapshot = project.get("script_splitting")
    if not isinstance(snapshot, dict):
        return {}
    profile = snapshot.get("resolved_profile")
    if not isinstance(profile, dict):
        return {}
    template_id = str(profile.get("id") or snapshot.get("template_id") or "")
    script_hash = _normalize_script_splitting_hash(snapshot.get("resolved_profile_hash") or profile.get("hash"))
    if not template_id or not script_hash:
        return {}
    return {
        "script_splitting_hash": script_hash,
        "script_splitting_template_id": template_id,
        "script_splitting_template_version": profile.get("version"),
    }


def ensure_project_script_splitting_snapshot(
    project: dict[str, Any],
    *,
    provider_capabilities: dict[str, Any] | None = None,
    data_root: str | Path | None = None,
    mark_migrated_from_missing: bool = False,
) -> bool:
    """Ensure project has a resolved script_splitting snapshot. Mutates project in-place."""
    existing = project.get("script_splitting")
    existing_profile = existing.get("resolved_profile") if isinstance(existing, dict) else None
    if isinstance(existing_profile, dict) and existing_profile.get("id"):
        profile = copy.deepcopy(existing_profile)
        profile = _normalize_cached_builtin_profile(profile)
        profile = _ensure_generation_mode_fields(profile)
        profile["hash"] = _normalize_script_splitting_hash(profile.get("hash")) or script_splitting_hash(profile)
        profile["generation_mode_compatibility"] = _generation_mode_compatibility(
            profile, project.get("generation_mode")
        )
        profile["provider_compatibility"] = check_provider_compatibility(profile, provider_capabilities)
        script_splitting = snapshot_from_profile(profile)
        _copy_snapshot_runtime_state(existing, script_splitting)
        changed = script_splitting != existing or project.get("script_splitting_template_id") != profile["id"]
        project["script_splitting_template_id"] = profile["id"]
        project["script_splitting"] = script_splitting
        return changed

    profile = resolve_script_splitting_profile(
        project.get("content_mode"),
        project.get("generation_mode"),
        project.get("script_splitting_template_id"),
        provider_capabilities=provider_capabilities,
        data_root=data_root,
    )
    project["script_splitting_template_id"] = profile["id"]
    project["script_splitting"] = snapshot_from_profile(profile)
    if mark_migrated_from_missing:
        project["migrated_from_missing_script_splitting"] = True
    return True


def current_profile(project: dict[str, Any]) -> dict[str, Any]:
    ensure_project_script_splitting_snapshot(project)
    return copy.deepcopy(project["script_splitting"]["resolved_profile"])


def current_hash(project: dict[str, Any]) -> str:
    ensure_project_script_splitting_snapshot(project)
    return str(project["script_splitting"]["resolved_profile_hash"])


def script_splitting_hash_from_script(script: dict[str, Any] | None) -> str:
    """Read the template hash carried by a generated episode/reference script."""
    if not isinstance(script, dict):
        return ""
    metadata = script.get("metadata")
    metadata_hash = metadata.get("script_splitting_hash") if isinstance(metadata, dict) else None
    return _normalize_script_splitting_hash(script.get("script_splitting_hash") or metadata_hash)


def script_splitting_staleness_for_script(
    project: dict[str, Any],
    script: dict[str, Any] | None,
    *,
    script_file: str | None = None,
    asset_kind: str | None = None,
) -> dict[str, Any]:
    """Return advisory split-template state for an existing script.

    Template switches are future-only: generated scripts/assets remain valid even
    when their stored hash differs from the project's current template hash.
    """
    expected_hash = current_hash(project)
    actual_hash = script_splitting_hash_from_script(script)
    snapshot = project.get("script_splitting") if isinstance(project.get("script_splitting"), dict) else {}
    marker = snapshot.get("asset_staleness") if isinstance(snapshot, dict) else None
    marker = marker if isinstance(marker, dict) else {}
    previous_hash = _normalize_script_splitting_hash(marker.get("previous_hash"))

    hash_differs = bool(actual_hash and expected_hash and actual_hash != expected_hash)
    reason = ""
    if hash_differs:
        reason = "template_changed_future_only"
    elif marker.get("reason") in {
        "template_changed_future_only",
        "generation_mode_changed_future_only",
        "template_and_generation_mode_changed_future_only",
    }:
        reason = str(marker.get("reason"))
    elif marker.get("status") == "stale":
        reason = "legacy_stale_marker_ignored"
    elif not actual_hash:
        reason = "script_hash_missing"

    return {
        "status": "current",
        "reason": reason,
        "script_file": script_file,
        "asset_kind": asset_kind,
        "current_template_id": project.get("script_splitting_template_id"),
        "current_hash": expected_hash,
        "script_hash": actual_hash or None,
        "previous_template_id": marker.get("previous_template_id"),
        "previous_hash": previous_hash or None,
        "template_hash_differs": hash_differs,
        "existing_assets_policy": marker.get("existing_assets_policy") or "preserve_existing",
        "suggested_action": "continue",
    }


def assert_script_splitting_assets_current(
    project: dict[str, Any],
    script: dict[str, Any] | None,
    *,
    script_file: str | None = None,
    asset_kind: str | None = None,
) -> dict[str, Any]:
    """Return advisory state for existing scripts without blocking generation."""
    return script_splitting_staleness_for_script(
        project,
        script,
        script_file=script_file,
        asset_kind=asset_kind,
    )


def render_profile_prompt_section(profile: dict[str, Any] | None) -> str:
    if not profile:
        return ""
    if profile.get("legacy_passthrough"):
        return ""
    rules = "\n".join(f"- {rule}" for rule in profile.get("split_rules") or [])
    forbidden = "\n".join(f"- {item}" for item in profile.get("forbidden_patterns") or [])
    fields = ", ".join(profile.get("output_fields") or [])
    gates = "\n".join(
        f"- {gate.get('id')}: {gate.get('description')}（{gate.get('severity')}）"
        for gate in profile.get("quality_gates") or []
        if isinstance(gate, dict)
    )
    examples = []
    for ex in profile.get("few_shot_examples") or []:
        if not isinstance(ex, dict):
            continue
        source = ex.get("source")
        good = ex.get("good") or ex.get("fixed")
        bad = ex.get("bad")
        if source and good:
            block = f"输入：{source}\n合格：{good}"
            if bad:
                block += f"\n不合格：{bad}"
            examples.append(block)
    examples_text = "\n\n".join(examples)
    return f"""# 拆分方案 Profile

当前拆分方案：{profile.get("id")} / {profile.get("name")}
模板 hash：{profile.get("hash")}
定位：{profile.get("description")}
支持生成方式：{", ".join(profile.get("supported_generation_modes") or profile.get("recommended_generation_modes") or [])}
输出字段：{fields}

## 模板拆分规则
{rules or "（无）"}

## 禁止写法
{forbidden or "（无）"}

## 模板质检
{gates or "（无）"}

## Few-shot 参考
{examples_text or "（无）"}
"""


def _relative_project_path(project_path: Path | None, path: Path) -> str:
    if project_path is None:
        return path.as_posix()
    try:
        return path.resolve().relative_to(project_path.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _safe_project_file(project_path: Path, rel_path: Any) -> Path | None:
    if not isinstance(rel_path, str) or not rel_path.strip():
        return None
    candidate = (project_path / rel_path).resolve()
    try:
        candidate.relative_to(project_path.resolve())
    except (OSError, ValueError):
        return None
    return candidate


def _add_existing_path(paths: set[str], project_path: Path | None, candidate: Path | None) -> None:
    if candidate is None or not candidate.is_file():
        return
    paths.add(_relative_project_path(project_path, candidate))


def _episode_numbers(project: dict[str, Any]) -> list[int]:
    numbers: list[int] = []
    for idx, episode in enumerate(project.get("episodes") or [], start=1):
        raw = episode.get("episode") if isinstance(episode, dict) else None
        try:
            number = int(raw)
        except (TypeError, ValueError):
            number = idx
        if number > 0:
            numbers.append(number)
    return numbers


def _script_paths(project: dict[str, Any], project_path: Path | None) -> list[Path]:
    if project_path is None:
        return []
    paths: list[Path] = []
    seen: set[Path] = set()
    for episode in project.get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        candidate = _safe_project_file(project_path, episode.get("script_file"))
        if candidate and candidate.suffix.lower() == ".json" and candidate not in seen:
            seen.add(candidate)
            paths.append(candidate)
    scripts_dir = project_path / "scripts"
    if scripts_dir.is_dir():
        for candidate in sorted(scripts_dir.glob("*.json")):
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                paths.append(candidate)
    return paths


def _load_json_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _iter_script_items(script: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in _SCRIPT_ITEM_LIST_KEYS:
        value = script.get(key)
        if isinstance(value, list):
            items.extend(item for item in value if isinstance(item, dict))
    return items


def _generated_asset_path(project_path: Path, rel_path: Any) -> Path | None:
    candidate = _safe_project_file(project_path, rel_path)
    return candidate if candidate and candidate.is_file() else None


def _output_state(
    *,
    count: int | None,
    paths: set[str] | list[str] | None = None,
    exists: bool | None = None,
    tracked: bool = True,
    reason: str | None = None,
) -> dict[str, Any]:
    resolved_paths = sorted(paths or [])
    if exists is not None:
        resolved_exists = exists
    elif count is None:
        resolved_exists = None
    else:
        resolved_exists = bool(count)
    return {
        "exists": resolved_exists,
        "count": count,
        "paths": resolved_paths,
        "tracked": tracked,
        "reason": reason,
    }


def _collect_template_change_outputs(
    project: dict[str, Any],
    project_path: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    path = Path(project_path) if project_path is not None else None
    episode_count = len(project.get("episodes") or [])
    step1_paths: set[str] = set()
    script_file_paths: set[str] = set()
    storyboard_paths: set[str] = set()
    video_paths: set[str] = set()
    reference_video_paths: set[str] = set()
    grid_paths: set[str] = set()

    if path is not None:
        for episode in _episode_numbers(project):
            draft_dir = path / "drafts" / f"episode_{episode}"
            for filename in _STEP1_DRAFT_FILES:
                _add_existing_path(step1_paths, path, draft_dir / filename)

        scripts = _script_paths(project, path)
        for script_path in scripts:
            _add_existing_path(script_file_paths, path, script_path)
            script = _load_json_file(script_path)
            if not script:
                continue
            for item in _iter_script_items(script):
                assets = item.get("generated_assets")
                if not isinstance(assets, dict):
                    continue
                _add_existing_path(
                    storyboard_paths,
                    path,
                    _generated_asset_path(path, assets.get("storyboard_image")),
                )
                rel_video = assets.get("video_clip")
                video_path = _generated_asset_path(path, rel_video)
                if video_path is not None:
                    rel_text = _relative_project_path(path, video_path)
                    if rel_text.startswith("reference_videos/"):
                        reference_video_paths.add(rel_text)
                    else:
                        video_paths.add(rel_text)

        for candidate in (
            sorted((path / "storyboards").glob("*.png")) if (path / "storyboards").is_dir() else []
        ):
            _add_existing_path(storyboard_paths, path, candidate)
        for candidate in (
            sorted((path / "videos").glob("*.mp4")) if (path / "videos").is_dir() else []
        ):
            _add_existing_path(video_paths, path, candidate)
        if (path / "reference_videos").is_dir():
            for candidate in sorted((path / "reference_videos").glob("*.mp4")):
                _add_existing_path(reference_video_paths, path, candidate)
        if (path / "grids").is_dir():
            for candidate in sorted((path / "grids").glob("*.png")):
                _add_existing_path(grid_paths, path, candidate)

    asset_binding_count = sum(
        len(project.get(key) or {})
        for key in ("characters", "scenes", "props")
        if isinstance(project.get(key), dict)
    )
    has_video_outputs = bool(video_paths or reference_video_paths)
    return {
        "step1": _output_state(count=len(step1_paths) or (episode_count if path is None else 0), paths=step1_paths),
        "scripts": _output_state(count=len(script_file_paths) or (episode_count if path is None else 0), paths=script_file_paths),
        "asset_bindings": _output_state(count=asset_binding_count, paths=[]),
        "storyboards": _output_state(count=len(storyboard_paths), paths=storyboard_paths),
        "grids": _output_state(count=len(grid_paths), paths=grid_paths),
        "videos": _output_state(count=len(video_paths), paths=video_paths),
        "reference_videos": _output_state(count=len(reference_video_paths), paths=reference_video_paths),
        "jianying_draft": _output_state(
            count=None,
            paths=[],
            exists=None if has_video_outputs else False,
            tracked=False,
            reason="external_path_required" if has_video_outputs else "no_generated_videos",
        ),
    }


def _affected_assets_from_outputs(
    outputs: dict[str, dict[str, Any]],
    *,
    include_jianying: bool,
) -> list[str]:
    affected: list[str] = []
    for key in _REGENERATION_ORDER:
        state = outputs.get(key) or {}
        count = state.get("count")
        exists = state.get("exists")
        if key == "jianying_draft":
            if include_jianying:
                affected.append(key)
            continue
        if exists or (isinstance(count, int) and count > 0):
            affected.append(key)
    return affected


def _rebuild_chain(
    affected_assets: list[str],
    outputs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    for key in _REGENERATION_ORDER:
        if key not in affected_assets:
            continue
        state = outputs.get(key) or {}
        chain.append(
            {
                "asset": key,
                "exists": state.get("exists"),
                "count": state.get("count"),
                "tracked": state.get("tracked", True),
                "reason": state.get("reason"),
            }
        )
    return chain


def preview_template_change(
    project: dict[str, Any],
    template_id: str,
    *,
    generation_mode: str | None = None,
    provider_capabilities: dict[str, Any] | None = None,
    data_root: str | Path | None = None,
    project_path: str | Path | None = None,
) -> dict[str, Any]:
    ensure_project_script_splitting_snapshot(project, data_root=data_root)
    current_template_id = project.get("script_splitting_template_id")
    current_template_hash = current_hash(project)
    current_generation_mode = (
        project.get("generation_mode") if project.get("generation_mode") in VALID_GENERATION_MODES else "storyboard"
    )
    next_generation_mode = generation_mode if generation_mode in VALID_GENERATION_MODES else current_generation_mode
    profile = resolve_script_splitting_profile(
        project.get("content_mode"),
        next_generation_mode,
        template_id,
        provider_capabilities=provider_capabilities,
        data_root=data_root,
    )
    outputs = _collect_template_change_outputs(project, project_path)
    has_generated_videos = bool(outputs["videos"]["count"] or outputs["reference_videos"]["count"])
    preserved_existing_assets = []
    template_changed = profile["hash"] != current_template_hash
    generation_mode_changed = next_generation_mode != current_generation_mode
    if template_changed or generation_mode_changed:
        preserved_existing_assets = _affected_assets_from_outputs(outputs, include_jianying=has_generated_videos)
    preserved_chain = _rebuild_chain(preserved_existing_assets, outputs)
    preserved_existing_asset_count = sum(
        int(item["count"])
        for item in preserved_chain
        if isinstance(item.get("count"), int) and item["count"] > 0
    )
    return {
        "preview": True,
        "current_template_id": current_template_id,
        "current_hash": current_template_hash,
        "next_template_id": profile["id"],
        "next_hash": profile["hash"],
        "current_generation_mode": current_generation_mode,
        "next_generation_mode": next_generation_mode,
        "generation_mode_changed": generation_mode_changed,
        "generation_mode_compatibility": profile.get("generation_mode_compatibility"),
        "provider_compatibility": profile.get("provider_compatibility"),
        "affected_assets": [],
        "affected_asset_count": 0,
        "affected_asset_type_count": 0,
        "existing_outputs": outputs,
        "rebuild_chain": [],
        "regeneration_chain": [],
        "preserved_existing_assets": preserved_existing_assets,
        "preserved_existing_asset_count": preserved_existing_asset_count,
        "preserved_existing_asset_type_count": len(preserved_existing_assets),
        "preserved_existing_chain": preserved_chain,
        "existing_assets_policy": "preserve_existing",
        "future_generation_policy": "use_next_template_for_ungenerated_episodes",
        "has_generated_videos": has_generated_videos,
        "has_jianying_draft": outputs["jianying_draft"]["exists"],
        "jianying_draft_tracking": outputs["jianying_draft"]["reason"],
        "requires_confirmation": False,
        "available_modes": ["preview", "apply_keep_drafts"],
        "suggested_action": "future_episodes_only" if template_changed or generation_mode_changed else "no_change",
    }


def mark_template_change_stale_assets(
    project: dict[str, Any],
    *,
    preview: dict[str, Any],
    mode: str,
    data_root: str | Path | None = None,
) -> None:
    """Record a future-only template switch on the project snapshot."""
    ensure_project_script_splitting_snapshot(project, data_root=data_root)
    project_hash = current_hash(project)
    snapshot = project.get("script_splitting")
    if not isinstance(snapshot, dict):
        return
    preserved_assets = sorted({str(item) for item in preview.get("preserved_existing_assets") or []})
    now = datetime.now(UTC).isoformat()
    template_changed = preview.get("current_hash") != preview.get("next_hash")
    generation_mode_changed = bool(preview.get("generation_mode_changed"))
    if template_changed and generation_mode_changed:
        reason = "template_and_generation_mode_changed_future_only"
    elif generation_mode_changed:
        reason = "generation_mode_changed_future_only"
    elif template_changed:
        reason = "template_changed_future_only"
    else:
        reason = "template_unchanged"
    marker = {
        "status": "current",
        "reason": reason,
        "mode": mode,
        "previous_template_id": preview.get("current_template_id"),
        "previous_hash": _normalize_script_splitting_hash(preview.get("current_hash")),
        "previous_generation_mode": preview.get("current_generation_mode"),
        "current_template_id": project.get("script_splitting_template_id"),
        "current_hash": project_hash,
        "current_generation_mode": project.get("generation_mode"),
        "generation_mode_changed": generation_mode_changed,
        "affected_assets": [],
        "preserved_existing_assets": preserved_assets,
        "rebuild_required_assets": [],
        "existing_assets_policy": "preserve_existing",
        "future_generation_policy": "use_current_template_for_ungenerated_episodes",
        "suggested_action": "continue",
        "created_at": now,
    }
    snapshot["asset_staleness"] = marker
    snapshot["last_template_change"] = marker

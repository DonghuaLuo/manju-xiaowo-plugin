"""
Prompt 工具函数

提供结构化 Prompt 到 YAML 格式的转换功能。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import yaml

_STYLE_PREFIX_RE = re.compile(r"^画风[：:]\s*")

# 预设选项定义
SHOT_TYPES = [
    "Extreme Close-up",
    "Close-up",
    "Medium Close-up",
    "Medium Shot",
    "Medium Long Shot",
    "Long Shot",
    "Extreme Long Shot",
    "Over-the-shoulder",
    "Point-of-view",
]

CAMERA_MOTIONS = [
    "Static",
    "Pan Left",
    "Pan Right",
    "Tilt Up",
    "Tilt Down",
    "Zoom In",
    "Zoom Out",
    "Tracking Shot",
]


def normalize_style(style: str | None) -> str:
    """Strip duplicated UI label prefixes from stored style prompts."""
    return _STYLE_PREFIX_RE.sub("", (style or "").strip())


def image_prompt_to_yaml(image_prompt: dict, project_style: str) -> str:
    """
    将 imagePrompt 结构转换为 YAML 格式字符串

    Args:
        image_prompt: segment 中的 image_prompt 对象，结构为：
            {
                "scene": "场景描述",
                "composition": {
                    "shot_type": "镜头类型",
                    "lighting": "光线描述",
                    "ambiance": "氛围描述"
                }
            }
        project_style: 项目级风格设置（从 project.json 读取）

    Returns:
        YAML 格式字符串，用于 Gemini API 调用
    """
    ordered = {
        "Style": normalize_style(project_style),
        "Scene": image_prompt["scene"],
        "Composition": {
            "shot_type": image_prompt["composition"]["shot_type"],
            "lighting": image_prompt["composition"]["lighting"],
            "ambiance": image_prompt["composition"]["ambiance"],
        },
    }
    return yaml.dump(ordered, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _clean_text(value: object) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class VideoPromptPolicy:
    """Controls provider/model-specific prompt enrichment."""

    supports_generated_audio: bool = True
    compact: bool = False
    max_visible_characters: int | None = None
    voice_style_max_chars: int | None = None
    mouth_cue_silent_name_limit: int = 3

    @property
    def effective_max_visible_characters(self) -> int:
        if self.max_visible_characters is not None:
            return self.max_visible_characters
        return 6 if self.compact else 10

    @property
    def effective_voice_style_max_chars(self) -> int:
        if self.voice_style_max_chars is not None:
            return self.voice_style_max_chars
        return 80 if self.compact else 140


def _truncate_text(value: str, max_chars: int) -> str:
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip(" ,，;；.。") + "..."


def _normalize_screen_position(value: object) -> str:
    raw = _clean_text(value).lower()
    if raw in {"left", "左", "左侧"}:
        return "left"
    if raw in {"center", "centre", "middle", "中", "中间", "中央"}:
        return "center"
    if raw in {"right", "右", "右侧"}:
        return "right"
    if raw in {"offscreen", "off-screen", "画外", "画面外"}:
        return "offscreen"
    return _clean_text(value)


def build_speaker_profiles(
    project: dict | None,
    item: dict | None,
    *,
    char_field: str | None = None,
    dialogue: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """Build per-character voice hints for the video prompt.

    The result is provider-agnostic prompt context, not a hard voice binding.
    """
    if not isinstance(project, dict) or not isinstance(item, dict):
        return []

    characters = project.get("characters", {})
    if not isinstance(characters, dict):
        characters = {}

    visible_names: list[str] = []
    speaker_names: list[str] = []

    def add_unique(target: list[str], value: object) -> None:
        name = _clean_text(value)
        if name and name not in target:
            target.append(name)

    fields = [char_field] if char_field else ["characters_in_segment", "characters_in_scene"]
    for field in fields:
        if not field:
            continue
        raw_names = item.get(field, [])
        if isinstance(raw_names, list):
            for name in raw_names:
                add_unique(visible_names, name)

    screen_by_speaker: dict[str, str] = {}
    for line in dialogue or []:
        if not isinstance(line, dict):
            continue
        speaker = _clean_text(line.get("speaker"))
        if not speaker:
            continue
        add_unique(speaker_names, speaker)
        screen_position = _normalize_screen_position(line.get("screen_position"))
        if screen_position and speaker not in screen_by_speaker:
            screen_by_speaker[speaker] = screen_position

    ordered_names = [*speaker_names, *(name for name in visible_names if name not in speaker_names)]
    profiles: list[dict[str, Any]] = []
    for name in ordered_names:
        data = characters.get(name, {})
        if not isinstance(data, dict):
            data = {}
        profile: dict[str, Any] = {"name": name, "is_speaker": name in speaker_names}
        voice_style = _clean_text(data.get("voice_style"))
        if voice_style:
            profile["voice_style"] = voice_style
        screen_position = screen_by_speaker.get(name, "")
        if screen_position:
            profile["screen_position"] = screen_position
        profiles.append(profile)
    return profiles


def _select_speaker_profiles(
    profiles: list[dict[str, Any]],
    dialogue_speakers: list[str],
    policy: VideoPromptPolicy,
) -> list[dict[str, Any]]:
    speaker_set = set(dialogue_speakers)
    speaker_profiles = [p for p in profiles if _clean_text(p.get("name")) in speaker_set]
    other_profiles = [p for p in profiles if _clean_text(p.get("name")) not in speaker_set]
    limit = policy.effective_max_visible_characters
    if limit <= 0:
        return speaker_profiles
    remaining = max(0, limit - len(speaker_profiles))
    return [*speaker_profiles, *other_profiles[:remaining]]


def _speaker_profile_to_yaml(profile: dict[str, Any], policy: VideoPromptPolicy) -> dict[str, str]:
    result = {"Name": _clean_text(profile.get("name"))}
    voice_style = _clean_text(profile.get("voice_style"))
    if policy.supports_generated_audio and profile.get("is_speaker") and voice_style:
        result["Voice_Style"] = _truncate_text(voice_style, policy.effective_voice_style_max_chars)
    screen_position = _clean_text(profile.get("screen_position"))
    if screen_position:
        result["Screen_Position"] = screen_position
    return result


def _format_mouth_cue(speaker: str, silent: list[str], policy: VideoPromptPolicy) -> str:
    if not silent:
        return f"{speaker}开口说这句台词。"
    if len(silent) <= policy.mouth_cue_silent_name_limit:
        return f"{speaker}开口说这句台词；{'、'.join(silent)}保持闭嘴不说话。"
    return f"{speaker}开口说这句台词；其他可见角色保持闭嘴不说话。"


def _dialogue_line_to_yaml(line: dict, speakers: list[str], policy: VideoPromptPolicy) -> dict[str, str]:
    speaker = _clean_text(line.get("speaker"))
    result = {
        "Speaker": speaker,
        "Line": _clean_text(line.get("line")),
    }
    emotion = _clean_text(line.get("emotion"))
    if emotion:
        result["Emotion"] = emotion
    screen_position = _normalize_screen_position(line.get("screen_position"))
    if screen_position:
        result["Screen_Position"] = screen_position
    if policy.supports_generated_audio and speaker:
        silent = [name for name in speakers if name and name != speaker]
        result["Mouth_Cue"] = _format_mouth_cue(speaker, silent, policy)
    return result


def _speaking_rules(policy: VideoPromptPolicy, has_voice_style: bool) -> list[str]:
    if not policy.supports_generated_audio:
        return []
    rules = [
        "每句台词只对应 Speaker 字段指定角色。",
        "当前台词只由 Speaker 指定角色开口发声，其他可见角色保持闭嘴不说话。",
    ]
    if has_voice_style:
        rules.append("如提供 Voice_Style，生成音频时尽量保持对应角色音色一致。")
    return rules


def video_prompt_to_yaml(
    video_prompt: dict,
    *,
    speaker_profiles: list[dict[str, Any]] | None = None,
    policy: VideoPromptPolicy | None = None,
) -> str:
    """
    将 videoPrompt 结构转换为 YAML 格式字符串

    Args:
        video_prompt: segment 中的 video_prompt 对象，结构为：
            {
                "action": "动作描述",
                "camera_motion": "摄像机运动",
                "ambiance_audio": "环境音效描述",
                "dialogue": [
                    {"speaker": "角色名", "line": "台词", "emotion": "语气", "screen_position": "left"}
                ]
            }

    Returns:
        YAML 格式字符串，用于 Veo API 调用
    """
    prompt_policy = policy or VideoPromptPolicy()
    dialogue_items = [d for d in video_prompt.get("dialogue", []) if isinstance(d, dict)]
    dialogue_speakers = [_clean_text(d.get("speaker")) for d in dialogue_items]
    profiles = _select_speaker_profiles(speaker_profiles or [], dialogue_speakers, prompt_policy)
    profile_names = [_clean_text(p.get("name")) for p in profiles if p.get("name")]
    speakers = []
    for name in [*profile_names, *dialogue_speakers]:
        if name and name not in speakers:
            speakers.append(name)
    dialogue = [_dialogue_line_to_yaml(d, speakers, prompt_policy) for d in dialogue_items]

    ordered = {
        "Action": video_prompt["action"],
        "Camera_Motion": video_prompt["camera_motion"],
    }
    optional_motion_fields = (
        ("subject_motion", "Subject_Motion"),
        ("emotion", "Emotion"),
        ("environment_motion", "Environment_Motion"),
        ("ambiance_audio", "Ambiance_Audio"),
        ("avoid", "Avoid"),
    )
    for source_key, yaml_key in optional_motion_fields:
        value = _clean_text(video_prompt.get(source_key))
        if value:
            ordered[yaml_key] = value

    if profiles and dialogue:
        ordered["Visible_Characters"] = [_speaker_profile_to_yaml(p, prompt_policy) for p in profiles if p.get("name")]

    # 仅在有对话时添加 Dialogue 字段
    if dialogue:
        ordered["Dialogue"] = dialogue
        rules = _speaking_rules(
            prompt_policy,
            has_voice_style=any("Voice_Style" in profile for profile in ordered.get("Visible_Characters", [])),
        )
        if rules:
            ordered["Speaking_Rules"] = rules

    return yaml.dump(ordered, allow_unicode=True, default_flow_style=False, sort_keys=False)


def is_structured_image_prompt(image_prompt) -> bool:
    """
    检查 image_prompt 是否为结构化格式

    Args:
        image_prompt: image_prompt 字段值

    Returns:
        True 如果是结构化格式（dict），False 如果是旧的字符串格式
    """
    return isinstance(image_prompt, dict) and "scene" in image_prompt


def is_structured_video_prompt(video_prompt) -> bool:
    """
    检查 video_prompt 是否为结构化格式

    Args:
        video_prompt: video_prompt 字段值

    Returns:
        True 如果是结构化格式（dict），False 如果是旧的字符串格式
    """
    return isinstance(video_prompt, dict) and "action" in video_prompt


def validate_shot_type(shot_type: str) -> bool:
    """验证镜头类型是否为预设选项"""
    return shot_type in SHOT_TYPES


def validate_camera_motion(camera_motion: str) -> bool:
    """验证摄像机运动是否为预设选项"""
    return camera_motion in CAMERA_MOTIONS

"""图像 / 视频 / 资产 prompt 的统一真相源。

WebUI（server/services/generation_tasks.py）和 Skill（agent_runtime_profile/.claude/skills/generate-assets）
都从这里取最终 prompt 文本，确保入口一致、不漂移。

设计要点：
- 无 backend 锁定：纯文本拼接，由调用方决定走哪个 image/video provider。
- 反向提示词统一以「画面避免：xxx」追加到 prompt 末尾，不再使用各 backend 的 negative_prompt 参数通道
  （image backends 大多 silent 丢弃，参数化反而增加分叉）。
- 防崩短语精简：扁平 4 项内核，避免 CFG 权重稀释。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 内部常量：防崩 / 反向 / 布局 / 风格前缀
# ---------------------------------------------------------------------------

# 角色图采用 issue #353 的四视图 16:9 角色设定集布局。
_CHARACTER_LAYOUT = (
    "横版 16:9 构图，纯白 (#FFFFFF) 背景，干净高级的角色设定集版式。\n\n"
    "版式要求：左侧约 40% 宽为大幅胸像特写，清晰展示角色面部、发型、眼神、气质、配饰与上装细节；"
    "左上角设置简洁角色信息区，可包含角色名、身份、年龄、身高、气质关键词等短标签，作为设定集排版元素；"
    "右侧约 60% 宽分为三个等宽全身视图面板，依次展示正面 / 四分之三侧面 / 背面的 A-Pose 全身视图。"
)
_CHARACTER_PROP_RULE = (
    "道具规则：如果角色描述中提到明确的关键道具、武器、容器、饰品、法器、标志性物件，"
    "则在左下角增加一个独立道具特写框，展示该道具的细节、材质、纹路、磨损或发光效果，并配少量设定说明；"
    "如果角色描述中没有明确关键道具，则不要添加道具特写框，左下角保持简洁留白或作为轻量说明区。"
)
_SCENE_LAYOUT = "主画面占四分之三区域展示环境整体外观与氛围，右下角嵌入关键细节小图。"
_PROP_LAYOUT = "三视图水平排列于纯净浅灰背景：左侧正面全视图、中间 45° 侧视图体现立体感、右侧关键细节特写。"

# 正向防崩（按资产类型差异化）。
_CHARACTER_GUARD = (
    "一致性要求：四个角色视图必须是同一人物，同一张脸，同一发型，同一五官，同一身材比例、"
    "同一服装设计、同一配饰设定；正面、侧面、背面服装结构要能互相对应，"
    "不能出现不同衣服、不同发型、不同脸型；五官对称，手指完整为五指，肢体比例协调，站姿自然。"
)
_CHARACTER_PRESENTATION_GUIDE = "展示要求：突出角色设定图质感，白底，无复杂背景，无场景，无战斗动作。"
_SCENE_GUARD = "空间透视正常，陈设固定，光影统一。"
_PROP_GUARD = "外观结构完整，焦点清晰。"

# 反向提示词：精简到核心 4 项，避免 CFG 权重稀释。
_NEGATIVE_TAIL_CHARACTER = (
    "画面避免：水印、乱码文字、过多文字、低分辨率、手指畸形、脸部崩坏、"
    "左右服装不一致、三视图人物不一致、多余角色、复杂背景、风格偏离项目设定。"
)
_NEGATIVE_TAIL_ASSET = "画面避免：水印、多余文字、低分辨率、手指畸形。"
_NEGATIVE_TAIL_VIDEO = "禁止出现：BGM、文字字幕、水印。"


def _style_prefix(style: str = "", style_description: str = "") -> str:
    """组合视觉风格前缀。两者都为空时返回空串。"""
    parts = []
    if style:
        parts.append(f"风格：{style}")
    if style_description:
        parts.append(f"描述：{style_description}")
    if not parts:
        return ""
    return "\n".join(parts) + "\n\n"


# ---------------------------------------------------------------------------
# 资产 prompt（character / scene / prop）
# ---------------------------------------------------------------------------


def build_character_prompt(name: str, description: str, style: str = "", style_description: str = "") -> str:
    """角色设计图 prompt（issue #353 四视图 16:9）。"""
    style_block = _style_prefix(style, style_description)
    return (
        f"{style_block}"
        f"角色「{name}」的设计参考图 / character reference sheet / turnaround sheet。\n\n"
        f"{description}\n\n"
        f"{_CHARACTER_LAYOUT}\n\n"
        f"{_CHARACTER_PROP_RULE}\n\n"
        f"{_CHARACTER_GUARD}\n\n"
        f"{_CHARACTER_PRESENTATION_GUIDE}\n\n"
        f"{_NEGATIVE_TAIL_CHARACTER}"
    )


def build_scene_prompt(name: str, description: str, style: str = "", style_description: str = "") -> str:
    """场景设计图 prompt（主+细节）。"""
    style_block = _style_prefix(style, style_description)
    return (
        f"{style_block}"
        f"标志性场景「{name}」的视觉参考。\n\n"
        f"{description}\n\n"
        f"{_SCENE_LAYOUT}\n\n"
        f"{_SCENE_GUARD}\n\n"
        f"{_NEGATIVE_TAIL_ASSET}"
    )


def build_prop_prompt(name: str, description: str, style: str = "", style_description: str = "") -> str:
    """道具设计图 prompt（三视图）。"""
    style_block = _style_prefix(style, style_description)
    return (
        f"{style_block}"
        f"道具「{name}」的多视角展示。\n\n"
        f"{description}\n\n"
        f"{_PROP_LAYOUT}\n\n"
        f"{_PROP_GUARD}\n\n"
        f"{_NEGATIVE_TAIL_ASSET}"
    )


# ---------------------------------------------------------------------------
# 分镜 / 视频 prompt 末尾增强
# ---------------------------------------------------------------------------


def append_video_negative_tail(prompt: str) -> str:
    """给视频生成 prompt 追加统一的反向提示词。

    调用方拿到分镜 video_prompt 文本后，在交给 video backend 之前过一遍此函数；
    避免在每个 caller 各自拼接、导致漂移。
    """
    if not prompt or not prompt.strip():
        return _NEGATIVE_TAIL_VIDEO
    if _NEGATIVE_TAIL_VIDEO in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\n{_NEGATIVE_TAIL_VIDEO}"


def build_storyboard_suffix(content_mode: str = "narration", *, aspect_ratio: str | None = None) -> str:
    """分镜图构图后缀。优先 aspect_ratio，缺省按 content_mode 推导。"""
    if aspect_ratio is None:
        ratio = "9:16" if content_mode == "narration" else "16:9"
    else:
        ratio = aspect_ratio
    if ratio == "9:16":
        return "竖屏构图。"
    if ratio == "16:9":
        return "横屏构图。"
    return ""

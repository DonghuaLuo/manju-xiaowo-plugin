"""
script_models.py - 剧本数据模型

使用 Pydantic 定义剧本的数据结构，用于：
1. Gemini API 的 response_schema（Structured Outputs）
2. 输出验证
"""

from dataclasses import dataclass
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

# 子模型禁止额外字段：patch_episode_script 允许创建叶子字段，结构校验必须能挡住 typo / hallucination。
_STRICT_CONFIG = ConfigDict(extra="forbid")

# ============ 枚举类型定义 ============

ShotType = Literal[
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

CameraMotion = Literal[
    "Static",
    "Pan Left",
    "Pan Right",
    "Tilt Up",
    "Tilt Down",
    "Zoom In",
    "Zoom Out",
    "Tracking Shot",
]

TransitionType = Literal[
    "cut",
    "fade",
    "dissolve",
]

VideoContinuityPolicy = Literal["auto", "start_only", "end_frame", "reference_assisted"]


class Dialogue(BaseModel):
    """对话条目"""

    model_config = _STRICT_CONFIG

    speaker: str = Field(description="说话人名称")
    line: str = Field(description="对话内容")
    emotion: str = Field(default="", description="这句台词的情绪/语气，例如紧张、低声、哽咽或愤怒但克制")
    screen_position: str = Field(default="", description="说话人在画面中的大致位置：left、center、right 或 offscreen")


class Composition(BaseModel):
    """构图信息"""

    model_config = _STRICT_CONFIG

    shot_type: ShotType = Field(description="镜头类型")
    lighting: str = Field(description="光线描述：光源、方向、色温；避免抽象词")
    ambiance: str = Field(description="整体氛围：可观察的环境效果；避免抽象情绪词")


class ImagePrompt(BaseModel):
    """分镜图生成 Prompt"""

    model_config = _STRICT_CONFIG

    scene: str = Field(description="画面静态描述：角色姿态、环境元素、光影氛围（动作请写到 video_prompt.action）")
    composition: Composition = Field(description="构图信息")


class VideoPrompt(BaseModel):
    """视频生成 Prompt"""

    model_config = _STRICT_CONFIG

    action: str = Field(description="动作描述：仅描述物理可观察动作，避免内心动词（如 陷入/回忆/意识到）")
    camera_motion: CameraMotion = Field(description="镜头运动")
    ambiance_audio: str = Field(description="环境音效：仅描述场景内的声音，禁止 BGM")
    dialogue: list[Dialogue] = Field(default_factory=list, description="对话列表，仅当原文有引号对话时填写")


class GeneratedAssets(BaseModel):
    """生成资源状态（初始化为空）"""

    model_config = _STRICT_CONFIG

    storyboard_image: str | None = Field(default=None, description="分镜图路径")
    storyboard_last_image: str | None = Field(default=None, description="分镜图最后一帧路径")
    grid_id: str | None = Field(default=None, description="关联的网格图生成 ID")
    grid_cell_index: int | None = Field(default=None, description="在网格图中的单元格索引")
    video_clip: str | None = Field(default=None, description="视频片段路径")
    video_thumbnail: str | None = Field(default=None, description="视频缩略图路径")
    video_uri: str | None = Field(default=None, description="视频 URI")
    status: Literal["pending", "storyboard_ready", "completed"] = Field(default="pending", description="生成状态")


class StoryboardGenerationSettings(BaseModel):
    """单分镜生成设置（人工 / UI 字段，对 LLM 隐藏）。"""

    model_config = _STRICT_CONFIG

    resolution: str | None = Field(default=None, description="单分镜分辨率覆盖")
    image_backend: str | None = Field(default=None, description="单分镜图片模型覆盖（provider/model）")
    use_current_as_reference: bool | None = Field(default=None, description="是否沿当前分镜继续生成")


class VideoGenerationSettings(BaseModel):
    """单视频生成设置（人工 / UI 字段，对 LLM 隐藏）。"""

    model_config = _STRICT_CONFIG

    resolution: str | None = Field(default=None, description="单视频分辨率覆盖")
    video_backend: str | None = Field(default=None, description="单视频视频模型覆盖（provider/model）")
    video_continuity_policy: VideoContinuityPolicy | None = Field(
        default=None, description="单视频连续性策略覆盖"
    )


# ============ 说书模式（Narration） ============


class NarrationSegment(BaseModel):
    """说书模式的片段

    注意：不设独立 `episode` 字段。集号已经编码在 `segment_id`
    （格式 E{集}S{序号}）中。避免 AI 在每个
    segment 上重复生成集号造成幻觉污染（详见 `NarrationEpisodeScript` docstring）。
    """

    model_config = _STRICT_CONFIG

    LEGACY_DROPPED_FIELDS: ClassVar[frozenset[str]] = frozenset({"clues_in_segment", "shot_tier"})

    @model_validator(mode="before")
    @classmethod
    def _strip_legacy_fields(cls, data: object) -> object:
        if isinstance(data, dict):
            data = dict(data)
            for key in cls.LEGACY_DROPPED_FIELDS:
                data.pop(key, None)
        return data

    segment_id: str = Field(
        description="片段 ID，统一格式 E{集}S{序号} 或 E{集}S{序号}_{子序号}，必须复制 Step 1 第一列"
    )
    duration_seconds: int = Field(ge=1, le=60, description="片段时长（秒）")
    segment_break: bool = Field(default=False, description="是否为场景切换点")
    novel_text: str = Field(description="小说原文（必须原样保留，用于后期配音）")
    characters_in_segment: list[str] = Field(description="出场角色名称列表")
    scenes: list[str] = Field(default_factory=list, description="出场场景名称列表")
    props: list[str] = Field(default_factory=list, description="出场道具名称列表")
    image_prompt: ImagePrompt = Field(description="分镜图生成提示词")
    video_prompt: VideoPrompt = Field(description="视频生成提示词")
    # transition_to_next 由 _add_metadata 基于 segment_break 确定默认值，并由用户 PATCH 路径管理；
    # LLM 无 prompt 引导，隐藏避免乱填污染剪映/compose-video 合成。
    transition_to_next: SkipJsonSchema[TransitionType] = Field(default="cut", description="转场类型")
    # 以下字段对 LLM 隐藏（SkipJsonSchema）：note 是人工备注、generated_assets 是 post-LLM 运行时状态。
    # 仍保留在 Pydantic 模型里以便存储 / 校验，但不出现在 response_schema 中，避免 LLM 填污染数据。
    storyboard_generation: SkipJsonSchema[StoryboardGenerationSettings] = Field(
        default_factory=StoryboardGenerationSettings, description="单分镜生成设置"
    )
    video_generation: SkipJsonSchema[VideoGenerationSettings] = Field(
        default_factory=VideoGenerationSettings, description="单视频生成设置"
    )
    note: SkipJsonSchema[str | None] = Field(default=None, description="用户备注（不参与生成）")
    generated_assets: SkipJsonSchema[GeneratedAssets] = Field(
        default_factory=GeneratedAssets, description="生成资源状态"
    )


class NovelInfo(BaseModel):
    """小说来源信息

    title/chapter 都带 default,以便 SkipJsonSchema[NovelInfo] 的 default_factory=NovelInfo 构造。
    真实值由 ``ScriptGenerator._add_metadata`` setdefault 注入(项目 title + ``f"第N集"``);
    LLM 不再被引导填写,避免虚构章节名污染 compose-video 的输出 mp4 文件命名。
    """

    model_config = _STRICT_CONFIG

    title: str = Field(default="", description="小说标题")
    chapter: str = Field(default="", description="章节名称")


class NarrationEpisodeScript(BaseModel):
    """说书模式剧集脚本

    注意：`episode` 字段不在 schema 中。CLI 参数 `--episode N` 是集号的唯一真相源，
    由 `ScriptGenerator._add_metadata` 写入。不让 AI 生成该字段，避免幻觉写错集号
    进而污染 project.json（曾导致 episode_10.json 内部 episode=1 覆盖第 1 集条目）。

    顶层不走 extra="forbid"：episode / metadata / generation_mode 等字段由运行时注入。
    typo 防护靠 ImagePrompt / VideoPrompt / Segment 等子模型的严格校验。
    """

    title: str = Field(description="剧集标题")
    # content_mode 由 _add_metadata setdefault 注入项目级真值;Literal 单值让 LLM 写无意义
    content_mode: SkipJsonSchema[Literal["narration"]] = Field(default="narration", description="内容模式")
    # 顶层 duration_seconds 由 ScriptGenerator._add_metadata 求各段之和重算，LLM 填的值会被覆盖；隐藏避免冗余。
    duration_seconds: SkipJsonSchema[int] = Field(default=0, description="总时长（秒）")
    # novel 由 _add_metadata 注入 {项目 title, f"第N集"};compose-video 用 chapter 作输出文件名,LLM 自由发挥反而不可预测
    novel: SkipJsonSchema[NovelInfo] = Field(default_factory=NovelInfo, description="小说来源信息")
    segments: list[NarrationSegment] = Field(description="片段列表")


# ============ 剧集动画模式（Drama） ============


class DramaScene(BaseModel):
    """剧集动画模式的场景"""

    model_config = _STRICT_CONFIG

    LEGACY_DROPPED_FIELDS: ClassVar[frozenset[str]] = frozenset({"scene_type", "clues_in_scene", "shot_tier"})

    @model_validator(mode="before")
    @classmethod
    def _strip_legacy_fields(cls, data: object) -> object:
        if isinstance(data, dict):
            data = dict(data)
            for key in cls.LEGACY_DROPPED_FIELDS:
                data.pop(key, None)
        return data

    scene_id: str = Field(description="场景 ID，格式 E{集}S{序号} 或 E{集}S{序号}_{子序号}")
    duration_seconds: int = Field(default=8, ge=1, le=60, description="场景时长（秒）")
    segment_break: bool = Field(default=False, description="是否为场景切换点")
    characters_in_scene: list[str] = Field(description="出场角色名称列表")
    scenes: list[str] = Field(default_factory=list, description="出场场景名称列表")
    props: list[str] = Field(default_factory=list, description="出场道具名称列表")
    image_prompt: ImagePrompt = Field(description="分镜图生成提示词")
    video_prompt: VideoPrompt = Field(description="视频生成提示词")
    # 见 NarrationSegment.transition_to_next 说明
    transition_to_next: SkipJsonSchema[TransitionType] = Field(default="cut", description="转场类型")
    # 见 NarrationSegment 同名字段说明。
    storyboard_generation: SkipJsonSchema[StoryboardGenerationSettings] = Field(
        default_factory=StoryboardGenerationSettings, description="单分镜生成设置"
    )
    video_generation: SkipJsonSchema[VideoGenerationSettings] = Field(
        default_factory=VideoGenerationSettings, description="单视频生成设置"
    )
    note: SkipJsonSchema[str | None] = Field(default=None, description="用户备注（不参与生成）")
    generated_assets: SkipJsonSchema[GeneratedAssets] = Field(
        default_factory=GeneratedAssets, description="生成资源状态"
    )


class DramaEpisodeScript(BaseModel):
    """剧集动画模式剧集脚本

    注意：`episode` 字段不在 schema 中，集号由 CLI 真相源通过 `_add_metadata` 写入。
    详见 `NarrationEpisodeScript` docstring。顶层不走 extra="forbid" 同理。
    """

    title: str = Field(description="剧集标题")
    # 见 NarrationEpisodeScript.content_mode 说明
    content_mode: SkipJsonSchema[Literal["drama"]] = Field(default="drama", description="内容模式")
    # 见 NarrationEpisodeScript.duration_seconds 说明。
    duration_seconds: SkipJsonSchema[int] = Field(default=0, description="总时长（秒）")
    # 见 NarrationEpisodeScript.novel 说明
    novel: SkipJsonSchema[NovelInfo] = Field(default_factory=NovelInfo, description="小说来源信息")
    scenes: list[DramaScene] = Field(description="场景列表")


# ============ 参考生视频模式（Reference Video） ============


class Shot(BaseModel):
    """参考视频单元内的一个镜头。"""

    model_config = _STRICT_CONFIG

    duration: int = Field(ge=1, le=15, description="该镜头时长（秒）")
    text: str = Field(description="镜头描述，可包含 @[角色]/@[场景]/@[道具] 引用")


class ReferenceResource(BaseModel):
    """参考图引用——只存名称 + 类型，具体路径从 project.json 对应 bucket 读时解析。"""

    model_config = _STRICT_CONFIG

    type: Literal["character", "scene", "prop"] = Field(description="引用的资源类型")
    name: str = Field(description="角色/场景/道具名称，必须在 project.json 对应 bucket 中已注册")


class ReferenceVideoUnit(BaseModel):
    """参考视频单元——一个视频文件的最小生成粒度。"""

    model_config = _STRICT_CONFIG

    unit_id: str = Field(description="格式 E{集}U{序号}")
    shots: list[Shot] = Field(min_length=1, max_length=4, description="1-4 个 shot")
    references: list[ReferenceResource] = Field(
        default_factory=list,
        description="按顺序决定 [图N] 编号",
    )
    duration_seconds: int = Field(description="派生字段：所有 shot 时长之和")
    # duration_override / transition_to_next / note / generated_assets 均为 UI / runtime / 人工字段，对 LLM 隐藏。
    duration_override: SkipJsonSchema[bool] = Field(default=False, description="true 时停止自动派生")
    transition_to_next: SkipJsonSchema[TransitionType] = Field(default="cut", description="转场类型")
    note: SkipJsonSchema[str | None] = Field(default=None, description="用户备注")
    generated_assets: SkipJsonSchema[GeneratedAssets] = Field(
        default_factory=GeneratedAssets, description="生成资源状态"
    )

    @model_validator(mode="after")
    def _check_duration_consistency(self) -> "ReferenceVideoUnit":
        if not self.duration_override:
            expected = sum(s.duration for s in self.shots)
            if self.duration_seconds != expected:
                raise ValueError(
                    f"duration_seconds ({self.duration_seconds}) 与 shots 总时长 ({expected}) 不符；"
                    "如需手动指定请置 duration_override=True"
                )
        return self


class ReferenceVideoScript(BaseModel):
    """参考生视频模式剧集脚本。

    注意：`episode` 字段不在 schema 中，集号由 CLI 真相源通过 `_add_metadata` 写入。
    详见 `NarrationEpisodeScript` docstring。顶层不走 extra="forbid" 同理。

    ``content_mode`` 仅承担"内容类型"维度（narration/drama），"视频来源"维度由
    ``generation_mode = "reference_video"`` 表达。两字段都对 LLM 隐藏，由
    ``ScriptGenerator._add_metadata`` 按项目级配置注入。
    """

    title: str = Field(description="剧集标题")
    # 对 LLM 隐藏：参考视频模式下这两个字段都由 _add_metadata 注入。
    content_mode: SkipJsonSchema[Literal["narration", "drama"]] = Field(
        default="narration", description="内容类型（narration/drama），参考视频模式实际不区分"
    )
    generation_mode: SkipJsonSchema[Literal["reference_video"]] = Field(
        default="reference_video", description="生成模式，固定 reference_video"
    )
    # 见 NarrationEpisodeScript.duration_seconds 说明。
    duration_seconds: SkipJsonSchema[int] = Field(default=0, description="总时长（秒）")
    # 见 NarrationEpisodeScript.novel 说明
    novel: SkipJsonSchema[NovelInfo] = Field(default_factory=NovelInfo, description="小说来源信息")
    video_units: list[ReferenceVideoUnit] = Field(description="视频单元列表")


# ============ content_mode → 剧本字段名分派 ============


@dataclass(frozen=True)
class ScriptShape:
    """某个 content_mode 下剧本的结构形状：列表字段名 / 每项 id 字段名 / 角色字段名。"""

    items_key: str
    id_field: str
    chars_field: str


SCRIPT_SHAPES: dict[str, ScriptShape] = {
    "narration": ScriptShape("segments", "segment_id", "characters_in_segment"),
    "drama": ScriptShape("scenes", "scene_id", "characters_in_scene"),
}


def script_shape(content_mode: str) -> ScriptShape:
    """返回该 content_mode 的剧本形状。

    忠实于既有二分语义（``"segments" if content_mode == "narration" else "scenes"``）：
    只有 ``"narration"`` 返回 narration 形状，其余一切（含未知值）落 drama。

    reference_video 模式用 video_units/unit_id/references 组织，结构不同，不经此分派
    （由 project_archive 的专用分支处理）。
    """
    if content_mode == "narration":
        return SCRIPT_SHAPES["narration"]
    return SCRIPT_SHAPES["drama"]

"""剧本生成 Prompt 构建器（drama / narration 两种 content_mode）。

设计原则：
- 不重复 schema 已声明的枚举（shot_type / camera_motion 等）；让 response_schema 直接约束。
- 多选枚举字段不在 prompt 里写"如何选"判据，避免把人的镜头审美灌给 LLM；
  让模型按画面内容自行决定。
- 不写无法被 LLM 自检的字数硬限制（"≤200 字"）；用示例隐性表达节奏。
- 字段说明给 1-2 个正例（必要时配一个反例），不堆"必须 / 禁止"清单。
- 节奏建议由 lib.prompt_rules.episode_pacing 注入，跨 subagent 与 builder 共享。
"""

from lib.prompt_rules import is_v2_enabled
from lib.prompt_rules.episode_pacing import render_pacing_section
from lib.script_splitting_templates import render_profile_prompt_section


def _format_names(items: dict) -> str:
    if not items:
        return "（暂无）"
    return "\n".join(f"- {name}" for name in items.keys())


def _profile_output_fields(profile: dict | None) -> list[str]:
    if not profile or profile.get("legacy_passthrough"):
        return []
    return [str(field) for field in profile.get("output_fields") or [] if str(field).strip()]


def _prompt_fragments(profile: dict | None) -> dict:
    fragments = profile.get("prompt_fragments") if isinstance(profile, dict) else None
    return fragments if isinstance(fragments, dict) else {}


def _format_prompt_fragment(text: str, **values) -> str:
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):
        return text


def _step1_drama_table(profile: dict | None, episode: int) -> str:
    fields = _profile_output_fields(profile) or [
        "scene_id",
        "scene_description",
        "duration_seconds",
        "segment_break",
    ]
    samples = {
        "scene_id": f"E{episode}S01",
        "scene_description": "详细的场景描述...",
        "dramatic_purpose": "本镜头的戏剧目的",
        "beat_type": "hook / conflict / reaction / reveal",
        "coverage_role": "establishing / action / reaction / insert / reveal",
        "start_state": "镜头开始时的角色站位、表情、道具状态",
        "visible_action": "可见动作、表情、视线或对白",
        "dialogue_core": "核心对白或空",
        "emotion_turn": "情绪变化",
        "reaction_target": "承接上一动作的反应角色或物件",
        "end_state": "镜头结束时必须接到下一镜的状态",
        "shot_size": "Close-up / Medium Shot / Long Shot",
        "camera_angle": "eye-level / low angle / high angle",
        "camera_motion": "Static / Tracking Shot / Pan Left",
        "screen_direction": "角色从画面左向右移动，下一镜保持方向",
        "eyeline_match": "她看向画面右侧，下一镜承接被看对象",
        "match_action": "手触到门把手，下一镜从门内接开门动作",
        "continuity_anchor": "角色位置、道具状态、场景方位等连续性锚点",
        "reference_assets": "角色:某人; 场景:某地; 道具:某物",
        "asset_binding_requirements": "缺少参考资产时写需求",
        "first_frame_intent": "首帧主体位置、视线和关键道具",
        "lighting_palette": "冷顶光 + 暖色台灯；主色锚点为青灰、米白、暗红",
        "sound_cue": "门轴声 / 脚步声 / 风铃声",
        "payoff_hook": "下一镜兑现身份反转或众人见证",
        "clue_state": "线索处于发现 / 遮挡 / 被验证 / 暂不揭示",
        "reveal_boundary": "本镜只让观众看到湿外套，不说明来者身份",
        "power_anchor": "青色符文长剑 / 阵法光圈 / 灵力裂纹",
        "scale_control": "近身细节 / 双人交锋 / 场景级冲击",
        "threat_vector": "威胁来自走廊尽头，距离角色约三米",
        "survival_resource": "只剩一发子弹 / 半瓶药 / 被堵住的消防门",
        "escape_route": "右侧消防门半掩，下一镜可接转身冲出",
        "folklore_taboo": "夜里不可跨祠堂门槛",
        "ritual_symbol": "门槛红绳 / 纸钱 / 牌位 / 香灰",
        "unseen_presence": "烛火偏向同一侧，门缝外有脚步声",
        "subtext": "她已知道真相但压住情绪",
        "acting_detail": "指尖压住纸角发白，笑容停在嘴角",
        "dialogue_timing": "推纸后停一拍再开口",
        "shot_sequence": "同一任务内的镜头顺序",
        "provider_hints": "运镜、运动幅度、参考图或音频提示",
        "audio_plan": "对白、环境音、旁白意图",
        "duration_seconds": "<duration>",
        "segment_break": "是",
        "transition_to_next": "cut / fade / dissolve",
        "production_note": "用于剪辑衔接的简短说明",
    }
    header = "| " + " | ".join(fields) + " |"
    separator = "| " + " | ".join("---" for _ in fields) + " |"
    row = "| " + " | ".join(samples.get(field, f"{field}...") for field in fields) + " |"
    return "\n".join([header, separator, row])


def _legacy_step1_drama_table(profile: dict | None, episode: int) -> str:
    fragment = _prompt_fragments(profile).get("normalize_table_template")
    if isinstance(fragment, str) and fragment.strip():
        return _format_prompt_fragment(fragment, episode=episode)
    return f"""| 场景 ID | 场景描述 | 时长 | segment_break |
|---------|---------|------|---------------|
| E{episode}S01 | 详细的场景描述... | <duration> | 是 |
| E{episode}S02 | 详细的场景描述... | <duration> | 否 |"""


def _legacy_step1_field_rule(profile: dict | None) -> str:
    fragment = _prompt_fragments(profile).get("normalize_field_rule")
    if isinstance(fragment, str) and fragment.strip():
        return fragment
    return "- 场景描述：改编后的剧本化描述，包含角色动作、对话、环境，适合视觉化呈现"


def _render_step1_to_json_bridge(profile: dict | None) -> str:
    fields = set(_profile_output_fields(profile))
    continuity_fields = {
        "start_state",
        "visible_action",
        "end_state",
        "continuity_anchor",
        "reference_assets",
        "asset_binding_requirements",
        "first_frame_intent",
        "shot_sequence",
        "provider_hints",
        "audio_plan",
        "coverage_role",
        "reaction_target",
        "screen_direction",
        "eyeline_match",
        "match_action",
        "lighting_palette",
        "sound_cue",
        "payoff_hook",
        "clue_state",
        "reveal_boundary",
        "power_anchor",
        "scale_control",
        "threat_vector",
        "survival_resource",
        "escape_route",
        "folklore_taboo",
        "ritual_symbol",
        "unseen_presence",
        "subtext",
        "acting_detail",
        "dialogue_timing",
        "production_note",
    }
    if not fields.intersection(continuity_fields):
        return ""
    return """
- 若 shots 表包含 start_state / visible_action / end_state：必须把状态衔接转写进 image_prompt.scene 与 video_prompt.action，不能只丢弃为备注。
- 若 shots 表包含 continuity_anchor / reference_assets / first_frame_intent：用它们约束角色站位、关键道具、首帧构图和候选 characters/scenes/props。
- 若 shots 表包含 shot_sequence / provider_hints / audio_plan：把可执行部分转写到 camera_motion、ambiance_audio、dialogue 或动作描述中；无法落入 schema 的信息要融入文字描述。
- 若 shots 表包含 coverage_role / reaction_target / screen_direction / eyeline_match / match_action：用它们组织镜头景别、视线方向、动作承接和反应镜头，避免生成孤立画面。
- 若 shots 表包含 sound_cue / lighting_palette / production_note：把声音、光源色彩和剪辑衔接意图转写到 ambiance_audio、composition.lighting 或 scene/action 描述中。
- 若 shots 表包含题材字段（payoff_hook / clue_state / power_anchor / threat_vector / folklore_taboo / subtext 等）：把其中可见、可听、可动的部分转成画面与动作，不要只作为备注保留。
"""


def _render_narration_step1_to_json_bridge(profile: dict | None) -> str:
    fields = set(_profile_output_fields(profile))
    bridge_fields = {
        "visual_focus",
        "shot_size",
        "camera_motion",
        "continuity_anchor",
        "first_frame_intent",
        "sound_cue",
        "transition_to_next",
    }
    if not fields.intersection(bridge_fields):
        return ""
    return """
- 若 segments 表包含 visual_focus / first_frame_intent / continuity_anchor：把画面焦点、首帧构图和连续性锚点转写进 image_prompt.scene 与候选 assets。
- 若 segments 表包含 camera_motion / sound_cue / transition_to_next：把可执行部分转写到 video_prompt.camera_motion、ambiance_audio 或动作描述中，不能只停留在拆分表备注里。
"""


def _format_duration_constraint(supported_durations: list[int], default_duration: int | None) -> str:
    """生成时长约束描述。连续整数集 ≥5 用区间表达，否则枚举。"""
    if not supported_durations:
        raise ValueError("supported_durations 不能为空：调用方必须提供 model 的合法时长列表")

    sorted_d = sorted(set(supported_durations))
    is_continuous = len(sorted_d) >= 5 and all(sorted_d[i] == sorted_d[i - 1] + 1 for i in range(1, len(sorted_d)))
    if is_continuous:
        body = f"{sorted_d[0]} 到 {sorted_d[-1]} 秒间整数任选"
    else:
        durations_str = ", ".join(str(d) for d in sorted_d)
        body = f"从 [{durations_str}] 秒中选择"

    if default_duration is not None:
        if default_duration not in sorted_d:
            raise ValueError(
                f"default_duration={default_duration} 不在 supported_durations={sorted_d} 内，"
                "调用方必须保证默认值合法（否则 prompt 会自相矛盾）"
            )
        return f"时长：{body}，默认 {default_duration} 秒"
    return f"时长：{body}，按内容节奏自行决定"


def _format_aspect_ratio_desc(aspect_ratio: str) -> str:
    if aspect_ratio == "9:16":
        return "竖屏构图"
    if aspect_ratio == "16:9":
        return "横屏构图"
    return f"{aspect_ratio} 构图"


# ---------------------------------------------------------------------------
# 字段写作指导（drama / narration 共用）
# ---------------------------------------------------------------------------

# image_prompt.scene 写作指导：原则 + 正反例。LLM 对示例的泛化优于对清单的执行。
# 好例用方括号小标注隐性传达"主体 / 环境 / 光线 / 氛围"四层覆盖。
_SCENE_WRITING_GUIDE = """用一段连贯的描述说明当前画面中真实可见的元素：角色姿态、面部可观察的状态、环境细节、可见的氛围信号（光线、雾、雨等）。聚焦"此刻这一帧"，不要混入过去/未来事件、抽象情绪词或镜头之外的元素。画面元素（材质、装束、道具质感、环境年代特征）须贴合上方 `<style>` 块定义的风格基调，避免与风格相冲的元素混入（例如赛博朋克风下不出现榻榻米，国风水墨下不出现霓虹屏）。
   好例：「[主体] 林清坐在窗边木桌前，左手撑着下巴，目光落在桌上一封拆开的信纸上。[环境] 桌面摊着信封与一只褪色的怀表。[光线] 半边脸笼在右侧落地窗逆光的蓝灰色阴影里。[氛围] 雨丝拍在木格窗棂，玻璃凝着细小水珠。」
   反例（跑偏）：「林清陷入了多年前那个绝望的雨夜，画面基调：忧郁。光影设定：冷调。」
   反例（过短）：「林清坐在窗边发呆。」——缺少环境元素、光线方向、氛围细节，至少应覆盖主体 / 环境 / 光线 / 氛围中三层。
   反例里这类词族也要避免：陷入 / 回忆 / 思绪 / 意识到 / 画外音 / BGM / 精致 / 震撼。"""

# video_prompt.action 写作指导：动态优先 + 正反例。
# 好例用方括号小标注隐性传达"主体动作 / 物件互动 / 环境动态"三层。
_ACTION_WRITING_GUIDE = """用一段描述说明该时长内主体的连贯动作（肢体动作、手势、表情过渡），可包含必要的环境互动（衣摆、尘埃、推门带起的气流等）。让画面"活"起来，但不要堆叠不可能在单镜头内完成的动作或蒙太奇切换。动词应描述物理可观察动作（伸手 / 转身 / 摩挲 / 投向 / 收紧），避免内心动词。动作幅度应与该 segment 的 duration 匹配：5 秒级镜头通常完成一个连贯动作 + 一个细节互动；8 秒级可承载一次动作过渡（如「抬头—对视—开口」），不要把三组以上独立动作塞进同一 action。
   好例：「[主体动作] 林清缓缓抬起头，眼角微微收紧。[物件互动] 手指无意识地摩挲信纸边缘。[环境动态] 窗外雨势渐大，桌面投下的雨痕影子在缓慢移动。」
   反例：「林清像蝴蝶般飞舞，思绪在过去与现在之间快速切换。」
   反例里这类词族也要避免：思绪飞舞 / 回忆翻涌 / 突然意识到 / 决心 / 仿佛 / 像蝴蝶般。"""

_LIGHTING_WRITING_GUIDE = (
    "描述具体的光源、方向、色温（如「左侧窗户透入的暖黄色晨光（约 3500K）」「头顶单点冷白色的吊灯」）。"
    "可附加摄影质感术语（如「浅景深」「逆光剪影」「丁达尔光柱」「轮廓光勾边」「35mm 胶片颗粒感」），"
    "让画面具备可观察的镜头语言而非抽象修辞；避免「光影神秘」「氛围唯美」这类抽象词。"
)
_AMBIANCE_WRITING_GUIDE = "描述可观察的环境效果（如「薄雾弥漫」「尘埃在光柱里翻飞」），避免抽象情绪词。"
_AMBIANCE_AUDIO_WRITING_GUIDE = (
    "只描写画内音（diegetic sound）：环境声、脚步、物体声响。不要写 BGM、配乐、画外音、旁白。"
)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_narration_prompt(
    project_overview: dict,
    style: str,
    style_description: str,
    characters: dict,
    scenes: dict,
    props: dict,
    segments_md: str,
    supported_durations: list[int],
    episode: int,
    default_duration: int | None = None,
    aspect_ratio: str = "9:16",
    target_language: str = "中文",
    script_splitting_profile: dict | None = None,
) -> str:
    """构建说书模式的剧本生成 prompt。"""
    character_names = list(characters.keys())
    scene_names = list(scenes.keys())
    prop_names = list(props.keys())
    pacing_block = (render_pacing_section("narration") + "\n\n") if is_v2_enabled() else ""
    profile_block = render_profile_prompt_section(script_splitting_profile)
    profile_section = f"{profile_block}\n" if profile_block else ""
    step1_bridge = _render_narration_step1_to_json_bridge(script_splitting_profile)
    step1_bridge_section = step1_bridge if step1_bridge else ""

    return f"""# 角色与任务

你是一位资深的短视频分镜编剧，专精把小说片段改写为可直接驱动 AI 图像 / 视频生成的结构化分镜剧本。
你的任务：基于下方"小说片段拆分表"，逐条产出符合 schema 的 JSON 剧本。

**输出语言**：所有字符串值必须使用 {target_language}；JSON 键名 / 枚举值保持英文。
**结构约束**：字段 / 枚举 / 必填项由 response_schema 强制；本提示只解释**如何写好每个字段的内容**。

{pacing_block}{profile_section}# 上下文

<overview>
{project_overview.get("synopsis", "")}

题材：{project_overview.get("genre", "")}
主题：{project_overview.get("theme", "")}
世界观：{project_overview.get("world_setting", "")}
</overview>

<style>
风格：{style}
描述：{style_description}
画面比例：{aspect_ratio}（{_format_aspect_ratio_desc(aspect_ratio)}）
</style>

<characters>
{_format_names(characters)}
</characters>

<scenes>
{_format_names(scenes)}
</scenes>

<props>
{_format_names(props)}
</props>

<segments>
{segments_md}
</segments>

segments 表每行是一个待生成的片段，包含：片段 ID（E{episode}S{{序号}}，当前为第 {episode} 集）、小说原文、{_format_duration_constraint(supported_durations, default_duration)}、是否含对话、是否为 segment_break。

<episode_constraints>
当前正在生成第 {episode} 集。本集所有 segment_id 必须严格使用 `E{episode}S{{两位序号}}` 格式（如 E{episode}S01、E{episode}S02），不得使用其他集号前缀。
若 segments 表里出现非 `E{episode}` 前缀（如 E1S..），视为脏数据，请按当前集号 `E{episode}` 重写。
</episode_constraints>

# 字段写作指引

对每个片段，按下列章节填写字段。

## 基础字段

- **novel_text**：原样复制小说原文，不修改、不删改标点。
- **characters_in_segment** / **scenes** / **props**：仅列出此片段画面或对话中实际出现的资产。
  - 候选 characters：[{", ".join(character_names) or "（无）"}]
  - 候选 scenes：[{", ".join(scene_names) or "（无）"}]
  - 候选 props：[{", ".join(prop_names) or "（无）"}]
  - 不要发明候选之外的名称。
- **segment_break** / **duration_seconds**：与 segments 表保持一致。
{step1_bridge_section}

## 图片提示词（image_prompt）——切换到「摄影师」视角

- **image_prompt.scene**：{_SCENE_WRITING_GUIDE}
- **image_prompt.composition.shot_type**：从枚举中按画面内容选择，不强加倾向。
- **image_prompt.composition.lighting**：{_LIGHTING_WRITING_GUIDE}
- **image_prompt.composition.ambiance**：{_AMBIANCE_WRITING_GUIDE}

## 视频提示词（video_prompt）——切换到「动作设计师」视角

- **video_prompt.action**：{_ACTION_WRITING_GUIDE}
- **video_prompt.camera_motion**：每个片段只选一种，按画面内容自行选择。
- **video_prompt.ambiance_audio**：{_AMBIANCE_AUDIO_WRITING_GUIDE}
- **video_prompt.dialogue**：仅当小说原文带引号对话时填写；speaker 必须出现在 characters_in_segment。
  - 每句 dialogue 同时填写 emotion（这句台词的语气/情绪）与 screen_position（left / center / right / offscreen，按画面站位选择）。

# 创作目标

输出可直接驱动 AI 生成的、视觉一致、节奏紧凑的分镜剧本。忠于原文叙事、保留情绪张力。
"""


def build_drama_prompt(
    project_overview: dict,
    style: str,
    style_description: str,
    characters: dict,
    scenes: dict,
    props: dict,
    scenes_md: str,
    supported_durations: list[int],
    episode: int,
    default_duration: int | None = None,
    aspect_ratio: str = "16:9",
    target_language: str = "中文",
    script_splitting_profile: dict | None = None,
) -> str:
    """构建剧集动画模式的剧本生成 prompt。"""
    character_names = list(characters.keys())
    scene_names = list(scenes.keys())
    prop_names = list(props.keys())
    pacing_block = (render_pacing_section("drama") + "\n\n") if is_v2_enabled() else ""
    profile_block = render_profile_prompt_section(script_splitting_profile)
    profile_section = f"{profile_block}\n" if profile_block else ""
    step1_bridge = _render_step1_to_json_bridge(script_splitting_profile)
    step1_bridge_section = step1_bridge if step1_bridge else ""

    return f"""# 角色与任务

你是一位资深的短剧分镜编剧，精通把改编后的剧本场景表转写为可直接驱动 AI 图像 / 视频生成的结构化分镜。
你的任务：基于下方"分镜拆分表"，逐条产出符合 schema 的 JSON 剧本。

**输出语言**：所有字符串值必须使用 {target_language}；JSON 键名 / 枚举值保持英文。
**结构约束**：字段 / 枚举 / 必填项由 response_schema 强制；本提示只解释**如何写好每个字段的内容**。

{pacing_block}{profile_section}# 上下文

<overview>
{project_overview.get("synopsis", "")}

题材：{project_overview.get("genre", "")}
主题：{project_overview.get("theme", "")}
世界观：{project_overview.get("world_setting", "")}
</overview>

<style>
风格：{style}
描述：{style_description}
画面比例：{aspect_ratio}（{_format_aspect_ratio_desc(aspect_ratio)}）
</style>

<characters>
{_format_names(characters)}
</characters>

<project_scenes>
{_format_names(scenes)}
</project_scenes>

<props>
{_format_names(props)}
</props>

<shots>
{scenes_md}
</shots>

shots 表每行是一个分镜，包含：分镜 ID（E{episode}S{{序号}}，当前为第 {episode} 集）、分镜描述、{_format_duration_constraint(supported_durations, default_duration)}、是否为 segment_break。

<episode_constraints>
当前正在生成第 {episode} 集。本集所有 scene_id 必须严格使用 `E{episode}S{{两位序号}}` 格式（如 E{episode}S01、E{episode}S02），不得使用其他集号前缀。
若 shots 表里出现非 `E{episode}` 前缀（如 E1S..），视为脏数据，请按当前集号 `E{episode}` 重写。
</episode_constraints>

# 字段写作指引

对每个分镜，按下列章节填写字段。

## 基础字段

- **characters_in_scene** / **scenes** / **props**：仅列出此分镜画面或对话中实际出现的资产。
  - 候选 characters：[{", ".join(character_names) or "（无）"}]
  - 候选 scenes：[{", ".join(scene_names) or "（无）"}]
  - 候选 props：[{", ".join(prop_names) or "（无）"}]
  - 不要发明候选之外的名称。
- **segment_break** / **duration_seconds**：与 shots 表保持一致。{step1_bridge_section}

## 图片提示词（image_prompt）——切换到「摄影师」视角

- **image_prompt.scene**：{_SCENE_WRITING_GUIDE}
- **image_prompt.composition.shot_type**：从枚举中按画面内容选择，不强加倾向。
- **image_prompt.composition.lighting**：{_LIGHTING_WRITING_GUIDE}
- **image_prompt.composition.ambiance**：{_AMBIANCE_WRITING_GUIDE}

## 视频提示词（video_prompt）——切换到「动作设计师」视角

- **video_prompt.action**：{_ACTION_WRITING_GUIDE}
- **video_prompt.camera_motion**：每个分镜只选一种，按画面内容自行选择。
- **video_prompt.ambiance_audio**：{_AMBIANCE_AUDIO_WRITING_GUIDE}
- **video_prompt.dialogue**：包含分镜中角色对话；speaker 必须出现在 characters_in_scene。
  - 每句 dialogue 同时填写 emotion（这句台词的语气/情绪）与 screen_position（left / center / right / offscreen，按画面站位选择）。

# 创作目标

输出可直接驱动 AI 生成的、视觉一致、节奏紧凑的分镜剧本。忠于原创设定、保留戏剧张力。
"""


def build_normalize_prompt(
    novel_text: str,
    project_overview: dict,
    style: str,
    characters: dict,
    scenes: dict,
    props: dict,
    default_duration: int | None,
    supported_durations: list[int],
    episode: int,
    script_splitting_profile: dict | None = None,
) -> str:
    """Step-1 normalization prompt: novel text → markdown scene table.

    Consumed by ``normalize_drama_script`` MCP tool. Sibling of
    ``build_drama_prompt`` (step 2 of the drama pipeline).
    """
    char_list = _format_names(characters)
    scene_list = _format_names(scenes)
    prop_list = _format_names(props)
    profile_block = render_profile_prompt_section(script_splitting_profile)
    profile_section = f"{profile_block}\n" if profile_block else ""

    # 规范化 + 校验：空集合或 default 不在集合内都会产出自相矛盾的提示词，
    # 让生成阶段失败比让 LLM 见到"只能取 — 中的值"更便于诊断（PR #528 review）。
    normalized_durations = sorted({int(d) for d in supported_durations})
    if not normalized_durations:
        raise ValueError("supported_durations 不能为空：必须提供模型支持的秒数集合")
    if default_duration is not None and int(default_duration) not in normalized_durations:
        raise ValueError(f"default_duration={default_duration} 不在 supported_durations={normalized_durations} 内")

    durations_str = ", ".join(str(d) for d in normalized_durations)
    max_dur = normalized_durations[-1]

    if default_duration is not None:
        duration_rules = (
            f"- 时长：只能取 {durations_str} 中的值（该视频模型支持的秒数集合）\n"
            f"- 每场景默认 {default_duration} 秒；打斗、大场面、情绪铺陈等画面可取更长值至上限 {max_dur} 秒，"
            "不要默认挑最短值"
        )
    else:
        duration_rules = (
            f"- 时长：只能取 {durations_str} 中的值（该视频模型支持的秒数集合）\n"
            f"- 按画面内容复杂度匹配合适时长（最长 {max_dur} 秒），不强制默认值"
        )

    legacy_passthrough = not script_splitting_profile or bool(script_splitting_profile.get("legacy_passthrough"))
    table_template = (
        _legacy_step1_drama_table(script_splitting_profile, episode)
        if legacy_passthrough
        else _step1_drama_table(script_splitting_profile, episode)
    )
    field_rule = (
        _legacy_step1_field_rule(script_splitting_profile)
        if legacy_passthrough
        else "- 按当前拆分方案的输出字段填写表格；字段名保持上方表头，不要省略模板要求的列\n"
        "- 场景 / 镜头描述：改编后的剧本化描述，包含角色动作、对话、环境，适合视觉化呈现"
    )
    return f"""你的任务是将小说原文改编为结构化的分镜场景表（Markdown 格式），用于后续 AI 视频生成。

{profile_section}## 项目信息

<overview>
{project_overview.get("synopsis", "")}

题材类型：{project_overview.get("genre", "")}
核心主题：{project_overview.get("theme", "")}
世界观设定：{project_overview.get("world_setting", "")}
</overview>

<style>
{style}
</style>

<characters>
{char_list}
</characters>

<scenes>
{scene_list}
</scenes>

<props>
{prop_list}
</props>

## 小说原文

<novel>
{novel_text}
</novel>

## 输出要求

将小说改编为场景列表，使用 Markdown 表格格式：

{table_template}

规则：
- 当前正在生成第 {episode} 集；所有场景 ID 必须使用 `E{episode}S{{两位序号}}` 格式，不得使用其他集号前缀
{field_rule}
{duration_rules}
- segment_break：场景切换点标记"是"，同一连续场景标"否"
- 每个场景应为一个独立的视觉画面，可以在指定时长内完成
- 避免一个场景包含多个不同的动作或画面切换

仅输出 Markdown 表格，不要包含其他解释文字。
"""

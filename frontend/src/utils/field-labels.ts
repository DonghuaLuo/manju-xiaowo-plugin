const MARKDOWN_TABLE_FIELD_LABELS: Record<string, string> = {
  acting_detail: "表演细节",
  asset_binding_requirements: "资产绑定要求",
  audio_plan: "声音方案",
  beat_type: "节拍类型",
  camera_angle: "机位角度",
  camera_motion: "运镜",
  character_count: "字数",
  characters_in_scene: "出场角色",
  characters_in_segment: "出场角色",
  clue_state: "线索状态",
  content_mode: "内容模式",
  continuity_anchor: "连续性锚点",
  coverage_role: "镜头功能",
  dialogue_core: "核心对白",
  dialogue_timing: "对白节奏",
  dramatic_purpose: "戏剧目的",
  duration: "时长",
  duration_seconds: "预计时长（秒）",
  emotion_turn: "情绪转折",
  end_state: "结束状态",
  escape_route: "逃生路线",
  eyeline_match: "视线衔接",
  first_frame_intent: "首帧意图",
  folklore_taboo: "民俗禁忌",
  generated_assets: "生成资产",
  has_dialogue: "有对话",
  hook_role: "钩子作用",
  lighting_palette: "光线色彩",
  match_action: "动作衔接",
  narrative_purpose: "叙事目的",
  novel_text: "原文",
  payoff_hook: "爽点承接",
  power_anchor: "力量锚点",
  production_note: "制作备注",
  props_in_scene: "道具",
  props_in_segment: "道具",
  provider_hints: "生成提示",
  reaction_target: "反应对象",
  reference_assets: "参考资产",
  references: "参考素材",
  reveal_boundary: "揭示边界",
  ritual_symbol: "仪式物件",
  scale_control: "奇观尺度",
  scene_description: "场景描述",
  scene_id: "场景编号",
  scenes: "场景",
  screen_direction: "画面方向",
  segment: "片段",
  segment_break: "场景切换",
  segment_id: "片段编号",
  segment_label: "片段编号",
  shot_sequence: "镜头顺序",
  shot_size: "景别",
  shots: "镜头列表",
  sound_cue: "声音提示",
  start_state: "起始状态",
  subtext: "潜台词",
  suspense_question: "悬念问题",
  survival_resource: "生存资源",
  threat_vector: "威胁方向",
  transition_to_next: "转场方式",
  unit_id: "视频单元编号",
  unseen_presence: "未现身存在",
  visible_action: "可见动作",
  visual_focus: "画面焦点",
};

function normalizeMarkdownFieldKey(value: string): string {
  return value
    .trim()
    .replace(/^`+|`+$/g, "")
    .trim()
    .toLocaleLowerCase();
}

function shouldHumanizeUnknownField(value: string): boolean {
  return /^[a-z][a-z0-9_]*$/i.test(value) && value.includes("_");
}

function titleCaseAsciiField(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toLocaleUpperCase() + part.slice(1))
    .join(" ");
}

export function readableMarkdownTableFieldLabel(label: string): string {
  const key = normalizeMarkdownFieldKey(label);
  if (!key) return label;

  const mapped = MARKDOWN_TABLE_FIELD_LABELS[key];
  if (mapped) return mapped;

  return shouldHumanizeUnknownField(key) ? titleCaseAsciiField(key) : label;
}

import { useEffect, useMemo, useState } from "react";
import { Copy, Download, Loader2, Save, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  API,
  type ScriptSplittingTemplateInfo,
  type ScriptSplittingTemplateUpsertPayload,
} from "@/api";
import {
  ScriptSplittingTemplateSelector,
  defaultScriptSplittingTemplateId,
  scriptSplittingContentModeDescription,
  scriptSplittingContentModeLabel,
  scriptSplittingTemplateDisplayDescription,
  scriptSplittingTemplateDisplayName,
  scriptSplittingTemplateSupportedGenerationModes,
  scriptSplittingTemplateSupportsGenerationMode,
  type ScriptSplittingContentMode,
} from "@/components/shared/ScriptSplittingTemplateSelector";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { radioCardClass } from "@/components/ui/darkroom-tokens";
import { useAppStore } from "@/stores/app-store";
import { errMsg } from "@/utils/async";
import { copyText } from "@/utils/clipboard";
import {
  GENERATION_MODES,
  generationModeLabel,
  type GenerationMode,
} from "@/utils/generation-mode";

const TEXTAREA_CLS =
  "min-h-24 w-full resize-y rounded-[7px] border border-hairline-soft bg-bg-grad-a/45 px-2.5 py-2 text-[12.5px] leading-[1.5] text-text outline-none transition-colors hover:border-hairline focus:border-accent focus:ring-2 focus:ring-accent/30";
const SMALL_BTN_CLS =
  "inline-flex h-8 items-center gap-1.5 rounded-[7px] border border-hairline-soft bg-bg-grad-a/45 px-2.5 text-[11.5px] font-medium text-text-2 transition hover:border-accent/40 hover:text-text disabled:cursor-not-allowed disabled:opacity-45";
const AI_RULES_COPY_TIP =
  "复制一段给外部 AI 的说明：它会先向你提问，再按固定格式输出可粘贴回来的拆分方案文案。";
type TemplateCreationMode = "improve" | "new_style";

const UNIVERSAL_TEMPLATE_BY_MODE: Record<ScriptSplittingContentMode, string> = {
  narration: "narration_legacy_reading_default",
  drama: "drama_legacy_scene_default",
};
const GENERATION_MODE_TEXT_LABELS = [
  "支持分镜生成模式",
  "支持视频生成方式",
  "推荐分镜生成模式",
  "分镜生成模式",
  "推荐生成模式",
];
const CONTENT_MODE_TEXT_LABELS = ["内容模式", "支持内容模式", "content_mode"];

interface DraftState {
  id: string;
  base_template_id: string;
  derived_from_template_id: string;
  creation_mode: TemplateCreationMode;
  name: string;
  description: string;
  content_mode: ScriptSplittingContentMode;
  recommended_generation_modes: GenerationMode[];
  intent_brief: string;
  derivation_note: string;
  tone_preferences: string;
  extra_split_rules: string;
  extra_forbidden_patterns: string;
  example_source: string;
  example_expected_output: string;
}

function lines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function draftFromTemplate(
  template: ScriptSplittingTemplateInfo | undefined,
  creationMode: TemplateCreationMode = "improve",
): DraftState {
  const overlay = template?.user_overlay ?? {};
  const displayName = template ? scriptSplittingTemplateDisplayName(template) : "";
  const displayDescription = template ? scriptSplittingTemplateDisplayDescription(template) : "";
  return {
    id: "",
    base_template_id: template?.source === "builtin" ? template.id : template?.base_template_id ?? template?.id ?? "",
    derived_from_template_id: template?.id ?? "",
    creation_mode: creationMode,
    name: template?.source === "builtin" ? `${displayName} 自定义` : displayName,
    description: displayDescription,
    content_mode: template?.content_mode ?? "narration",
    recommended_generation_modes: scriptSplittingTemplateSupportedGenerationModes(template).length
      ? scriptSplittingTemplateSupportedGenerationModes(template)
      : ["storyboard"],
    intent_brief: overlay.intent_brief ?? "",
    derivation_note: overlay.derivation_note ?? "",
    tone_preferences: (overlay.tone_preferences ?? []).join("\n"),
    extra_split_rules: (overlay.extra_split_rules ?? []).join("\n"),
    extra_forbidden_patterns: (overlay.extra_forbidden_patterns ?? []).join("\n"),
    example_source: overlay.example_source ?? "",
    example_expected_output: overlay.example_expected_output ?? "",
  };
}

function payloadFromDraft(draft: DraftState): ScriptSplittingTemplateUpsertPayload {
  return {
    id: draft.id.trim() || null,
    base_template_id: draft.base_template_id,
    derived_from_template_id: draft.derived_from_template_id || null,
    creation_mode: draft.creation_mode,
    name: draft.name,
    description: draft.description,
    supported_generation_modes: draft.recommended_generation_modes,
    recommended_generation_modes: draft.recommended_generation_modes,
    intent_brief: draft.intent_brief,
    derivation_note: draft.derivation_note,
    tone_preferences: lines(draft.tone_preferences),
    extra_split_rules: lines(draft.extra_split_rules),
    extra_forbidden_patterns: lines(draft.extra_forbidden_patterns),
    example_source: draft.example_source,
    example_expected_output: draft.example_expected_output,
  };
}

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function baseTemplateIdFromTemplate(template: ScriptSplittingTemplateInfo | undefined): string {
  if (!template) return "";
  return template.source === "builtin" ? template.id : template.base_template_id ?? "";
}

function copySourceTemplateIdFromTemplate(template: ScriptSplittingTemplateInfo | undefined): string {
  return template?.id ?? "";
}

function stripListMarker(line: string): string {
  return line.replace(/^\s*(?:[-*•·]|\d+[.)、])\s*/, "").trim();
}

function normalizeSectionTitle(line: string): string {
  return line
    .trim()
    .replace(/^#{1,6}\s*/, "")
    .replace(/[：:]\s*$/, "")
    .trim();
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function inlineValue(text: string, labels: string[]): string {
  for (const label of labels) {
    const re = new RegExp(`^\\s*(?:[-*•·]\\s*)?${escapeRegExp(label)}\\s*[:：]\\s*(.+?)\\s*$`, "im");
    const match = text.match(re);
    if (match?.[1]?.trim()) {
      return stripListMarker(match[1]);
    }
  }
  return "";
}

function sectionValue(text: string, names: string[]): string {
  const sourceLines = text.replace(/\r\n/g, "\n").split("\n");
  const startIndex = sourceLines.findIndex((line) => names.includes(normalizeSectionTitle(line)));
  if (startIndex < 0) return "";
  const body: string[] = [];
  for (let i = startIndex + 1; i < sourceLines.length; i += 1) {
    const line = sourceLines[i] ?? "";
    if (/^\s*#{1,6}\s+\S/.test(line)) break;
    body.push(line);
  }
  return body.join("\n").trim();
}

function sectionLines(text: string, names: string[]): string {
  return lines(sectionValue(text, names)).map(stripListMarker).filter(Boolean).join("\n");
}

function firstText(text: string, labels: string[], sections: string[]): string {
  return inlineValue(text, labels) || sectionValue(text, sections);
}

function parseRecommendedGenerationModes(value: string, fallback: GenerationMode[]): GenerationMode[] {
  const normalized = value.toLowerCase();
  const modes: GenerationMode[] = [];
  const add = (mode: GenerationMode) => {
    if (!modes.includes(mode)) modes.push(mode);
  };
  if (/图生视频|分镜图|storyboard/.test(value) || normalized.includes("storyboard")) add("storyboard");
  if (/参考视频|reference[\s_-]?video/.test(value) || normalized.includes("reference_video")) add("reference_video");
  if (/宫格|九宫格|grid/.test(value) || normalized.includes("grid")) add("grid");
  return modes.length ? modes : fallback;
}

function parseContentMode(value: string, fallback: ScriptSplittingContentMode): ScriptSplittingContentMode {
  if (/剧情模式|剧集模式|短剧|drama/i.test(value)) return "drama";
  if (/旁白模式|说书|朗读|narration/i.test(value)) return "narration";
  return fallback;
}

function normalizeTemplateName(value: string): string {
  return value.replace(/\s+/g, " ").trim().toLocaleLowerCase();
}

function nextImprovedTemplateName(
  baseTemplate: ScriptSplittingTemplateInfo | undefined,
  templates: ScriptSplittingTemplateInfo[],
): string {
  const baseName = baseTemplate ? scriptSplittingTemplateDisplayName(baseTemplate) : "自定义拆分方案";
  const derivedFromId = baseTemplate?.id ?? "";
  const prefix = `${baseName} · 改进版`;
  const count = templates.filter((tpl) => (
    (derivedFromId && tpl.derived_from_template_id === derivedFromId)
    || scriptSplittingTemplateDisplayName(tpl).startsWith(prefix)
  )).length;
  return `${prefix} ${count + 1}`;
}

function ensureImprovementVersionName(
  parsedName: string,
  baseTemplate: ScriptSplittingTemplateInfo | undefined,
  templates: ScriptSplittingTemplateInfo[],
): string {
  const name = parsedName.trim();
  if (!name) return nextImprovedTemplateName(baseTemplate, templates);
  if (/改进版|版本|v\d+/i.test(name)) return name;
  const version = nextImprovedTemplateName(baseTemplate, templates).match(/改进版\s*(\d+)/)?.[1] ?? "1";
  return `${name} · 改进版 ${version}`;
}

function templateRuleSummary(template: ScriptSplittingTemplateInfo | undefined): string[] {
  if (!template) return ["- 当前没有可用基础模板，请先选择内容模式和视频生成方式。"];
  const rows: string[] = [
    `- 输出字段：${(template.output_fields ?? []).join(" / ") || "沿用基础契约字段"}`,
    `- 支持视频生成方式：${scriptSplittingTemplateSupportedGenerationModes(template).join(" / ") || "storyboard"}`,
  ];
  const splitRules = (template.split_rules ?? []).slice(0, 8);
  if (splitRules.length) {
    rows.push("- 基础拆分规则摘要：");
    rows.push(...splitRules.map((rule) => `  - ${rule}`));
  }
  const forbidden = (template.forbidden_patterns ?? []).slice(0, 6);
  if (forbidden.length) {
    rows.push("- 基础禁止写法摘要：");
    rows.push(...forbidden.map((rule) => `  - ${rule}`));
  }
  return rows;
}

function draftFromAiTemplateText(
  text: string,
  baseTemplate: ScriptSplittingTemplateInfo | undefined,
  fallbackBaseTemplateId: string,
  fallbackGenerationMode: GenerationMode,
  fallbackContentMode: ScriptSplittingContentMode,
  creationMode: TemplateCreationMode,
  templates: ScriptSplittingTemplateInfo[],
  derivationNote: string,
): DraftState {
  const baseDraft = draftFromTemplate(baseTemplate, creationMode);
  const recommendedText = firstText(
    text,
    GENERATION_MODE_TEXT_LABELS,
    GENERATION_MODE_TEXT_LABELS,
  );
  const contentModeText = firstText(text, CONTENT_MODE_TEXT_LABELS, CONTENT_MODE_TEXT_LABELS);
  const fallbackModes = baseDraft.recommended_generation_modes.length
    ? baseDraft.recommended_generation_modes
    : [fallbackGenerationMode];
  const parsedName = firstText(text, ["标题", "方案名称", "名称", "name"], ["标题", "方案名称"]);
  const parsedDescription = firstText(text, ["描述", "方案描述", "定位", "description"], ["描述", "方案描述", "定位"]);
  const parsedNote = firstText(text, ["改进备注", "修改备注", "备注", "derivation_note"], ["改进备注", "修改备注", "备注"]);
  const fallbackName = creationMode === "improve"
    ? nextImprovedTemplateName(baseTemplate, templates)
    : "";
  const fallbackDescription = creationMode === "improve" ? baseDraft.description : "";
  const finalNote = derivationNote.trim() || parsedNote;
  const finalDescription = parsedDescription || (
    finalNote ? `${fallbackDescription || "基于当前模板改进。"} 改进备注：${finalNote}` : fallbackDescription
  );

  return {
    ...baseDraft,
    id: inlineValue(text, ["模板ID", "方案ID", "id", "ID"]) || baseDraft.id,
    base_template_id: inlineValue(text, ["来源模板", "基础模板", "base_template_id"]) || baseDraft.base_template_id || fallbackBaseTemplateId,
    derived_from_template_id: baseTemplate?.id ?? "",
    creation_mode: creationMode,
    name: creationMode === "improve"
      ? ensureImprovementVersionName(parsedName || fallbackName, baseTemplate, templates)
      : parsedName,
    description: finalDescription,
    content_mode: parseContentMode(contentModeText, baseDraft.content_mode || fallbackContentMode),
    recommended_generation_modes: parseRecommendedGenerationModes(recommendedText, fallbackModes),
    intent_brief: firstText(text, ["方案目标", "创作意图", "目标", "intent_brief"], ["方案目标", "创作意图", "目标"]) || baseDraft.intent_brief,
    derivation_note: finalNote,
    tone_preferences: sectionLines(text, ["风格偏好", "节奏偏好", "语气偏好", "tone_preferences"]) || baseDraft.tone_preferences,
    extra_split_rules: sectionLines(text, ["拆分规则", "追加拆分规则", "规则", "extra_split_rules"]) || baseDraft.extra_split_rules,
    extra_forbidden_patterns: sectionLines(text, ["禁止写法", "禁用写法", "避免事项", "extra_forbidden_patterns"]) || baseDraft.extra_forbidden_patterns,
    example_source: sectionValue(text, ["示例输入", "示例原文", "example_source"]) || baseDraft.example_source,
    example_expected_output: sectionValue(text, ["示例输出", "期望拆分", "example_expected_output"]) || baseDraft.example_expected_output,
  };
}

function buildExternalAiTemplateRulesPrompt({
  contentModeLabelText,
  generationModeLabelText,
  baseTemplate,
  baseTemplateId,
  creationMode,
  derivationNote,
}: {
  contentModeLabelText: string;
  generationModeLabelText: string;
  baseTemplate: ScriptSplittingTemplateInfo | undefined;
  baseTemplateId: string;
  creationMode: TemplateCreationMode;
  derivationNote: string;
}): string {
  const baseName = baseTemplate ? scriptSplittingTemplateDisplayName(baseTemplate) : "当前基础拆分方案";
  const baseDescription = baseTemplate ? scriptSplittingTemplateDisplayDescription(baseTemplate) : "沿用当前基础拆分逻辑";
  const improveMode = creationMode === "improve";
  return [
    "你是短剧/小说视频拆分方案顾问。请帮我整理一个可粘贴到「满剧」项目设置里的拆分方案文案。",
    "",
    "工作方式：",
    "1. 不要一开始直接生成最终方案，先用提问的方式询问我的需求。",
    "2. 问题重点包括：作品类型、内容节奏、每段长度偏好、是否保留原文、是否需要强钩子、是否强调角色/场景/道具连续性、禁止出现的拆分方式。",
    "3. 当信息足够后，再输出最终文案。最终文案只用下面格式，不要输出 JSON，不要额外解释。",
    improveMode
      ? "4. 这是基于选中模板的改进版：请继承它的系统字段和可落地规则骨架，但用户的新题材、新风格和新镜头语言优先。"
      : "4. 这是全新风格模板：只继承系统格式和字段契约，不要继承某个预设模板的题材风格。",
    "",
    "当前基础信息：",
    `- 创建方式：${improveMode ? "基于选中模板改进" : "创建全新风格模板"}`,
    `- 内容模式：${contentModeLabelText}`,
    `- 当前视频生成方式：${generationModeLabelText}`,
    `- 来源模板：${baseTemplateId}`,
    `- 来源模板标题：${baseName}`,
    `- 来源模板描述：${baseDescription}`,
    derivationNote.trim() ? `- 用户改进备注：${derivationNote.trim()}` : "",
    "",
    "基础模板规则摘要：",
    ...templateRuleSummary(baseTemplate),
    "",
    "最终文案格式：",
    "# 拆分方案",
    "标题：给这个方案取一个清晰标题",
    "描述：一句话说明适合什么作品和生成目标",
    `内容模式：${contentModeLabelText}`,
    `创建方式：${improveMode ? "基于选中模板改进" : "创建全新风格模板"}`,
    `来源模板：${baseTemplateId}`,
    "支持视频生成方式：图生视频 / 参考视频 / 宫格分镜（从这三个中文名称中选择一个或多个，必须包含当前视频生成方式）",
    "改进备注：如果是基于现有模板改进，说明相对来源模板改了什么；全新风格模板可写“全新风格”。",
    "",
    "## 方案目标",
    "说明这个方案希望把内容拆成什么样的视频单元。",
    "",
    "## 风格偏好",
    "- 每行一条节奏、语气或画面偏好。",
    "",
    "## 拆分规则",
    "- 每行一条具体、可执行的拆分规则。",
    "",
    "## 禁止写法",
    "- 每行一条必须避免的拆分方式。",
    "",
    "## 示例输入",
    "放一小段原文或剧情描述。",
    "",
    "## 示例输出",
    "给出期望的拆分效果示例。",
  ].join("\n");
}

export function ScriptSplittingTemplatesSection() {
  const { t } = useTranslation("dashboard");
  const [templates, setTemplates] = useState<ScriptSplittingTemplateInfo[]>([]);
  const [contentMode, setContentMode] = useState<ScriptSplittingContentMode>("narration");
  const [generationMode, setGenerationMode] = useState<GenerationMode>("storyboard");
  const [templateId, setTemplateId] = useState("");
  const [creationMode, setCreationMode] = useState<TemplateCreationMode>("improve");
  const [derivationNote, setDerivationNote] = useState("");
  const [draft, setDraft] = useState<DraftState>(() => draftFromTemplate(undefined));
  const [aiTemplateText, setAiTemplateText] = useState("");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(
    () => templates.find((tpl) => (
      tpl.id === templateId
      && tpl.content_mode === contentMode
      && scriptSplittingTemplateSupportsGenerationMode(tpl, generationMode)
    )),
    [contentMode, generationMode, templateId, templates],
  );
  const builtinTemplates = useMemo(
    () => templates.filter((tpl) => (
      tpl.source === "builtin"
      && tpl.content_mode === contentMode
      && scriptSplittingTemplateSupportsGenerationMode(tpl, generationMode)
    )),
    [contentMode, generationMode, templates],
  );
  const fallbackBaseTemplateId = baseTemplateIdFromTemplate(selected)
    || builtinTemplates[0]?.id
    || defaultScriptSplittingTemplateId(contentMode, templates, generationMode);
  const universalBaseTemplateId = UNIVERSAL_TEMPLATE_BY_MODE[contentMode];
  const universalBaseTemplate = templates.find((tpl) => tpl.id === universalBaseTemplateId)
    ?? templates.find((tpl) => tpl.id === defaultScriptSplittingTemplateId(contentMode, templates, generationMode));
  const activeBaseTemplate = creationMode === "improve" ? selected : universalBaseTemplate;
  const activeBaseTemplateId = creationMode === "improve"
    ? (copySourceTemplateIdFromTemplate(selected) || fallbackBaseTemplateId)
    : (universalBaseTemplate?.id ?? fallbackBaseTemplateId);
  const canDelete = Boolean(selected && selected.source !== "builtin");
  const parsedSplitRuleCount = lines(draft.extra_split_rules).length;
  const parsedForbiddenCount = lines(draft.extra_forbidden_patterns).length;
  const aiDeclaredContentMode = aiTemplateText.trim()
    ? firstText(aiTemplateText, CONTENT_MODE_TEXT_LABELS, CONTENT_MODE_TEXT_LABELS)
    : "";
  const aiDeclaredGenerationModes = aiTemplateText.trim()
    ? firstText(aiTemplateText, GENERATION_MODE_TEXT_LABELS, GENERATION_MODE_TEXT_LABELS)
    : "";
  const duplicateTitle = useMemo(() => {
    const currentName = normalizeTemplateName(draft.name);
    if (!currentName) return false;
    return templates.some((tpl) => normalizeTemplateName(scriptSplittingTemplateDisplayName(tpl)) === currentName && tpl.id !== draft.id);
  }, [draft.id, draft.name, templates]);
  const draftModeMismatch = Boolean(
    aiTemplateText.trim()
    && !draft.recommended_generation_modes.includes(generationMode),
  );
  const draftContentModeMismatch = Boolean(
    aiTemplateText.trim()
    && draft.content_mode !== contentMode,
  );
  const missingDeclaredContentMode = Boolean(aiTemplateText.trim() && !aiDeclaredContentMode.trim());
  const missingDeclaredGenerationModes = Boolean(aiTemplateText.trim() && !aiDeclaredGenerationModes.trim());
  const canSaveAiDraft = Boolean(
    aiTemplateText.trim()
    && activeBaseTemplateId
    && draft.base_template_id
    && draft.name.trim()
    && draft.description.trim()
    && parsedSplitRuleCount > 0,
  )
    && !missingDeclaredContentMode
    && !missingDeclaredGenerationModes
    && !draftModeMismatch
    && !draftContentModeMismatch
    && !duplicateTitle;

  const pickTemplateId = (
    mode: ScriptSplittingContentMode,
    genMode: GenerationMode,
    nextTemplates = templates,
    preferredTemplateId = templateId,
  ) => (
    preferredTemplateId
    && nextTemplates.some((tpl) => (
      tpl.id === preferredTemplateId
      && tpl.content_mode === mode
      && scriptSplittingTemplateSupportsGenerationMode(tpl, genMode)
    ))
      ? preferredTemplateId
    : defaultScriptSplittingTemplateId(mode, nextTemplates, genMode)
  );

  const selectTemplate = (nextId: string, nextTemplates = templates) => {
    const nextTemplate = nextTemplates.find((tpl) => tpl.id === nextId);
    setTemplateId(nextId);
    setDraft(draftFromTemplate(nextTemplate, creationMode));
    setAiTemplateText("");
  };

  const refresh = async (
    nextMode = contentMode,
    preferredTemplateId = templateId,
    nextGenerationMode = generationMode,
  ) => {
    setLoading(true);
    try {
      const res = await API.getScriptSplittingTemplates();
      const nextId = pickTemplateId(nextMode, nextGenerationMode, res.templates, preferredTemplateId);
      setTemplates(res.templates);
      setTemplateId(nextId);
      const nextTemplate = res.templates.find((tpl) => tpl.id === nextId);
      setDraft(draftFromTemplate(nextTemplate, creationMode));
      setAiTemplateText("");
      setError(null);
    } catch (err: unknown) {
      setError(errMsg(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    void API.getScriptSplittingTemplates()
      .then((res) => {
        if (cancelled) return;
        const nextId = defaultScriptSplittingTemplateId("narration", res.templates, "storyboard");
        setTemplates(res.templates);
        setTemplateId(nextId);
        const nextTemplate = res.templates.find((tpl) => tpl.id === nextId);
        setDraft(draftFromTemplate(nextTemplate, creationMode));
        setAiTemplateText("");
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(errMsg(err));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const switchContentMode = (next: ScriptSplittingContentMode) => {
    setContentMode(next);
    selectTemplate(pickTemplateId(next, generationMode, templates, ""));
  };

  const switchGenerationMode = (next: GenerationMode) => {
    setGenerationMode(next);
    if (!scriptSplittingTemplateSupportsGenerationMode(selected, next)) {
      selectTemplate(pickTemplateId(contentMode, next, templates, ""));
    }
  };

  const switchCreationMode = (next: TemplateCreationMode) => {
    setCreationMode(next);
    setAiTemplateText("");
    const nextBase = next === "improve" ? selected : universalBaseTemplate;
    setDraft(draftFromTemplate(nextBase, next));
  };

  const updateDerivationNote = (value: string) => {
    setDerivationNote(value);
    if (aiTemplateText.trim()) {
      setDraft(draftFromAiTemplateText(
        aiTemplateText,
        activeBaseTemplate,
        activeBaseTemplateId,
        generationMode,
        contentMode,
        creationMode,
        templates,
        value,
      ));
    }
  };

  const handleAiTemplateTextChange = (value: string) => {
    setAiTemplateText(value);
    if (!value.trim()) {
      setDraft(draftFromTemplate(activeBaseTemplate, creationMode));
      return;
    }
    setDraft(draftFromAiTemplateText(
      value,
      activeBaseTemplate,
      activeBaseTemplateId,
      generationMode,
      contentMode,
      creationMode,
      templates,
      derivationNote,
    ));
  };

  const handleCopyAiRules = async () => {
    try {
      await copyText(buildExternalAiTemplateRulesPrompt({
        contentModeLabelText: scriptSplittingContentModeLabel(contentMode, t),
        generationModeLabelText: generationModeLabel(generationMode, t),
        baseTemplate: activeBaseTemplate,
        baseTemplateId: activeBaseTemplateId,
        creationMode,
        derivationNote,
      }));
      useAppStore.getState().pushToast(
        t("script_splitting_ai_rules_copied", { defaultValue: "AI 生成规则已复制" }),
        "success",
      );
    } catch (err: unknown) {
      useAppStore.getState().pushToast(errMsg(err), "error");
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const result = await API.saveScriptSplittingTemplate(payloadFromDraft({
        ...draft,
        base_template_id: activeBaseTemplateId,
        derived_from_template_id: creationMode === "improve" ? (activeBaseTemplate?.id ?? "") : "",
        creation_mode: creationMode,
        derivation_note: derivationNote.trim() || draft.derivation_note,
      }));
      useAppStore.getState().pushToast(
        t("script_splitting_template_saved", { defaultValue: "拆分方案已保存" }),
        "success",
      );
      setContentMode(result.template.content_mode);
      const nextGenerationMode = scriptSplittingTemplateSupportsGenerationMode(result.template, generationMode)
        ? generationMode
        : (scriptSplittingTemplateSupportedGenerationModes(result.template)[0] ?? generationMode);
      setGenerationMode(nextGenerationMode);
      await refresh(result.template.content_mode, result.template.id, nextGenerationMode);
    } catch (err: unknown) {
      useAppStore.getState().pushToast(errMsg(err), "error");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selected) return;
    setDeleting(true);
    try {
      await API.deleteScriptSplittingTemplate(selected.id);
      useAppStore.getState().pushToast(
        t("script_splitting_template_deleted", { defaultValue: "拆分方案已删除" }),
        "success",
      );
      setDeleteOpen(false);
      await refresh(contentMode);
    } catch (err: unknown) {
      useAppStore.getState().pushToast(errMsg(err), "error");
    } finally {
      setDeleting(false);
    }
  };

  const handleExport = async () => {
    if (!selected) return;
    try {
      const payload = await API.exportScriptSplittingTemplate(selected.id);
      downloadJson(`${selected.id}.script-splitting-template.json`, {
        schema: payload.schema,
        template: payload.template,
      });
    } catch (err: unknown) {
      useAppStore.getState().pushToast(errMsg(err), "error");
    }
  };

  return (
    <section className="space-y-5">
      <div>
        <div className="font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-accent-2">
          全局方案库
        </div>
        <h2 className="mt-1 text-[18px] font-semibold tracking-tight text-text">
          {t("script_splitting_template_section_title", { defaultValue: "拆分方案" })}
        </h2>
      </div>

      <div className="rounded-[12px] border border-hairline bg-bg-grad-a/35 p-4">
        <div className="mb-4 space-y-4">
          <div className="space-y-2 border-t border-hairline-soft pt-4">
            <div className="text-[12px] font-semibold text-text">
              {t("content_mode", { defaultValue: "内容模式" })}
            </div>
            <div className="flex flex-wrap gap-2.5" role="radiogroup" aria-label={t("content_mode", { defaultValue: "内容模式" })}>
              {(["narration", "drama"] as const).map((mode) => (
                <label key={mode} className={radioCardClass(contentMode === mode)}>
                  <input
                    type="radio"
                    name="scriptSplittingContentMode"
                    value={mode}
                    checked={contentMode === mode}
                    onChange={() => switchContentMode(mode)}
                    className="sr-only"
                  />
                  {scriptSplittingContentModeLabel(mode, t)}
                </label>
              ))}
            </div>
            <p className="text-[11.5px] leading-[1.45] text-text-4">
              {scriptSplittingContentModeDescription(contentMode, t)}
            </p>
          </div>
          <div className="space-y-2">
            <div className="text-[12px] font-semibold text-text">
              {t("generation_mode", { defaultValue: "分镜生成模式" })}
            </div>
            <div className="flex flex-wrap gap-2.5" role="radiogroup" aria-label={t("generation_mode", { defaultValue: "分镜生成模式" })}>
              {GENERATION_MODES.map((mode) => (
                <label key={mode} className={radioCardClass(generationMode === mode)}>
                  <input
                    type="radio"
                    name="scriptSplittingGenerationMode"
                    value={mode}
                    checked={generationMode === mode}
                    onChange={() => switchGenerationMode(mode)}
                    className="sr-only"
                  />
                  {generationModeLabel(mode, t)}
                </label>
              ))}
            </div>
            <p className="text-[11.5px] leading-[1.45] text-text-4">
              {t("script_splitting_generation_mode_filter_hint", {
                defaultValue: "这里用于筛选当前内容模式下支持该视频生成方式的拆分方案。",
              })}
            </p>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-6 text-text-3">
            <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin text-accent-2" aria-hidden />
            <span className="font-mono text-[11px] uppercase tracking-[0.14em]">loading</span>
          </div>
        ) : error ? (
          <p className="text-[12px] text-warm">{error}</p>
        ) : (
          <ScriptSplittingTemplateSelector
            value={templateId}
            contentMode={contentMode}
            generationMode={generationMode}
            templates={templates}
            onChange={selectTemplate}
            requireGenerationModeSupport
          />
        )}

        {selected && (
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="button" className={SMALL_BTN_CLS} onClick={() => void handleExport()}>
              <Download className="h-3.5 w-3.5" aria-hidden />
              {t("common:export", { defaultValue: "导出" })}
            </button>
            <button
              type="button"
              className={SMALL_BTN_CLS}
              onClick={() => setDeleteOpen(true)}
              disabled={!canDelete}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
              {t("common:delete", { defaultValue: "删除" })}
            </button>
          </div>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.55fr)]">
        <div className="rounded-[12px] border border-hairline bg-bg-grad-a/30 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-text-3">
                自定义拆分方案
              </div>
              <p className="mt-1 max-w-2xl text-[12px] leading-[1.55] text-text-3">
                先复制规则给外部 AI，让它通过提问整理你的需求；拿到最终文案后，粘贴到下面输入框即可自动识别并保存。
              </p>
            </div>
            <button
              type="button"
              className={SMALL_BTN_CLS}
              title={AI_RULES_COPY_TIP}
              aria-label={AI_RULES_COPY_TIP}
              onClick={() => void handleCopyAiRules()}
              disabled={!activeBaseTemplateId}
            >
              <Copy className="h-3.5 w-3.5" aria-hidden />
              {t("script_splitting_copy_ai_rules", { defaultValue: "复制 AI 生成规则" })}
            </button>
          </div>
          <div className="mt-4 space-y-3">
            <div>
              <div className="mb-2 text-[12px] font-semibold text-text">
                {t("script_splitting_creation_mode", { defaultValue: "创建方式" })}
              </div>
              <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label={t("script_splitting_creation_mode", { defaultValue: "创建方式" })}>
                <label className={radioCardClass(creationMode === "improve")}>
                  <input
                    type="radio"
                    name="scriptSplittingTemplateCreationMode"
                    value="improve"
                    checked={creationMode === "improve"}
                    onChange={() => switchCreationMode("improve")}
                    className="sr-only"
                  />
                  <span className="block text-[12.5px] font-semibold">
                    {t("script_splitting_improve_existing_template", { defaultValue: "基于选中模板改进" })}
                  </span>
                  <span className="mt-1 block text-[11px] leading-[1.4] text-text-4">
                    {t("script_splitting_improve_existing_desc", { defaultValue: "继承当前模板规则骨架，适合做升级版、变体或继续迭代。" })}
                  </span>
                </label>
                <label className={radioCardClass(creationMode === "new_style")}>
                  <input
                    type="radio"
                    name="scriptSplittingTemplateCreationMode"
                    value="new_style"
                    checked={creationMode === "new_style"}
                    onChange={() => switchCreationMode("new_style")}
                    className="sr-only"
                  />
                  <span className="block text-[12.5px] font-semibold">
                    {t("script_splitting_new_style_template", { defaultValue: "创建全新风格模板" })}
                  </span>
                  <span className="mt-1 block text-[11px] leading-[1.4] text-text-4">
                    {t("script_splitting_new_style_desc", { defaultValue: "只使用系统格式和字段契约，适合完全不同的新题材、新节奏。" })}
                  </span>
                </label>
              </div>
            </div>
            {creationMode === "improve" && (
              <div>
                <label className="mb-1.5 block text-[12px] font-semibold text-text">
                  {t("script_splitting_derivation_note", { defaultValue: "改进备注" })}
                </label>
                <textarea
                  value={derivationNote}
                  onChange={(event) => updateDerivationNote(event.target.value)}
                  placeholder="例如：更强前三秒钩子、减少背景铺垫、强调角色道具连续性。"
                  className={`${TEXTAREA_CLS} min-h-16`}
                />
              </div>
            )}
          </div>
          <p className="mt-2 text-[11.5px] leading-[1.45] text-text-4">
            {AI_RULES_COPY_TIP}
          </p>
          <textarea
            value={aiTemplateText}
            onChange={(event) => handleAiTemplateTextChange(event.target.value)}
            placeholder={[
              "把外部 AI 生成的最终文案粘贴到这里。",
              "建议包含：标题、描述、内容模式、来源模板、支持视频生成方式、方案目标、风格偏好、拆分规则、禁止写法、示例输入、示例输出。",
            ].join("\n")}
            className={`${TEXTAREA_CLS} mt-3 min-h-72 text-[12.5px]`}
          />
          {aiTemplateText.trim() ? (
            <div className="mt-3 rounded-[10px] border border-hairline-soft bg-bg-grad-b/30 p-3">
              <div className="text-[12.5px] font-semibold text-text">
                {draft.name || t("script_splitting_template_name_missing", { defaultValue: "未识别标题" })}
              </div>
              <p className="mt-1 text-[11.5px] leading-[1.45] text-text-4">
                {draft.description || t("script_splitting_template_desc_missing", { defaultValue: "未识别描述，保存前建议让外部 AI 补齐。" })}
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <span className="rounded-full border border-hairline-soft bg-bg-grad-a/45 px-2 py-0.5 text-[10.5px] text-text-3">
                  {creationMode === "improve"
                    ? t("script_splitting_improve_existing_template", { defaultValue: "基于选中模板改进" })
                    : t("script_splitting_new_style_template", { defaultValue: "创建全新风格模板" })}
                </span>
                <span className="rounded-full border border-hairline-soft bg-bg-grad-a/45 px-2 py-0.5 text-[10.5px] text-text-3">
                  {scriptSplittingContentModeLabel(draft.content_mode, t)}
                </span>
                {draft.recommended_generation_modes.map((mode) => (
                  <span
                    key={mode}
                    className="rounded-full border border-hairline-soft bg-bg-grad-a/45 px-2 py-0.5 text-[10.5px] text-text-3"
                  >
                    {generationModeLabel(mode, t)}
                  </span>
                ))}
                <span className="rounded-full border border-hairline-soft bg-bg-grad-a/45 px-2 py-0.5 text-[10.5px] text-text-3">
                  {t("script_splitting_rule_count", { defaultValue: "{{count}} 条拆分规则", count: parsedSplitRuleCount })}
                </span>
                <span className="rounded-full border border-hairline-soft bg-bg-grad-a/45 px-2 py-0.5 text-[10.5px] text-text-3">
                  {t("script_splitting_forbidden_count", { defaultValue: "{{count}} 条禁止写法", count: parsedForbiddenCount })}
                </span>
              </div>
              {duplicateTitle && (
                <p className="mt-2 text-[11.5px] leading-[1.45] text-warm">
                  {t("script_splitting_ai_duplicate_title", {
                    defaultValue: "已存在同名拆分方案，请让外部 AI 换一个标题后再保存。",
                  })}
                </p>
              )}
              {!draft.name.trim() && (
                <p className="mt-2 text-[11.5px] leading-[1.45] text-warm">
                  {t("script_splitting_ai_missing_title", { defaultValue: "没有识别到标题，保存前需要补齐标题。" })}
                </p>
              )}
              {!draft.description.trim() && (
                <p className="mt-2 text-[11.5px] leading-[1.45] text-warm">
                  {t("script_splitting_ai_missing_description", { defaultValue: "没有识别到描述，保存前需要补齐描述。" })}
                </p>
              )}
              {parsedSplitRuleCount === 0 && (
                <p className="mt-2 text-[11.5px] leading-[1.45] text-warm">
                  {t("script_splitting_ai_missing_rules", { defaultValue: "没有识别到拆分规则，请让外部 AI 按格式补充“拆分规则”。" })}
                </p>
              )}
              {missingDeclaredContentMode && (
                <p className="mt-2 text-[11.5px] leading-[1.45] text-warm">
                  {t("script_splitting_ai_missing_content_mode", {
                    defaultValue: "没有识别到“内容模式”，请让外部 AI 明确写出旁白模式或剧情模式后再保存。",
                  })}
                </p>
              )}
              {missingDeclaredGenerationModes && (
                <p className="mt-2 text-[11.5px] leading-[1.45] text-warm">
                  {t("script_splitting_ai_missing_generation_modes", {
                    defaultValue: "没有识别到“支持视频生成方式”，请让外部 AI 明确写出图生视频、参考视频或宫格分镜后再保存。",
                  })}
                </p>
              )}
              {parsedForbiddenCount === 0 && (
                <p className="mt-2 text-[11.5px] leading-[1.45] text-text-4">
                  {t("script_splitting_ai_missing_forbidden", { defaultValue: "建议补充“禁止写法”，方便后续生成更稳定。" })}
                </p>
              )}
              {(draftContentModeMismatch || draftModeMismatch) && (
                <p className="mt-2 text-[11.5px] leading-[1.45] text-warm">
                  {draftContentModeMismatch
                    ? t("script_splitting_ai_content_mode_mismatch", {
                        defaultValue: "粘贴内容识别出的内容模式和当前筛选不一致，请让外部 AI 修正后再保存。",
                      })
                    : t("script_splitting_ai_generation_mode_mismatch", {
                        defaultValue: "粘贴内容没有声明支持当前视频生成方式，请让外部 AI 补充后再保存。",
                      })}
                </p>
              )}
            </div>
          ) : (
            <p className="mt-3 text-[11.5px] leading-[1.45] text-text-4">
              {t("script_splitting_ai_paste_hint", {
                defaultValue: "当前没有粘贴文案。粘贴后会自动提取关键信息，不需要手动填写多个字段。",
              })}
            </p>
          )}
          <div className="mt-4 flex justify-end">
            <button
              type="button"
              className={SMALL_BTN_CLS}
              onClick={() => void handleSave()}
              disabled={saving || !canSaveAiDraft}
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin" aria-hidden /> : <Save className="h-3.5 w-3.5" aria-hidden />}
              {saving ? t("common:saving") : t("script_splitting_save_ai_template", { defaultValue: "保存为拆分方案" })}
            </button>
          </div>
        </div>

        {selected?.split_rules?.length ? (
          <div className="rounded-[12px] border border-hairline bg-bg-grad-a/30 p-4">
            <div className="mb-2 font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-text-3">
              当前方案规则
            </div>
            <div className="space-y-1.5">
              {selected.split_rules.slice(0, 8).map((rule) => (
                <p key={rule} className="text-[12.5px] leading-[1.5] text-text-2">
                  {rule}
                </p>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      <ConfirmDialog
        open={deleteOpen}
        title={t("script_splitting_delete_template", { defaultValue: "删除拆分方案" })}
        confirmLabel={t("common:delete", { defaultValue: "删除" })}
        loadingLabel={t("common:deleting", { defaultValue: "删除中" })}
        tone="danger"
        loading={deleting}
        onConfirm={handleDelete}
        onCancel={() => setDeleteOpen(false)}
      />
    </section>
  );
}

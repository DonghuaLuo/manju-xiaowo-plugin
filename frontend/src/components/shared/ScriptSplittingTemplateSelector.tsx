import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  CheckCircle2,
  Hash,
  Sparkles,
} from "lucide-react";
import {
  type ScriptSplittingProviderCompatibility,
  type ScriptSplittingTemplateInfo,
} from "@/api";
import { FieldLabel } from "@/components/ui/FieldLabel";
import { SelectMenu } from "@/components/ui/SelectMenu";
import {
  GENERATION_MODES,
  generationModeLabel,
  type GenerationMode,
} from "@/utils/generation-mode";

export type ScriptSplittingContentMode = "narration" | "drama";
type Translate = (key: string, options?: Record<string, unknown>) => string;

export function scriptSplittingContentModeLabel(mode: ScriptSplittingContentMode, t: Translate): string {
  return mode === "drama"
    ? t("drama_animation", { defaultValue: "剧情模式" })
    : t("narration_visuals", { defaultValue: "旁白模式" });
}

export function scriptSplittingContentModeDescription(mode: ScriptSplittingContentMode, t: Translate): string {
  return mode === "drama"
    ? t("content_mode_drama_desc", { defaultValue: "把小说改编为剧情场景，再生成分镜和视频。" })
    : t("content_mode_narration_desc", { defaultValue: "保留小说旁白原文，按朗读节奏拆成可视化片段。" });
}

const UNIVERSAL_TEMPLATE_BY_MODE: Record<ScriptSplittingContentMode, string> = {
  narration: "narration_legacy_reading_default",
  drama: "drama_legacy_scene_default",
};

export function scriptSplittingTemplateSupportedGenerationModes(
  template: ScriptSplittingTemplateInfo | undefined,
): GenerationMode[] {
  return (template?.supported_generation_modes?.length
    ? template.supported_generation_modes
    : template?.recommended_generation_modes) ?? [];
}

export function scriptSplittingTemplateSupportsGenerationMode(
  template: ScriptSplittingTemplateInfo | undefined,
  generationMode: GenerationMode,
): boolean {
  const supported = scriptSplittingTemplateSupportedGenerationModes(template);
  return supported.length === 0 || supported.includes(generationMode);
}

export function disabledGenerationModesForTemplate(
  template: ScriptSplittingTemplateInfo | undefined,
): GenerationMode[] {
  const supported = scriptSplittingTemplateSupportedGenerationModes(template);
  if (!supported.length) return [];
  return GENERATION_MODES.filter((mode) => !supported.includes(mode));
}

export function isUniversalScriptSplittingTemplate(template: ScriptSplittingTemplateInfo | undefined): boolean {
  return Boolean(template && UNIVERSAL_TEMPLATE_BY_MODE[template.content_mode] === template.id);
}

export function defaultScriptSplittingTemplateId(
  contentMode: ScriptSplittingContentMode,
  templates: ScriptSplittingTemplateInfo[],
  generationMode?: GenerationMode,
): string {
  const universalId = UNIVERSAL_TEMPLATE_BY_MODE[contentMode];
  const universal = templates.find((tpl) => tpl.id === universalId && tpl.content_mode === contentMode);
  if (universal && (!generationMode || scriptSplittingTemplateSupportsGenerationMode(universal, generationMode))) {
    return universal.id;
  }
  return templates.find((tpl) => (
    tpl.content_mode === contentMode
    && (!generationMode || scriptSplittingTemplateSupportsGenerationMode(tpl, generationMode))
  ))?.id ?? "";
}

export function firstRecommendedGenerationMode(
  template: ScriptSplittingTemplateInfo | undefined,
  fallback: GenerationMode,
): GenerationMode {
  const supported = scriptSplittingTemplateSupportedGenerationModes(template);
  if (template?.default_generation_mode && supported.includes(template.default_generation_mode)) {
    return template.default_generation_mode;
  }
  return supported[0] ?? fallback;
}

const BUILTIN_TEMPLATE_DISPLAY: Record<string, { name: string; description: string }> = {
  narration_legacy_reading_default: {
    name: "通用拆分方案",
    description: "兼容图生视频、参考视频和宫格分镜，按朗读节奏与自然段落拆成可生成片段。",
  },
  narration_storytelling_classic: {
    name: "经典说书节奏",
    description: "适合连载小说讲述：按一个清晰信息点一段来拆，画面跟着旁白稳步推进。",
  },
  narration_suspense_hook: {
    name: "悬疑钩子节奏",
    description: "适合悬疑、复仇和反转内容：开头更抓人，段尾保留追问，让观众愿意继续看。",
  },
  narration_cinematic_manga_drama: {
    name: "旁白漫剧镜头流",
    description: "适合说书、漫剧和轻剧情旁白：保留原文，同时把每段补成更明确的画面焦点和镜头衔接。",
  },
  drama_legacy_scene_default: {
    name: "通用拆分方案",
    description: "兼容图生视频、参考视频和宫格分镜，把剧情拆成清晰可生成的视觉场景。",
  },
  drama_web_short_hook: {
    name: "短剧爽点节奏",
    description: "适合爽文和短剧：强化冲突、反转、众人反应和爽点兑现，同时保留可剪辑的镜头衔接。",
  },
  drama_reference_continuity_lite: {
    name: "角色道具连续性",
    description: "适合需要人物、场景、道具前后保持一致的剧情视频：每个镜头会强调主体位置、关键道具和首帧画面。",
  },
  drama_cinematic_shot_flow: {
    name: "影视镜头流",
    description: "通用制作型预设：用建立镜头、动作镜头、反应镜头和插入镜头组织剧情，适合追求真人/动漫剧感。",
  },
  drama_suspense_clue_chain: {
    name: "悬疑线索推进",
    description: "适合悬疑、刑侦、复仇和反转：按异常信号、线索特写、人物反应和延迟揭示来拆镜。",
  },
  drama_xuanhuan_xianxia_spectacle: {
    name: "玄幻修仙奇观",
    description: "适合玄幻、修仙、异能和国风战斗：先锚定法器、阵法或环境影响，再拆成稳定动作段落。",
  },
  drama_apocalypse_survival_pressure: {
    name: "末世压迫逃生",
    description: "适合末世、生存、灾变和怪物压迫：强调威胁方向、资源状态、出口路线和逃生衔接。",
  },
  drama_folk_horror_ritual_dread: {
    name: "民俗鬼怪氛围",
    description: "适合民俗、怪谈、灵异和乡土恐怖：用禁忌物、仪式物、声音线索和延迟露出来制造压迫。",
  },
  drama_emotional_conflict_performance: {
    name: "情感冲突表演",
    description: "适合婚恋、家庭、虐恋、职场和关系修罗场：用视线、停顿、微表情和物件细节承接情绪。",
  },
  drama_reference_continuity: {
    name: "参考视频高一致性",
    description: "适合直接做参考视频：把连续动作合并成短视频单元，并明确角色、场景、道具参考，优先保证前后镜头一致。",
  },
};

export function scriptSplittingTemplateDisplayName(template: ScriptSplittingTemplateInfo): string {
  return BUILTIN_TEMPLATE_DISPLAY[template.id]?.name ?? template.name;
}

export function scriptSplittingTemplateDisplayDescription(template: ScriptSplittingTemplateInfo): string {
  return BUILTIN_TEMPLATE_DISPLAY[template.id]?.description ?? template.description ?? "";
}

function capabilityLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function compatibilityTone(status?: string): string {
  if (status === "ok") return "border-emerald-400/25 bg-emerald-400/10 text-emerald-200";
  if (status === "block") return "border-rose-400/30 bg-rose-400/10 text-rose-100";
  if (status === "warn") return "border-amber-400/25 bg-amber-400/10 text-amber-100";
  return "border-hairline-soft bg-bg-grad-a/45 text-text-3";
}

function providerStatusLabel(status: string, t: (key: string, options?: Record<string, unknown>) => string): string {
  if (status === "ok") return t("provider_status_ok", { defaultValue: "模型兼容" });
  if (status === "block") return t("provider_status_block", { defaultValue: "模型不兼容" });
  if (status === "warn") return t("provider_status_warn", { defaultValue: "模型需注意" });
  return t("provider_status_unknown", { defaultValue: "模型待检测" });
}

function ProviderCompatibilityBadge({
  compatibility,
}: {
  compatibility?: ScriptSplittingProviderCompatibility | null;
}) {
  const { t } = useTranslation("dashboard");
  if (!compatibility) return null;
  const status = compatibility.status ?? "unknown";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10.5px] ${compatibilityTone(status)}`}>
      {status === "ok" ? (
        <CheckCircle2 className="h-3 w-3" aria-hidden />
      ) : (
        <AlertTriangle className="h-3 w-3" aria-hidden />
      )}
      {providerStatusLabel(status, t)}
    </span>
  );
}

export interface ScriptSplittingTemplateSelectorProps {
  value: string | null | undefined;
  contentMode: ScriptSplittingContentMode;
  generationMode: GenerationMode;
  templates: ScriptSplittingTemplateInfo[];
  onChange: (templateId: string) => void;
  label?: string;
  disabled?: boolean;
  showHash?: boolean;
  variant?: "select" | "cards";
  requireGenerationModeSupport?: boolean;
}

export function ScriptSplittingTemplateSelector({
  value,
  contentMode,
  generationMode,
  templates,
  onChange,
  label,
  disabled,
  showHash = false,
  variant = "select",
  requireGenerationModeSupport = false,
}: ScriptSplittingTemplateSelectorProps) {
  const { t } = useTranslation("dashboard");
  const filtered = useMemo(
    () => templates.filter((tpl) => (
      tpl.content_mode === contentMode
      && (!requireGenerationModeSupport || scriptSplittingTemplateSupportsGenerationMode(tpl, generationMode))
    )),
    [contentMode, generationMode, requireGenerationModeSupport, templates],
  );
  const selectedId = value || defaultScriptSplittingTemplateId(
    contentMode,
    templates,
    requireGenerationModeSupport ? generationMode : undefined,
  );
  const selected = filtered.find((tpl) => tpl.id === selectedId) ?? filtered[0];
  const selectedValue = selected?.id ?? "";
  const selectedDescription = selected ? scriptSplittingTemplateDisplayDescription(selected) : "";
  const selectedSupportedModes = scriptSplittingTemplateSupportedGenerationModes(selected);
  const modeCompatible = scriptSplittingTemplateSupportsGenerationMode(selected, generationMode);

  return (
    <div className="space-y-2.5">
      <FieldLabel>
        {label ?? t("script_splitting_template_label", { defaultValue: "拆分方案模板" })}
      </FieldLabel>
      {variant === "cards" ? (
        <div
          className="grid gap-2"
          role="radiogroup"
          aria-label={label ?? t("script_splitting_template_label", { defaultValue: "拆分方案模板" })}
        >
          {filtered.map((tpl) => {
            const isSelected = tpl.id === selectedValue;
            const displayName = scriptSplittingTemplateDisplayName(tpl);
            const displayDescription = scriptSplittingTemplateDisplayDescription(tpl);
            const supportedModes = scriptSplittingTemplateSupportedGenerationModes(tpl);
            const cardModeCompatible = scriptSplittingTemplateSupportsGenerationMode(tpl, generationMode);
            return (
              <button
                key={tpl.id}
                type="button"
                role="radio"
                aria-checked={isSelected}
                disabled={disabled}
                onClick={() => onChange(tpl.id)}
                className={`w-full rounded-[10px] border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60 ${
                  isSelected
                    ? "border-accent/55 bg-accent-dim/70 text-text"
                    : "border-hairline-soft bg-bg-grad-a/35 text-text-2 hover:border-hairline hover:bg-bg-grad-a/55"
                }`}
              >
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-[13px] font-semibold text-text">{displayName}</span>
                      {isUniversalScriptSplittingTemplate(tpl) && (
                        <span className="rounded-full border border-accent/30 bg-accent-dim px-2 py-0.5 text-[10.5px] text-accent-2">
                          {t("script_splitting_universal_badge", { defaultValue: "通用" })}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-[12px] leading-[1.5] text-text-3">{displayDescription}</p>
                  </div>
                  {isSelected && <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-accent-2" aria-hidden />}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {supportedModes.map((mode) => (
                    <span
                      key={mode}
                      className={`rounded-full border px-2 py-0.5 text-[10.5px] ${
                        mode === generationMode
                          ? "border-accent/35 bg-accent-dim text-accent-2"
                          : "border-hairline-soft bg-bg-grad-a/45 text-text-4"
                      }`}
                    >
                      {generationModeLabel(mode, t)}
                    </span>
                  ))}
                  <ProviderCompatibilityBadge compatibility={tpl.provider_compatibility} />
                  {!cardModeCompatible && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-amber-400/25 bg-amber-400/10 px-2 py-0.5 text-[10.5px] text-amber-100">
                      <AlertTriangle className="h-3 w-3" aria-hidden />
                      {t("script_splitting_generation_mode_warning_short", { defaultValue: "不支持当前方式" })}
                    </span>
                  )}
                </div>
              </button>
            );
          })}
          {!filtered.length && (
            <p className="text-[11.5px] text-text-4">
              {t("script_splitting_templates_loading", { defaultValue: "模板加载中…" })}
            </p>
          )}
        </div>
      ) : (
        <SelectMenu
          value={selectedValue}
          disabled={disabled || filtered.length === 0}
          options={filtered.map((tpl) => ({
            value: tpl.id,
            label: scriptSplittingTemplateDisplayName(tpl),
            description: scriptSplittingTemplateDisplayDescription(tpl),
            hint: [
              isUniversalScriptSplittingTemplate(tpl)
                ? t("script_splitting_universal_badge", { defaultValue: "通用" })
                : null,
              scriptSplittingTemplateSupportedGenerationModes(tpl).map((mode) => generationModeLabel(mode, t)).join(" / "),
            ].filter(Boolean).join(" · "),
          }))}
          onChange={onChange}
          ariaLabel={label ?? t("script_splitting_template_label", { defaultValue: "拆分方案模板" })}
          panelLabel={scriptSplittingContentModeLabel(contentMode, t)}
          maxHeightClassName="max-h-80"
          triggerClassName="min-h-11"
          minPanelWidth={420}
        />
      )}
      {selected && variant !== "cards" ? (
        <div className="rounded-[10px] border border-hairline-soft bg-bg-grad-a/35 p-3">
          <div className="flex flex-wrap items-center gap-1.5">
            {selectedSupportedModes.map((mode) => (
              <span
                key={mode}
                className={`rounded-full border px-2 py-0.5 text-[10.5px] ${
                  mode === generationMode
                    ? "border-accent/35 bg-accent-dim text-accent-2"
                    : "border-hairline-soft bg-bg-grad-a/45 text-text-4"
                }`}
              >
                {generationModeLabel(mode, t)}
              </span>
            ))}
            <ProviderCompatibilityBadge compatibility={selected.provider_compatibility} />
          </div>
          <p className="mt-2 text-[12px] leading-[1.55] text-text-3">{selectedDescription}</p>
          {!modeCompatible && (
            <p className="mt-2 inline-flex items-center gap-1.5 text-[11.5px] leading-[1.45] text-warm">
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
              {t("script_splitting_generation_mode_warning", {
                defaultValue: "当前生成方式不在此方案支持范围内。",
              })}
            </p>
          )}
          <div className="mt-2 flex flex-wrap gap-1.5">
            {(selected.required_capabilities ?? []).map((cap) => (
              <span
                key={cap}
                className="inline-flex items-center gap-1 rounded-full border border-hairline-soft bg-bg-grad-a/45 px-2 py-0.5 text-[10.5px] text-text-3"
              >
                <Sparkles className="h-3 w-3 text-accent-2" aria-hidden />
                {capabilityLabel(cap)}
              </span>
            ))}
          </div>
          {showHash && selected.hash && (
            <div className="mt-2 inline-flex max-w-full items-center gap-1.5 rounded-full border border-hairline-soft bg-bg-grad-b/40 px-2 py-0.5 font-mono text-[10px] text-text-4">
              <Hash className="h-3 w-3 shrink-0" aria-hidden />
              <span className="truncate">{selected.hash.slice(0, 12)}</span>
            </div>
          )}
        </div>
      ) : variant !== "cards" ? (
        <p className="text-[11.5px] text-text-4">
          {t("script_splitting_templates_loading", { defaultValue: "模板加载中…" })}
        </p>
      ) : null}
    </div>
  );
}

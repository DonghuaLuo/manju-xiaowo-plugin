import { useParams, useLocation } from "wouter";
import { errMsg, voidCall, voidPromise } from "@/utils/async";
import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { BookmarkPlus, ChevronLeft, Loader2 } from "lucide-react";
import {
  API,
  type GenerationRoutePreviewItem,
  type GenerationRoutePreviewRequest,
  type ProviderRecommendation,
  type QualityStatsResponse,
  type ScriptSplittingTemplateInfo,
  type ScriptSplittingTemplatePreview,
  type StyleTemplateInfo,
  type VideoCapabilitiesResponse,
} from "@/api";
import { useAppStore } from "@/stores/app-store";
import { PROVIDER_NAMES } from "@/components/ui/ProviderIcon";
import {
  getProviderModels,
  getCustomProviderModels,
  lookupStoryboardVideoStartImageSupport,
  lookupVideoContinuitySupport,
  storyboardVideoStartImageSupportFromCapabilities,
  videoContinuitySupportFromCapabilities,
} from "@/utils/provider-models";
import { ModelConfigSection } from "@/components/shared/ModelConfigSection";
import { StylePicker, type StylePickerValue } from "@/components/shared/StylePicker";
import {
  ScriptSplittingTemplateSelector,
  defaultScriptSplittingTemplateId,
  scriptSplittingTemplateSupportsGenerationMode,
} from "@/components/shared/ScriptSplittingTemplateSelector";
import { SelectMenu } from "@/components/ui/SelectMenu";
import { DEFAULT_TEMPLATE_ID, type StyleTemplate } from "@/data/style-templates";
import type {
  CustomProviderInfo,
  GenerationProfiles,
  ImageGenerationProfile,
  ProviderInfo,
  ShotTier,
  ShotTierProfile,
  VideoContinuityPolicy,
  VideoGenerationProfile,
} from "@/types";
import { GenerationModeSelector } from "@/components/shared/GenerationModeSelector";
import { ACCENT_BTN_CLS, ACCENT_BUTTON_STYLE, GHOST_BTN_LG_CLS, radioCardClass } from "@/components/ui/darkroom-tokens";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useWarnUnsaved } from "@/hooks/useWarnUnsaved";
import { normalizeMode, type GenerationMode } from "@/utils/generation-mode";
import { VIDEO_CONTINUITY_POLICIES, normalizeVideoContinuityPolicy } from "@/utils/video-continuity";
import { getProjectDisplayName } from "@/utils/project-display";
import type { UploadFileInput } from "@/utils/desktop-file";
import {
  IMAGE_PROFILE_RESOLUTIONS,
  REFERENCE_IMAGE_POLICIES,
  SHOT_TIERS,
  VIDEO_PROFILE_RESOLUTIONS,
  createDefaultGenerationProfiles,
  createDefaultShotTierProfiles,
  generationProfilesSignature,
  normalizeGenerationProfiles,
  normalizeShotTierProfiles,
  shotTierProfilesSignature,
} from "@/utils/generation-profiles";

function deriveStyleValue(
  project: Record<string, unknown>,
  projectName: string,
  templates: StyleTemplate[],
  templatePrompts: Record<string, string>,
): StylePickerValue {
  const styleImage = project.style_image as string | undefined;
  const templateId = (project.style_template_id as string | undefined) ?? null;
  if (styleImage) {
    return {
      mode: "custom",
      templateId: null,
      activeCategory: "live",
      uploadedFile: null,
      uploadedPreview: API.getFileUrl(projectName, styleImage),
      stylePrompt: (project.style_description as string | undefined) ?? "",
    };
  }
  const effectiveId = templateId ?? DEFAULT_TEMPLATE_ID;
  const tpl = templates.find((x) => x.id === effectiveId);
  const existingStyle = typeof project.style === "string" ? project.style : "";
  return {
    mode: "template",
    templateId: effectiveId,
    activeCategory: tpl?.category ?? "live",
    uploadedFile: null,
    uploadedPreview: null,
    stylePrompt: existingStyle.trim() ? existingStyle : (templatePrompts[effectiveId] ?? ""),
  };
}

function findQualityGroup(
  stats: QualityStatsResponse | undefined,
  groupName: string,
) {
  return stats?.groups?.generation_quality?.find((item) => item.key === groupName);
}

function groupRoutePreviewIssues(
  routes: GenerationRoutePreviewItem[],
  unknownError: string,
  formatWarning: (
    route: GenerationRoutePreviewItem,
    warning: NonNullable<GenerationRoutePreviewItem["warnings"]>[number],
  ) => string,
): string[] {
  const issues: Array<{ index: number; text: string }> = [];
  const errorGroups = new Map<string, { index: number; labels: string[] }>();

  routes.forEach((route, index) => {
    if (!route.ok) {
      const error = route.error ?? unknownError;
      const label = route.label ?? route.task_kind;
      const existing = errorGroups.get(error);
      if (existing) {
        existing.labels.push(label);
      } else {
        errorGroups.set(error, { index, labels: [label] });
      }
      return;
    }
    (route.warnings ?? []).forEach((warning) => {
      issues.push({ index, text: formatWarning(route, warning) });
    });
  });

  for (const [error, group] of errorGroups) {
    issues.push({ index: group.index, text: `${group.labels.join("、")}: ${error}` });
  }

  return issues.sort((a, b) => a.index - b.index).map((issue) => issue.text);
}

function normalizeStyleTemplatePayload(templates: StyleTemplateInfo[]): {
  templates: StyleTemplate[];
  prompts: Record<string, string>;
} {
  return {
    prompts: Object.fromEntries(templates.map((tpl) => [tpl.id, tpl.prompt])),
    templates: templates.map((tpl) => ({
      id: tpl.id,
      category: tpl.category,
      thumbnailFile: tpl.thumbnail_file,
      thumbnailUrl: tpl.thumbnail_url ?? null,
      name: tpl.name ?? null,
      tagline: tpl.tagline ?? null,
    })),
  };
}

type SourceLanguage = "zh" | "en" | "vi";
type ImageProfileKey = "asset" | "storyboard_draft" | "storyboard_final" | "grid";
type VideoProfileKey = "video_draft" | "video_final" | "reference_video_draft" | "reference_video_final";

interface InitialProjectSettingsSnapshot {
  videoBackend: string;
  imageBackendT2I: string;
  imageBackendI2I: string;
  audioOverride: boolean | null;
  textScript: string;
  textOverview: string;
  textStyle: string;
  aspectRatio: string;
  generationMode: string;
  videoContinuityPolicy: VideoContinuityPolicy;
  defaultDuration: number | null;
  episodeTargetUnits: string;
  sourceLanguage: SourceLanguage;
  videoResolution: string | null;
  imageResolution: string | null;
  generationProfiles: string;
  shotTierProfiles: string;
}

const SOURCE_LANGUAGES: SourceLanguage[] = ["zh", "en", "vi"];
const DEFAULT_EPISODE_TARGET_UNITS = 1000;
const PROFILE_INPUT_CLS =
  "h-9 w-full rounded-[7px] border border-hairline-soft bg-bg-grad-a/45 px-2.5 text-[12.5px] text-text outline-none transition-colors hover:border-hairline focus:border-accent focus:ring-2 focus:ring-accent/30";

function routeLabel(route: GenerationRoutePreviewItem): string {
  return route.label ?? route.profile_key ?? route.task_kind;
}

function formatRouteWarning(
  t: (key: string, options?: Record<string, unknown>) => string,
  route: GenerationRoutePreviewItem,
  warning: { key: string; params?: Record<string, unknown> },
): string {
  const params = warning.params ?? {};
  const label = routeLabel(route);
  if (warning.key === "video_resolution_adjusted") {
    return t("generation_route_warning_video_resolution_adjusted", {
      defaultValue: "{{label}}：分辨率 {{requested}} 已调整为 {{resolved}}",
      label,
      requested: params.requested,
      resolved: params.resolved,
      supported: params.supported,
    });
  }
  if (warning.key === "video_duration_adjusted") {
    return t("generation_route_warning_video_duration_adjusted", {
      defaultValue: "{{label}}：时长 {{requested}}s 已调整为 {{resolved}}s",
      label,
      requested: params.requested,
      resolved: params.resolved,
      supported: params.supported,
    });
  }
  if (warning.key === "video_generate_audio_disabled") {
    return t("generation_route_warning_video_generate_audio_disabled", {
      defaultValue: "{{label}}：当前模型不支持音频，已关闭",
      label,
      provider: params.provider,
      model: params.model,
    });
  }
  if (warning.key === "video_service_tier_adjusted") {
    return t("generation_route_warning_video_service_tier_adjusted", {
      defaultValue: "{{label}}：服务档位 {{requested}} 已调整为 {{resolved}}",
      label,
      requested: params.requested,
      resolved: params.resolved,
      supported: params.supported,
    });
  }
  if (warning.key === "video_seed_ignored") {
    return t("generation_route_warning_video_seed_ignored", {
      defaultValue: "{{label}}：当前模型不支持 seed，已忽略",
      label,
      provider: params.provider,
      model: params.model,
    });
  }
  if (warning.key === "video_capabilities_unavailable") {
    return t("generation_route_warning_video_capabilities_unavailable", {
      defaultValue: "{{label}}：无法确认当前模型能力，请检查时长 / 分辨率 / 参考图配置",
      label,
      provider: params.provider,
      model: params.model,
      reason: params.reason,
    });
  }
  return `${label}: ${warning.key}`;
}

function normalizeSourceLanguage(value: unknown): SourceLanguage {
  return value === "en" || value === "vi" ? value : "zh";
}

function normalizeEpisodeTargetUnits(value: unknown): number {
  const numericValue = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numericValue) && numericValue > 0
    ? Math.floor(numericValue)
    : DEFAULT_EPISODE_TARGET_UNITS;
}

// ─── Section card primitive ─────────────────────────────────────────────────

interface SectionCardProps {
  kicker: string;
  title?: string;
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

function SectionCard({ kicker, title, description, children, footer }: SectionCardProps) {
  return (
    <section
      className="overflow-hidden rounded-[12px] border border-hairline"
      style={{
        background:
          "linear-gradient(180deg, oklch(0.20 0.012 270 / 0.55), oklch(0.16 0.010 265 / 0.55))",
        boxShadow:
          "inset 0 1px 0 oklch(1 0 0 / 0.03), 0 18px 40px -28px oklch(0 0 0 / 0.5)",
      }}
    >
      <header className="px-5 pt-4 pb-3 border-b border-hairline-soft">
        <div className="font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-accent-2">
          {kicker}
        </div>
        {title ? (
          <h2 className="mt-1 text-[15px] font-semibold tracking-tight text-text">{title}</h2>
        ) : null}
        {description ? (
          <p className="mt-1 text-[12px] leading-[1.55] text-text-3">{description}</p>
        ) : null}
      </header>
      <div className="px-5 py-4">{children}</div>
      {footer ? (
        <footer className="border-t border-hairline-soft bg-[oklch(0.16_0.010_265_/_0.5)] px-5 py-3">
          {footer}
        </footer>
      ) : null}
    </section>
  );
}

// ─── Component ───────────────────────────────────────────────────────────────

export function ProjectSettingsPage() {
  const { t } = useTranslation("dashboard");
  const params = useParams<{ projectName: string }>();
  const projectName = params.projectName || "";
  const [, navigate] = useLocation();

  const [options, setOptions] = useState<{
    video_backends: string[];
    image_backends: string[];
    text_backends: string[];
    provider_names?: Record<string, string>;
  } | null>(null);
  const [globalDefaults, setGlobalDefaults] = useState<{
    video: string;
    imageT2I: string;
    imageI2I: string;
    textScript: string;
    textOverview: string;
    textStyle: string;
  }>({ video: "", imageT2I: "", imageI2I: "", textScript: "", textOverview: "", textStyle: "" });

  const allProviderNames = useMemo(
    () => ({ ...PROVIDER_NAMES, ...(options?.provider_names ?? {}) }),
    [options],
  );

  // Project-level overrides (from project.json)
  // "" means "follow global default"
  const [videoBackend, setVideoBackend] = useState<string>("");
  const [imageBackendT2I, setImageBackendT2I] = useState<string>("");
  const [imageBackendI2I, setImageBackendI2I] = useState<string>("");
  const [audioOverride, setAudioOverride] = useState<boolean | null>(null);
  const [textScript, setTextScript] = useState<string>("");
  const [textOverview, setTextOverview] = useState<string>("");
  const [textStyle, setTextStyle] = useState<string>("");
  const [aspectRatio, setAspectRatio] = useState<string>("");
  const [contentMode, setContentMode] = useState<"narration" | "drama">("narration");
  const [generationMode, setGenerationMode] = useState<GenerationMode>("storyboard");
  const [videoContinuityPolicy, setVideoContinuityPolicy] = useState<VideoContinuityPolicy>("auto");
  const [defaultDuration, setDefaultDuration] = useState<number | null>(null);
  const [episodeTargetUnits, setEpisodeTargetUnits] = useState<string>(String(DEFAULT_EPISODE_TARGET_UNITS));
  const [sourceLanguage, setSourceLanguage] = useState<SourceLanguage>("zh");
  const [videoResolution, setVideoResolution] = useState<string | null>(null);
  const [imageResolution, setImageResolution] = useState<string | null>(null);
  const [modelSettings, setModelSettings] = useState<Record<string, { resolution: string | null }>>({});
  const [generationProfiles, setGenerationProfiles] = useState<GenerationProfiles>(
    () => createDefaultGenerationProfiles(),
  );
  const [shotTierProfiles, setShotTierProfiles] = useState<Record<ShotTier, ShotTierProfile>>(
    () => createDefaultShotTierProfiles(),
  );
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [customProviders, setCustomProviders] = useState<CustomProviderInfo[]>([]);
  const [videoCapabilities, setVideoCapabilities] = useState<VideoCapabilitiesResponse | null>(null);
  const [scriptSplittingTemplates, setScriptSplittingTemplates] = useState<ScriptSplittingTemplateInfo[]>([]);
  const [scriptSplittingTemplateId, setScriptSplittingTemplateId] = useState<string>("");
  const [initialScriptSplittingTemplateId, setInitialScriptSplittingTemplateId] = useState("");
  const [scriptSplittingPreview, setScriptSplittingPreview] = useState<ScriptSplittingTemplatePreview | null>(null);
  const [scriptSplittingPreviewLoading, setScriptSplittingPreviewLoading] = useState(false);
  const [changingScriptSplittingTemplate, setChangingScriptSplittingTemplate] = useState(false);
  const [projectTitle, setProjectTitle] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [routePreview, setRoutePreview] = useState<{
    loading: boolean;
    routes: GenerationRoutePreviewItem[];
    recommendations: ProviderRecommendation[];
    qualityStats?: QualityStatsResponse;
    error?: string;
  }>({ loading: false, routes: [], recommendations: [] });

  // ── Style picker state (independent save flow) ─────────────────────────────
  const [styleValue, setStyleValue] = useState<StylePickerValue | null>(null);
  const [savingStyle, setSavingStyle] = useState(false);
  const [savingFavoriteStyle, setSavingFavoriteStyle] = useState(false);
  const [analyzingStyle, setAnalyzingStyle] = useState(false);
  const [styleTemplates, setStyleTemplates] = useState<StyleTemplate[]>([]);
  const [styleTemplatePrompts, setStyleTemplatePrompts] = useState<Record<string, string>>({});
  const initialRef = useRef<InitialProjectSettingsSnapshot>({
    videoBackend: "", imageBackendT2I: "", imageBackendI2I: "", audioOverride: null,
    textScript: "", textOverview: "", textStyle: "",
    aspectRatio: "", generationMode: "storyboard",
    videoContinuityPolicy: "auto",
    defaultDuration: null,
    episodeTargetUnits: String(DEFAULT_EPISODE_TARGET_UNITS),
    sourceLanguage: "zh",
    videoResolution: null,
    imageResolution: null,
    generationProfiles: generationProfilesSignature(),
    shotTierProfiles: shotTierProfilesSignature(),
  });
  // 风格区独立保存，但"未保存就离开"也需被 isDirty 拦截。
  const initialStyleRef = useRef<StylePickerValue | null>(null);

  useEffect(() => {
    let disposed = false;

    voidCall(Promise.all([
      API.getSystemConfig(),
      API.getProject(projectName),
      API.getStyleTemplates().catch(() => ({ success: false, templates: [] as StyleTemplateInfo[] })),
      API.getScriptSplittingTemplates().catch(() => ({
        success: false,
        templates: [] as ScriptSplittingTemplateInfo[],
      })),
      getProviderModels().catch(() => [] as ProviderInfo[]),
      getCustomProviderModels().catch(() => [] as CustomProviderInfo[]),
      API.getVideoCapabilities(projectName).catch(() => null),
    ]).then(([
      configRes,
      projectRes,
      styleTemplatesRes,
      scriptTemplatesRes,
      providerList,
      customProviderList,
      videoCaps,
    ]) => {
      if (disposed) return;
      const { templates, prompts: templatePrompts } = normalizeStyleTemplatePayload(styleTemplatesRes.templates);
      setStyleTemplates(templates);
      setStyleTemplatePrompts(templatePrompts);
      setScriptSplittingTemplates(scriptTemplatesRes.templates);

      setOptions({
        video_backends: configRes.options?.video_backends ?? [],
        image_backends: configRes.options?.image_backends ?? [],
        text_backends: configRes.options?.text_backends ?? [],
        provider_names: configRes.options?.provider_names,
      });
      setGlobalDefaults({
        video: configRes.settings?.default_video_backend ?? "",
        imageT2I:
          configRes.settings?.default_image_backend_t2i ??
          configRes.settings?.default_image_backend ??
          "",
        imageI2I:
          configRes.settings?.default_image_backend_i2i ??
          configRes.settings?.default_image_backend ??
          "",
        textScript: configRes.settings?.text_backend_script ?? "",
        textOverview: configRes.settings?.text_backend_overview ?? "",
        textStyle: configRes.settings?.text_backend_style ?? "",
      });
      setProviders(providerList);
      setCustomProviders(customProviderList);
      setVideoCapabilities(videoCaps);

      const project = projectRes.project as unknown as Record<string, unknown>;
      const vb = (project.video_backend as string | undefined) ?? "";
      // Read T2I/I2I split fields; lazy-upgrade in project_manager populates both from legacy image_backend
      const ibt2i = (project.image_provider_t2i as string | undefined) ?? "";
      const ibi2i = (project.image_provider_i2i as string | undefined) ?? "";
      const rawAudio = project.video_generate_audio;
      const ao = typeof rawAudio === "boolean" ? rawAudio : null;
      const ts = (project.text_backend_script as string | undefined) ?? "";
      const to = (project.text_backend_overview as string | undefined) ?? "";
      const tst = (project.text_backend_style as string | undefined) ?? "";

      const rawAr = typeof project.aspect_ratio === "string" ? project.aspect_ratio : "";
      // Backend's get_aspect_ratio() falls back to "9:16" when unset (generation_tasks.py).
      // Mirror that here so the UI reflects the actually-effective ratio.
      const ar = rawAr || "9:16";
      const gm = normalizeMode(project.generation_mode);
      const contentMode = project.content_mode === "drama" ? "drama" : "narration";
      const rawScriptSplittingTemplateId =
        typeof project.script_splitting_template_id === "string" && project.script_splitting_template_id
          ? project.script_splitting_template_id
          : "";
      const rawScriptSplittingTemplate = scriptTemplatesRes.templates.find(
        (tpl) => tpl.id === rawScriptSplittingTemplateId,
      );
      const currentScriptSplittingTemplateId =
        rawScriptSplittingTemplateId
        && rawScriptSplittingTemplate?.content_mode === contentMode
        && scriptSplittingTemplateSupportsGenerationMode(rawScriptSplittingTemplate, gm)
          ? rawScriptSplittingTemplateId
          : defaultScriptSplittingTemplateId(
              contentMode,
              scriptTemplatesRes.templates,
              gm,
            );
      const vcp = normalizeVideoContinuityPolicy(project.video_continuity_policy);
      const dd = project.default_duration != null ? (project.default_duration as number) : null;
      const targetUnits = normalizeEpisodeTargetUnits(project.episode_target_units);
      const targetUnitsInput = String(targetUnits);
      const lang = normalizeSourceLanguage(project.source_language);

      setVideoBackend(vb);
      setImageBackendT2I(ibt2i);
      setImageBackendI2I(ibi2i);
      setAudioOverride(ao);
      setTextScript(ts);
      setTextOverview(to);
      setTextStyle(tst);
      setAspectRatio(ar);
      setContentMode(contentMode);
      setGenerationMode(gm);
      setScriptSplittingTemplateId(currentScriptSplittingTemplateId);
      setInitialScriptSplittingTemplateId(currentScriptSplittingTemplateId);
      setVideoContinuityPolicy(vcp);
      setDefaultDuration(dd);
      setEpisodeTargetUnits(targetUnitsInput);
      setSourceLanguage(lang);
      setProjectTitle(typeof project.title === "string" ? project.title : "");

      // model_settings 的 key 以 effective backend（override ‖ global default）读写，
      // 与 handleSave 保持一致；legacy video_model_settings 作为旧项目兼容回退。
      const defaultVideo = configRes.settings?.default_video_backend ?? "";
      const defaultImageT2I =
        configRes.settings?.default_image_backend_t2i ||
        configRes.settings?.default_image_backend ||
        "";
      const effectiveVb = vb || defaultVideo;
      const effectiveIb = ibt2i || defaultImageT2I; // T2I treated as canonical for resolution
      const ms = (project.model_settings ?? {}) as Record<string, { resolution: string | null }>;
      const legacyVideo = (project.video_model_settings ?? {}) as Record<string, { resolution?: string | null }>;
      const vModelId = effectiveVb && effectiveVb.includes("/") ? effectiveVb.split("/")[1] : effectiveVb;
      const vRes: string | null =
        (effectiveVb ? (ms[effectiveVb]?.resolution ?? null) : null) ||
        (vModelId ? (legacyVideo[vModelId]?.resolution ?? null) : null) ||
        null;
      const iRes = effectiveIb ? (ms[effectiveIb]?.resolution ?? null) : null;
      setVideoResolution(vRes);
      setImageResolution(iRes);
      setModelSettings(ms);
      const normalizedProfiles = normalizeGenerationProfiles(
        project.generation_profiles as GenerationProfiles | undefined,
        createDefaultGenerationProfiles({
          imageResolution: iRes,
          videoResolution: vRes,
        }),
      );
      setGenerationProfiles(normalizedProfiles);
      const normalizedShotTiers = normalizeShotTierProfiles(
        project.shot_tier_profiles as Partial<Record<ShotTier, ShotTierProfile>> | undefined,
      );
      setShotTierProfiles(normalizedShotTiers);

      const derivedStyle = deriveStyleValue(project, projectName, templates, templatePrompts);
      setStyleValue(derivedStyle);
      initialStyleRef.current = derivedStyle;
      initialRef.current = {
        videoBackend: vb, imageBackendT2I: ibt2i, imageBackendI2I: ibi2i, audioOverride: ao,
        textScript: ts, textOverview: to, textStyle: tst,
        aspectRatio: ar, generationMode: gm, videoContinuityPolicy: vcp, defaultDuration: dd,
        episodeTargetUnits: targetUnitsInput, sourceLanguage: lang,
        videoResolution: vRes, imageResolution: iRes,
        generationProfiles: generationProfilesSignature(normalizedProfiles),
        shotTierProfiles: shotTierProfilesSignature(normalizedShotTiers),
      };
    }));

    return () => { disposed = true; };
  }, [projectName]);

  // blob: URL 所有权集中：StylePicker 只通过 onChange 更换引用，
  // revoke 统一在此 effect 做（URL 变更或卸载时）。
  useEffect(() => {
    const url = styleValue?.uploadedPreview;
    if (!url?.startsWith("blob:")) return;
    return () => URL.revokeObjectURL(url);
  }, [styleValue?.uploadedPreview]);

  // initialRef / initialStyleRef 是加载时快照，用于 dirty-check。
  // react-hooks v7 的 react-hooks/refs 规则禁止 render 阶段读 ref，
  // 但本场景 ref 内容只在 fetch 完成时写一次，render 阶段读是稳定的。
  // 改 state 会导致 fetch effect 内 setState 触发 set-state-in-effect。
  /* eslint-disable react-hooks/refs */
  const styleIsDirty = (() => {
    const init = initialStyleRef.current;
    if (!styleValue || !init) return false;
    if (styleValue.mode !== init.mode) return true;
    if (styleValue.stylePrompt !== init.stylePrompt) return true;
    if (styleValue.mode === "template") return styleValue.templateId !== init.templateId;
    // custom 模式：新上传文件、或既有图被用户清空（preview 从 URL 变为 null）
    return styleValue.uploadedFile !== null || styleValue.uploadedPreview !== init.uploadedPreview;
  })();

  // "无风格"态：模版未选 + 未上传新文件 + 未保留旧预览
  const isStyleCleared = !!styleValue
    && styleValue.templateId === null
    && styleValue.uploadedFile === null
    && !styleValue.uploadedPreview
    && !styleValue.stylePrompt.trim();
  const hasInitialStyle = !!initialStyleRef.current
    && (initialStyleRef.current.templateId !== null
      || initialStyleRef.current.uploadedPreview !== null
      || !!initialStyleRef.current.stylePrompt.trim());
  const normalizedGenerationProfiles = normalizeGenerationProfiles(
    generationProfiles,
    createDefaultGenerationProfiles({
      imageResolution,
      videoResolution,
    }),
  );
  const normalizedShotTierProfiles = normalizeShotTierProfiles(shotTierProfiles);
  const normalizedGenerationProfilesSignature = generationProfilesSignature(normalizedGenerationProfiles);
  const normalizedShotTierProfilesSignature = shotTierProfilesSignature(normalizedShotTierProfiles);
  const scriptSplittingTemplateDirty =
    Boolean(scriptSplittingTemplateId)
    && scriptSplittingTemplateId !== initialScriptSplittingTemplateId;
  const videoProfileRows: Array<[VideoProfileKey, string]> = [
    ["video_draft", t("generation_profile_video_draft")],
    ["video_final", t("generation_profile_video_final")],
    ...(generationMode === "reference_video"
      ? ([
          ["reference_video_draft", t("generation_profile_reference_video_draft")],
          ["reference_video_final", t("generation_profile_reference_video_final")],
        ] as Array<[VideoProfileKey, string]>)
      : []),
  ];
  const routePreviewRequest = useMemo<GenerationRoutePreviewRequest>(() => {
    const profiles = normalizeGenerationProfiles(
      generationProfiles,
      createDefaultGenerationProfiles({
        imageResolution,
        videoResolution,
      }),
    );
    const tierProfiles = normalizeShotTierProfiles(shotTierProfiles);
    const routes: GenerationRoutePreviewRequest["routes"] = [
      { label: t("generation_profile_asset"), task_kind: "character", quality: "final", capability: "t2i" },
      { label: t("generation_profile_storyboard_draft"), task_kind: "storyboard", quality: "draft", capability: "t2i" },
      { label: t("generation_profile_storyboard_final"), task_kind: "storyboard", quality: "final", capability: "i2i" },
      { label: `${t("generation_profile_grid")} T2I`, task_kind: "grid", quality: "final", capability: "t2i" },
      { label: `${t("generation_profile_grid")} I2I`, task_kind: "grid", quality: "final", capability: "i2i" },
      { label: t("generation_profile_video_draft"), task_kind: "video", quality: "draft" },
      { label: t("generation_profile_video_final"), task_kind: "video", quality: "final" },
      ...SHOT_TIERS.map((tier) => ({
        label: `${tier} ${t("generation_profile_video_final")}`,
        task_kind: "video" as const,
        quality: "final" as const,
        payload: { shot_tier: tier },
      })),
    ];
    if (generationMode === "reference_video") {
      routes.push(
        { label: t("generation_profile_reference_video_draft"), task_kind: "reference_video", quality: "draft" },
        { label: t("generation_profile_reference_video_final"), task_kind: "reference_video", quality: "final" },
      );
    }
    return {
      project_overrides: {
        generation_profiles: profiles,
        shot_tier_profiles: tierProfiles,
        video_backend: videoBackend || null,
        image_provider_t2i: imageBackendT2I || null,
        image_provider_i2i: imageBackendI2I || null,
        video_generate_audio: audioOverride,
        video_continuity_policy: videoContinuityPolicy,
        default_duration: defaultDuration,
        model_settings: modelSettings,
      },
      routes,
    };
  }, [
    audioOverride,
    defaultDuration,
    generationProfiles,
    generationMode,
    imageBackendI2I,
    imageBackendT2I,
    imageResolution,
    modelSettings,
    shotTierProfiles,
    t,
    videoBackend,
    videoContinuityPolicy,
    videoResolution,
  ]);

  const isDirty =
    videoBackend !== initialRef.current.videoBackend ||
    imageBackendT2I !== initialRef.current.imageBackendT2I ||
    imageBackendI2I !== initialRef.current.imageBackendI2I ||
    audioOverride !== initialRef.current.audioOverride ||
    textScript !== initialRef.current.textScript ||
    textOverview !== initialRef.current.textOverview ||
    textStyle !== initialRef.current.textStyle ||
    aspectRatio !== initialRef.current.aspectRatio ||
    videoContinuityPolicy !== initialRef.current.videoContinuityPolicy ||
    defaultDuration !== initialRef.current.defaultDuration ||
    episodeTargetUnits !== initialRef.current.episodeTargetUnits ||
    sourceLanguage !== initialRef.current.sourceLanguage ||
    videoResolution !== initialRef.current.videoResolution ||
    imageResolution !== initialRef.current.imageResolution ||
    normalizedGenerationProfilesSignature !== initialRef.current.generationProfiles ||
    normalizedShotTierProfilesSignature !== initialRef.current.shotTierProfiles ||
    scriptSplittingTemplateDirty ||
    styleIsDirty;
  /* eslint-enable react-hooks/refs */

  useWarnUnsaved(isDirty);

  useEffect(() => {
    if (!options || !projectName) return;
    let disposed = false;
    const controller = new AbortController();

    const timer = window.setTimeout(() => {
      setRoutePreview((prev) => ({ ...prev, loading: true, error: undefined }));
      voidCall(Promise.all([
        API.previewGenerationRoutes(projectName, routePreviewRequest, { signal: controller.signal }),
        API.getProviderRecommendations({ projectName, callType: "video", minCalls: 1, limit: 3 })
          .catch(() => ({ recommendations: [] as ProviderRecommendation[], min_calls: 1 })),
        API.getQualityStats(projectName).catch(() => undefined),
      ]).then(([preview, recommendations, qualityStats]) => {
        if (disposed) return;
        setRoutePreview({
          loading: false,
          routes: preview.routes,
          recommendations: recommendations.recommendations,
          qualityStats,
        });
      }).catch((error: unknown) => {
        if (disposed || controller.signal.aborted) return;
        setRoutePreview({
          loading: false,
          routes: [],
          recommendations: [],
          qualityStats: undefined,
          error: errMsg(error),
        });
      }));
    }, 350);

    return () => {
      disposed = true;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [options, projectName, routePreviewRequest]);

  useEffect(() => {
    if (!projectName || !scriptSplittingTemplateId) return;
    if (!scriptSplittingTemplateDirty) {
      const timer = window.setTimeout(() => {
        setScriptSplittingPreview(null);
        setScriptSplittingPreviewLoading(false);
      }, 0);
      return () => window.clearTimeout(timer);
    }
    let disposed = false;
    const timer = window.setTimeout(() => {
      setScriptSplittingPreviewLoading(true);
      voidCall(API.previewScriptSplittingTemplateChange(projectName, scriptSplittingTemplateId)
        .then((res) => {
          if (disposed) return;
          setScriptSplittingPreview(res.preview);
        })
        .catch((error: unknown) => {
          if (disposed) return;
          setScriptSplittingPreview(null);
          useAppStore.getState().pushToast(
            t("script_splitting_preview_failed", {
              defaultValue: "拆分方案预览失败: {{message}}",
              message: errMsg(error),
            }),
            "error",
          );
        })
        .finally(() => {
          if (!disposed) setScriptSplittingPreviewLoading(false);
        }));
    }, 250);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
    };
  }, [projectName, scriptSplittingTemplateDirty, scriptSplittingTemplateId, t]);

  const routePreviewIssues = useMemo(() => groupRoutePreviewIssues(
    routePreview.routes,
    t("unknown_error", { defaultValue: "未知错误" }),
    (route, warning) => formatRouteWarning(t, route, warning),
  ), [routePreview.routes, t]);
  const finalQualityStats = findQualityGroup(routePreview.qualityStats, "final");
  const displayedQualityAverage =
    finalQualityStats?.average_rating ?? routePreview.qualityStats?.average_rating ?? null;
  const effectiveVideoBackendForContinuity = videoBackend || globalDefaults.video || "";
  const videoContinuitySupport = useMemo(() => {
    if (!effectiveVideoBackendForContinuity) return null;
    const capsBackend = videoCapabilities
      ? `${videoCapabilities.provider_id}/${videoCapabilities.model}`
      : "";
    const capsSupport = videoContinuitySupportFromCapabilities(videoCapabilities);
    if (capsSupport && capsBackend === effectiveVideoBackendForContinuity) {
      return capsSupport;
    }
    return lookupVideoContinuitySupport(effectiveVideoBackendForContinuity, customProviders);
  }, [customProviders, effectiveVideoBackendForContinuity, videoCapabilities]);
  const storyboardVideoStartImageUnsupported = useMemo(() => {
    if (generationMode === "reference_video" || !effectiveVideoBackendForContinuity) return false;
    const capsBackend = videoCapabilities
      ? `${videoCapabilities.provider_id}/${videoCapabilities.model}`
      : "";
    const capsStartImageSupport = storyboardVideoStartImageSupportFromCapabilities(videoCapabilities);
    if (capsStartImageSupport !== null && capsBackend === effectiveVideoBackendForContinuity) {
      return capsStartImageSupport === false;
    }
    return lookupStoryboardVideoStartImageSupport(effectiveVideoBackendForContinuity, customProviders) === false;
  }, [customProviders, effectiveVideoBackendForContinuity, generationMode, videoCapabilities]);
  const updateImageProfile = (
    key: ImageProfileKey,
    patch: Partial<ImageGenerationProfile>,
  ) => {
    setGenerationProfiles((prev) => {
      const base = normalizeGenerationProfiles(prev, normalizedGenerationProfiles);
      return {
        ...base,
        [key]: {
          ...base[key],
          ...patch,
        },
      };
    });
  };

  const updateVideoProfile = (
    key: VideoProfileKey,
    patch: Partial<VideoGenerationProfile>,
  ) => {
    setGenerationProfiles((prev) => {
      const base = normalizeGenerationProfiles(prev, normalizedGenerationProfiles);
      return {
        ...base,
        [key]: {
          ...base[key],
          ...patch,
        },
      };
    });
  };

  const updateShotTierProfile = (
    tier: ShotTier,
    patch: Partial<ShotTierProfile>,
  ) => {
    setShotTierProfiles((prev) => {
      const base = normalizeShotTierProfiles(prev);
      return {
        ...base,
        [tier]: {
          ...base[tier],
          ...patch,
          profiles: {
            ...(base[tier].profiles ?? {}),
            ...(patch.profiles ?? {}),
          },
        },
      };
    });
  };

  const updateShotTierOverride = (
    tier: ShotTier,
    key: "storyboard_final" | "video_final",
    patch: Partial<ImageGenerationProfile | VideoGenerationProfile>,
  ) => {
    setShotTierProfiles((prev) => {
      const base = normalizeShotTierProfiles(prev);
      const currentProfiles = base[tier].profiles ?? {};
      const currentProfile = currentProfiles[key] ?? {};
      return {
        ...base,
        [tier]: {
          ...base[tier],
          profiles: {
            ...currentProfiles,
            [key]: {
              ...currentProfile,
              ...patch,
            },
          },
        },
      };
    });
  };

  const [pendingNavigation, setPendingNavigation] = useState<string | null>(null);

  const guardedNavigate = useCallback((path: string) => {
    if (isDirty) {
      setPendingNavigation(path);
      return;
    }
    navigate(path);
  }, [isDirty, navigate, setPendingNavigation]);

  const confirmDiscardAndNavigate = useCallback(() => {
    if (!pendingNavigation) return;
    const target = pendingNavigation;
    setPendingNavigation(null);
    navigate(target);
  }, [pendingNavigation, navigate, setPendingNavigation]);

  // Cross-tab switch from custom → template may leave {mode:"template", templateId:null}
  // while an uploaded preview still lingers — no user-chosen card. Block save so
  // clicking it can't silently route to the "clear style" PATCH branch. The
  // explicit 清空风格 action zeroes uploadedFile/uploadedPreview too, bypassing this.
  const isStyleIncomplete =
    !!styleValue
    && styleValue.mode === "template"
    && !styleValue.templateId
    && (styleValue.uploadedFile !== null || !!styleValue.uploadedPreview);
  const isStyleSaveDisabled = savingStyle || savingFavoriteStyle || !styleIsDirty || isStyleIncomplete;
  const canFavoriteStyle = !!styleValue
    && styleValue.mode === "custom"
    && !savingStyle
    && !savingFavoriteStyle
    && !analyzingStyle
    && (styleValue.uploadedFile !== null || !!styleValue.uploadedPreview)
    && !!styleValue.stylePrompt.trim();

  const handleSaveStyle = useCallback(async () => {
    if (!styleValue) return;
    setSavingStyle(true);
    try {
      const stylePrompt = styleValue.stylePrompt.trim();
      if (styleValue.mode === "template" && styleValue.templateId) {
        await API.updateProject(projectName, {
          style_template_id: styleValue.templateId,
          ...(stylePrompt ? { style: stylePrompt } : {}),
        });
      } else if (styleValue.mode === "custom" && styleValue.uploadedFile) {
        await API.uploadStyleImage(projectName, styleValue.uploadedFile, {
          styleDescription: stylePrompt || undefined,
        });
      } else if (styleValue.mode === "custom" && styleValue.uploadedPreview) {
        await API.updateProject(projectName, {
          style_template_id: null,
          style_description: stylePrompt,
        });
      } else if (stylePrompt) {
        await API.updateProject(projectName, {
          style_template_id: null,
          clear_style_image: true,
          style: stylePrompt,
        });
      } else {
        // 清空风格：显式清掉模板 ID 与自定义图
        await API.updateProject(projectName, {
          style_template_id: null,
          clear_style_image: true,
        });
      }
      // Refetch project to reset styleValue from canonical server state
      const refreshed = await API.getProject(projectName);
      const nextStyle = deriveStyleValue(
        refreshed.project as unknown as Record<string, unknown>,
        projectName,
        styleTemplates,
        styleTemplatePrompts,
      );
      setStyleValue(nextStyle);
      initialStyleRef.current = nextStyle;
      useAppStore.getState().pushToast(t("saved"), "success");
    } catch (e: unknown) {
      useAppStore.getState().pushToast(t("save_failed", { message: errMsg(e) }), "error");
    } finally {
      setSavingStyle(false);
    }
  }, [styleValue, projectName, styleTemplates, styleTemplatePrompts, t]);

  const handleFavoriteStyle = useCallback(async () => {
    if (!styleValue || styleValue.mode !== "custom") return;
    const stylePrompt = styleValue.stylePrompt.trim();
    if (!stylePrompt || (!styleValue.uploadedFile && !styleValue.uploadedPreview)) {
      useAppStore.getState().pushToast(t("style_favorite_invalid"), "warning");
      return;
    }

    setSavingFavoriteStyle(true);
    try {
      if (styleValue.uploadedFile) {
        await API.uploadStyleImage(projectName, styleValue.uploadedFile, {
          styleDescription: stylePrompt,
        });
      } else {
        await API.updateProject(projectName, {
          style_template_id: null,
          style_description: stylePrompt,
        });
      }

      await API.createFavoriteStyleTemplate({
        stylePrompt,
        projectName,
        file: styleValue.uploadedFile,
      });

      const [templatesRes, refreshed] = await Promise.all([
        API.getStyleTemplates(),
        API.getProject(projectName),
      ]);
      const { templates, prompts } = normalizeStyleTemplatePayload(templatesRes.templates);
      setStyleTemplates(templates);
      setStyleTemplatePrompts(prompts);

      const nextStyle = deriveStyleValue(
        refreshed.project as unknown as Record<string, unknown>,
        projectName,
        templates,
        prompts,
      );
      setStyleValue(nextStyle);
      initialStyleRef.current = nextStyle;
      useAppStore.getState().pushToast(t("style_favorite_saved"), "success");
    } catch (e: unknown) {
      useAppStore.getState().pushToast(t("style_favorite_failed", { message: errMsg(e) }), "error");
    } finally {
      setSavingFavoriteStyle(false);
    }
  }, [projectName, styleValue, t]);

  const handleClearStyle = useCallback(() => {
    if (!styleValue) return;
    setStyleValue({
      ...styleValue,
      templateId: null,
      uploadedFile: null,
      uploadedPreview: null,
      stylePrompt: "",
    });
  }, [styleValue]);

  const handleAnalyzeCustomStyle = useCallback(async (file: UploadFileInput): Promise<string> => {
    setAnalyzingStyle(true);
    try {
      const result = await API.analyzeStyleImage(file);
      return result.style_description;
    } catch (e: unknown) {
      useAppStore.getState().pushToast(t("templates:analyze_style_failed", { message: errMsg(e) }), "error");
      return styleValue?.stylePrompt ?? "";
    } finally {
      setAnalyzingStyle(false);
    }
  }, [styleValue?.stylePrompt, t]);

  const handleScriptSplittingTemplateChange = useCallback((templateId: string) => {
    setScriptSplittingTemplateId(templateId);
  }, []);

  const handleApplyScriptSplittingTemplate = useCallback(async () => {
    if (!scriptSplittingTemplateId || !scriptSplittingTemplateDirty) {
      return;
    }
    setChangingScriptSplittingTemplate(true);
    try {
      const result = await API.changeScriptSplittingTemplate(
        projectName,
        scriptSplittingTemplateId,
        false,
        "apply_keep_drafts",
      );
      const nextId = result.project.script_splitting_template_id || scriptSplittingTemplateId;
      setScriptSplittingTemplateId(nextId);
      setInitialScriptSplittingTemplateId(nextId);
      setScriptSplittingPreview(null);
      const refreshedVideoCaps = await API.getVideoCapabilities(projectName).catch(() => null);
      setVideoCapabilities(refreshedVideoCaps);
      useAppStore.getState().pushToast(
        t("script_splitting_template_saved", { defaultValue: "拆分方案已应用" }),
        "success",
      );
    } catch (e: unknown) {
      useAppStore.getState().pushToast(
        t("script_splitting_template_save_failed", {
          defaultValue: "拆分方案应用失败: {{message}}",
          message: errMsg(e),
        }),
        "error",
      );
    } finally {
      setChangingScriptSplittingTemplate(false);
    }
  }, [projectName, scriptSplittingTemplateDirty, scriptSplittingTemplateId, t]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      let savedScriptSplittingTemplateId = initialScriptSplittingTemplateId;
      if (scriptSplittingTemplateDirty && scriptSplittingTemplateId) {
        const result = await API.changeScriptSplittingTemplate(
          projectName,
          scriptSplittingTemplateId,
          false,
          "apply_keep_drafts",
        );
        savedScriptSplittingTemplateId = result.project.script_splitting_template_id || scriptSplittingTemplateId;
        setScriptSplittingTemplateId(savedScriptSplittingTemplateId);
        setInitialScriptSplittingTemplateId(savedScriptSplittingTemplateId);
        setScriptSplittingPreview(null);
      }

      // resolution 的 key 用 effective backend（override ‖ global default），
      // 否则"跟随全局默认"路径下用户选的分辨率不会被写入。
      const effectiveVideo = videoBackend || globalDefaults.video || "";
      const effectiveImageT2I = imageBackendT2I || globalDefaults.imageT2I || "";
      const newModelSettings: Record<string, { resolution: string | null }> = { ...modelSettings };
      if (effectiveVideo) {
        newModelSettings[effectiveVideo] = { resolution: videoResolution };
      }
      if (effectiveImageT2I) {
        newModelSettings[effectiveImageT2I] = { resolution: imageResolution };
      }

      const normalizedEpisodeTargetUnits = normalizeEpisodeTargetUnits(episodeTargetUnits);
      const savedGenerationProfiles = normalizeGenerationProfiles(
        generationProfiles,
        createDefaultGenerationProfiles({
          imageResolution,
          videoResolution,
        }),
      );
      const savedShotTierProfiles = normalizeShotTierProfiles(shotTierProfiles);

      await API.updateProject(projectName, {
        video_backend: videoBackend || null,
        image_provider_t2i: imageBackendT2I || null,
        image_provider_i2i: imageBackendI2I || null,
        video_generate_audio: audioOverride,
        text_backend_script: textScript || null,
        text_backend_overview: textOverview || null,
        text_backend_style: textStyle || null,
        aspect_ratio: aspectRatio || undefined,
        video_continuity_policy: videoContinuityPolicy,
        default_duration: defaultDuration,
        episode_target_units: normalizedEpisodeTargetUnits,
        source_language: sourceLanguage,
        model_settings: newModelSettings,
        generation_profiles: savedGenerationProfiles,
        shot_tier_profiles: savedShotTierProfiles,
      });
      const savedEpisodeTargetUnits = String(normalizedEpisodeTargetUnits);
      const refreshedVideoCaps = await API.getVideoCapabilities(projectName).catch(() => null);
      setVideoCapabilities(refreshedVideoCaps);
      setEpisodeTargetUnits(savedEpisodeTargetUnits);
      setModelSettings(newModelSettings);
      setGenerationProfiles(savedGenerationProfiles);
      setShotTierProfiles(savedShotTierProfiles);
      initialRef.current = {
        videoBackend, imageBackendT2I, imageBackendI2I, audioOverride,
        textScript, textOverview, textStyle,
        aspectRatio, generationMode, videoContinuityPolicy, defaultDuration,
        episodeTargetUnits: savedEpisodeTargetUnits, sourceLanguage,
        videoResolution, imageResolution,
        generationProfiles: generationProfilesSignature(savedGenerationProfiles),
        shotTierProfiles: shotTierProfilesSignature(savedShotTierProfiles),
      };
      useAppStore.getState().pushToast(t("saved"), "success");
    } catch (e: unknown) {
      useAppStore.getState().pushToast(t("save_failed", { message: errMsg(e) }), "error");
    } finally {
      setSaving(false);
    }
  }, [modelSettings, initialScriptSplittingTemplateId, scriptSplittingTemplateDirty, scriptSplittingTemplateId, videoBackend, imageBackendT2I, imageBackendI2I, audioOverride, textScript, textOverview, textStyle, aspectRatio, generationMode, videoContinuityPolicy, defaultDuration, episodeTargetUnits, sourceLanguage, videoResolution, imageResolution, generationProfiles, shotTierProfiles, projectName, t, globalDefaults.video, globalDefaults.imageT2I]);

  return (
    <div
      className="relative flex h-full min-h-0 flex-col text-text"
      style={
        {
          background:
            "radial-gradient(900px 480px at 8% -10%, oklch(0.32 0.05 295 / 0.22), transparent 55%), radial-gradient(800px 460px at 100% 110%, oklch(0.26 0.04 260 / 0.22), transparent 55%), linear-gradient(180deg, var(--color-bg-grad-a), var(--color-bg-grad-b))",
        }
      }
    >
      {/* ─── Sticky top bar ─── */}
      <header
        className="sticky top-0 z-30 shrink-0"
        style={{
          background:
            "linear-gradient(180deg, oklch(0.20 0.011 265 / 0.55), oklch(0.15 0.010 265 / 0.45))",
          backdropFilter: "blur(28px) saturate(1.5)",
          WebkitBackdropFilter: "blur(28px) saturate(1.5)",
          borderBottom: "1px solid var(--color-hairline)",
          boxShadow:
            "inset 0 1px 0 oklch(1 0 0 / 0.05), 0 6px 24px -12px oklch(0 0 0 / 0.45)",
        }}
      >
        <div className="mx-auto flex w-full max-w-[980px] items-center gap-4 px-6 py-4">
          <button
            onClick={() => guardedNavigate(`/app/projects/${projectName}`)}
            className="inline-flex items-center gap-1.5 rounded-md border border-hairline-soft bg-bg-grad-a/45 px-2.5 py-1.5 text-[12px] text-text-3 transition-colors hover:border-hairline hover:bg-bg-grad-a hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            aria-label={t("back_to_project")}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            <span>{t("back_to_project")}</span>
          </button>
          <span aria-hidden className="h-5 w-px bg-hairline-soft" />
          <div className="min-w-0 flex-1">
            <div className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-accent-2">
              Project Booth — {projectName.toUpperCase()}
            </div>
            <h1
              className="font-editorial mt-0.5 truncate"
              style={{
                fontWeight: 400,
                fontSize: 24,
                lineHeight: 1.05,
                letterSpacing: "-0.012em",
                color: "var(--color-text)",
              }}
              title={getProjectDisplayName(projectTitle, t("untitled_project"))}
            >
              {t("common:settings")}
              <span className="ml-2 align-middle font-mono text-[11.5px] font-medium uppercase tracking-[0.08em] text-text-3">
                {t("project_settings")} · {getProjectDisplayName(projectTitle, t("untitled_project"))}
              </span>
            </h1>
          </div>
        </div>
      </header>

      {/* ─── Scrollable body ─── */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[980px] space-y-5 px-6 py-7 pb-24">
          <div>
            <div className="font-mono text-[9.5px] font-bold uppercase tracking-[0.16em] text-text-3">
              {t("model_config")}
            </div>
            <p className="mt-1 text-[12.5px] leading-[1.55] text-text-3">
              {t("model_config_project_desc")}
            </p>
          </div>

          {/* Style picker (independent save flow, mutually exclusive template / custom) */}
          {styleValue && (
            <SectionCard
              kicker="Visual Style"
              title={t("project_style_section_title")}
              footer={
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    // handleSaveStyle 在 onClick 时才执行，ref 写入是合法的；规则误报。
                    // eslint-disable-next-line react-hooks/refs
                    onClick={voidPromise(handleSaveStyle)}
                    disabled={isStyleSaveDisabled}
                    className={ACCENT_BTN_CLS}
                    style={ACCENT_BUTTON_STYLE}
                  >
                    {savingStyle && (
                      <Loader2 aria-hidden className="h-3.5 w-3.5 motion-safe:animate-spin" />
                    )}
                    {savingStyle ? t("style_saving") : t("style_save")}
                  </button>
                  {styleValue.mode === "custom" && (
                    <button
                      type="button"
                      // handleFavoriteStyle 在 onClick 时才执行，ref 写入是合法的；规则误报。
                      // eslint-disable-next-line react-hooks/refs
                      onClick={voidPromise(handleFavoriteStyle)}
                      disabled={!canFavoriteStyle}
                      title={!canFavoriteStyle ? t("style_favorite_invalid") : undefined}
                      className="inline-flex items-center gap-1.5 rounded-[7px] border border-hairline-soft bg-bg-grad-a/55 px-2.5 py-1.5 text-[12px] font-medium text-text-2 transition-colors hover:border-accent/45 hover:bg-accent-dim hover:text-accent-2 disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    >
                      {savingFavoriteStyle ? (
                        <Loader2 aria-hidden className="h-3.5 w-3.5 motion-safe:animate-spin" />
                      ) : (
                        <BookmarkPlus aria-hidden className="h-3.5 w-3.5" />
                      )}
                      {savingFavoriteStyle ? t("style_favoriting") : t("style_favorite")}
                    </button>
                  )}
                  {hasInitialStyle && !isStyleCleared && !savingStyle && !savingFavoriteStyle && (
                    <button
                      type="button"
                      onClick={handleClearStyle}
                      className="rounded-[7px] px-2.5 py-1.5 text-[12px] text-text-3 transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                    >
                      {t("style_clear")}
                    </button>
                  )}
                  {isStyleCleared && !savingStyle && !savingFavoriteStyle && styleIsDirty && (
                    <p className="text-[11.5px] text-text-3">{t("style_cleared_hint")}</p>
                  )}
                </div>
              }
            >
              <StylePicker
                value={styleValue}
                onChange={setStyleValue}
                templates={styleTemplates}
                templatePrompts={styleTemplatePrompts}
                onAnalyzeCustomStyle={handleAnalyzeCustomStyle}
                analyzingCustomStyle={analyzingStyle}
              />
            </SectionCard>
          )}

          {scriptSplittingTemplates.length > 0 && (
            <SectionCard
              kicker="Script Split"
              title={t("script_splitting_template_section_title", {
                defaultValue: "拆分方案",
              })}
              footer={
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={voidPromise(handleApplyScriptSplittingTemplate)}
                    disabled={
                      changingScriptSplittingTemplate
                      || scriptSplittingPreviewLoading
                      || !scriptSplittingTemplateDirty
                    }
                    className={ACCENT_BTN_CLS}
                    style={ACCENT_BUTTON_STYLE}
                  >
                    {changingScriptSplittingTemplate && (
                      <Loader2 aria-hidden className="h-3.5 w-3.5 motion-safe:animate-spin" />
                    )}
                    {changingScriptSplittingTemplate
                      ? t("common:saving")
                      : t("script_splitting_apply_template", { defaultValue: "应用拆分方案" })}
                  </button>
                  {scriptSplittingPreviewLoading && (
                    <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-text-4">
                      <Loader2 aria-hidden className="h-3.5 w-3.5 motion-safe:animate-spin" />
                      preview
                    </span>
                  )}
                  {scriptSplittingPreview && scriptSplittingTemplateDirty && (
                    <span className="text-[11.5px] leading-[1.45] text-text-3">
                      {t("script_splitting_preview_future_only_summary", {
                        defaultValue: "仅影响之后未生成的分集；已生成内容保持不变。",
                      })}
                    </span>
                  )}
                </div>
              }
            >
              <ScriptSplittingTemplateSelector
                value={scriptSplittingTemplateId}
                contentMode={contentMode}
                generationMode={generationMode}
                templates={scriptSplittingTemplates}
                onChange={handleScriptSplittingTemplateChange}
                requireGenerationModeSupport
              />
              {scriptSplittingPreview && scriptSplittingTemplateDirty && (
                <div className="mt-3 space-y-1.5 rounded-[10px] border border-white/10 bg-white/[0.035] p-3 text-[12px] leading-[1.55] text-text-3">
                  <p>
                    {t("script_splitting_future_only_detail", {
                      defaultValue: "新方案会作为之后分集的拆分规则；已有 Step 1、JSON 剧本、分镜图、视频和剪映草稿都不会被标记重建。",
                    })}
                  </p>
                  {(scriptSplittingPreview.preserved_existing_asset_count ?? 0) > 0 ? (
                    <p>
                      {t("script_splitting_preserved_existing_count", {
                        defaultValue: "已检测到 {{count}} 项历史产物，将继续保留。",
                        count: scriptSplittingPreview.preserved_existing_asset_count,
                      })}
                    </p>
                  ) : null}
                </div>
              )}
              {videoCapabilities?.provider_compatibility?.warnings?.length ? (
                <div className="mt-3 rounded-[10px] border border-amber-400/25 bg-amber-400/10 p-3">
                  {videoCapabilities.provider_compatibility.warnings.map((warning) => (
                    <p key={warning} className="text-[12px] leading-[1.5] text-amber-100">
                      {warning}
                    </p>
                  ))}
                </div>
              ) : null}
            </SectionCard>
          )}

          {options && (
            <>
              {/* Model config (video + duration + image + text) */}
              <SectionCard kicker="Engine Routing" title={t("model_config")}>
                <ModelConfigSection
                  value={{
                    videoBackend,
                    imageBackendT2I,
                    imageBackendI2I,
                    textBackendScript: textScript,
                    textBackendOverview: textOverview,
                    textBackendStyle: textStyle,
                    defaultDuration,
                    videoResolution,
                    imageResolution,
                  }}
                  onChange={(next) => {
                    setVideoBackend(next.videoBackend);
                    setImageBackendT2I(next.imageBackendT2I);
                    setImageBackendI2I(next.imageBackendI2I);
                    setTextScript(next.textBackendScript);
                    setTextOverview(next.textBackendOverview);
                    setTextStyle(next.textBackendStyle);
                    setDefaultDuration(next.defaultDuration);
                    setVideoResolution(next.videoResolution);
                    setImageResolution(next.imageResolution);
                  }}
                  providers={providers}
                  customProviders={customProviders}
                  options={{
                    videoBackends: options.video_backends,
                    imageBackends: options.image_backends,
                    textBackends: options.text_backends,
                    providerNames: allProviderNames,
                  }}
                  globalDefaults={{
                    video: globalDefaults.video,
                    imageT2I: globalDefaults.imageT2I ?? "",
                    imageI2I: globalDefaults.imageI2I ?? "",
                    textScript: globalDefaults.textScript ?? "",
                    textOverview: globalDefaults.textOverview ?? "",
                    textStyle: globalDefaults.textStyle ?? "",
                  }}
                  videoContinuitySupport={videoContinuitySupport}
                  storyboardVideoStartImageUnsupported={storyboardVideoStartImageUnsupported}
                />
                <div className="mt-4 rounded-[10px] border border-hairline-soft bg-bg-grad-a/35 p-3">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <div>
                      <div className="text-[13px] font-semibold text-text">
                        {t("video_continuity_policy_label")}
                      </div>
                      <div className="mt-1 text-[11.5px] leading-[1.45] text-text-4">
                        {t(`video_continuity_policy_${videoContinuityPolicy}_hint`)}
                      </div>
                    </div>
                    <div className="w-44 shrink-0">
                      <SelectMenu
                        value={videoContinuityPolicy}
                        options={VIDEO_CONTINUITY_POLICIES.map((policy) => ({
                          value: policy,
                          label: t(`video_continuity_policy_${policy}`),
                        }))}
                        onChange={(next) => setVideoContinuityPolicy(normalizeVideoContinuityPolicy(next))}
                        ariaLabel={t("video_continuity_policy_label")}
                        panelLabel={t("video_continuity_policy_label")}
                      />
                    </div>
                  </div>
                </div>
              </SectionCard>

              <SectionCard
                kicker="Quality Strategy"
                title={t("generation_profiles_section_title")}
                description={t("generation_profiles_section_desc")}
              >
                <div className="space-y-4">
                  <div className="rounded-[10px] border border-hairline-soft bg-bg-grad-b/35 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-text-3">
                        {t("generation_route_preview_label", { defaultValue: "Route Check" })}
                      </span>
                      {routePreview.loading && (
                        <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin text-accent-2" aria-hidden />
                      )}
                      {!routePreview.loading && !routePreview.error && routePreviewIssues.length === 0 && (
                        <span className="rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2 py-0.5 text-[11px] text-emerald-200">
                          {t("generation_route_preview_ok", { defaultValue: "当前策略可用" })}
                        </span>
                      )}
                    </div>
                    {routePreview.error && (
                      <div className="mt-2 text-[12px] text-rose-200">
                        {routePreview.error}
                      </div>
                    )}
                    {routePreviewIssues.length > 0 && (
                      <div className="mt-2 space-y-1">
                        {routePreviewIssues.slice(0, 5).map((issue) => (
                          <div key={issue} className="text-[12px] text-amber-100">
                            {issue}
                          </div>
                        ))}
                      </div>
                    )}
                    {routePreview.recommendations.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {routePreview.recommendations.map((item) => (
                          <button
                            type="button"
                            key={`${item.provider}/${item.model}/${item.call_type}`}
                            onClick={() => setVideoBackend(`${item.provider}/${item.model}`)}
                            className="max-w-full truncate rounded-full border border-hairline-soft bg-bg-grad-a/45 px-2 py-0.5 text-[10px] text-text-3 transition-colors hover:border-accent/45 hover:text-accent-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                            title={`${item.provider}/${item.model}`}
                          >
                            {item.provider}/{item.model} · {Math.round(item.success_rate * 100)}%
                          </button>
                        ))}
                      </div>
                    )}
                    {routePreview.qualityStats && routePreview.qualityStats.count > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <span className="rounded-full border border-hairline-soft bg-bg-grad-a/45 px-2 py-0.5 text-[10px] text-text-3">
                          {finalQualityStats
                            ? t("quality_stats_final_average", {
                                defaultValue: "精修版平均 {{score}}",
                                score: displayedQualityAverage?.toFixed(1) ?? "-",
                              })
                            : t("quality_stats_average", {
                                defaultValue: "平均 {{score}}",
                                score: displayedQualityAverage?.toFixed(1) ?? "-",
                              })}
                        </span>
                        <span className="rounded-full border border-hairline-soft bg-bg-grad-a/45 px-2 py-0.5 text-[10px] text-text-4">
                          {t("quality_stats_sample_count", {
                            defaultValue: "全版本 {{count}} 条",
                            count: routePreview.qualityStats.count,
                          })}
                        </span>
                        {(routePreview.qualityStats.dimension_averages ?? []).slice(0, 4).map((item) => (
                          <span
                            key={item.key}
                            className="rounded-full border border-hairline-soft bg-bg-grad-a/45 px-2 py-0.5 text-[10px] text-text-3"
                          >
                            {t("quality_stats_dimension_average", {
                              defaultValue: "全版本 {{key}} {{score}}",
                              key: item.key,
                              score: item.average_rating?.toFixed(1) ?? "-",
                            })}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="space-y-2">
                    {SHOT_TIERS.map((tier) => {
                      const tierProfile = normalizedShotTierProfiles[tier];
                      const storyboardOverride = (tierProfile.profiles?.storyboard_final ?? {}) as ImageGenerationProfile;
                      const videoOverride = (tierProfile.profiles?.video_final ?? {}) as VideoGenerationProfile;
                      const tierVideoStartImageUnsupported = Boolean(
                        generationMode !== "reference_video" &&
                          videoOverride.video_backend &&
                          lookupStoryboardVideoStartImageSupport(videoOverride.video_backend, customProviders) === false,
                      );
                      return (
                        <div
                          key={tier}
                          className="rounded-[10px] border border-hairline-soft bg-bg-grad-a/30 p-3"
                        >
                          <div className="mb-3 flex items-center gap-2">
                            <span className="num inline-flex h-6 min-w-6 items-center justify-center rounded-md bg-accent-soft px-2 text-[12px] font-bold text-bg-grad-b">
                              {tier}
                            </span>
                            <span className="text-[13px] font-semibold text-text">
                              {t("shot_tier_strategy_title", {
                                defaultValue: "{{tier}} 档策略",
                                tier,
                              })}
                            </span>
                          </div>
                          <div className="grid gap-3 sm:grid-cols-5">
                            <label className="block">
                              <span className="mb-1.5 block text-[11px] text-text-3">
                                {t("shot_tier_retry_budget", { defaultValue: "重试预算" })}
                              </span>
                              <input
                                type="number"
                                min={1}
                                max={6}
                                step={1}
                                value={tierProfile.retry_budget ?? 1}
                                onChange={(event) =>
                                  updateShotTierProfile(tier, {
                                    retry_budget: Math.max(1, Number(event.currentTarget.value) || 1),
                                  })
                                }
                                className={PROFILE_INPUT_CLS}
                              />
                            </label>
                            <label className="block">
                              <span className="mb-1.5 block text-[11px] text-text-3">
                                {t("shot_tier_reference_policy", { defaultValue: "参考图策略" })}
                              </span>
                              <SelectMenu
                                value={tierProfile.reference_image_policy ?? "balanced"}
                                options={REFERENCE_IMAGE_POLICIES.map((policy) => ({
                                  value: policy,
                                  label: policy,
                                }))}
                                onChange={(next) =>
                                  updateShotTierProfile(tier, {
                                    reference_image_policy: next,
                                  })
                                }
                                ariaLabel={t("shot_tier_reference_policy", { defaultValue: "参考图策略" })}
                                panelLabel={t("shot_tier_reference_policy", { defaultValue: "参考图策略" })}
                                className={PROFILE_INPUT_CLS}
                              />
                            </label>
                            <label className="block">
                              <span className="mb-1.5 block text-[11px] text-text-3">
                                {t("video_continuity_policy_label")}
                              </span>
                              <SelectMenu
                                value={tierProfile.video_continuity_policy ?? "auto"}
                                options={VIDEO_CONTINUITY_POLICIES.map((policy) => ({
                                  value: policy,
                                  label: t(`video_continuity_policy_${policy}`),
                                }))}
                                onChange={(next) =>
                                  updateShotTierProfile(tier, {
                                    video_continuity_policy: normalizeVideoContinuityPolicy(next),
                                  })
                                }
                                ariaLabel={t("video_continuity_policy_label")}
                                panelLabel={t("video_continuity_policy_label")}
                                className={PROFILE_INPUT_CLS}
                              />
                            </label>
                            <label className="block">
                              <span className="mb-1.5 block text-[11px] text-text-3">
                                {t("generation_profile_storyboard_final")}
                              </span>
                              <SelectMenu
                                value={storyboardOverride.resolution ?? ""}
                                options={[
                                  { value: "", label: t("follow_global_default") },
                                  ...IMAGE_PROFILE_RESOLUTIONS.map((resolution) => ({
                                    value: resolution,
                                    label: resolution,
                                  })),
                                ]}
                                onChange={(next) =>
                                  updateShotTierOverride(tier, "storyboard_final", {
                                    resolution: next || null,
                                  })
                                }
                                ariaLabel={t("generation_profile_storyboard_final")}
                                panelLabel={t("generation_profile_storyboard_final")}
                                className={PROFILE_INPUT_CLS}
                              />
                            </label>
                            <label className="block">
                              <span className="mb-1.5 block text-[11px] text-text-3">
                                {t("generation_profile_video_final")}
                              </span>
                              <SelectMenu
                                value={videoOverride.resolution ?? ""}
                                options={[
                                  { value: "", label: t("follow_global_default") },
                                  ...VIDEO_PROFILE_RESOLUTIONS.map((resolution) => ({
                                    value: resolution,
                                    label: resolution,
                                  })),
                                ]}
                                onChange={(next) =>
                                  updateShotTierOverride(tier, "video_final", {
                                    resolution: next || null,
                                  })
                                }
                                ariaLabel={t("generation_profile_video_final")}
                                panelLabel={t("generation_profile_video_final")}
                                className={PROFILE_INPUT_CLS}
                              />
                            </label>
                            <label className="block sm:col-span-2">
                              <span className="mb-1.5 block text-[11px] text-text-3">
                                {t("video_backend_label", { defaultValue: "视频供应商" })}
                              </span>
                              <SelectMenu
                                value={videoOverride.video_backend ?? ""}
                                options={[
                                  { value: "", label: t("follow_global_default") },
                                  ...options.video_backends.map((backend) => ({
                                    value: backend,
                                    label: backend,
                                  })),
                                ]}
                                onChange={(next) =>
                                  updateShotTierOverride(tier, "video_final", {
                                    video_backend: next || null,
                                  })
                                }
                                ariaLabel={t("video_backend_label", { defaultValue: "视频供应商" })}
                                panelLabel={t("video_backend_label", { defaultValue: "视频供应商" })}
                                className={PROFILE_INPUT_CLS}
                              />
                              {tierVideoStartImageUnsupported && (
                                <span
                                  role="status"
                                  className="mt-1.5 block text-[11.5px] leading-[1.45] text-warm"
                                >
                                  {t("templates:storyboard_video_model_requires_start_image", {
                                    defaultValue:
                                      "当前图生视频 / 宫格生视频流程会用当前分镜作为视频起始图。此模型不支持首帧输入，可能失败或偏离当前分镜，请切换到支持 I2V / 首帧的视频模型。",
                                  })}
                                </span>
                              )}
                            </label>
                            <label className="block">
                              <span className="mb-1.5 block text-[11px] text-text-3">
                                {t("video_service_tier_label", { defaultValue: "服务档位" })}
                              </span>
                              <input
                                value={videoOverride.service_tier ?? ""}
                                onChange={(event) =>
                                  updateShotTierOverride(tier, "video_final", {
                                    service_tier: event.currentTarget.value || null,
                                  })
                                }
                                className={PROFILE_INPUT_CLS}
                                placeholder="default"
                              />
                            </label>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {([
                    ["asset", t("generation_profile_asset")],
                    ["storyboard_draft", t("generation_profile_storyboard_draft")],
                    ["storyboard_final", t("generation_profile_storyboard_final")],
                    ["grid", t("generation_profile_grid")],
                  ] as const).map(([key, label]) => (
                    <div
                      key={key}
                      className="grid items-center gap-3 rounded-[10px] border border-hairline-soft bg-bg-grad-a/30 p-3 sm:grid-cols-[minmax(0,1fr)_180px]"
                    >
                      <div className="min-w-0">
                        <div className="text-[13px] font-semibold text-text">{label}</div>
                      </div>
                      <label className="block">
                        <span className="mb-1.5 block text-[11px] text-text-3">
                          {t("resolution_label")}
                        </span>
                        <SelectMenu
                          value={normalizedGenerationProfiles[key]?.resolution ?? ""}
                          options={IMAGE_PROFILE_RESOLUTIONS.map((resolution) => ({
                            value: resolution,
                            label: resolution,
                          }))}
                          onChange={(next) =>
                            updateImageProfile(key, { resolution: next || null })
                          }
                          ariaLabel={t("resolution_label")}
                          panelLabel={t("resolution_label")}
                          className={PROFILE_INPUT_CLS}
                        />
                      </label>
                    </div>
                  ))}

                  {videoProfileRows.map(([key, label]) => {
                    const profile = normalizedGenerationProfiles[key];
                    const audioValue =
                      profile?.generate_audio == null
                        ? "project"
                        : profile.generate_audio
                          ? "true"
                          : "false";
                    return (
                      <div
                        key={key}
                        className="grid gap-3 rounded-[10px] border border-hairline-soft bg-bg-grad-a/30 p-3 sm:grid-cols-[minmax(0,1fr)_repeat(2,130px)]"
                      >
                        <div className="min-w-0">
                          <div className="text-[13px] font-semibold text-text">{label}</div>
                        </div>
                        <label className="block">
                          <span className="mb-1.5 block text-[11px] text-text-3">
                            {t("resolution_label")}
                          </span>
                          <SelectMenu
                            value={profile?.resolution ?? ""}
                            options={VIDEO_PROFILE_RESOLUTIONS.map((resolution) => ({
                              value: resolution,
                              label: resolution,
                            }))}
                            onChange={(next) =>
                              updateVideoProfile(key, { resolution: next || null })
                            }
                            ariaLabel={t("resolution_label")}
                            panelLabel={t("resolution_label")}
                            className={PROFILE_INPUT_CLS}
                          />
                        </label>
                        <label className="block">
                          <span className="mb-1.5 block text-[11px] text-text-3">
                            {t("generate_audio_label")}
                          </span>
                          <SelectMenu
                            value={audioValue}
                            options={[
                              { value: "project", label: t("follow_global_default") },
                              { value: "true", label: t("enabled_label") },
                              { value: "false", label: t("disabled_label") },
                            ]}
                            onChange={(value) => {
                              updateVideoProfile(key, {
                                generate_audio:
                                  value === "project" ? null : value === "true",
                              });
                            }}
                            ariaLabel={t("generate_audio_label")}
                            panelLabel={t("generate_audio_label")}
                            className={PROFILE_INPUT_CLS}
                          />
                        </label>
                      </div>
                    );
                  })}
                </div>
              </SectionCard>

              {/* Episode planning */}
              <SectionCard kicker="Episode Planning" title={t("episode_planning_section_title")}>
                <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_180px]">
                  <fieldset>
                    <legend className="mb-2.5 block font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-text-3">
                      {t("source_language_label")}
                    </legend>
                    <div className="flex flex-wrap gap-2.5">
                      {SOURCE_LANGUAGES.map((lang) => (
                        <label key={lang} className={radioCardClass(sourceLanguage === lang)}>
                          <input
                            type="radio"
                            name="sourceLanguage"
                            value={lang}
                            checked={sourceLanguage === lang}
                            onChange={() => setSourceLanguage(lang)}
                            className="sr-only"
                          />
                          {t(`source_language_${lang}`)}
                        </label>
                      ))}
                    </div>
                  </fieldset>

                  <label className="block">
                    <span className="mb-2.5 block font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-text-3">
                      {t("episode_target_units_label")}
                    </span>
                    <input
                      type="number"
                      min={1}
                      step={1}
                      value={episodeTargetUnits}
                      onChange={(e) => setEpisodeTargetUnits(e.currentTarget.value)}
                      className="h-9 w-full rounded-[7px] border border-hairline-soft bg-bg-grad-a/45 px-3 text-[13px] text-text outline-none transition-colors hover:border-hairline focus:border-accent focus:ring-2 focus:ring-accent/30"
                    />
                    <span className="mt-1 block text-[11.5px] leading-[1.45] text-text-3">
                      {t("episode_target_units_hint")}
                    </span>
                  </label>
                </div>
              </SectionCard>

              {/* Aspect ratio */}
              <SectionCard kicker="Frame Aspect">
                <fieldset>
                  <legend className="mb-2.5 block font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-text-3">
                    {t("aspect_ratio_label")}
                  </legend>
                  <div className="flex gap-2.5">
                    {(["9:16", "16:9"] as const).map((ar) => (
                      <label key={ar} className={radioCardClass(aspectRatio === ar)}>
                        <input
                          type="radio"
                          name="aspectRatio"
                          value={ar}
                          checked={aspectRatio === ar}
                          onChange={() => {
                            setAspectRatio(ar);
                            if (initialRef.current.aspectRatio && ar !== initialRef.current.aspectRatio) {
                              useAppStore.getState().pushToast(
                                t("aspect_ratio_change_warning"),
                                "warning",
                              );
                            }
                          }}
                          className="sr-only"
                        />
                        <span className="inline-flex items-center gap-2">
                          <span
                            aria-hidden
                            className="block rounded-[1.5px] border border-hairline"
                            style={{
                              width: ar === "16:9" ? 12 : 7.5,
                              height: ar === "16:9" ? 7.5 : 12,
                              background:
                                aspectRatio === ar ? "var(--color-accent-soft)" : "transparent",
                            }}
                          />
                          {ar === "9:16" ? t("portrait_9_16") : t("landscape_16_9")}
                        </span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              </SectionCard>

              {/* Generation mode */}
              <SectionCard kicker="Pipeline Mode">
                <fieldset>
                  <legend className="mb-2 block font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-text-3">
                    {t("generation_mode")}
                  </legend>
                  <GenerationModeSelector
                    value={generationMode}
                    onChange={() => {}}
                    readOnly
                  />
                  <p className="mt-2 text-[11.5px] leading-[1.45] text-text-4">
                    {t("generation_mode_locked_hint", {
                      defaultValue: "已创建项目的生成方式固定，不能在项目设置中修改；拆分方案只能在兼容当前生成方式的范围内切换。",
                    })}
                  </p>
                </fieldset>
              </SectionCard>

              {/* Audio override */}
              <SectionCard kicker="Audio Channel">
                <div className="mb-2.5 font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-text-3">
                  {t("generate_audio_label")}
                </div>
                <fieldset className="flex flex-wrap gap-x-5 gap-y-2">
                  <legend className="sr-only">{t("audio_settings_sr_label")}</legend>
                  <label className="inline-flex items-center gap-2 text-[12.5px] text-text-2">
                    <input
                      type="radio"
                      name="audio"
                      value=""
                      checked={audioOverride === null}
                      onChange={() => setAudioOverride(null)}
                      className="accent-[oklch(0.76_0.09_295)]"
                    />
                    {t("follow_global_default")}
                  </label>
                  <label className="inline-flex items-center gap-2 text-[12.5px] text-text-2">
                    <input
                      type="radio"
                      name="audio"
                      value="true"
                      checked={audioOverride === true}
                      onChange={() => setAudioOverride(true)}
                      className="accent-[oklch(0.76_0.09_295)]"
                    />
                    {t("enabled_label")}
                  </label>
                  <label className="inline-flex items-center gap-2 text-[12.5px] text-text-2">
                    <input
                      type="radio"
                      name="audio"
                      value="false"
                      checked={audioOverride === false}
                      onChange={() => setAudioOverride(false)}
                      className="accent-[oklch(0.76_0.09_295)]"
                    />
                    {t("disabled_label")}
                  </label>
                </fieldset>
              </SectionCard>
            </>
          )}

          {!options && (
            <div className="flex items-center gap-2 py-6 text-text-3">
              <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin text-accent-2" aria-hidden />
              <span className="font-mono text-[11px] uppercase tracking-[0.14em]">
                {t("loading_config")}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ─── Sticky save bar ─── */}
      <footer
        className="shrink-0"
        style={{
          background:
            "linear-gradient(180deg, oklch(0.18 0.011 265 / 0.65), oklch(0.14 0.009 265 / 0.85))",
          backdropFilter: "blur(20px) saturate(1.3)",
          WebkitBackdropFilter: "blur(20px) saturate(1.3)",
          borderTop: "1px solid var(--color-hairline)",
          boxShadow: "0 -8px 28px -12px oklch(0 0 0 / 0.55)",
        }}
      >
        <div className="mx-auto flex w-full max-w-[980px] items-center justify-between gap-3 px-6 py-3">
          <div className="min-w-0 flex items-center gap-2 text-[11.5px] text-text-3">
            <span
              aria-hidden
              className="inline-block h-1.5 w-1.5 rounded-full"
              style={{
                background: isDirty ? "var(--color-warm)" : "var(--color-good)",
                boxShadow: isDirty
                  ? "0 0 6px oklch(0.85 0.13 75 / 0.4)"
                  : "0 0 6px oklch(0.78 0.10 155 / 0.4)",
              }}
            />
            <span className="font-mono text-[10px] font-bold uppercase tracking-[0.14em]">
              {isDirty ? t("unsaved_changes_hint") : t("saved")}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              onClick={() => guardedNavigate(`/app/projects/${projectName}`)}
              className={GHOST_BTN_LG_CLS}
            >
              {t("common:cancel")}
            </button>
            <button
              // handleSave 在 onClick 时才执行；规则误报。
              // eslint-disable-next-line react-hooks/refs
              onClick={voidPromise(handleSave)}
              disabled={saving}
              className={`${ACCENT_BTN_CLS} px-5`}
              style={ACCENT_BUTTON_STYLE}
            >
              {saving && <Loader2 aria-hidden className="h-3.5 w-3.5 motion-safe:animate-spin" />}
              {saving ? t("common:saving") : t("common:save")}
            </button>
          </div>
        </div>
      </footer>

      <ConfirmDialog
        open={pendingNavigation !== null}
        tone="danger"
        title={t("unsaved_changes_confirm")}
        confirmLabel={t("common:confirm")}
        cancelLabel={t("common:cancel")}
        onCancel={() => setPendingNavigation(null)}
        onConfirm={confirmDiscardAndNavigate}
      />
    </div>
  );
}

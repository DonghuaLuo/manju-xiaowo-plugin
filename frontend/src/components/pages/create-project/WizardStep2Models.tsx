import { useTranslation } from "react-i18next";
import { AlertTriangle, ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { ModelConfigSection, type ModelConfigValue } from "@/components/shared/ModelConfigSection";
import { SelectMenu } from "@/components/ui/SelectMenu";
import { ACCENT_BTN_CLS, ACCENT_BUTTON_STYLE, CARD_STYLE, GHOST_BTN_LG_CLS } from "@/components/ui/darkroom-tokens";
import {
  IMAGE_PROFILE_RESOLUTIONS,
  VIDEO_PROFILE_RESOLUTIONS,
  createDefaultGenerationProfiles,
  normalizeGenerationProfiles,
} from "@/utils/generation-profiles";
import { VIDEO_CONTINUITY_POLICIES, normalizeVideoContinuityPolicy } from "@/utils/video-continuity";
import type { GenerationMode } from "@/utils/generation-mode";
import {
  lookupStoryboardVideoStartImageSupport,
  lookupVideoContinuitySupport,
} from "@/utils/provider-models";
import type {
  GenerationProfiles,
  ImageGenerationProfile,
  ProviderInfo,
  VideoContinuityPolicy,
  VideoGenerationProfile,
} from "@/types";
import type { CustomProviderInfo } from "@/types/custom-provider";

export interface WizardStep2Data {
  options: {
    video: string[];
    image: string[];
    text: string[];
    providerNames: Record<string, string>;
  };
  providers: ProviderInfo[];
  customProviders: CustomProviderInfo[];
  globalDefaults: {
    video: string;
    imageT2I: string;
    imageI2I: string;
    textScript: string;
    textOverview: string;
    textStyle: string;
  };
}

export interface WizardStep2ModelsProps {
  value: ModelConfigValue;
  onChange: (next: ModelConfigValue) => void;
  generationProfilesExpanded: boolean;
  onGenerationProfilesExpandedChange: (next: boolean) => void;
  generationProfiles: GenerationProfiles;
  onGenerationProfilesChange: (next: GenerationProfiles) => void;
  videoContinuityPolicy: VideoContinuityPolicy;
  onVideoContinuityPolicyChange: (next: VideoContinuityPolicy) => void;
  generationMode?: GenerationMode;
  onBack: () => void;
  onNext: () => void;
  onCancel: () => void;
  data: WizardStep2Data | null;
  error: string | null;
}

export function WizardStep2Models({
  value,
  onChange,
  generationProfilesExpanded,
  onGenerationProfilesExpandedChange,
  generationProfiles,
  onGenerationProfilesChange,
  videoContinuityPolicy,
  onVideoContinuityPolicyChange,
  generationMode,
  onBack,
  onNext,
  onCancel,
  data,
  error,
}: WizardStep2ModelsProps) {
  const { t } = useTranslation(["common", "templates", "dashboard"]);
  const loading = !data && !error;
  const defaultGenerationProfiles = createDefaultGenerationProfiles({
    imageResolution: value.imageResolution,
    videoResolution: value.videoResolution,
  });
  const normalizedGenerationProfiles = normalizeGenerationProfiles(
    generationProfiles,
    defaultGenerationProfiles,
  );
  const effectiveVideoBackend = value.videoBackend || data?.globalDefaults.video || "";
  const referenceVideoUnsupported = Boolean(
    data &&
      generationMode === "reference_video" &&
      effectiveVideoBackend &&
      !lookupVideoContinuitySupport(effectiveVideoBackend, data.customProviders).referenceImages,
  );
  const storyboardVideoStartImageUnsupported = Boolean(
    data &&
      generationMode !== "reference_video" &&
      effectiveVideoBackend &&
      lookupStoryboardVideoStartImageSupport(effectiveVideoBackend, data.customProviders) === false,
  );

  const updateImageProfile = (
    key: ImageProfileKey,
    patch: Partial<ImageGenerationProfile>,
  ) => {
    onGenerationProfilesChange(
      normalizeGenerationProfiles(
        {
          ...normalizedGenerationProfiles,
          [key]: {
            ...normalizedGenerationProfiles[key],
            ...patch,
          },
        },
        defaultGenerationProfiles,
      ),
    );
  };

  const updateVideoProfile = (
    key: VideoProfileKey,
    patch: Partial<VideoGenerationProfile>,
  ) => {
    onGenerationProfilesChange(
      normalizeGenerationProfiles(
        {
          ...normalizedGenerationProfiles,
          [key]: {
            ...normalizedGenerationProfiles[key],
            ...patch,
          },
        },
        defaultGenerationProfiles,
      ),
    );
  };

  return (
    <div className="space-y-5">
      {loading && (
        <div className="flex items-center justify-center gap-2 py-12 text-text-3">
          <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin text-accent-2" aria-hidden />
          <span className="font-mono text-[11px] uppercase tracking-[0.14em]">{t("common:loading")}</span>
        </div>
      )}
      {error && (
        <div role="alert" className="rounded-[8px] border border-hairline-soft bg-bg-grad-a/45 px-4 py-6 text-center">
          <div className="inline-flex items-center gap-1.5 font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-warm">
            <AlertTriangle aria-hidden className="h-3 w-3" />
            {t("common:error")}
          </div>
          <p className="mt-1.5 text-[12.5px] text-text-2">{error}</p>
        </div>
      )}
      {data && (
        <>
          <ModelConfigSection
            value={value}
            onChange={onChange}
            providers={data.providers}
            customProviders={data.customProviders}
            options={{
              videoBackends: data.options.video,
              imageBackends: data.options.image,
              textBackends: data.options.text,
              providerNames: data.options.providerNames,
            }}
            globalDefaults={data.globalDefaults}
            storyboardVideoStartImageUnsupported={storyboardVideoStartImageUnsupported}
          />
          {referenceVideoUnsupported ? (
            <div
              role="alert"
              className="rounded-[8px] border border-warm/35 bg-warm/10 px-3 py-2.5 text-[12.5px] leading-[1.55] text-warm"
            >
              {t("dashboard:reference_video_model_requires_reference_images", {
                defaultValue:
                  "参考视频预览模式需要支持参考图的视频模型。请切换到支持 reference images 的模型，或返回选择图生视频 / 宫格模式。",
              })}
            </div>
          ) : null}
          <GenerationProfilesEditor
            expanded={generationProfilesExpanded}
            onExpandedChange={onGenerationProfilesExpandedChange}
            profiles={normalizedGenerationProfiles}
            onUpdateImage={updateImageProfile}
            onUpdateVideo={updateVideoProfile}
            videoContinuityPolicy={videoContinuityPolicy}
            onVideoContinuityPolicyChange={onVideoContinuityPolicyChange}
            generationMode={generationMode}
          />
        </>
      )}

      <div className="mt-7 flex items-center justify-between border-t border-hairline-soft pt-5">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-[7px] px-2.5 py-1.5 text-[12.5px] text-text-3 transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          {t("common:cancel")}
        </button>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onBack}
            className={GHOST_BTN_LG_CLS}
          >
            <span aria-hidden>←</span>
            {t("templates:prev_step")}
          </button>
          <button
            type="button"
            onClick={onNext}
            disabled={loading || referenceVideoUnsupported}
            className={ACCENT_BTN_CLS}
            style={ACCENT_BUTTON_STYLE}
          >
            {t("templates:next_step")}
            <span aria-hidden>→</span>
          </button>
        </div>
      </div>
    </div>
  );
}

type ImageProfileKey = "asset" | "storyboard_draft" | "storyboard_final" | "grid";
type VideoProfileKey =
  | "video_draft"
  | "video_final"
  | "reference_video_draft"
  | "reference_video_final";

const PROFILE_INPUT_CLS =
  "h-9 w-full rounded-[7px] border border-hairline-soft bg-bg-grad-a/45 px-2.5 text-[12.5px] text-text outline-none transition-colors hover:border-hairline focus:border-accent focus:ring-2 focus:ring-accent/30";

function GenerationProfilesEditor({
  expanded,
  onExpandedChange,
  profiles,
  onUpdateImage,
  onUpdateVideo,
  videoContinuityPolicy,
  onVideoContinuityPolicyChange,
  generationMode,
}: {
  expanded: boolean;
  onExpandedChange: (next: boolean) => void;
  profiles: GenerationProfiles;
  onUpdateImage: (key: ImageProfileKey, patch: Partial<ImageGenerationProfile>) => void;
  onUpdateVideo: (key: VideoProfileKey, patch: Partial<VideoGenerationProfile>) => void;
  videoContinuityPolicy: VideoContinuityPolicy;
  onVideoContinuityPolicyChange: (next: VideoContinuityPolicy) => void;
  generationMode?: GenerationMode;
}) {
  const { t } = useTranslation(["dashboard", "templates"]);
  const videoProfileRows: Array<[VideoProfileKey, string]> = [
    ["video_draft", t("dashboard:generation_profile_video_draft")],
    ["video_final", t("dashboard:generation_profile_video_final")],
    ...(generationMode === "reference_video"
      ? ([
          ["reference_video_draft", t("dashboard:generation_profile_reference_video_draft")],
          ["reference_video_final", t("dashboard:generation_profile_reference_video_final")],
        ] as Array<[VideoProfileKey, string]>)
      : []),
  ];
  return (
    <section className="rounded-[10px] border border-hairline p-4" style={CARD_STYLE}>
      <button
        id="create-project-generation-profiles-toggle"
        type="button"
        aria-expanded={expanded}
        aria-controls="create-project-generation-profiles-panel"
        onClick={() => onExpandedChange(!expanded)}
        className="flex w-full items-start gap-3 rounded-[8px] text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
      >
        <span
          className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-[7px] border border-hairline-soft bg-bg-grad-a/55 text-accent-2"
          aria-hidden
        >
          {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-accent-2">
            Quality Strategy
          </span>
          <span className="mt-1 block text-[13.5px] font-medium text-text">
            {t("dashboard:generation_profiles_section_title")}
          </span>
          <span className="mt-1 block text-[12.5px] leading-[1.55] text-text-3">
            {t("dashboard:generation_profiles_section_desc")}
          </span>
        </span>
        <span className="mt-0.5 rounded-[7px] border border-hairline-soft px-2 py-1 text-[11px] text-text-3">
          {t("dashboard:advanced_settings", { defaultValue: "高级设置" })}
        </span>
      </button>

      {expanded && (
        <div id="create-project-generation-profiles-panel" className="mt-4 space-y-4 border-t border-hairline-soft pt-4">
          <div className="grid gap-3 rounded-[10px] border border-hairline-soft bg-bg-grad-a/30 p-3 sm:grid-cols-[minmax(0,1fr)_220px]">
            <div className="min-w-0">
              <div className="text-[13px] font-semibold text-text">
                {t("dashboard:video_continuity_policy_label")}
              </div>
              <p className="mt-1 text-[12px] leading-[1.5] text-text-3">
                {t(`dashboard:video_continuity_policy_${videoContinuityPolicy}_hint`)}
              </p>
            </div>
            <label className="block">
              <span className="mb-1.5 block text-[11px] text-text-3">
                {t("dashboard:video_continuity_policy_label")}
              </span>
              <SelectMenu
                value={videoContinuityPolicy}
                options={VIDEO_CONTINUITY_POLICIES.map((policy) => ({
                  value: policy,
                  label: t(`dashboard:video_continuity_policy_${policy}`),
                }))}
                onChange={(next) => onVideoContinuityPolicyChange(normalizeVideoContinuityPolicy(next))}
                ariaLabel={t("dashboard:video_continuity_policy_label")}
                panelLabel={t("dashboard:video_continuity_policy_label")}
                className={PROFILE_INPUT_CLS}
              />
            </label>
          </div>

          {([
            ["asset", t("dashboard:generation_profile_asset")],
            ["storyboard_draft", t("dashboard:generation_profile_storyboard_draft")],
            ["storyboard_final", t("dashboard:generation_profile_storyboard_final")],
            ["grid", t("dashboard:generation_profile_grid")],
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
                  {t("templates:resolution_label")}
                </span>
                <SelectMenu
                  value={profiles[key]?.resolution ?? ""}
                  options={IMAGE_PROFILE_RESOLUTIONS.map((resolution) => ({
                    value: resolution,
                    label: resolution,
                  }))}
                  onChange={(next) => onUpdateImage(key, { resolution: next || null })}
                  ariaLabel={t("templates:resolution_label")}
                  panelLabel={t("templates:resolution_label")}
                  className={PROFILE_INPUT_CLS}
                />
              </label>
            </div>
          ))}

          {videoProfileRows.map(([key, label]) => {
            const profile = profiles[key];
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
                    {t("templates:resolution_label")}
                  </span>
                  <SelectMenu
                    value={profile?.resolution ?? ""}
                    options={VIDEO_PROFILE_RESOLUTIONS.map((resolution) => ({
                      value: resolution,
                      label: resolution,
                    }))}
                    onChange={(next) => onUpdateVideo(key, { resolution: next || null })}
                    ariaLabel={t("templates:resolution_label")}
                    panelLabel={t("templates:resolution_label")}
                    className={PROFILE_INPUT_CLS}
                  />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-[11px] text-text-3">
                    {t("dashboard:generate_audio_label")}
                  </span>
                  <SelectMenu
                    value={audioValue}
                    options={[
                      { value: "project", label: t("dashboard:follow_global_default") },
                      { value: "true", label: t("dashboard:enabled_label") },
                      { value: "false", label: t("dashboard:disabled_label") },
                    ]}
                    onChange={(next) => {
                      onUpdateVideo(key, {
                        generate_audio: next === "project" ? null : next === "true",
                      });
                    }}
                    ariaLabel={t("dashboard:generate_audio_label")}
                    panelLabel={t("dashboard:generate_audio_label")}
                    className={PROFILE_INPUT_CLS}
                  />
                </label>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

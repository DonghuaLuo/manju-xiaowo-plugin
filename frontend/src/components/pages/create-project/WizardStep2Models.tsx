import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { ModelConfigSection, type ModelConfigValue } from "@/components/shared/ModelConfigSection";
import { SelectMenu } from "@/components/ui/SelectMenu";
import { ACCENT_BTN_CLS, ACCENT_BUTTON_STYLE, CARD_STYLE, GHOST_BTN_LG_CLS } from "@/components/ui/darkroom-tokens";
import {
  IMAGE_PROFILE_RESOLUTIONS,
  VIDEO_PROFILE_RESOLUTIONS,
  coerceResolutionForOptions,
  createDefaultGenerationProfiles,
  normalizeGenerationProfiles,
} from "@/utils/generation-profiles";
import type { GenerationMode } from "@/utils/generation-mode";
import {
  lookupResolutions,
  lookupStoryboardVideoStartImageSupport,
  lookupVideoContinuitySupport,
} from "@/utils/provider-models";
import { useEndpointCatalogStore } from "@/stores/endpoint-catalog-store";
import type {
  GenerationProfiles,
  ImageGenerationProfile,
  MediaType,
  ProviderInfo,
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
  generationMode?: GenerationMode;
  onBack: () => void;
  onNext: () => void;
  onCancel: () => void;
  data: WizardStep2Data | null;
  error: string | null;
}

type ImageProfileKey = "asset" | "storyboard_draft" | "storyboard_final" | "grid";
type VideoProfileKey =
  | "video_draft"
  | "video_final"
  | "reference_video_draft"
  | "reference_video_final";

const IMAGE_PROFILE_KEYS: ImageProfileKey[] = ["asset", "storyboard_draft", "storyboard_final", "grid"];
const VIDEO_PROFILE_KEYS: VideoProfileKey[] = [
  "video_draft",
  "video_final",
  "reference_video_draft",
  "reference_video_final",
];

function resolutionOptionsForBackend(
  data: WizardStep2Data | null,
  backend: string,
  fallback: readonly string[],
  endpointToMediaType: Record<string, MediaType>,
): string[] {
  if (!data || !backend) return [...fallback];
  const res = lookupResolutions(
    data.providers,
    backend,
    data.customProviders,
    endpointToMediaType,
  );
  return res.options.length > 0 ? res.options : [...fallback];
}

export function WizardStep2Models({
  value,
  onChange,
  generationProfilesExpanded,
  onGenerationProfilesExpandedChange,
  generationProfiles,
  onGenerationProfilesChange,
  generationMode,
  onBack,
  onNext,
  onCancel,
  data,
  error,
}: WizardStep2ModelsProps) {
  const { t } = useTranslation(["common", "templates", "dashboard"]);
  const loading = !data && !error;

  const endpointToMediaType = useEndpointCatalogStore((s) => s.endpointToMediaType);
  const fetchEndpointCatalog = useEndpointCatalogStore((s) => s.fetch);
  useEffect(() => {
    if ((data?.customProviders.length ?? 0) > 0) void fetchEndpointCatalog();
  }, [data?.customProviders.length, fetchEndpointCatalog]);

  const effectiveImageBackend = value.imageBackendT2I || data?.globalDefaults.imageT2I || "";
  const effectiveVideoBackend = value.videoBackend || data?.globalDefaults.video || "";
  const imageResolutionOptions = useMemo(
    () =>
      resolutionOptionsForBackend(
        data,
        effectiveImageBackend,
        IMAGE_PROFILE_RESOLUTIONS,
        endpointToMediaType,
      ),
    [data, effectiveImageBackend, endpointToMediaType],
  );
  const videoResolutionOptions = useMemo(
    () =>
      resolutionOptionsForBackend(
        data,
        effectiveVideoBackend,
        VIDEO_PROFILE_RESOLUTIONS,
        endpointToMediaType,
      ),
    [data, effectiveVideoBackend, endpointToMediaType],
  );

  const defaultGenerationProfiles = useMemo(
    () =>
      createDefaultGenerationProfiles({
        imageResolution: value.imageResolution,
        videoResolution: value.videoResolution,
        imageResolutionOptions,
        videoResolutionOptions,
      }),
    [imageResolutionOptions, value.imageResolution, value.videoResolution, videoResolutionOptions],
  );
  const normalizedGenerationProfiles = normalizeGenerationProfiles(
    generationProfiles,
    defaultGenerationProfiles,
  );
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

  useEffect(() => {
    if (!data) return;
    const nextImageResolution = coerceResolutionForOptions(
      value.imageResolution,
      imageResolutionOptions,
      "1K",
    );
    const nextVideoResolution = coerceResolutionForOptions(
      value.videoResolution,
      videoResolutionOptions,
      "720p",
    );
    if (
      nextImageResolution !== value.imageResolution ||
      nextVideoResolution !== value.videoResolution
    ) {
      onChange({
        ...value,
        imageResolution: nextImageResolution,
        videoResolution: nextVideoResolution,
      });
    }
  }, [
    data,
    imageResolutionOptions,
    onChange,
    value,
    videoResolutionOptions,
  ]);

  useEffect(() => {
    if (!data) return;
    let changed = false;
    const next = normalizeGenerationProfiles(generationProfiles, defaultGenerationProfiles);

    for (const key of IMAGE_PROFILE_KEYS) {
      const current = next[key]?.resolution;
      if (!current) continue;
      const coerced = coerceResolutionForOptions(current, imageResolutionOptions, current);
      if (coerced !== current) {
        next[key] = { ...next[key], resolution: coerced };
        changed = true;
      }
    }

    for (const key of VIDEO_PROFILE_KEYS) {
      const current = next[key]?.resolution;
      if (!current) continue;
      const coerced = coerceResolutionForOptions(current, videoResolutionOptions, current);
      if (coerced !== current) {
        next[key] = { ...next[key], resolution: coerced };
        changed = true;
      }
    }

    if (changed) onGenerationProfilesChange(next);
  }, [
    data,
    defaultGenerationProfiles,
    generationProfiles,
    imageResolutionOptions,
    onGenerationProfilesChange,
    videoResolutionOptions,
  ]);

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
                  "参考视频模式需要支持参考图的视频模型。请切换到支持 reference images 的模型，或返回选择图生视频 / 宫格分镜。",
              })}
            </div>
          ) : null}
          <GenerationProfilesEditor
            expanded={generationProfilesExpanded}
            onExpandedChange={onGenerationProfilesExpandedChange}
            profiles={normalizedGenerationProfiles}
            onReplaceProfiles={(next) =>
              onGenerationProfilesChange(
                normalizeGenerationProfiles(next, defaultGenerationProfiles),
              )
            }
            onUpdateImage={updateImageProfile}
            generationMode={generationMode}
            imageResolutionOptions={imageResolutionOptions}
            videoResolutionOptions={videoResolutionOptions}
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

const PROFILE_INPUT_CLS =
  "h-9 w-full rounded-[7px] border border-hairline-soft bg-bg-grad-a/45 px-2.5 text-[12.5px] text-text outline-none transition-colors hover:border-hairline focus:border-accent focus:ring-2 focus:ring-accent/30";

function GenerationProfilesEditor({
  expanded,
  onExpandedChange,
  profiles,
  onReplaceProfiles,
  onUpdateImage,
  generationMode,
  imageResolutionOptions,
  videoResolutionOptions,
}: {
  expanded: boolean;
  onExpandedChange: (next: boolean) => void;
  profiles: GenerationProfiles;
  onReplaceProfiles: (next: GenerationProfiles) => void;
  onUpdateImage: (key: ImageProfileKey, patch: Partial<ImageGenerationProfile>) => void;
  generationMode?: GenerationMode;
  imageResolutionOptions: readonly string[];
  videoResolutionOptions: readonly string[];
}) {
  const { t } = useTranslation(["dashboard", "templates"]);
  const updateStoryboardResolution = (resolution: string | null) => {
    onReplaceProfiles({
      ...profiles,
      storyboard_draft: {
        ...profiles.storyboard_draft,
        resolution,
      },
      storyboard_final: {
        ...profiles.storyboard_final,
        resolution,
      },
    });
  };
  const updateVideoDefaults = (patch: Partial<VideoGenerationProfile>) => {
    onReplaceProfiles({
      ...profiles,
      video_draft: {
        ...profiles.video_draft,
        ...patch,
      },
      video_final: {
        ...profiles.video_final,
        ...patch,
      },
    });
  };
  const updateReferenceVideoDefaults = (patch: Partial<VideoGenerationProfile>) => {
    onReplaceProfiles({
      ...profiles,
      reference_video_draft: {
        ...profiles.reference_video_draft,
        ...patch,
      },
      reference_video_final: {
        ...profiles.reference_video_final,
        ...patch,
      },
    });
  };
  const storyboardResolution = profiles.storyboard_final?.resolution ?? profiles.storyboard_draft?.resolution ?? "";
  const videoResolution = profiles.video_final?.resolution ?? profiles.video_draft?.resolution ?? "";
  const referenceVideoResolution =
    profiles.reference_video_final?.resolution ?? profiles.reference_video_draft?.resolution ?? "";
  const videoAudioValue =
    profiles.video_final?.generate_audio == null
      ? "false"
      : profiles.video_final.generate_audio
        ? "true"
        : "false";
  const referenceVideoAudioValue =
    profiles.reference_video_final?.generate_audio == null
      ? "false"
      : profiles.reference_video_final.generate_audio
        ? "true"
        : "false";
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
            Generation Defaults
          </span>
          <span className="mt-1 block text-[13.5px] font-medium text-text">
            {t("dashboard:generation_profiles_section_title")}
          </span>
          <span className="mt-1 block text-[12.5px] leading-[1.55] text-text-3">
            {t("dashboard:generation_profiles_section_desc", {
              defaultValue:
                "设置项目级默认分辨率。单个分镜和单个视频后续仍可在镜头面板里单独覆盖模型、分辨率和连续性。",
            })}
          </span>
        </span>
        <span className="mt-0.5 rounded-[7px] border border-hairline-soft px-2 py-1 text-[11px] text-text-3">
          {t("dashboard:advanced_settings", { defaultValue: "高级设置" })}
        </span>
      </button>

      {expanded && (
        <div id="create-project-generation-profiles-panel" className="mt-4 space-y-4 border-t border-hairline-soft pt-4">
          {([
            ["asset", t("dashboard:generation_profile_asset")],
            ["storyboard", t("dashboard:storyboard_defaults_label", { defaultValue: "分镜图" })],
            ...(generationMode === "grid"
              ? ([["grid", t("dashboard:generation_profile_grid")]] as const)
              : []),
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
                  value={
                    key === "storyboard"
                      ? storyboardResolution
                      : profiles[key]?.resolution ?? ""
                  }
                  options={imageResolutionOptions.map((resolution) => ({
                    value: resolution,
                    label: resolution,
                  }))}
                  onChange={(next) => {
                    if (key === "storyboard") {
                      updateStoryboardResolution(next || null);
                      return;
                    }
                    onUpdateImage(key, { resolution: next || null });
                  }}
                  ariaLabel={t("templates:resolution_label")}
                  panelLabel={t("templates:resolution_label")}
                  className={PROFILE_INPUT_CLS}
                />
              </label>
            </div>
          ))}

          {([
            ["video", t("dashboard:video_defaults_label", { defaultValue: "分镜视频" })],
            ...(generationMode === "reference_video"
              ? ([["reference_video", t("dashboard:reference_video_defaults_label", { defaultValue: "参考视频" })]] as const)
              : []),
          ] as const).map(([key, label]) => {
            const currentResolution = key === "video" ? videoResolution : referenceVideoResolution;
            const currentAudioValue = key === "video" ? videoAudioValue : referenceVideoAudioValue;
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
                    value={currentResolution}
                    options={videoResolutionOptions.map((resolution) => ({
                      value: resolution,
                      label: resolution,
                    }))}
                    onChange={(next) => {
                      const patch = { resolution: next || null };
                      if (key === "video") {
                        updateVideoDefaults(patch);
                        return;
                      }
                      updateReferenceVideoDefaults(patch);
                    }}
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
                    value={currentAudioValue}
                    options={[
                      { value: "true", label: t("dashboard:enabled_label") },
                      { value: "false", label: t("dashboard:disabled_label") },
                    ]}
                    onChange={(next) => {
                      const patch = {
                        generate_audio: next === "true",
                      };
                      if (key === "video") {
                        updateVideoDefaults(patch);
                        return;
                      }
                      updateReferenceVideoDefaults(patch);
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

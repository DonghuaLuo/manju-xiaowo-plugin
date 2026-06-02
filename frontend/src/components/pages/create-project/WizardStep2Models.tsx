import { useTranslation } from "react-i18next";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ModelConfigSection, type ModelConfigValue } from "@/components/shared/ModelConfigSection";
import { ACCENT_BTN_CLS, ACCENT_BUTTON_STYLE, CARD_STYLE, GHOST_BTN_LG_CLS } from "@/components/ui/darkroom-tokens";
import {
  IMAGE_PROFILE_RESOLUTIONS,
  VIDEO_PROFILE_RESOLUTIONS,
  createDefaultGenerationProfiles,
  normalizeGenerationProfiles,
} from "@/utils/generation-profiles";
import type {
  GenerationProfiles,
  ImageGenerationProfile,
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
  useCustomGenerationProfiles: boolean;
  onUseCustomGenerationProfilesChange: (next: boolean) => void;
  generationProfiles: GenerationProfiles;
  onGenerationProfilesChange: (next: GenerationProfiles) => void;
  onBack: () => void;
  onNext: () => void;
  onCancel: () => void;
  data: WizardStep2Data | null;
  error: string | null;
}

export function WizardStep2Models({
  value,
  onChange,
  useCustomGenerationProfiles,
  onUseCustomGenerationProfilesChange,
  generationProfiles,
  onGenerationProfilesChange,
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

  const handleCustomProfilesToggle = (checked: boolean) => {
    onUseCustomGenerationProfilesChange(checked);
    if (checked) onGenerationProfilesChange(defaultGenerationProfiles);
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
          />
          <GenerationProfilesEditor
            enabled={useCustomGenerationProfiles}
            onEnabledChange={handleCustomProfilesToggle}
            profiles={normalizedGenerationProfiles}
            onUpdateImage={updateImageProfile}
            onUpdateVideo={updateVideoProfile}
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
            disabled={loading}
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
  enabled,
  onEnabledChange,
  profiles,
  onUpdateImage,
  onUpdateVideo,
}: {
  enabled: boolean;
  onEnabledChange: (next: boolean) => void;
  profiles: GenerationProfiles;
  onUpdateImage: (key: ImageProfileKey, patch: Partial<ImageGenerationProfile>) => void;
  onUpdateVideo: (key: VideoProfileKey, patch: Partial<VideoGenerationProfile>) => void;
}) {
  const { t } = useTranslation(["dashboard", "templates"]);
  return (
    <section className="rounded-[10px] border border-hairline p-4" style={CARD_STYLE}>
      <div className="flex items-start gap-3">
        <input
          id="create-project-generation-profiles-enabled"
          type="checkbox"
          checked={enabled}
          onChange={(event) => onEnabledChange(event.currentTarget.checked)}
          className="mt-0.5 h-4 w-4 rounded border-hairline-soft bg-bg-grad-a accent-[var(--color-accent)]"
        />
        <label htmlFor="create-project-generation-profiles-enabled" className="min-w-0 cursor-pointer">
          <span className="block font-mono text-[10px] font-bold uppercase tracking-[0.16em] text-accent-2">
            Quality Strategy
          </span>
          <span className="mt-1 block text-[13.5px] font-medium text-text">
            {t("dashboard:generation_profiles_section_title")}
          </span>
          <span className="mt-1 block text-[12.5px] leading-[1.55] text-text-3">
            {t("dashboard:generation_profiles_section_desc")}
          </span>
        </label>
      </div>

      {enabled && (
        <div className="mt-4 space-y-4 border-t border-hairline-soft pt-4">
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
                <select
                  value={profiles[key]?.resolution ?? ""}
                  onChange={(event) =>
                    onUpdateImage(key, { resolution: event.currentTarget.value || null })
                  }
                  className={PROFILE_INPUT_CLS}
                >
                  {IMAGE_PROFILE_RESOLUTIONS.map((resolution) => (
                    <option key={resolution} value={resolution}>
                      {resolution}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          ))}

          {([
            ["video_draft", t("dashboard:generation_profile_video_draft")],
            ["video_final", t("dashboard:generation_profile_video_final")],
            ["reference_video_draft", t("dashboard:generation_profile_reference_video_draft")],
            ["reference_video_final", t("dashboard:generation_profile_reference_video_final")],
          ] as const).map(([key, label]) => {
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
                  <select
                    value={profile?.resolution ?? ""}
                    onChange={(event) =>
                      onUpdateVideo(key, { resolution: event.currentTarget.value || null })
                    }
                    className={PROFILE_INPUT_CLS}
                  >
                    {VIDEO_PROFILE_RESOLUTIONS.map((resolution) => (
                      <option key={resolution} value={resolution}>
                        {resolution}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-[11px] text-text-3">
                    {t("dashboard:generate_audio_label")}
                  </span>
                  <select
                    value={audioValue}
                    onChange={(event) => {
                      const next = event.currentTarget.value;
                      onUpdateVideo(key, {
                        generate_audio: next === "project" ? null : next === "true",
                      });
                    }}
                    className={PROFILE_INPUT_CLS}
                  >
                    <option value="project">{t("dashboard:follow_global_default")}</option>
                    <option value="true">{t("dashboard:enabled_label")}</option>
                    <option value="false">{t("dashboard:disabled_label")}</option>
                  </select>
                </label>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

import type { GenerationProfiles } from "@/types";

export const IMAGE_PROFILE_RESOLUTIONS = ["512px", "1K", "2K", "4K"] as const;
export const VIDEO_PROFILE_RESOLUTIONS = ["480p", "720p", "1080p", "4K"] as const;

interface DefaultProfileInput {
  imageResolution?: string | null;
  videoResolution?: string | null;
}

export function createDefaultGenerationProfiles({
  imageResolution,
  videoResolution,
}: DefaultProfileInput = {}): GenerationProfiles {
  const finalImageResolution = imageResolution || "2K";
  const finalVideoResolution = videoResolution || "1080p";

  return {
    asset: {
      image_provider_t2i: null,
      image_provider_i2i: null,
      resolution: finalImageResolution,
    },
    storyboard_draft: {
      image_provider_t2i: null,
      image_provider_i2i: null,
      resolution: "1K",
    },
    storyboard_final: {
      image_provider_t2i: null,
      image_provider_i2i: null,
      resolution: finalImageResolution,
    },
    grid: {
      image_provider_t2i: null,
      image_provider_i2i: null,
      resolution: finalImageResolution,
    },
    video_draft: {
      video_backend: null,
      resolution: "720p",
      duration_seconds: null,
      generate_audio: false,
      service_tier: "default",
    },
    video_final: {
      video_backend: null,
      resolution: finalVideoResolution,
      duration_seconds: null,
      generate_audio: true,
      service_tier: "default",
    },
    reference_video_draft: {
      video_backend: null,
      resolution: "720p",
      duration_seconds: null,
      generate_audio: false,
      service_tier: "default",
    },
    reference_video_final: {
      video_backend: null,
      resolution: finalVideoResolution,
      duration_seconds: null,
      generate_audio: true,
      service_tier: "default",
    },
  };
}

export function normalizeGenerationProfiles(
  profiles?: GenerationProfiles | null,
  defaults: GenerationProfiles = createDefaultGenerationProfiles(),
): GenerationProfiles {
  const normalizeVideo = (profile?: GenerationProfiles["video_draft"]) => {
    const normalized = { ...(profile ?? {}) };
    delete normalized.duration_seconds;
    return normalized;
  };

  return {
    asset: { ...defaults.asset, ...(profiles?.asset ?? {}) },
    storyboard_draft: {
      ...defaults.storyboard_draft,
      ...(profiles?.storyboard_draft ?? {}),
    },
    storyboard_final: {
      ...defaults.storyboard_final,
      ...(profiles?.storyboard_final ?? {}),
    },
    grid: {
      ...defaults.grid,
      ...(profiles?.grid ?? {}),
    },
    video_draft: {
      ...defaults.video_draft,
      ...normalizeVideo(profiles?.video_draft),
    },
    video_final: {
      ...defaults.video_final,
      ...normalizeVideo(profiles?.video_final),
    },
    reference_video_draft: {
      ...defaults.reference_video_draft,
      ...normalizeVideo(profiles?.reference_video_draft),
    },
    reference_video_final: {
      ...defaults.reference_video_final,
      ...normalizeVideo(profiles?.reference_video_final),
    },
  };
}

export function generationProfilesSignature(profiles?: GenerationProfiles | null): string {
  return JSON.stringify(normalizeGenerationProfiles(profiles));
}

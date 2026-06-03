import type { GenerationProfiles, ShotTier, ShotTierProfile } from "@/types";

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

export const SHOT_TIERS = ["S", "A", "B"] as const satisfies readonly ShotTier[];
export const REFERENCE_IMAGE_POLICIES = ["full_context", "balanced", "lean"] as const;
const VIDEO_CONTINUITY_PROFILE_POLICIES = ["auto", "start_only", "end_frame", "reference_assisted"] as const;

export type ShotTierProfiles = Partial<Record<ShotTier, ShotTierProfile>>;

export function createDefaultShotTierProfiles(): Record<ShotTier, ShotTierProfile> {
  return {
    S: {
      label: "hero",
      retry_budget: 1,
      reference_image_policy: "full_context",
      video_continuity_policy: "auto",
      prefer_final_storyboard_source: true,
      profiles: {
        storyboard_final: {
          resolution: "2K",
        },
        video_final: {
          resolution: "1080p",
          generate_audio: true,
          service_tier: "default",
        },
      },
    },
    A: {
      label: "standard",
      retry_budget: 1,
      reference_image_policy: "balanced",
      video_continuity_policy: "auto",
      prefer_final_storyboard_source: true,
      profiles: {},
    },
    B: {
      label: "utility",
      retry_budget: 1,
      reference_image_policy: "lean",
      video_continuity_policy: "start_only",
      prefer_final_storyboard_source: false,
      profiles: {
        storyboard_final: {
          resolution: "1K",
        },
        video_final: {
          resolution: "720p",
          generate_audio: false,
          service_tier: "default",
        },
      },
    },
  };
}

export function normalizeShotTierProfiles(
  profiles?: ShotTierProfiles | null,
): Record<ShotTier, ShotTierProfile> {
  const defaults = createDefaultShotTierProfiles();
  return Object.fromEntries(
    SHOT_TIERS.map((tier) => {
      const raw: ShotTierProfile = profiles?.[tier] ?? {};
      return [
        tier,
        {
          ...defaults[tier],
          ...raw,
          retry_budget: Number.isFinite(Number(raw.retry_budget))
            ? Math.max(1, Math.floor(Number(raw.retry_budget)))
            : defaults[tier].retry_budget,
          profiles: {
            ...(defaults[tier].profiles ?? {}),
            ...(raw.profiles ?? {}),
          },
          video_continuity_policy: VIDEO_CONTINUITY_PROFILE_POLICIES.includes(
            raw.video_continuity_policy as typeof VIDEO_CONTINUITY_PROFILE_POLICIES[number],
          )
            ? raw.video_continuity_policy
            : defaults[tier].video_continuity_policy,
        },
      ];
    }),
  ) as Record<ShotTier, ShotTierProfile>;
}

export function shotTierProfilesSignature(profiles?: ShotTierProfiles | null): string {
  return JSON.stringify(normalizeShotTierProfiles(profiles));
}

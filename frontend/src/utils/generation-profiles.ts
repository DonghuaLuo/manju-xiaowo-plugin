import type { GenerationProfiles, ShotTier, ShotTierProfile } from "@/types";

export const IMAGE_PROFILE_RESOLUTIONS = ["512px", "1K", "2K", "4K"] as const;
export const VIDEO_PROFILE_RESOLUTIONS = ["480p", "720p", "1080p", "4K"] as const;

interface DefaultProfileInput {
  imageResolution?: string | null;
  videoResolution?: string | null;
  imageResolutionOptions?: readonly string[] | null;
  videoResolutionOptions?: readonly string[] | null;
}

const IMAGE_FINAL_FALLBACK = "2K";
const IMAGE_DRAFT_FALLBACK = "1K";
const VIDEO_FINAL_FALLBACK = "1080p";
const VIDEO_DRAFT_FALLBACK = "720p";

function uniqueOptions(options?: readonly string[] | null): string[] {
  return Array.from(
    new Set((options ?? []).map((option) => option.trim()).filter(Boolean)),
  );
}

function findMatchingOption(options: readonly string[], value?: string | null): string | null {
  const trimmed = value?.trim();
  if (!trimmed) return null;
  return (
    options.find((option) => option === trimmed) ??
    options.find((option) => option.toLowerCase() === trimmed.toLowerCase()) ??
    null
  );
}

function resolutionRank(value?: string | null): number | null {
  const normalized = value?.trim().toLowerCase();
  if (!normalized) return null;
  const dimensionMatch = normalized.match(/(\d+(?:\.\d+)?)\s*(?:x|\*|×)\s*(\d+(?:\.\d+)?)/);
  if (dimensionMatch) {
    return Math.min(Number(dimensionMatch[1]), Number(dimensionMatch[2]));
  }
  const unitMatch = normalized.match(/^(\d+(?:\.\d+)?)\s*(k|p|px)$/);
  if (!unitMatch) return null;
  const valueNumber = Number(unitMatch[1]);
  if (!Number.isFinite(valueNumber)) return null;
  if (unitMatch[2] === "k") return valueNumber * 1024;
  return valueNumber;
}

export function coerceResolutionForOptions(
  value: string | null | undefined,
  options: readonly string[] | null | undefined,
  fallback: string,
): string {
  const candidates = uniqueOptions(options);
  const preferred = value?.trim() || fallback;
  if (candidates.length === 0) return preferred;

  const exact = findMatchingOption(candidates, preferred) ?? findMatchingOption(candidates, fallback);
  if (exact) return exact;

  const targetRank = resolutionRank(preferred) ?? resolutionRank(fallback);
  if (targetRank !== null) {
    const rankedCandidates = candidates
      .map((option) => ({ option, rank: resolutionRank(option) }))
      .filter((item): item is { option: string; rank: number } => item.rank !== null)
      .sort((a, b) => a.rank - b.rank);
    const lowerOrEqual = rankedCandidates.filter((item) => item.rank <= targetRank).at(-1);
    if (lowerOrEqual) return lowerOrEqual.option;
    if (rankedCandidates.length > 0) return rankedCandidates[0].option;
  }

  return candidates[0];
}

export function createDefaultGenerationProfiles({
  imageResolution,
  videoResolution,
  imageResolutionOptions,
  videoResolutionOptions,
}: DefaultProfileInput = {}): GenerationProfiles {
  const finalImageResolution = coerceResolutionForOptions(
    imageResolution,
    imageResolutionOptions,
    IMAGE_FINAL_FALLBACK,
  );
  const draftImageResolution = coerceResolutionForOptions(
    IMAGE_DRAFT_FALLBACK,
    imageResolutionOptions,
    finalImageResolution,
  );
  const finalVideoResolution = coerceResolutionForOptions(
    videoResolution,
    videoResolutionOptions,
    VIDEO_FINAL_FALLBACK,
  );
  const draftVideoResolution = coerceResolutionForOptions(
    VIDEO_DRAFT_FALLBACK,
    videoResolutionOptions,
    finalVideoResolution,
  );

  return {
    asset: {
      image_provider_t2i: null,
      image_provider_i2i: null,
      resolution: finalImageResolution,
    },
    storyboard_draft: {
      image_provider_t2i: null,
      image_provider_i2i: null,
      resolution: draftImageResolution,
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
      resolution: draftVideoResolution,
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
      resolution: draftVideoResolution,
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

export function createDefaultShotTierProfiles(
  input: DefaultProfileInput = {},
): Record<ShotTier, ShotTierProfile> {
  const defaults = createDefaultGenerationProfiles(input);
  const finalImageResolution = defaults.storyboard_final?.resolution ?? IMAGE_FINAL_FALLBACK;
  const draftImageResolution = defaults.storyboard_draft?.resolution ?? finalImageResolution;
  const finalVideoResolution = defaults.video_final?.resolution ?? VIDEO_FINAL_FALLBACK;
  const draftVideoResolution = defaults.video_draft?.resolution ?? finalVideoResolution;

  return {
    S: {
      label: "hero",
      retry_budget: 1,
      reference_image_policy: "full_context",
      video_continuity_policy: "auto",
      prefer_final_storyboard_source: true,
      profiles: {
        storyboard_final: {
          resolution: finalImageResolution,
        },
        video_final: {
          resolution: finalVideoResolution,
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
          resolution: draftImageResolution,
        },
        video_final: {
          resolution: draftVideoResolution,
          generate_audio: false,
          service_tier: "default",
        },
      },
    },
  };
}

export function normalizeShotTierProfiles(
  profiles?: ShotTierProfiles | null,
  defaults: Record<ShotTier, ShotTierProfile> = createDefaultShotTierProfiles(),
): Record<ShotTier, ShotTierProfile> {
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

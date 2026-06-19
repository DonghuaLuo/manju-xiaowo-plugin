import type { GenerationProfiles } from "@/types";

export const IMAGE_PROFILE_RESOLUTIONS = ["1K", "2K", "3K", "4K"] as const;
export const VIDEO_PROFILE_RESOLUTIONS = ["480p", "720p", "1080p", "4K"] as const;

interface DefaultProfileInput {
  imageResolution?: string | null;
  videoResolution?: string | null;
  imageResolutionOptions?: readonly string[] | null;
  videoResolutionOptions?: readonly string[] | null;
}

const IMAGE_CHANNEL_FALLBACK = "1K";
const VIDEO_CHANNEL_FALLBACK = "720p";
const ASSET_FALLBACK = "1K";
const GRID_FALLBACK = "2K";

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
  const channelImageResolution = coerceResolutionForOptions(
    imageResolution,
    imageResolutionOptions,
    IMAGE_CHANNEL_FALLBACK,
  );
  const assetResolution = coerceResolutionForOptions(
    ASSET_FALLBACK,
    imageResolutionOptions,
    channelImageResolution,
  );
  const gridResolution = coerceResolutionForOptions(
    GRID_FALLBACK,
    imageResolutionOptions,
    channelImageResolution,
  );
  const channelVideoResolution = coerceResolutionForOptions(
    videoResolution,
    videoResolutionOptions,
    VIDEO_CHANNEL_FALLBACK,
  );

  return {
    asset: {
      image_provider_t2i: null,
      image_provider_i2i: null,
      resolution: assetResolution,
    },
    storyboard_draft: {
      image_provider_t2i: null,
      image_provider_i2i: null,
      resolution: channelImageResolution,
    },
    storyboard_final: {
      image_provider_t2i: null,
      image_provider_i2i: null,
      resolution: channelImageResolution,
    },
    grid: {
      image_provider_t2i: null,
      image_provider_i2i: null,
      resolution: gridResolution,
    },
    video_draft: {
      video_backend: null,
      resolution: channelVideoResolution,
      duration_seconds: null,
      generate_audio: false,
    },
    video_final: {
      video_backend: null,
      resolution: channelVideoResolution,
      duration_seconds: null,
      generate_audio: true,
    },
    reference_video_draft: {
      video_backend: null,
      resolution: channelVideoResolution,
      duration_seconds: null,
      generate_audio: false,
    },
    reference_video_final: {
      video_backend: null,
      resolution: channelVideoResolution,
      duration_seconds: null,
      generate_audio: true,
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
    delete normalized.service_tier;
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

function pruneNullishEntries<T extends Record<string, unknown>>(value: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => item !== null && item !== undefined),
  ) as Partial<T>;
}

function isShallowEqualRecord(
  left: Record<string, unknown> | null | undefined,
  right: Record<string, unknown> | null | undefined,
): boolean {
  const leftEntries = Object.entries(left ?? {});
  const rightEntries = Object.entries(right ?? {});
  if (leftEntries.length !== rightEntries.length) return false;
  return leftEntries.every(([key, value]) => right?.[key] === value);
}

export function compactGenerationProfiles(
  profiles?: GenerationProfiles | null,
  defaults: GenerationProfiles = createDefaultGenerationProfiles(),
): GenerationProfiles {
  const normalized = normalizeGenerationProfiles(profiles, defaults);
  const compact: GenerationProfiles = {};

  const collect = (key: keyof GenerationProfiles) => {
    const current = pruneNullishEntries((normalized[key] ?? {}) as Record<string, unknown>);
    const baseline = pruneNullishEntries((defaults[key] ?? {}) as Record<string, unknown>);
    if (!isShallowEqualRecord(current, baseline) && Object.keys(current).length > 0) {
      compact[key] = current;
    }
  };

  collect("asset");
  collect("storyboard_draft");
  collect("storyboard_final");
  collect("grid");
  collect("video_draft");
  collect("video_final");
  collect("reference_video_draft");
  collect("reference_video_final");

  return compact;
}

export function generationProfilesSignature(profiles?: GenerationProfiles | null): string {
  return JSON.stringify(normalizeGenerationProfiles(profiles));
}

import type { VideoContinuityMetadata } from "@/api";
import type { DramaScene, NarrationSegment, VideoContinuityPolicy } from "@/types";
import type { VideoContinuitySupport } from "@/utils/provider-models";

type Segment = NarrationSegment | DramaScene;

export type VideoContinuityEffectivePolicy = "start_only" | "end_frame" | "reference_assisted";

export interface ShotVideoContinuityPlan {
  requestedPolicy: VideoContinuityPolicy;
  effectivePolicy: VideoContinuityEffectivePolicy;
  reason?: string;
  nextStoryboardId?: string;
}

export const VIDEO_CONTINUITY_POLICIES = [
  "auto",
  "start_only",
  "end_frame",
  "reference_assisted",
] as const satisfies readonly VideoContinuityPolicy[];

const POLICIES = new Set<VideoContinuityPolicy>(VIDEO_CONTINUITY_POLICIES);

const EFFECTIVE_POLICIES = new Set<VideoContinuityEffectivePolicy>([
  "start_only",
  "end_frame",
  "reference_assisted",
]);

export function normalizeVideoContinuityPolicy(value: unknown): VideoContinuityPolicy {
  const policy = String(value ?? "auto").trim().toLowerCase() as VideoContinuityPolicy;
  return POLICIES.has(policy) ? policy : "auto";
}

function segmentId(segment: Segment | null | undefined): string | undefined {
  if (!segment) return undefined;
  const raw = "segment_id" in segment ? segment.segment_id : segment.scene_id;
  return raw || undefined;
}

function referenceSet(segment: Segment | null | undefined, field: "scenes"): Set<string> {
  const value = segment?.[field];
  if (!Array.isArray(value)) return new Set();
  return new Set(value.map((item) => String(item).trim()).filter(Boolean));
}

function sceneChanged(current: Segment, next: Segment): boolean {
  const currentScenes = referenceSet(current, "scenes");
  const nextScenes = referenceSet(next, "scenes");
  if (currentScenes.size === 0 || nextScenes.size === 0) return false;
  for (const item of currentScenes) {
    if (nextScenes.has(item)) return false;
  }
  return true;
}

function autoSkipReason(current: Segment, next: Segment): string | undefined {
  const transition = String(current.transition_to_next ?? "cut").trim().toLowerCase();
  if (transition === "fade" || transition === "dissolve") return `transition_${transition}`;
  if (Boolean(next.segment_break)) return "next_segment_break";
  if (sceneChanged(current, next)) return "scene_changed";
  return undefined;
}

export function resolveExpectedShotVideoContinuity({
  policy,
  support,
  currentSegment,
  nextSegment,
}: {
  policy: VideoContinuityPolicy | null | undefined;
  support: VideoContinuitySupport | null | undefined;
  currentSegment: Segment;
  nextSegment?: Segment;
}): ShotVideoContinuityPlan {
  const requestedPolicy = normalizeVideoContinuityPolicy(policy);
  const capabilities = support ?? {
    endFrame: false,
    referenceImages: false,
    referenceWithStartImage: false,
  };

  const startOnly = (reason?: string): ShotVideoContinuityPlan => ({
    requestedPolicy,
    effectivePolicy: "start_only",
    reason,
    nextStoryboardId: segmentId(nextSegment),
  });

  if (requestedPolicy === "start_only") return startOnly("policy_start_only");
  if (!nextSegment) return startOnly("last_storyboard");

  const nextStoryboardId = segmentId(nextSegment);
  if (!nextSegment.generated_assets?.storyboard_image) {
    return {
      ...startOnly("next_storyboard_missing"),
      nextStoryboardId,
    };
  }

  if (requestedPolicy === "auto") {
    const skipReason = autoSkipReason(currentSegment, nextSegment);
    if (skipReason) return startOnly(skipReason);
    if (capabilities.endFrame) {
      return { requestedPolicy, effectivePolicy: "end_frame", nextStoryboardId };
    }
    if (capabilities.referenceImages && capabilities.referenceWithStartImage) {
      return { requestedPolicy, effectivePolicy: "reference_assisted", nextStoryboardId };
    }
    if (capabilities.referenceImages) return startOnly("provider_no_reference_with_start_image");
    return startOnly("provider_no_end_image");
  }

  if (requestedPolicy === "reference_assisted") {
    if (!capabilities.referenceImages) return startOnly("provider_no_reference_images");
    if (!capabilities.referenceWithStartImage) return startOnly("provider_no_reference_with_start_image");
    return { requestedPolicy, effectivePolicy: "reference_assisted", nextStoryboardId };
  }

  if (capabilities.endFrame) {
    return { requestedPolicy, effectivePolicy: "end_frame", nextStoryboardId };
  }
  return startOnly("provider_no_end_image");
}

export function videoContinuityMetadataToPlan(
  metadata: VideoContinuityMetadata | null | undefined,
): ShotVideoContinuityPlan | null {
  if (!metadata) return null;
  const requestedPolicy = normalizeVideoContinuityPolicy(metadata.requested_policy);
  const effective = String(metadata.effective_policy ?? "start_only").trim().toLowerCase();
  const effectivePolicy = EFFECTIVE_POLICIES.has(effective as VideoContinuityEffectivePolicy)
    ? (effective as VideoContinuityEffectivePolicy)
    : "start_only";
  return {
    requestedPolicy,
    effectivePolicy,
    reason: metadata.skip_reason,
    nextStoryboardId: metadata.end_storyboard_id,
  };
}

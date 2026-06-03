import { describe, expect, it } from "vitest";

import type { NarrationSegment } from "@/types";
import { resolveExpectedShotVideoContinuity } from "./video-continuity";

function segment(
  id: string,
  overrides: Partial<NarrationSegment> = {},
): NarrationSegment {
  return {
    segment_id: id,
    episode: 1,
    duration_seconds: 5,
    segment_break: false,
    novel_text: "",
    characters_in_segment: [],
    image_prompt: "",
    video_prompt: "",
    scenes: ["祠堂"],
    props: [],
    transition_to_next: "cut",
    generated_assets: {
      storyboard_image: `storyboards/scene_${id}.png`,
      storyboard_last_image: null,
      grid_id: null,
      grid_cell_index: null,
      video_clip: null,
      video_thumbnail: null,
      video_uri: null,
      status: "pending",
    },
    ...overrides,
  };
}

describe("resolveExpectedShotVideoContinuity", () => {
  it("uses reference-assisted under auto when end frame is unavailable", () => {
    const plan = resolveExpectedShotVideoContinuity({
      policy: "auto",
      support: { endFrame: false, referenceImages: true, referenceWithStartImage: true },
      currentSegment: segment("E1S01"),
      nextSegment: segment("E1S02"),
    });

    expect(plan.effectivePolicy).toBe("reference_assisted");
    expect(plan.nextStoryboardId).toBe("E1S02");
  });

  it("does not use reference-assisted when references would drop the start frame", () => {
    const plan = resolveExpectedShotVideoContinuity({
      policy: "auto",
      support: { endFrame: false, referenceImages: true, referenceWithStartImage: false },
      currentSegment: segment("E1S01"),
      nextSegment: segment("E1S02"),
    });

    expect(plan.effectivePolicy).toBe("start_only");
    expect(plan.reason).toBe("provider_no_reference_with_start_image");
    expect(plan.nextStoryboardId).toBe("E1S02");
  });

  it("keeps end frame preferred under auto when available", () => {
    const plan = resolveExpectedShotVideoContinuity({
      policy: "auto",
      support: { endFrame: true, referenceImages: true, referenceWithStartImage: false },
      currentSegment: segment("E1S01"),
      nextSegment: segment("E1S02"),
    });

    expect(plan.effectivePolicy).toBe("end_frame");
    expect(plan.nextStoryboardId).toBe("E1S02");
  });
});

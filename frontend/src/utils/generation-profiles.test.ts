import { describe, expect, it } from "vitest";
import {
  coerceResolutionForOptions,
  createDefaultGenerationProfiles,
} from "./generation-profiles";

describe("generation profile resolution defaults", () => {
  it("chooses supported defaults for constrained provider models", () => {
    const profiles = createDefaultGenerationProfiles({
      imageResolutionOptions: ["1K"],
      videoResolutionOptions: ["480p", "720p"],
    });

    expect(profiles.asset?.resolution).toBe("1K");
    expect(profiles.storyboard_final?.resolution).toBe("1K");
    expect(profiles.storyboard_draft?.resolution).toBe("1K");
    expect(profiles.video_final?.resolution).toBe("720p");
    expect(profiles.video_draft?.resolution).toBe("720p");
  });

  it("defaults role, scene, and prop master assets to 1K", () => {
    const profiles = createDefaultGenerationProfiles({
      imageResolutionOptions: ["1K", "2K", "3K", "4K"],
    });

    expect(profiles.asset?.resolution).toBe("1K");
  });

  it("preserves exact supported options before falling back to nearest lower option", () => {
    expect(coerceResolutionForOptions("1080p", ["720p", "1080p", "4K"], "720p")).toBe("1080p");
    expect(coerceResolutionForOptions("4K", ["480p", "720p", "1080p"], "1080p")).toBe("1080p");
  });
});

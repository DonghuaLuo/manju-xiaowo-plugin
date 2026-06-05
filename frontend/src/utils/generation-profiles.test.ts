import { describe, expect, it } from "vitest";
import {
  coerceResolutionForOptions,
  createDefaultGenerationProfiles,
  createDefaultShotTierProfiles,
} from "./generation-profiles";

describe("generation profile resolution defaults", () => {
  it("chooses supported defaults for constrained provider models", () => {
    const profiles = createDefaultGenerationProfiles({
      imageResolutionOptions: ["512px", "1K"],
      videoResolutionOptions: ["480p", "720p"],
    });

    expect(profiles.storyboard_final?.resolution).toBe("1K");
    expect(profiles.storyboard_draft?.resolution).toBe("1K");
    expect(profiles.video_final?.resolution).toBe("720p");
    expect(profiles.video_draft?.resolution).toBe("720p");
  });

  it("applies the same supported defaults to shot-tier overrides", () => {
    const tiers = createDefaultShotTierProfiles({
      imageResolutionOptions: ["512px"],
      videoResolutionOptions: ["480p"],
    });

    expect(tiers.S.profiles?.storyboard_final?.resolution).toBe("512px");
    expect(tiers.S.profiles?.video_final?.resolution).toBe("480p");
    expect(tiers.B.profiles?.storyboard_final?.resolution).toBe("512px");
    expect(tiers.B.profiles?.video_final?.resolution).toBe("480p");
  });

  it("preserves exact supported options before falling back to nearest lower option", () => {
    expect(coerceResolutionForOptions("1080p", ["720p", "1080p", "4K"], "720p")).toBe("1080p");
    expect(coerceResolutionForOptions("4K", ["480p", "720p", "1080p"], "1080p")).toBe("1080p");
  });
});

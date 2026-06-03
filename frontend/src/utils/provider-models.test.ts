import { describe, expect, it } from "vitest";
import {
  lookupStoryboardVideoStartImageSupport,
  storyboardVideoStartImageSupportFromCapabilities,
} from "./provider-models";

describe("provider-models storyboard video start image support", () => {
  it("flags known reference-only video models as unsupported for current-storyboard video", () => {
    expect(lookupStoryboardVideoStartImageSupport("dashscope/happyhorse-1.0-r2v")).toBe(false);
    expect(lookupStoryboardVideoStartImageSupport("vidu/viduq3-mix")).toBe(false);
  });

  it("allows models that can use the current storyboard as start image", () => {
    expect(lookupStoryboardVideoStartImageSupport("dashscope/wan2.7-r2v")).toBe(true);
    expect(lookupStoryboardVideoStartImageSupport("vidu/viduq3-turbo")).toBe(true);
    expect(lookupStoryboardVideoStartImageSupport("openai/sora-2")).toBe(true);
  });

  it("uses backend capabilities when they are available", () => {
    expect(
      storyboardVideoStartImageSupportFromCapabilities({
        supports_start_image: false,
        video_continuity_capabilities: ["reference_images"],
      }),
    ).toBe(false);
    expect(
      storyboardVideoStartImageSupportFromCapabilities({
        supports_start_image: false,
        supports_reference_with_start_image: true,
        video_continuity_capabilities: ["reference_images", "reference_images_with_start_image"],
      }),
    ).toBe(true);
  });
});

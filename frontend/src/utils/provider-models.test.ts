import { describe, expect, it } from "vitest";
import {
  lookupVideoServiceTiers,
  lookupStoryboardVideoStartImageSupport,
  storyboardVideoStartImageSupportFromCapabilities,
  videoServiceTiersFromCapabilities,
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

describe("provider-models video service tiers", () => {
  it("derives tiers from explicit capability payloads", () => {
    expect(videoServiceTiersFromCapabilities({ service_tiers: ["default"] })).toEqual(["default"]);
    expect(videoServiceTiersFromCapabilities({ supports_service_tier: true })).toEqual(["default", "flex"]);
    expect(videoServiceTiersFromCapabilities({ capabilities: ["text_to_video", "flex_tier"] })).toEqual([
      "default",
      "flex",
    ]);
  });

  it("looks up built-in model tiers from flex_tier capability", () => {
    const providers = [
      {
        id: "ark",
        display_name: "Ark",
        description: "",
        status: "ready",
        media_types: ["video"],
        capabilities: [],
        configured_keys: [],
        missing_keys: [],
        models: {
          "doubao-seedance-1-5-pro": {
            display_name: "Seedance 1.5",
            media_type: "video",
            capabilities: ["text_to_video", "flex_tier"],
            default: true,
            supported_durations: [5],
            duration_resolution_constraints: {},
            resolutions: ["720p"],
          },
          "doubao-seedance-2-0": {
            display_name: "Seedance 2",
            media_type: "video",
            capabilities: ["text_to_video"],
            default: false,
            supported_durations: [5],
            duration_resolution_constraints: {},
            resolutions: ["720p"],
          },
        },
      },
    ] as Parameters<typeof lookupVideoServiceTiers>[0];

    expect(lookupVideoServiceTiers(providers, "ark/doubao-seedance-1-5-pro")).toEqual(["default", "flex"]);
    expect(lookupVideoServiceTiers(providers, "ark/doubao-seedance-2-0")).toEqual(["default"]);
  });

  it("keeps custom ark-seedance flex disabled for Seedance 2 models", () => {
    const customProviders = [
      {
        id: 7,
        display_name: "Custom Ark",
        discovery_format: "openai",
        base_url: "",
        api_key_masked: "",
        created_at: "",
        models: [
          {
            id: 1,
            model_id: "doubao-seedance-1.5-pro",
            display_name: "Seedance 1.5",
            endpoint: "ark-seedance",
            is_default: true,
            is_enabled: true,
            price_unit: null,
            price_input: null,
            price_output: null,
            currency: null,
            supported_durations: [5],
            resolution: null,
          },
          {
            id: 2,
            model_id: "doubao-seedance-2.0",
            display_name: "Seedance 2",
            endpoint: "ark-seedance",
            is_default: false,
            is_enabled: true,
            price_unit: null,
            price_input: null,
            price_output: null,
            currency: null,
            supported_durations: [5],
            resolution: null,
          },
        ],
      },
    ] as Parameters<typeof lookupVideoServiceTiers>[2];

    expect(lookupVideoServiceTiers([], "custom-7/doubao-seedance-1.5-pro", customProviders)).toEqual([
      "default",
      "flex",
    ]);
    expect(lookupVideoServiceTiers([], "custom-7/doubao-seedance-2.0", customProviders)).toEqual(["default"]);
  });
});

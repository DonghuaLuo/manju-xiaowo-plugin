import { describe, expect, it } from "vitest";
import {
  lookupResolutions,
  lookupSharedImageOutputFormats,
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

describe("provider-models image output formats", () => {
  const providers = [
    {
      id: "openai",
      display_name: "OpenAI",
      description: "",
      status: "ready",
      media_types: ["image"],
      capabilities: [],
      configured_keys: [],
      missing_keys: [],
      models: {
        "gpt-image-2": {
          display_name: "GPT Image 2",
          media_type: "image",
          capabilities: ["text_to_image", "image_to_image"],
          default: true,
          image_output_formats: ["png", "jpg", "webp"],
          supported_durations: [],
          duration_resolution_constraints: {},
          resolutions: ["1K"],
        },
        "gpt-image-png": {
          display_name: "GPT Image PNG",
          media_type: "image",
          capabilities: ["text_to_image", "image_to_image"],
          default: false,
          image_output_formats: ["png"],
          supported_durations: [],
          duration_resolution_constraints: {},
          resolutions: ["1K"],
        },
      },
    },
    {
      id: "gemini-aistudio",
      display_name: "Gemini",
      description: "",
      status: "ready",
      media_types: ["image"],
      capabilities: [],
      configured_keys: [],
      missing_keys: [],
      models: {
        "imagen": {
          display_name: "Imagen",
          media_type: "image",
          capabilities: ["text_to_image"],
          default: true,
          image_output_formats: [],
          supported_durations: [],
          duration_resolution_constraints: {},
          resolutions: ["1K"],
        },
      },
    },
  ] as Parameters<typeof lookupSharedImageOutputFormats>[0];

  it("returns only formats supported by all selected image backends", () => {
    expect(
      lookupSharedImageOutputFormats(providers, [
        "openai/gpt-image-2",
        "openai/gpt-image-png",
      ]),
    ).toEqual(["png"]);
  });

  it("uses the selected model formats when both image slots resolve to the same backend", () => {
    expect(
      lookupSharedImageOutputFormats(providers, [
        "openai/gpt-image-2",
        "openai/gpt-image-2",
      ]),
    ).toEqual(["png", "jpg", "webp"]);
  });

  it("hides provider output format choices when any selected backend has no support", () => {
    expect(
      lookupSharedImageOutputFormats(providers, [
        "openai/gpt-image-2",
        "gemini-aistudio/imagen",
      ]),
    ).toEqual([]);
  });
});

describe("provider-models custom image resolutions", () => {
  const customProviders = [
    {
      id: 12,
      display_name: "Custom Images",
      discovery_format: "openai",
      base_url: "",
      api_key_masked: "",
      created_at: "",
      models: [
        {
          id: 1,
          model_id: "gpt-image-2",
          display_name: "GPT Image 2",
          endpoint: "openai-images",
          is_default: true,
          is_enabled: true,
          price_unit: null,
          price_input: null,
          price_output: null,
          currency: null,
          supported_durations: [],
          resolution: null,
        },
        {
          id: 2,
          model_id: "gemini-3.1-flash-image-preview",
          display_name: "Gemini 3.1 Flash Image",
          endpoint: "gemini-image",
          is_default: false,
          is_enabled: true,
          price_unit: null,
          price_input: null,
          price_output: null,
          currency: null,
          supported_durations: [],
          resolution: null,
        },
      ],
    },
  ] as Parameters<typeof lookupResolutions>[2];

  it("uses GPT Image 2's current OpenAI tiers for custom OpenAI-image relays", () => {
    expect(
      lookupResolutions([], "custom-12/gpt-image-2", customProviders, {
        "openai-images": "image",
      }).options,
    ).toEqual(["1K", "2K", "3K", "4K"]);
  });

  it("uses standard K tiers for custom Gemini image endpoints", () => {
    expect(
      lookupResolutions([], "custom-12/gemini-3.1-flash-image-preview", customProviders, {
        "gemini-image": "image",
      }).options,
    ).toEqual(["1K", "2K", "3K", "4K"]);
  });
});

import { API } from "@/api";
import type { CustomProviderInfo, MediaType, ProviderInfo } from "@/types";

const CUSTOM_PREFIX = "custom-";

// ---------------------------------------------------------------------------
// Built-in providers cache
// ---------------------------------------------------------------------------

let _cache: ProviderInfo[] | null = null;
let _promise: Promise<ProviderInfo[]> | null = null;

/** Fetch (or return cached) built-in provider list including models. */
export async function getProviderModels(): Promise<ProviderInfo[]> {
  if (_cache) return _cache;
  if (!_promise) {
    _promise = API.getProviders()
      .then((res) => {
        _cache = res.providers;
        _promise = null;
        return _cache;
      })
      .catch((err) => {
        _promise = null;
        throw err;
      });
  }
  return _promise;
}

// ---------------------------------------------------------------------------
// Custom providers cache
// ---------------------------------------------------------------------------

let _customCache: CustomProviderInfo[] | null = null;
let _customPromise: Promise<CustomProviderInfo[]> | null = null;

/** Fetch (or return cached) custom provider list. */
export async function getCustomProviderModels(): Promise<CustomProviderInfo[]> {
  if (_customCache) return _customCache;
  if (!_customPromise) {
    _customPromise = API.listCustomProviders()
      .then((res) => {
        _customCache = res.providers;
        _customPromise = null;
        return _customCache;
      })
      .catch((err) => {
        _customPromise = null;
        throw err;
      });
  }
  return _customPromise;
}

// ---------------------------------------------------------------------------
// Cache invalidation
// ---------------------------------------------------------------------------

/** Invalidate all provider caches (call after provider config changes). */
export function invalidateProviderModelsCache(): void {
  _cache = null;
  _promise = null;
  _customCache = null;
  _customPromise = null;
}

// ---------------------------------------------------------------------------
// Lookup
// ---------------------------------------------------------------------------

/**
 * Given a video backend string like "gemini-aistudio/veo-3.1-generate-preview"
 * or "custom-3/my-model", look up supported_durations.
 * Returns undefined if provider/model not found.
 */
export function lookupSupportedDurations(
  providers: ProviderInfo[],
  videoBackend: string,
  customProviders?: CustomProviderInfo[],
): number[] | undefined {
  const slashIdx = videoBackend.indexOf("/");
  if (slashIdx === -1) return undefined;
  const providerId = videoBackend.slice(0, slashIdx);
  const modelId = videoBackend.slice(slashIdx + 1);

  // Custom provider: "custom-{db_id}/{model_id}"
  if (providerId.startsWith(CUSTOM_PREFIX) && customProviders) {
    const dbId = parseInt(providerId.slice(CUSTOM_PREFIX.length), 10);
    const cp = customProviders.find((p) => p.id === dbId);
    const model = cp?.models?.find((m) => m.model_id === modelId);
    if (model?.supported_durations?.length) {
      return model.supported_durations;
    }
    return undefined;
  }

  // Built-in provider
  const provider = providers.find((p) => p.id === providerId);
  const model = provider?.models?.[modelId];
  return model?.supported_durations?.length
    ? model.supported_durations
    : undefined;
}

// ---------------------------------------------------------------------------
// Resolution lookup
// ---------------------------------------------------------------------------

export const IMAGE_STANDARD_RESOLUTIONS = ["512px", "1K", "2K", "4K"];
export const VIDEO_STANDARD_RESOLUTIONS = ["480p", "720p", "1080p", "4K"];

/** 返回该 (provider, model) 下的分辨率候选 + 是否自定义供应商（决定 picker 模式）。
 *  自定义 provider 路径需要从 endpoint 推 media_type 选标准分辨率集；该 map 由调用方
 *  从 endpoint-catalog-store 读出注入（保持本文件无 store 副作用）。 */
export function lookupResolutions(
  providers: ProviderInfo[],
  backend: string,
  customProviders?: CustomProviderInfo[],
  endpointToMediaType?: Record<string, MediaType>,
): { options: string[]; isCustom: boolean } {
  const slashIdx = backend.indexOf("/");
  if (slashIdx === -1) return { options: [], isCustom: false };
  const providerId = backend.slice(0, slashIdx);
  const modelId = backend.slice(slashIdx + 1);

  if (providerId.startsWith(CUSTOM_PREFIX) && customProviders) {
    const dbId = parseInt(providerId.slice(CUSTOM_PREFIX.length), 10);
    const cp = customProviders.find((p) => p.id === dbId);
    const model = cp?.models?.find((m) => m.model_id === modelId);
    if (!model) return { options: [], isCustom: true };
    const media = endpointToMediaType?.[model.endpoint];
    const standard =
      media === "image"
        ? IMAGE_STANDARD_RESOLUTIONS
        : media === "video"
          ? VIDEO_STANDARD_RESOLUTIONS
          : [];
    return { options: standard, isCustom: true };
  }

  const provider = providers.find((p) => p.id === providerId);
  const model = provider?.models?.[modelId];
  return { options: model?.resolutions ?? [], isCustom: false };
}

export type VideoServiceTier = "default" | "flex";

const VIDEO_SERVICE_TIERS = ["default", "flex"] as const satisfies readonly VideoServiceTier[];

function normalizeVideoServiceTiers(items?: readonly unknown[] | null): VideoServiceTier[] | null {
  if (!items?.length) return null;
  const set = new Set<VideoServiceTier>();
  for (const item of items) {
    const value = String(item).trim().toLowerCase();
    if (value === "default" || value === "flex") set.add(value);
  }
  if (set.size === 0) return null;
  set.add("default");
  return VIDEO_SERVICE_TIERS.filter((tier) => set.has(tier));
}

function seedanceModelFamily(modelId: string): "seedance_1_0" | "seedance_1_5" | "seedance_2" {
  const model = modelId.toLowerCase();
  if (model.includes("seedance-2") || model.includes("seedance2") || model.includes("seedance-2.0")) {
    return "seedance_2";
  }
  if (model.includes("seedance-1-0") || model.includes("seedance-1.0")) {
    return "seedance_1_0";
  }
  return "seedance_1_5";
}

export function videoServiceTiersFromCapabilities(
  caps:
    | {
        capabilities?: string[] | null;
        supports_service_tier?: boolean;
        service_tiers?: string[] | null;
      }
    | null
    | undefined,
): VideoServiceTier[] | null {
  if (!caps) return null;
  const explicit = normalizeVideoServiceTiers(caps.service_tiers);
  if (explicit) return explicit;
  if (caps.supports_service_tier === true) return ["default", "flex"];
  if (caps.supports_service_tier === false) return ["default"];
  const capabilities = caps.capabilities ?? [];
  if (capabilities.includes("flex_tier")) return ["default", "flex"];
  if (capabilities.length > 0) return ["default"];
  return null;
}

/** Conservative UI hint for video service tiers. Backend resolver remains authoritative. */
export function lookupVideoServiceTiers(
  providers: ProviderInfo[],
  backend: string,
  customProviders?: CustomProviderInfo[],
): VideoServiceTier[] | null {
  const slashIdx = backend.indexOf("/");
  if (slashIdx === -1) return null;
  const providerId = backend.slice(0, slashIdx);
  const modelId = backend.slice(slashIdx + 1);

  if (providerId.startsWith(CUSTOM_PREFIX) && customProviders) {
    const dbId = parseInt(providerId.slice(CUSTOM_PREFIX.length), 10);
    const cp = customProviders.find((p) => p.id === dbId);
    const model = cp?.models?.find((m) => m.model_id === modelId);
    if (!model) return null;
    if (model.endpoint === "ark-seedance") {
      return seedanceModelFamily(model.model_id) === "seedance_2" ? ["default"] : ["default", "flex"];
    }
    return ["default"];
  }

  const provider = providers.find((p) => p.id === providerId);
  const model = provider?.models?.[modelId];
  return videoServiceTiersFromCapabilities(model);
}

export type VideoContinuityCapability = "end_frame" | "reference_images" | "start_only";
export interface VideoContinuitySupport {
  endFrame: boolean;
  referenceImages: boolean;
  referenceWithStartImage: boolean;
}

const VIDU_START_END_MODELS = new Set([
  "viduq3-turbo",
  "viduq3-pro",
  "viduq2-pro-fast",
  "viduq2-pro",
  "viduq2-turbo",
  "viduq1",
  "viduq1-classic",
  "vidu2.0",
]);

const VIDU_START_IMAGE_MODELS = new Set([
  "viduq3-turbo",
  "viduq3-pro",
  "viduq3-pro-fast",
  "viduq2-pro-fast",
  "viduq2-pro",
  "viduq2-turbo",
  "viduq1",
  "viduq1-classic",
  "vidu2.0",
]);

const VIDU_REFERENCE_MODELS = new Set([
  "viduq3-mix",
  "viduq3-turbo",
  "viduq3",
  "viduq2-pro",
  "viduq2",
  "viduq1",
  "vidu2.0",
]);

function videoContinuitySupport(
  support: Partial<VideoContinuitySupport> = {},
): VideoContinuitySupport {
  const referenceImages = Boolean(support.referenceImages);
  return {
    endFrame: Boolean(support.endFrame),
    referenceImages,
    referenceWithStartImage: Boolean(referenceImages && support.referenceWithStartImage),
  };
}

function dashscopeR2vSupportsStartReference(modelId: string): boolean {
  return modelId.includes("wan") && modelId.includes("r2v");
}

function dashscopeSupportsStartImage(modelId: string): boolean {
  if (modelId.includes("i2v")) return true;
  if (modelId.includes("r2v")) return dashscopeR2vSupportsStartReference(modelId);
  if (modelId.includes("t2v")) return false;
  return true;
}

function lookupCustomEndpoint(
  providerId: string,
  modelId: string,
  customProviders?: CustomProviderInfo[],
): string {
  if (!providerId.startsWith(CUSTOM_PREFIX) || !customProviders) return "";
  const dbId = parseInt(providerId.slice(CUSTOM_PREFIX.length), 10);
  const cp = customProviders.find((p) => p.id === dbId);
  return cp?.models?.find((m) => m.model_id.toLowerCase() === modelId)?.endpoint.toLowerCase() ?? "";
}

export function capabilityFromVideoContinuitySupport(
  support: VideoContinuitySupport,
): VideoContinuityCapability {
  if (support.endFrame) return "end_frame";
  if (support.referenceImages && support.referenceWithStartImage) return "reference_images";
  return "start_only";
}

export function videoContinuitySupportFromCapabilities(
  caps:
    | {
        supports_end_image?: boolean;
        supports_last_frame?: boolean;
        supports_reference_images?: boolean;
        supports_reference_with_start_image?: boolean;
        video_continuity_capabilities?: string[];
      }
    | null
    | undefined,
): VideoContinuitySupport | null {
  if (!caps) return null;
  const rawCapabilities = caps.video_continuity_capabilities ?? [];
  const referenceImages = Boolean(caps.supports_reference_images || rawCapabilities.includes("reference_images"));
  return videoContinuitySupport({
    endFrame: Boolean(caps.supports_end_image || caps.supports_last_frame || rawCapabilities.includes("end_image")),
    referenceImages,
    referenceWithStartImage: Boolean(
      referenceImages &&
        (caps.supports_reference_with_start_image ||
          rawCapabilities.includes("reference_images_with_start_image")),
    ),
  });
}

/** Conservative UI hint for storyboard-video continuity. Backend capability checks remain authoritative. */
export function lookupVideoContinuitySupport(
  backend: string,
  customProviders?: CustomProviderInfo[],
): VideoContinuitySupport {
  const slashIdx = backend.indexOf("/");
  if (slashIdx === -1) return videoContinuitySupport();
  const providerId = backend.slice(0, slashIdx).toLowerCase();
  const modelId = backend.slice(slashIdx + 1).toLowerCase();

  if (providerId.startsWith(CUSTOM_PREFIX) && customProviders) {
    const endpoint = lookupCustomEndpoint(providerId, modelId, customProviders);
    if (endpoint === "v2-video-generations") {
      return videoContinuitySupport({ endFrame: true, referenceImages: true, referenceWithStartImage: true });
    }
    if (endpoint.includes("openai") || endpoint.includes("grok")) {
      return videoContinuitySupport({ referenceImages: true, referenceWithStartImage: true });
    }
    if (endpoint.includes("dashscope") && modelId.includes("r2v")) {
      return videoContinuitySupport({
        referenceImages: true,
        referenceWithStartImage: dashscopeR2vSupportsStartReference(modelId),
      });
    }
    return videoContinuitySupport();
  }

  if ((providerId === "gemini-aistudio" || providerId === "gemini-vertex") && modelId.startsWith("veo-3.1")) {
    return videoContinuitySupport({ endFrame: true, referenceImages: true, referenceWithStartImage: true });
  }
  if (providerId === "ark") {
    if (modelId.includes("seedance-2")) {
      return videoContinuitySupport({ endFrame: true, referenceImages: true, referenceWithStartImage: true });
    }
    if (modelId.includes("seedance-1-5-pro")) return videoContinuitySupport({ endFrame: true });
    if (modelId.includes("seedance-1-0-pro") && !modelId.includes("fast")) {
      return videoContinuitySupport({ endFrame: true });
    }
    return videoContinuitySupport();
  }
  if (providerId === "vidu") {
    return videoContinuitySupport({
      endFrame: VIDU_START_END_MODELS.has(modelId),
      referenceImages: VIDU_REFERENCE_MODELS.has(modelId),
    });
  }
  if (providerId === "v2-video-generations") {
    return videoContinuitySupport({ endFrame: true, referenceImages: true, referenceWithStartImage: true });
  }
  if (providerId === "openai" && modelId.startsWith("sora")) {
    return videoContinuitySupport({ referenceImages: true, referenceWithStartImage: true });
  }
  if (providerId === "grok") {
    return videoContinuitySupport({ referenceImages: true, referenceWithStartImage: true });
  }
  if (providerId === "dashscope" && modelId.includes("r2v")) {
    return videoContinuitySupport({
      referenceImages: true,
      referenceWithStartImage: dashscopeR2vSupportsStartReference(modelId),
    });
  }
  return videoContinuitySupport();
}

export function storyboardVideoStartImageSupportFromCapabilities(
  caps:
    | {
        supports_start_image?: boolean;
        supports_first_frame?: boolean;
        supports_end_image?: boolean;
        supports_last_frame?: boolean;
        supports_reference_with_start_image?: boolean;
        video_continuity_capabilities?: string[];
      }
    | null
    | undefined,
): boolean | null {
  if (!caps) return null;
  const rawCapabilities = caps.video_continuity_capabilities ?? [];
  if (
    caps.supports_start_image ||
    caps.supports_first_frame ||
    caps.supports_end_image ||
    caps.supports_last_frame ||
    caps.supports_reference_with_start_image ||
    rawCapabilities.includes("start_image") ||
    rawCapabilities.includes("end_image") ||
    rawCapabilities.includes("reference_images_with_start_image")
  ) {
    return true;
  }
  if (
    "supports_start_image" in caps ||
    "supports_first_frame" in caps ||
    rawCapabilities.length > 0
  ) {
    return false;
  }
  return null;
}

export function lookupStoryboardVideoStartImageSupport(
  backend: string,
  customProviders?: CustomProviderInfo[],
): boolean | null {
  const slashIdx = backend.indexOf("/");
  if (slashIdx === -1) return null;
  const providerId = backend.slice(0, slashIdx).toLowerCase();
  const modelId = backend.slice(slashIdx + 1).toLowerCase();

  if (providerId.startsWith(CUSTOM_PREFIX)) {
    const endpoint = lookupCustomEndpoint(providerId, modelId, customProviders);
    if (!endpoint) return null;
    if (
      endpoint === "openai-video" ||
      endpoint === "newapi-video" ||
      endpoint === "v2-video-generations" ||
      endpoint === "ark-seedance"
    ) {
      return true;
    }
    if (endpoint === "vidu-video" || endpoint.includes("vidu")) {
      return VIDU_START_IMAGE_MODELS.has(modelId);
    }
    if (endpoint === "dashscope-async-video" || endpoint.includes("dashscope")) {
      return dashscopeSupportsStartImage(modelId);
    }
    return null;
  }

  if (providerId === "vidu") return VIDU_START_IMAGE_MODELS.has(modelId);
  if (providerId === "dashscope") return dashscopeSupportsStartImage(modelId);
  if (
    providerId === "gemini-aistudio" ||
    providerId === "gemini-vertex" ||
    providerId === "ark" ||
    providerId === "v2-video-generations" ||
    providerId === "openai" ||
    providerId === "grok" ||
    providerId === "newapi"
  ) {
    return true;
  }
  return null;
}

export function lookupVideoContinuityCapability(
  backend: string,
  customProviders?: CustomProviderInfo[],
): VideoContinuityCapability {
  return capabilityFromVideoContinuitySupport(
    lookupVideoContinuitySupport(backend, customProviders),
  );
}

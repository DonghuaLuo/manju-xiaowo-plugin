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

export type VideoContinuityCapability = "end_frame" | "reference_images" | "start_only";
export interface VideoContinuitySupport {
  endFrame: boolean;
  referenceImages: boolean;
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

const VIDU_REFERENCE_MODELS = new Set([
  "viduq3-mix",
  "viduq3-turbo",
  "viduq3",
  "viduq2-pro",
  "viduq2",
  "viduq1",
  "vidu2.0",
]);

export function capabilityFromVideoContinuitySupport(
  support: VideoContinuitySupport,
): VideoContinuityCapability {
  if (support.endFrame) return "end_frame";
  if (support.referenceImages) return "reference_images";
  return "start_only";
}

export function videoContinuitySupportFromCapabilities(
  caps:
    | {
        supports_end_image?: boolean;
        supports_last_frame?: boolean;
        supports_reference_images?: boolean;
        video_continuity_capabilities?: string[];
      }
    | null
    | undefined,
): VideoContinuitySupport | null {
  if (!caps) return null;
  const rawCapabilities = caps.video_continuity_capabilities ?? [];
  return {
    endFrame: Boolean(caps.supports_end_image || caps.supports_last_frame || rawCapabilities.includes("end_image")),
    referenceImages: Boolean(caps.supports_reference_images || rawCapabilities.includes("reference_images")),
  };
}

/** Conservative UI hint for storyboard-video continuity. Backend capability checks remain authoritative. */
export function lookupVideoContinuitySupport(
  backend: string,
  customProviders?: CustomProviderInfo[],
): VideoContinuitySupport {
  const slashIdx = backend.indexOf("/");
  if (slashIdx === -1) return { endFrame: false, referenceImages: false };
  const providerId = backend.slice(0, slashIdx).toLowerCase();
  const modelId = backend.slice(slashIdx + 1).toLowerCase();

  if (providerId.startsWith(CUSTOM_PREFIX) && customProviders) {
    const dbId = parseInt(providerId.slice(CUSTOM_PREFIX.length), 10);
    const cp = customProviders.find((p) => p.id === dbId);
    const endpoint = cp?.models?.find((m) => m.model_id.toLowerCase() === modelId)?.endpoint ?? "";
    if (endpoint === "v2-video-generations") return { endFrame: true, referenceImages: false };
    if (endpoint.includes("openai") || endpoint.includes("grok")) return { endFrame: false, referenceImages: true };
    if (endpoint.includes("dashscope") && modelId.includes("r2v")) return { endFrame: false, referenceImages: true };
    return { endFrame: false, referenceImages: false };
  }

  if ((providerId === "gemini-aistudio" || providerId === "gemini-vertex") && modelId.startsWith("veo-3.1")) {
    return { endFrame: true, referenceImages: false };
  }
  if (providerId === "ark") {
    if (modelId.includes("seedance-2")) return { endFrame: true, referenceImages: true };
    if (modelId.includes("seedance-1-5-pro")) return { endFrame: true, referenceImages: false };
    if (modelId.includes("seedance-1-0-pro") && !modelId.includes("fast")) {
      return { endFrame: true, referenceImages: false };
    }
    return { endFrame: false, referenceImages: false };
  }
  if (providerId === "vidu") {
    return {
      endFrame: VIDU_START_END_MODELS.has(modelId),
      referenceImages: VIDU_REFERENCE_MODELS.has(modelId),
    };
  }
  if (providerId === "v2-video-generations") return { endFrame: true, referenceImages: false };
  if (providerId === "openai" && modelId.startsWith("sora")) return { endFrame: false, referenceImages: true };
  if (providerId === "grok") return { endFrame: false, referenceImages: true };
  if (providerId === "dashscope" && modelId.includes("r2v")) return { endFrame: false, referenceImages: true };
  return { endFrame: false, referenceImages: false };
}

export function lookupVideoContinuityCapability(
  backend: string,
  customProviders?: CustomProviderInfo[],
): VideoContinuityCapability {
  return capabilityFromVideoContinuitySupport(
    lookupVideoContinuitySupport(backend, customProviders),
  );
}

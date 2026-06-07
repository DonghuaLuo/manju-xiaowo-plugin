/**
 * API 调用封装 (TypeScript)
 *
 * Typed API layer for all backend endpoints.
 * Import: import { API } from '@/api';
 */

import { PluginSDK } from "xiaowo-sdk";
import type {
  ProjectData,
  ProjectSummary,
  ImportConflictPolicy,
  ImportArchiveResponse,
  ImportFailureDiagnostics,
  EpisodeScript,
  TaskItem,
  TaskStats,
  SessionMeta,
  AssistantSnapshot,
  SkillInfo,
  ProjectOverview,
  ProjectChangeBatchPayload,
  ProjectEventSnapshotPayload,
  GetSystemConfigResponse,
  SystemConfigPatch,
  ProviderInfo,
  ProviderConfigDetail,
  ProviderTestResult,
  ProviderCredential,
  UsageStatsResponse,
  CustomProviderInfo,
  CustomProviderModelInfo,
  CustomProviderCreateRequest,
  CustomProviderModelInput,
  DiscoveredModel,
  EndpointDescriptor,
  CustomProviderCredentials,
  AnthropicDiscoverRequest,
  AnthropicDiscoverResponse,
  CostEstimateResponse,
  ReferenceVideoUnit,
  ReferenceResource,
  TransitionType,
  GenerationProfiles,
  GenerationQuality,
  StoryboardFinalGenerationMode,
  StoryboardGenerationSettings,
  VideoGenerationSettings,
  VideoContinuityPolicy,
} from "@/types";
import type { GenerationMode } from "@/utils/generation-mode";
import type { StyleCategory } from "@/data/style-templates";
import type { GridGeneration } from "@/types/grid";
import type { Asset, AssetType, AssetCreatePayload, AssetUpdatePayload } from "@/types/asset";
import type {
  AgentCredential,
  CreateAgentCredentialRequest,
  PresetProvidersResponse,
  TestConnectionRequest,
  TestConnectionResponse,
  UpdateAgentCredentialRequest,
} from "@/types/agent-credential";
import i18n from "./i18n";
import {
  getUploadFileName,
  isDesktopFileRef,
  type UploadFileInput,
} from "@/utils/desktop-file";

// ==================== Helper types ====================

/** Standard error response body from backend (mirrors FastAPI HTTPException detail). */
export interface ErrorResponse {
  detail: string | { msg?: string }[];
}

/**
 * Error thrown when uploading a source file conflicts with an existing file
 * (HTTP 409). Carries the existing filename and a server-suggested alternative
 * so callers can prompt the user to retry with `on_conflict=rename|replace`.
 */
export class ConflictError extends Error {
  constructor(
    public readonly existing: string,
    public readonly suggestedName: string,
    message: string
  ) {
    super(message);
    this.name = "ConflictError";
  }
}

/** Error payload from the import project endpoint (extends ErrorResponse with import-specific fields). */
interface ImportErrorPayload {
  detail?: string | { msg?: string }[];
  errors?: string[];
  warnings?: string[];
  conflict_project_name?: string;
  diagnostics?: unknown;
}

/** Version metadata returned by the versions API. */
interface ProviderInputImageMetadata {
  purpose?: string;
  source_path?: string;
  input_path?: string;
  source_mime?: string;
  input_mime?: string;
  source_bytes?: number;
  input_bytes?: number;
  source_size?: { width?: number; height?: number };
  input_size?: { width?: number; height?: number };
  estimated_base64_bytes?: number;
  resized?: boolean;
  transcoded?: boolean;
  copied?: boolean;
  max_long_edge?: number;
  jpeg_quality?: number | null;
}

export interface VideoContinuityMetadata {
  requested_policy?: string;
  effective_policy?: string;
  start_storyboard_id?: string;
  end_storyboard_id?: string;
  submitted_end_image?: string;
  submitted_reference_images?: string[];
  skip_reason?: string;
  provider_supports_end_image?: boolean;
  provider_supports_reference_images?: boolean;
  provider_supports_reference_with_start_image?: boolean;
  provider_max_reference_images?: number | null;
  provider?: string;
  model?: string;
  transition_to_next?: string;
}

export interface VersionInfo {
  version: number;
  file?: string;
  filename: string;
  created_at: string;
  file_size: number;
  is_current: boolean;
  file_url?: string;
  prompt?: string;
  restored_from?: number;
  generation_quality?: GenerationQuality | null;
  generation_profile_key?: string | null;
  generation_route?: {
    task_kind?: string;
    media_type?: string;
    provider?: string;
    model?: string;
    resolution?: string;
    duration_seconds?: number;
    generate_audio?: boolean;
    service_tier?: string;
    seed?: number;
    supported_resolutions?: string[];
    supported_durations?: number[];
    duration_resolution_constraints?: Record<string, number[]>;
    warnings?: Array<{ key: string; params?: Record<string, unknown> }>;
    provider_capability_hash?: string | null;
  };
  generation_route_warnings?: Array<{ key: string; params?: Record<string, unknown> }>;
  provider_capability_hash?: string | null;
  provider_input_images?: Record<
    string,
    ProviderInputImageMetadata | ProviderInputImageMetadata[] | null | undefined
  >;
  provider_input_payload?: Record<string, unknown> | null;
  video_continuity?: VideoContinuityMetadata | null;
  source_storyboard_generation_quality?: string;
  final_generation_mode?: string | null;
  source_version?: number | string | null;
}

export type VersionResourceType = "storyboards" | "videos" | "characters" | "scenes" | "props";

export type DesignResourceType = "characters" | "scenes" | "props";

export interface DesignResourceUsage {
  script_file: string;
  episode?: number | string | null;
  kind: string;
  item_id?: string | null;
}

export interface ExternalGenerationReference {
  index: number;
  filename: string;
  label: string;
  path: string;
  url: string;
  description?: string;
}

export interface ExternalGenerationPackage {
  project_name: string;
  script_file: string;
  segment_id: string;
  storyboard: {
    prompt: string;
    external_prompt: string;
    references: ExternalGenerationReference[];
  };
  video: {
    prompt: string;
    external_prompt: string;
    references: ExternalGenerationReference[];
  };
}

/** Options for {@link API.openTaskStream}. */
export interface TaskStreamOptions {
  projectName?: string;
  lastEventId?: number | string;
  onSnapshot?: (payload: TaskStreamSnapshotPayload, event: MessageEvent) => void;
  onTask?: (payload: TaskStreamTaskPayload, event: MessageEvent) => void;
  onError?: (event: Event) => void;
}

export interface TaskStreamSnapshotPayload {
  tasks: TaskItem[];
  stats: TaskStats;
}

export interface TaskStreamTaskPayload {
  action: "created" | "updated";
  task: TaskItem;
  stats: TaskStats;
}

export interface ProjectEventStreamOptions {
  projectName: string;
  onSnapshot?: (payload: ProjectEventSnapshotPayload, event: MessageEvent) => void;
  onChanges?: (payload: ProjectChangeBatchPayload, event: MessageEvent) => void;
  onError?: (event: Event) => void;
}

export interface ApiEventSource {
  readonly CONNECTING: 0;
  readonly OPEN: 1;
  readonly CLOSED: 2;
  readonly url: string;
  withCredentials: boolean;
  readyState: number;
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  addEventListener(
    type: string,
    listener: ((event: MessageEvent) => void) | EventListenerObject | null,
    options?: boolean | AddEventListenerOptions,
  ): void;
  removeEventListener(
    type: string,
    listener: ((event: MessageEvent) => void) | EventListenerObject | null,
    options?: boolean | EventListenerOptions,
  ): void;
  close(): void;
}

/** Filters for {@link API.listTasks} and {@link API.listProjectTasks}. */
export interface TaskListFilters {
  projectName?: string;
  status?: string;
  taskType?: string;
  source?: string;
  page?: number;
  pageSize?: number;
}

/** Filters for {@link API.getUsageStats} and {@link API.getUsageCalls}. */
export interface UsageStatsFilters {
  projectName?: string;
  startDate?: string;
  endDate?: string;
}

export interface UsageCallsFilters {
  projectName?: string;
  callType?: string;
  status?: string;
  startDate?: string;
  endDate?: string;
  page?: number;
  pageSize?: number;
}

/** Generic success response used by many endpoints. */
export interface SuccessResponse {
  success: boolean;
  message?: string;
}

export interface FileDeleteError {
  file: string;
  message?: string;
}

/** 说书模式片段 PATCH 入参（drama 模式片段走 {@link API.updateScene}）。 */
export interface SegmentUpdatePayload {
  script_file: string;
  duration_seconds?: number;
  segment_break?: boolean;
  image_prompt?: unknown;
  video_prompt?: unknown;
  transition_to_next?: string;
  note?: string;
  characters_in_segment?: string[];
  scenes?: string[];
  props?: string[];
  storyboard_generation?: StoryboardGenerationSettings;
  video_generation?: VideoGenerationSettings;
}

/** Payload for {@link API.createProject}. */
export interface CreateProjectPayload {
  title: string;
  name?: string;
  style?: string | null;
  content_mode?: "narration" | "drama";
  aspect_ratio?: "9:16" | "16:9";
  source_language?: "zh" | "en" | "vi";
  episode_target_units?: number | null;
  generation_mode?: GenerationMode;
  script_splitting_template_id?: string | null;
  default_duration?: number | null;
  style_template_id?: string | null;
  video_backend?: string | null;
  image_backend?: string | null;
  image_provider_t2i?: string | null;
  image_provider_i2i?: string | null;
  text_backend_script?: string | null;
  text_backend_overview?: string | null;
  text_backend_style?: string | null;
  model_settings?: Record<string, { resolution?: string | null }>;
  generation_profiles?: GenerationProfiles;
  video_service_tier?: string | null;
}

export interface GenerationRequestOptions {
  quality?: GenerationQuality;
  final_generation_mode?: StoryboardFinalGenerationMode | null;
  resolution?: string | null;
  source_version?: number | null;
  image_provider?: string | null;
  image_model?: string | null;
  duration_seconds?: number | null;
  video_backend?: string | null;
  video_continuity_policy?: VideoContinuityPolicy | null;
  generate_audio?: boolean | null;
  service_tier?: string | null;
  seed?: number | null;
}

export interface GenerationRoutePreviewRequest {
  project_overrides?: Partial<ProjectData>;
  routes: Array<{
    label?: string | null;
    task_kind: "character" | "scene" | "prop" | "storyboard" | "grid" | "video" | "reference_video";
    quality?: GenerationQuality | null;
    capability?: "t2i" | "i2i" | null;
    payload?: Record<string, unknown> | null;
  }>;
}

export interface GenerationRoutePreviewItem {
  ok: boolean;
  label?: string | null;
  task_kind: string;
  media_type?: "image" | "video";
  quality?: GenerationQuality | null;
  profile_key?: string | null;
  provider_id?: string | null;
  model_id?: string | null;
  resolution?: string | null;
  duration_seconds?: number | null;
  generate_audio?: boolean | null;
  service_tier?: string | null;
  seed?: number | null;
  supported_resolutions?: string[];
  supported_durations?: number[];
  duration_resolution_constraints?: Record<string, number[]>;
  warnings?: Array<{ key: string; params?: Record<string, unknown> }>;
  error?: string;
}

export interface GenerationRoutePreviewResponse {
  routes: GenerationRoutePreviewItem[];
}

export interface StoryboardReferencePreflightSource {
  kind: string;
  name?: string;
  label: string;
  path?: string;
  exists?: boolean;
}

export interface StoryboardReferencePreflightScenario {
  quality: GenerationQuality;
  profile_key?: string | null;
  provider_id?: string | null;
  model_id?: string | null;
  max_reference_images?: number | null;
  reference_image_count: number;
  sources: StoryboardReferencePreflightSource[];
  ok: boolean;
  message?: string | null;
  route_error?: string | null;
}

export interface StoryboardReferencePreflightResponse {
  ok: boolean;
  message?: string | null;
  scenarios: StoryboardReferencePreflightScenario[];
}

export interface ScriptSplittingProviderCompatibility {
  status: "ok" | "warn" | "block" | "unknown";
  provider_id?: string | null;
  model?: string | null;
  capabilities?: string[];
  missing_required?: string[];
  missing_preferred?: string[];
  warnings?: string[];
}

export interface ScriptSplittingGenerationModeCompatibility {
  status: "ok" | "warn" | "block";
  generation_mode: string;
  warnings?: string[];
}

export interface ScriptSplittingTemplateInfo {
  id: string;
  version?: number | null;
  source?: string;
  base_template_id?: string | null;
  derived_from_template_id?: string | null;
  creation_mode?: "improve" | "new_style" | null;
  content_mode: "narration" | "drama";
  name: string;
  description?: string;
  supported_generation_modes?: GenerationMode[];
  recommended_generation_modes?: GenerationMode[];
  default_generation_mode?: GenerationMode | null;
  required_capabilities?: string[];
  preferred_capabilities?: string[];
  output_fields?: string[];
  split_rules?: string[];
  forbidden_patterns?: string[];
  user_overlay?: {
    intent_brief?: string;
    derivation_note?: string;
    tone_preferences?: string[];
    extra_split_rules?: string[];
    extra_forbidden_patterns?: string[];
    example_source?: string;
    example_expected_output?: string;
  };
  hash?: string;
  generation_mode_compatibility?: ScriptSplittingGenerationModeCompatibility;
  provider_compatibility?: ScriptSplittingProviderCompatibility;
}

export interface ScriptSplittingTemplateValidationIssue {
  id: string;
  check_type: string;
  severity: "block" | "warn";
  field: string;
  message: string;
  repair_hint?: string;
  autofix_allowed?: boolean;
}

export interface ScriptSplittingTemplateValidation {
  ok: boolean;
  errors: ScriptSplittingTemplateValidationIssue[];
  warnings: ScriptSplittingTemplateValidationIssue[];
  profile?: ScriptSplittingTemplateInfo;
}

export interface ScriptSplittingTemplatesResponse {
  success: boolean;
  templates: ScriptSplittingTemplateInfo[];
}

export interface ScriptSplittingTemplateUpsertPayload {
  id?: string | null;
  base_template_id?: string | null;
  derived_from_template_id?: string | null;
  creation_mode?: "improve" | "new_style" | null;
  name?: string | null;
  description?: string | null;
  supported_generation_modes?: GenerationMode[] | null;
  recommended_generation_modes?: GenerationMode[] | null;
  intent_brief?: string | null;
  derivation_note?: string | null;
  tone_preferences?: string[] | null;
  extra_split_rules?: string[] | null;
  extra_forbidden_patterns?: string[] | null;
  example_source?: string | null;
  example_expected_output?: string | null;
}

export interface ScriptSplittingTemplateMutationResponse {
  success: boolean;
  template: ScriptSplittingTemplateInfo;
  validation?: ScriptSplittingTemplateValidation;
}

export interface ScriptSplittingTemplateExportResponse {
  success: boolean;
  schema: string;
  template: ScriptSplittingTemplateInfo;
}

export interface ScriptSplittingTemplatePreview {
  preview: boolean;
  current_template_id?: string | null;
  current_hash?: string | null;
  next_template_id: string;
  next_hash?: string;
  current_generation_mode?: GenerationMode | null;
  next_generation_mode?: GenerationMode | null;
  generation_mode_changed?: boolean;
  generation_mode_compatibility?: ScriptSplittingGenerationModeCompatibility;
  provider_compatibility?: ScriptSplittingProviderCompatibility;
  affected_assets: string[];
  affected_asset_count?: number;
  affected_asset_type_count?: number;
  existing_outputs?: Record<string, {
    exists?: boolean | null;
    count?: number | null;
    paths?: string[];
    tracked?: boolean;
    reason?: string | null;
  }>;
  rebuild_chain?: Array<{
    asset: string;
    exists?: boolean | null;
    count?: number | null;
    tracked?: boolean;
    reason?: string | null;
  }>;
  regeneration_chain?: string[];
  preserved_existing_assets?: string[];
  preserved_existing_asset_count?: number;
  preserved_existing_asset_type_count?: number;
  preserved_existing_chain?: Array<{
    asset: string;
    exists?: boolean | null;
    count?: number | null;
    tracked?: boolean;
    reason?: string | null;
  }>;
  existing_assets_policy?: string;
  future_generation_policy?: string;
  has_generated_videos?: boolean;
  has_jianying_draft?: boolean | null;
  jianying_draft_tracking?: string | null;
  requires_confirmation?: boolean;
  available_modes?: ScriptSplittingTemplateApplyMode[];
  suggested_action: string;
}

export type ScriptSplittingTemplateApplyMode = "preview" | "apply_keep_drafts" | "apply_rebuild_step1";

export interface ScriptSplittingTemplateChangeResponse {
  success: boolean;
  project: ProjectData;
}

export interface VideoCapabilitiesResponse {
  provider_id: string;
  model: string;
  supported_durations: number[];
  max_duration: number;
  max_reference_images: number | null;
  resolutions?: string[];
  duration_resolution_constraints?: Record<string, number[]>;
  capabilities?: string[];
  supports_generate_audio?: boolean;
  supports_seed?: boolean;
  supports_service_tier?: boolean;
  supports_start_image?: boolean;
  supports_end_image?: boolean;
  supports_reference_images?: boolean;
  supports_reference_with_start_image?: boolean;
  supports_first_frame?: boolean;
  supports_last_frame?: boolean;
  video_continuity_capabilities?: Array<
    "start_image" | "end_image" | "reference_images" | "reference_images_with_start_image"
  >;
  recommended_continuity_policy?: "end_frame" | "reference_assisted" | "start_only";
  service_tiers?: string[];
  endpoint?: string | null;
  endpoint_family?: string | null;
  source: "registry" | "custom";
  default_duration?: number | null;
  content_mode?: string | null;
  generation_mode?: string | null;
  script_splitting_template_id?: string | null;
  script_splitting_hash?: string | null;
  provider_compatibility?: ScriptSplittingProviderCompatibility;
}

export interface QualityRatingRequest {
  resource_type: VersionResourceType | "reference_videos";
  resource_id: string;
  version?: number | null;
  rating: number;
  dimensions?: Record<string, number>;
  note?: string | null;
  provider?: string | null;
  model?: string | null;
  generation_quality?: string | null;
}

export interface QualityStatsResponse {
  count: number;
  average_rating: number | null;
  dimension_averages?: Array<{ key: string; count: number; average_rating: number | null }>;
  groups: Record<string, Array<{ key: string; count: number; average_rating: number | null }>>;
  ratings: Array<Record<string, unknown>>;
}

export interface QualityAnalysisGroupItem {
  key: string;
  label?: string;
  count: number;
  average_rating: number | null;
  project_name?: string;
  project_title?: string;
  provider?: string;
  model?: string;
  dimension_averages?: Array<{ key: string; count: number; average_rating: number | null }>;
  [key: string]: unknown;
}

export interface QualityAnalysisResponse {
  count: number;
  average_rating: number | null;
  project_count: number;
  total_projects: number;
  rated_model_count: number;
  dimension_averages: Array<{ key: string; count: number; average_rating: number | null }>;
  groups: Record<string, QualityAnalysisGroupItem[]>;
  ratings: Array<Record<string, unknown>>;
}

export interface FinalizationTaskReportResponse {
  summary: Record<string, number>;
  items: Array<Record<string, unknown>>;
}

export interface ProviderRecommendation {
  provider: string;
  model: string;
  call_type: string;
  total_calls: number;
  success_calls: number;
  failed_calls: number;
  success_rate: number;
  avg_duration_seconds?: number | null;
  avg_success_cost_usd?: number | null;
}

function compactGenerationOptions(options: GenerationRequestOptions = {}): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(options).filter(([, value]) => value !== undefined && value !== null),
  );
}

export interface StyleTemplateInfo {
  id: string;
  category: StyleCategory;
  prompt: string;
  thumbnail_file: string;
  thumbnail_url?: string | null;
  name?: string | null;
  tagline?: string | null;
  source?: string;
}

export interface CreateFavoriteStyleTemplatePayload {
  stylePrompt: string;
  projectName?: string | null;
  file?: UploadFileInput | null;
}

/** Draft metadata returned by listDrafts. */
export interface DraftInfo {
  episode: number;
  step: number;
  filename: string;
  modified_at: string;
}

function normalizeDiagnosticsBucket(value: unknown): { code: string; message: string; location?: string }[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter(
      (item): item is { code: string; message: string; location?: string } =>
        Boolean(item)
        && typeof item === "object"
        && typeof (item as { code?: unknown }).code === "string"
        && typeof (item as { message?: unknown }).message === "string"
    )
    .map((item) => ({
      code: item.code,
      message: item.message,
      ...(typeof item.location === "string" ? { location: item.location } : {}),
    }));
}

function normalizeImportFailureDiagnostics(value: unknown): ImportFailureDiagnostics {
  const payload = (value && typeof value === "object") ? value as Record<string, unknown> : {};
  return {
    blocking: normalizeDiagnosticsBucket(payload.blocking),
    auto_fixable: normalizeDiagnosticsBucket(payload.auto_fixable),
    warnings: normalizeDiagnosticsBucket(payload.warnings),
  };
}

// ==================== API class ====================

type LocalAssetRoots = {
  projects_root: string;
  global_assets_root?: string;
};

let localAssetRoots: LocalAssetRoots | null = null;
let localAssetRootsPromise: Promise<LocalAssetRoots | null> | null = null;

function hasTauriBridge(): boolean {
  if (typeof window === "undefined") return false;
  const tauriWindow = window as unknown as { __TAURI__?: { core?: unknown } };
  return Boolean(tauriWindow.__TAURI__?.core);
}

function normalizeLocalPath(path: string): string {
  return path.replace(/\\/g, "/").replace(/\/+$/, "");
}

function cleanRelativePath(path: string): string | null {
  const normalized = path.replace(/\\/g, "/").replace(/^\/+/, "");
  const parts = normalized.split("/").filter(Boolean);
  if (parts.some((part) => part === "." || part === "..")) return null;
  return parts.join("/");
}

function decodePathSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

function decodeRelativePath(path: string): string {
  return path.split("/").map(decodePathSegment).join("/");
}

function isAbsoluteLocalPath(path: string): boolean {
  return /^[a-zA-Z]:[\\/]/.test(path) || path.startsWith("\\\\") || path.startsWith("//");
}

function appendCacheParam(url: string, key: string, value?: number | string | null): string {
  if (value == null || value === "") return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}${key}=${encodeURIComponent(String(value))}`;
}

function joinLocalPath(root: string, ...segments: string[]): string | null {
  const cleaned = segments.map(cleanRelativePath);
  if (cleaned.some((segment) => segment == null)) return null;
  return [normalizeLocalPath(root), ...(cleaned as string[])].filter(Boolean).join("/");
}

function convertLocalFileSrc(path: string, cacheKey = "v", cacheBust?: number | string | null): string {
  return appendCacheParam(PluginSDK.convertFileSrc(path), cacheKey, cacheBust);
}

async function ensureLocalAssetRoots(): Promise<LocalAssetRoots | null> {
  if (localAssetRoots) return localAssetRoots;
  if (localAssetRootsPromise) return localAssetRootsPromise;
  if (!hasTauriBridge()) return null;

  localAssetRootsPromise = (async () => {
    try {
      const roots = await PluginSDK.callBackend<Partial<LocalAssetRoots>>("manju_api_get_asset_roots", {});
      if (typeof roots.projects_root === "string" && roots.projects_root.trim()) {
        localAssetRoots = {
          projects_root: normalizeLocalPath(roots.projects_root),
          ...(typeof roots.global_assets_root === "string" && roots.global_assets_root.trim()
            ? { global_assets_root: normalizeLocalPath(roots.global_assets_root) }
            : {}),
        };
        return localAssetRoots;
      }
    } catch {
      // Fall back to the plugin directory exposed by the host below.
    }

    try {
      const info = await PluginSDK.getInfo();
      if (info.plugin_dir) {
        localAssetRoots = {
          projects_root: normalizeLocalPath(`${info.plugin_dir}/backend/projects`),
          global_assets_root: normalizeLocalPath(`${info.plugin_dir}/backend/projects/_global_assets`),
        };
        return localAssetRoots;
      }
    } catch {
      // Browser-only tests or early startup can continue without local roots.
    }

    return null;
  })().finally(() => {
    localAssetRootsPromise = null;
  });

  return localAssetRootsPromise;
}

function projectFileToLocalUrl(
  projectName: string,
  path: string,
  cacheBust?: number | string | null,
): string | null {
  if (isAbsoluteLocalPath(path)) {
    return convertLocalFileSrc(path, "v", cacheBust);
  }
  if (!localAssetRoots?.projects_root) return null;
  const filePath = joinLocalPath(localAssetRoots.projects_root, projectName, path);
  return filePath ? convertLocalFileSrc(filePath, "v", cacheBust) : null;
}

function globalAssetToLocalPath(path: string): string | null {
  if (isAbsoluteLocalPath(path)) return path;
  if (!localAssetRoots?.projects_root) return null;
  const cleaned = cleanRelativePath(path);
  if (!cleaned?.startsWith("_global_assets/")) return null;
  const root = localAssetRoots.global_assets_root
    ? normalizeLocalPath(localAssetRoots.global_assets_root).replace(/\/_global_assets$/, "")
    : localAssetRoots.projects_root;
  return joinLocalPath(root, cleaned);
}

function globalAssetToLocalUrl(
  path: string,
  cacheBust?: number | string | null,
): string | null {
  const filePath = globalAssetToLocalPath(path);
  return filePath ? convertLocalFileSrc(filePath, "fp", cacheBust) : null;
}

function favoriteStyleThumbnailToLocalUrl(
  fileName: string,
  cacheBust?: number | string | null,
): string | null {
  if (!localAssetRoots?.projects_root) return null;
  const cleaned = cleanRelativePath(fileName);
  if (!cleaned || cleaned.includes("/")) return null;
  const filePath = joinLocalPath(localAssetRoots.projects_root, "_style_favorites", "images", cleaned);
  return filePath ? convertLocalFileSrc(filePath, "fp", cacheBust) : null;
}

function resolveApiFileUrl(value: string): string | null {
  try {
    const parsed = new URL(value, window.location.href);
    const resource = parsed.pathname
      .replace(/^\/api\/v1\/?/, "")
      .replace(/^\/api\/?/, "")
      .replace(/^\/+/, "");

    if (resource.startsWith("files/")) {
      const [, encodedProjectName, ...pathParts] = resource.split("/");
      if (!encodedProjectName || pathParts.length === 0) return null;
      return projectFileToLocalUrl(
        decodePathSegment(encodedProjectName),
        decodeRelativePath(pathParts.join("/")),
        parsed.searchParams.get("v") ?? parsed.searchParams.get("fp"),
      );
    }

    if (resource.startsWith("global-assets/")) {
      const [, type, ...filenameParts] = resource.split("/");
      if (!type || filenameParts.length === 0) return null;
      return globalAssetToLocalUrl(
        `_global_assets/${decodeRelativePath(type)}/${decodeRelativePath(filenameParts.join("/"))}`,
        parsed.searchParams.get("fp") ?? parsed.searchParams.get("v"),
      );
    }

    if (resource.startsWith("style-templates/favorites/")) {
      const [, , ...filenameParts] = resource.split("/");
      if (filenameParts.length !== 1) return null;
      return favoriteStyleThumbnailToLocalUrl(
        decodePathSegment(filenameParts[0]),
        parsed.searchParams.get("fp") ?? parsed.searchParams.get("v"),
      );
    }
  } catch {
    return null;
  }
  return null;
}

function resolveLocalMediaUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  if (isAbsoluteLocalPath(value)) return convertLocalFileSrc(value);
  return resolveApiFileUrl(value) ?? value;
}

function normalizeProjectSummaryUrls(project: ProjectSummary): ProjectSummary {
  return {
    ...project,
    thumbnail: resolveLocalMediaUrl(project.thumbnail),
  };
}

function normalizeStyleTemplateUrls(template: StyleTemplateInfo): StyleTemplateInfo {
  if (!template.thumbnail_url) return template;
  return {
    ...template,
    thumbnail_url: resolveLocalMediaUrl(template.thumbnail_url) ?? template.thumbnail_url,
  };
}

function normalizeVersionUrls(version: VersionInfo): VersionInfo {
  return {
    ...version,
    file_url: version.file_url ? resolveLocalMediaUrl(version.file_url) ?? version.file_url : version.file_url,
  };
}

export function __resetLocalAssetRootsForTests(): void {
  localAssetRoots = null;
  localAssetRootsPromise = null;
}

type DesktopResourceResult = {
  success?: boolean;
  error?: {
    code?: string;
    message?: string;
  };
  content?: DesktopContent;
};

type DesktopContent =
  | { kind: "empty" }
  | { kind: "json"; value: unknown }
  | { kind: "text"; text: string; mimeType?: string }
  | { kind: "binary"; base64: string; mimeType?: string };

type DesktopRequestContent =
  | DesktopContent
  | { kind: "fields"; fields: Record<string, string[]> };

type PluginStreamPayload = {
  stream: string;
  event: string;
  id?: string | number | null;
  data?: unknown;
};

export type ExportTaskKind = "project_archive" | "jianying_draft" | "asset_archive";
export type ExportTaskStatus = "queued" | "running" | "completed" | "failed";

export interface AssetArchiveIncludeOptions {
  character: boolean;
  scene: boolean;
  prop: boolean;
  styleFavorites: boolean;
}

export interface AssetArchiveExportOptions {
  includeAssets: AssetArchiveIncludeOptions;
  includeGlobalConfig: boolean;
  includeScriptSplittingTemplates: boolean;
}

export interface ExportTaskStartResponse {
  ok?: boolean;
  detail?: string;
  taskId?: string;
  status?: ExportTaskStatus;
  exportPath?: string;
  draftPath?: string;
}

export interface JianyingDraftExportSummary {
  episode?: number;
  total_count?: number;
  exported_count?: number;
  missing_count?: number;
  exported_ids?: string[];
  missing_ids?: string[];
  missing_items?: Array<{
    id?: string;
    reason?: string;
    resource_type?: string;
    video_clip?: string;
  }>;
}

export interface ExportTaskEvent {
  taskId?: string;
  kind?: ExportTaskKind;
  status?: ExportTaskStatus;
  projectName?: string;
  scope?: "full" | "current";
  episode?: number;
  exportPath?: string;
  draftPath?: string;
  draftDir?: string;
  diagnostics?: unknown;
  summary?: unknown;
  error?: string;
  updatedAt?: string;
}

export interface FinalizeEpisodeResponse {
  success?: boolean;
  mode?: "storyboard" | "reference_video";
  project_name?: string;
  episode?: number;
  script_file?: string;
  storyboards?: Array<{ resource_id: string; task_id: string; deduped?: boolean }>;
  videos?: Array<{ resource_id: string; task_id: string; deduped?: boolean; dependency_task_id?: string | null }>;
  reference_videos?: Array<{ resource_id: string; task_id: string; deduped?: boolean }>;
  issues?: Array<{ resource_id?: string; kind?: string; message?: string }>;
  summary?: {
    storyboards_enqueued?: number;
    videos_enqueued?: number;
    reference_videos_enqueued?: number;
    already_final?: number;
    issues?: number;
  };
}

export interface AssetArchiveExportInfoResponse {
  ok?: boolean;
  projectsRoot?: string;
  globalAssetsRoot?: string;
  styleFavoritesRoot?: string;
  scriptSplittingTemplatesRoot?: string;
  detail?: string;
}

export interface DetectJianyingDraftRootResponse {
  ok?: boolean;
  path?: string;
  detail?: string;
}

export interface ExportTaskStatusResponse {
  ok?: boolean;
  task?: ExportTaskEvent;
  detail?: string;
}

export interface OpenDesktopPathResponse {
  ok?: boolean;
  path?: string;
  openedPath?: string;
  detail?: string;
}

export interface SaveDiagnosticsResponse {
  ok?: boolean;
  path?: string;
  filename?: string;
  detail?: string;
}

function bytesToBase64(bytes: Uint8Array): string {
  const chunkSize = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

function statusFromDesktopError(code?: string): number {
  switch (code) {
    case "validation_error":
      return 422;
    case "not_found":
      return 404;
    case "conflict":
      return 409;
    case "too_large":
      return 413;
    case "forbidden":
      return 403;
    case "unauthorized":
      return 401;
    default:
      return 500;
  }
}

function ensureExportTaskStarted(result: ExportTaskStartResponse): {
  taskId: string;
  status: ExportTaskStatus;
  exportPath?: string;
  draftPath?: string;
} {
  if (!result.ok || !result.taskId) {
    throw new Error(result.detail || "导出任务启动失败");
  }
  return {
    taskId: result.taskId,
    status: result.status || "queued",
    exportPath: result.exportPath,
    draftPath: result.draftPath,
  };
}

async function localFileDescriptor(fieldName: string, file: UploadFileInput) {
  if (isDesktopFileRef(file)) {
    return {
      fieldName,
      path: file.path,
      filename: file.name,
      contentType: file.contentType,
    };
  }

  const bytes = new Uint8Array(await file.arrayBuffer());
  return {
    fieldName,
    filename: file.name,
    contentType: file.type || undefined,
    base64: bytesToBase64(bytes),
  };
}

type IpcScalar = string | number | boolean | null | undefined;
type IpcRecord = Record<string, IpcScalar>;
type IpcQuery = Record<string, IpcScalar | IpcScalar[]>;
type LocalFileDescriptor = Awaited<ReturnType<typeof localFileDescriptor>>;

function compactIpcRecord(record?: IpcRecord): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  for (const [key, value] of Object.entries(record ?? {})) {
    if (value !== null && value !== undefined) out[key] = value;
  }
  return out;
}

function compactIpcQuery(query?: IpcQuery): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const [key, rawValue] of Object.entries(query ?? {})) {
    const values = Array.isArray(rawValue) ? rawValue : [rawValue];
    const normalized = values
      .filter((value): value is string | number | boolean => value !== null && value !== undefined)
      .map(String);
    if (normalized.length > 0) out[key] = normalized;
  }
  return out;
}

function jsonBody(value: unknown): DesktopContent {
  return { kind: "json", value };
}

function textBody(text: string, mimeType = "text/plain;charset=UTF-8"): DesktopContent {
  return { kind: "text", text, mimeType };
}

function desktopContentValue(content: DesktopContent | undefined): unknown {
  if (!content || content.kind === "empty") return undefined;
  if (content.kind === "json") return content.value;
  if (content.kind === "text") return content.text;
  return content;
}

function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail || fallback;
  if (Array.isArray(detail) && detail.length > 0) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const msg = (item as { msg?: unknown }).msg;
          if (typeof msg === "string") return msg;
          if (typeof msg === "number" || typeof msg === "boolean") return String(msg);
        }
        return "";
      })
      .filter(Boolean)
      .join("; ") || fallback;
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string") return message || fallback;
    if (typeof message === "number" || typeof message === "boolean") return String(message);
  }
  return fallback;
}

class ManjuApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly payload: unknown;

  constructor(message: string, options: { status: number; code?: string; payload: unknown }) {
    super(message);
    this.name = "ManjuApiError";
    this.status = options.status;
    this.code = options.code;
    this.payload = options.payload;
  }
}

function throwManjuApiError(result: DesktopResourceResult, fallback = "请求失败"): never {
  const payload = desktopContentValue(result.content) ?? { detail: result.error?.message };
  const detail = payload && typeof payload === "object" && "detail" in payload ? payload.detail : result.error?.message;
  throw new ManjuApiError(detailMessage(detail, fallback), {
    status: statusFromDesktopError(result.error?.code),
    code: result.error?.code,
    payload,
  });
}

type ManjuIpcPayload = {
  pathParams?: IpcRecord;
  query?: IpcQuery;
  body?: DesktopRequestContent | null;
  fields?: IpcRecord;
  files?: LocalFileDescriptor[];
  locale?: string;
};

async function callManjuApiResult(command: string, payload: ManjuIpcPayload = {}): Promise<DesktopResourceResult> {
  return PluginSDK.callBackend<DesktopResourceResult>(command, {
    pathParams: compactIpcRecord(payload.pathParams),
    query: compactIpcQuery(payload.query),
    locale: payload.locale ?? i18n.language ?? "zh",
    ...(payload.body ? { body: payload.body } : {}),
    ...(payload.fields ? { fields: compactIpcRecord(payload.fields) } : {}),
    ...(payload.files ? { files: payload.files } : {}),
  });
}

async function callManjuApi<T = unknown>(
  command: string,
  payload: ManjuIpcPayload = {},
  fallback = "请求失败",
): Promise<T> {
  const result = await callManjuApiResult(command, payload);
  if (result.success === false) {
    throwManjuApiError(result, fallback);
  }
  return desktopContentValue(result.content) as T;
}

async function callManjuFileApi<T = unknown>(
  command: string,
  payload: Omit<ManjuIpcPayload, "files"> & { files: Array<{ fieldName: string; file: UploadFileInput }> },
  fallback = "请求失败",
): Promise<T> {
  const result = await callManjuFileApiResult(command, payload);
  if (result.success === false) {
    throwManjuApiError(result, fallback);
  }
  return desktopContentValue(result.content) as T;
}

async function callManjuFileApiResult(
  command: string,
  payload: Omit<ManjuIpcPayload, "files"> & { files: Array<{ fieldName: string; file: UploadFileInput }> },
): Promise<DesktopResourceResult> {
  return callManjuApiResult(command, {
    ...payload,
    files: await Promise.all(payload.files.map(({ fieldName, file }) => localFileDescriptor(fieldName, file))),
  });
}

function assertNotAborted(signal?: AbortSignal): void {
  if (!signal?.aborted) return;
  throw new DOMException("The operation was aborted.", "AbortError");
}
class PluginApiEventSource extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSED = 2;
  readonly url: string;
  withCredentials = false;
  readyState = PluginApiEventSource.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  private readonly stream: string;
  private readonly query: Record<string, string[]>;
  private readonly backendHandler: (payload: PluginStreamPayload) => void;
  private readonly seenEventIds = new Set<string>();
  private lastEventId: string | number | null = null;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(stream: string, query: IpcQuery = {}) {
    super();
    this.stream = stream;
    this.url = stream;
    this.query = compactIpcQuery(query);
    this.backendHandler = (payload) => {
      if (!payload || payload.stream !== this.stream || this.readyState === PluginApiEventSource.CLOSED) {
        return;
      }
      if (this.isDuplicateEvent(payload)) {
        return;
      }
      this.rememberEventCursor(payload);
      this.emitMessage(payload.event || "message", payload.data);
    };

    PluginSDK.onBackendEvent<PluginStreamPayload>("manju_api_event", this.backendHandler);
    queueMicrotask(() => {
      if (this.readyState === PluginApiEventSource.CLOSED) return;
      this.readyState = PluginApiEventSource.OPEN;
      const event = new Event("open");
      this.dispatchEvent(event);
      this.onopen?.(event);
      void PluginSDK.callBackend<{ events?: PluginStreamPayload[] }>("manju_api_event_subscribe", {
        query: this.query,
        stream: this.stream,
      })
        .then((snapshot) => {
          for (const eventPayload of snapshot.events ?? []) {
            this.backendHandler(eventPayload);
          }
          this.schedulePoll();
        })
        .catch(() => {
          const errorEvent = new Event("error");
          this.dispatchEvent(errorEvent);
          this.onerror?.(errorEvent);
          this.schedulePoll();
        });
    });
  }

  addEventListener(
    type: string,
    listener: ((event: MessageEvent) => void) | EventListenerObject | null,
    options?: boolean | AddEventListenerOptions,
  ): void {
    super.addEventListener(type, listener as EventListenerOrEventListenerObject | null, options);
  }

  removeEventListener(
    type: string,
    listener: ((event: MessageEvent) => void) | EventListenerObject | null,
    options?: boolean | EventListenerOptions,
  ): void {
    super.removeEventListener(type, listener as EventListenerOrEventListenerObject | null, options);
  }

  close(): void {
    if (this.readyState === PluginApiEventSource.CLOSED) return;
    this.readyState = PluginApiEventSource.CLOSED;
    if (this.pollTimer) {
      clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
    PluginSDK.offBackendEvent("manju_api_event", this.backendHandler);
  }

  private rememberEventCursor(payload: PluginStreamPayload): void {
    if (
      payload.event === "snapshot"
      && payload.data
      && typeof payload.data === "object"
      && "last_event_id" in payload.data
    ) {
      const snapshot = payload.data as { last_event_id?: unknown };
      const lastEventId = snapshot.last_event_id;
      if ((typeof lastEventId === "string" || typeof lastEventId === "number") && lastEventId !== "") {
        this.lastEventId = String(lastEventId);
      }
      return;
    }
    if (payload.id != null && payload.id !== "") {
      this.lastEventId = payload.id;
    }
  }

  private isDuplicateEvent(payload: PluginStreamPayload): boolean {
    if (payload.id == null || payload.id === "") {
      return false;
    }
    const key = `${payload.stream}:${payload.event}:${String(payload.id)}`;
    if (this.seenEventIds.has(key)) {
      return true;
    }
    this.seenEventIds.add(key);
    if (this.seenEventIds.size > 1000) {
      const oldest = this.seenEventIds.values().next().value;
      if (oldest) {
        this.seenEventIds.delete(oldest);
      }
    }
    return false;
  }

  private schedulePoll(): void {
    if (this.readyState === PluginApiEventSource.CLOSED || this.pollTimer) return;
    this.pollTimer = setTimeout(() => {
      this.pollTimer = null;
      void this.poll();
    }, 1000);
  }

  private async poll(): Promise<void> {
    if (this.readyState === PluginApiEventSource.CLOSED) return;
    try {
      const result = await PluginSDK.callBackend<{ events?: PluginStreamPayload[] }>("manju_api_event_poll", {
        query: this.query,
        stream: this.stream,
        lastEventId: this.lastEventId,
      });
      for (const eventPayload of result.events ?? []) {
        this.backendHandler(eventPayload);
      }
    } catch {
      const errorEvent = new Event("error");
      this.dispatchEvent(errorEvent);
      this.onerror?.(errorEvent);
    } finally {
      this.schedulePoll();
    }
  }

  private emitMessage(type: string, data: unknown): void {
    const event = new MessageEvent(type, {
      data: typeof data === "string" ? data : JSON.stringify(data ?? {}),
    });
    this.dispatchEvent(event);
    if (type === "message") {
      this.onmessage?.(event);
    }
  }
}

class API {
  // ==================== 系统配置 ====================

  static async getSystemConfig(): Promise<GetSystemConfigResponse> {
    return callManjuApi("manju_api_get_system_config");
  }

  static async updateSystemConfig(
    patch: SystemConfigPatch,
  ): Promise<GetSystemConfigResponse> {
    return callManjuApi("manju_api_update_system_config", { body: jsonBody(patch) });
  }

  static async getStyleTemplates(): Promise<{ success: boolean; templates: StyleTemplateInfo[] }> {
    await ensureLocalAssetRoots();
    const result = await callManjuApi<{ success: boolean; templates: StyleTemplateInfo[] }>("manju_api_get_style_templates");
    return {
      ...result,
      templates: result.templates.map(normalizeStyleTemplateUrls),
    };
  }

  static async createFavoriteStyleTemplate(
    payload: CreateFavoriteStyleTemplatePayload,
  ): Promise<{ success: boolean; template: StyleTemplateInfo }> {
    const result = await callManjuFileApi<{ success: boolean; template: StyleTemplateInfo }>(
      "manju_api_create_favorite_style_template",
      {
        fields: {
          style_prompt: payload.stylePrompt,
          project_name: payload.projectName ?? "",
        },
        files: payload.file ? [{ fieldName: "file", file: payload.file }] : [],
      },
      "收藏风格失败",
    );
    await ensureLocalAssetRoots();
    return {
      ...result,
      template: normalizeStyleTemplateUrls(result.template),
    };
  }

  static async deleteFavoriteStyleTemplate(templateId: string): Promise<SuccessResponse> {
    return callManjuApi("manju_api_delete_favorite_style_template", {
      pathParams: { template_id: templateId },
    });
  }


  // ==================== 项目管理 ====================

  static async listProjects(
    params: { check_extmodel?: boolean } = {},
  ): Promise<{ projects: ProjectSummary[] }> {
    await ensureLocalAssetRoots();
    const result = await callManjuApi<{ projects: ProjectSummary[] }>("manju_api_list_projects", {
      query: { check_extmodel: params.check_extmodel },
    });
    return {
      ...result,
      projects: result.projects.map(normalizeProjectSummaryUrls),
    };
  }

  static async createProject(
    payload: CreateProjectPayload,
  ): Promise<{ success: boolean; name: string; project: ProjectData }> {
    return callManjuApi("manju_api_create_project", { body: jsonBody(payload) });
  }

  static async getProject(
    name: string
  ): Promise<{
    project: ProjectData;
    scripts: Record<string, EpisodeScript>;
    asset_fingerprints?: Record<string, number>;
  }> {
    await ensureLocalAssetRoots();
    return callManjuApi("manju_api_get_project", { pathParams: { name } });
  }

  static async updateProject(
    name: string,
    updates: Partial<ProjectData> & { clear_style_image?: boolean }
  ): Promise<{ success: boolean; project: ProjectData }> {
    if ("content_mode" in updates) {
      throw new Error("项目创建后不支持修改 content_mode");
    }
    if ("generation_mode" in updates) {
      throw new Error("项目创建后不支持修改 generation_mode");
    }
    if ("script_splitting_template_id" in updates || "script_splitting" in updates) {
      throw new Error("请使用专用接口修改拆分方案");
    }
    return callManjuApi("manju_api_update_project", {
      pathParams: { name },
      body: jsonBody(updates),
    });
  }

  static async deleteProject(name: string): Promise<SuccessResponse> {
    return callManjuApi("manju_api_delete_project", { pathParams: { name } });
  }

  /** 三级解析（项目 > 系统设置 > 系统默认）后的视频模型能力。 */
  static async getVideoCapabilities(name: string): Promise<VideoCapabilitiesResponse> {
    return callManjuApi("manju_api_get_video_capabilities", { pathParams: { name } });
  }

  static async getScriptSplittingTemplates(
    contentMode?: "narration" | "drama",
  ): Promise<ScriptSplittingTemplatesResponse> {
    return callManjuApi("manju_api_get_script_splitting_templates", {
      query: { content_mode: contentMode },
    });
  }

  static async saveScriptSplittingTemplate(
    payload: ScriptSplittingTemplateUpsertPayload,
  ): Promise<ScriptSplittingTemplateMutationResponse> {
    return callManjuApi("manju_api_save_script_splitting_template", { body: jsonBody(payload) });
  }

  static async importScriptSplittingTemplate(
    template: Record<string, unknown>,
  ): Promise<ScriptSplittingTemplateMutationResponse> {
    return callManjuApi("manju_api_import_script_splitting_template", { body: jsonBody({ template }) });
  }

  static async exportScriptSplittingTemplate(templateId: string): Promise<ScriptSplittingTemplateExportResponse> {
    return callManjuApi("manju_api_export_script_splitting_template", { pathParams: { template_id: templateId } });
  }

  static async deleteScriptSplittingTemplate(
    templateId: string,
  ): Promise<{ success: boolean }> {
    return callManjuApi("manju_api_delete_script_splitting_template", { pathParams: { template_id: templateId } });
  }

  static async previewScriptSplittingTemplateChange(
    name: string,
    templateId: string,
    generationMode?: GenerationMode | null,
  ): Promise<{ success: boolean; preview: ScriptSplittingTemplatePreview }> {
    return callManjuApi("manju_api_preview_script_splitting_template_change", {
      pathParams: { name },
      body: jsonBody({ template_id: templateId, generation_mode: generationMode ?? undefined }),
    });
  }

  static async changeScriptSplittingTemplate(
    name: string,
    templateId: string,
    confirm = false,
    mode: ScriptSplittingTemplateApplyMode = "apply_keep_drafts",
    generationMode?: GenerationMode | null,
  ): Promise<ScriptSplittingTemplateChangeResponse> {
    return callManjuApi("manju_api_change_script_splitting_template", {
      pathParams: { name },
      body: jsonBody({
        template_id: templateId,
        generation_mode: generationMode ?? undefined,
        confirm,
        mode,
      }),
    });
  }

  static async previewGenerationRoutes(
    name: string,
    payload: GenerationRoutePreviewRequest,
    options: { signal?: AbortSignal } = {},
  ): Promise<GenerationRoutePreviewResponse> {
    assertNotAborted(options.signal);
    return callManjuApi("manju_api_preview_generation_routes", {
      pathParams: { project_name: name },
      body: jsonBody(payload),
    });
  }

  static async previewStoryboardReferenceUsage(
    projectName: string,
    segmentId: string,
    payload: {
      script_file: string;
      characters?: string[] | null;
      scenes?: string[] | null;
      props?: string[] | null;
      quality?: GenerationQuality | null;
      final_generation_mode?: StoryboardFinalGenerationMode | null;
      resolution?: string | null;
      source_version?: number | null;
      image_provider_t2i?: string | null;
      image_provider_i2i?: string | null;
      image_provider?: string | null;
      image_model?: string | null;
    },
  ): Promise<StoryboardReferencePreflightResponse> {
    return callManjuApi("manju_api_preview_storyboard_reference_usage", {
      pathParams: { project_name: projectName, segment_id: segmentId },
      body: jsonBody(payload),
    });
  }
  static async startProjectArchiveExport(
    projectName: string,
    scope: "full" | "current",
    exportPath: string,
  ): Promise<{ taskId: string; status: ExportTaskStatus; exportPath?: string }> {
    const result = await PluginSDK.callBackend<ExportTaskStartResponse>("manju_api_start_project_archive_export", {
      projectName,
      scope,
      exportPath,
    });
    return ensureExportTaskStarted(result);
  }

  static async getAssetArchiveExportInfo(): Promise<{
    projectsRoot: string;
    globalAssetsRoot?: string;
    styleFavoritesRoot?: string;
    scriptSplittingTemplatesRoot?: string;
  }> {
    const result = await PluginSDK.callBackend<AssetArchiveExportInfoResponse>(
      "manju_api_get_asset_archive_export_info",
      {},
    );
    if (!result.ok || !result.projectsRoot) {
      throw new Error(result.detail || "读取项目目录失败");
    }
    return {
      projectsRoot: result.projectsRoot,
      globalAssetsRoot: result.globalAssetsRoot,
      styleFavoritesRoot: result.styleFavoritesRoot,
      scriptSplittingTemplatesRoot: result.scriptSplittingTemplatesRoot,
    };
  }

  static async startAssetArchiveExport(
    exportPath: string,
    options: AssetArchiveExportOptions,
  ): Promise<{ taskId: string; status: ExportTaskStatus; exportPath?: string }> {
    const result = await PluginSDK.callBackend<ExportTaskStartResponse>(
      "manju_api_start_asset_archive_export",
      {
        exportPath,
        ...options,
      },
    );
    return ensureExportTaskStarted(result);
  }

  static async getExportTaskStatus(taskId: string): Promise<ExportTaskEvent | null> {
    const result = await PluginSDK.callBackend<ExportTaskStatusResponse>("manju_api_get_export_task_status", {
      taskId,
    });
    if (!result.ok || !result.task) return null;
    return result.task;
  }

  static async openDesktopPath(path: string): Promise<void> {
    const result = await PluginSDK.callBackend<OpenDesktopPathResponse>("manju_api_open_desktop_path", {
      path,
    });
    if (!result.ok) {
      throw new Error(result.detail || "打开保存位置失败");
    }
  }

  static async saveDiagnosticsArchive(exportPath: string): Promise<{ path: string; filename?: string }> {
    const result = await PluginSDK.callBackend<SaveDiagnosticsResponse>("manju_api_save_diagnostics_archive", {
      exportPath,
    });
    if (!result.ok || !result.path) {
      throw new Error(result.detail || "诊断包保存失败");
    }
    return { path: result.path, filename: result.filename };
  }

  static async startJianyingDraftExport(
    projectName: string,
    episode: number,
    draftPath: string,
    jianyingVersion: string = "6",
  ): Promise<{ taskId: string; status: ExportTaskStatus; draftPath?: string }> {
    const result = await PluginSDK.callBackend<ExportTaskStartResponse>("manju_api_start_jianying_draft_export", {
      projectName,
      episode,
      draftPath,
      jianyingVersion,
    });
    return ensureExportTaskStarted(result);
  }

  static async detectJianyingDraftRoot(): Promise<string> {
    const result = await PluginSDK.callBackend<DetectJianyingDraftRootResponse>(
      "manju_api_detect_jianying_draft_root",
      {},
    );
    if (!result.ok) return "";
    return result.path || "";
  }

  static async importProject(
    file: UploadFileInput,
    conflictPolicy: ImportConflictPolicy = "prompt"
  ): Promise<ImportArchiveResponse> {
    const result = await callManjuFileApiResult("manju_api_import_project", {
      fields: { conflict_policy: conflictPolicy },
      files: [{ fieldName: "file", file }],
    });

    if (result.success === false) {
      const payload = (desktopContentValue(result.content) ?? {
        detail: result.error?.message,
        errors: [],
        warnings: [],
      }) as ImportErrorPayload;
      const error = new Error(
        typeof payload.detail === "string" ? payload.detail : "导入失败"
      ) as Error & {
        status?: number;
        detail?: string;
        errors?: string[];
        warnings?: string[];
        conflict_project_name?: string;
        diagnostics?: ImportFailureDiagnostics;
      };
      error.status = statusFromDesktopError(result.error?.code);
      error.detail = typeof payload.detail === "string" ? payload.detail : "导入失败";
      error.errors = Array.isArray(payload.errors) ? payload.errors : [];
      error.warnings = Array.isArray(payload.warnings) ? payload.warnings : [];
      if (typeof payload.conflict_project_name === "string") {
        error.conflict_project_name = payload.conflict_project_name;
      }
      const diagnostics = normalizeImportFailureDiagnostics(payload.diagnostics);
      if (
        diagnostics.blocking.length > 0
        || diagnostics.auto_fixable.length > 0
        || diagnostics.warnings.length > 0
      ) {
        error.diagnostics = diagnostics;
      }
      throw error;
    }

    const payload = desktopContentValue(result.content) as ImportArchiveResponse & { diagnostics?: { auto_fixed?: unknown[]; warnings?: unknown[] } };
    return {
      ...payload,
      diagnostics: {
        auto_fixed: normalizeDiagnosticsBucket(payload?.diagnostics?.auto_fixed),
        warnings: normalizeDiagnosticsBucket(payload?.diagnostics?.warnings),
      },
    };
  }

  // ==================== 角色管理 ====================

  static async addCharacter(
    projectName: string,
    name: string,
    description: string,
    voiceStyle: string = ""
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_add_character", {
      pathParams: { project_name: projectName },
      body: jsonBody({ name, description, voice_style: voiceStyle }),
    });
  }

  static async updateCharacter(
    projectName: string,
    charName: string,
    updates: Record<string, unknown>
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_update_character", {
      pathParams: { project_name: projectName, entry_name: charName },
      body: jsonBody(updates),
    });
  }

  static async deleteCharacter(
    projectName: string,
    charName: string
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_delete_character", {
      pathParams: { project_name: projectName, entry_name: charName },
    });
  }

  // ==================== 项目场景管理 ====================

  static async addProjectScene(
    projectName: string,
    name: string,
    description: string
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_add_project_scene", {
      pathParams: { project_name: projectName },
      body: jsonBody({ name, description }),
    });
  }

  static async updateProjectScene(
    projectName: string,
    sceneName: string,
    updates: Record<string, unknown>
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_update_project_scene", {
      pathParams: { project_name: projectName, entry_name: sceneName },
      body: jsonBody(updates),
    });
  }

  static async deleteProjectScene(
    projectName: string,
    sceneName: string
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_delete_project_scene", {
      pathParams: { project_name: projectName, entry_name: sceneName },
    });
  }

  // ==================== 项目道具管理 ====================

  static async addProjectProp(
    projectName: string,
    name: string,
    description: string
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_add_project_prop", {
      pathParams: { project_name: projectName },
      body: jsonBody({ name, description }),
    });
  }

  static async updateProjectProp(
    projectName: string,
    propName: string,
    updates: Record<string, unknown>
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_update_project_prop", {
      pathParams: { project_name: projectName, entry_name: propName },
      body: jsonBody(updates),
    });
  }

  static async deleteProjectProp(
    projectName: string,
    propName: string
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_delete_project_prop", {
      pathParams: { project_name: projectName, entry_name: propName },
    });
  }

  // ==================== 场景管理 ====================

  static async getScript(
    projectName: string,
    scriptFile: string
  ): Promise<EpisodeScript> {
    return callManjuApi("manju_api_get_script", {
      pathParams: { name: projectName, script_file: scriptFile },
    });
  }

  static async updateScene(
    projectName: string,
    sceneId: string,
    scriptFile: string,
    updates: Record<string, unknown>
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_update_scene", {
      pathParams: { name: projectName, scene_id: sceneId },
      body: jsonBody({ script_file: scriptFile, updates }),
    });
  }

  // ==================== 片段管理（说书模式） ====================

  /** `updates` 字段形状参见 {@link SegmentUpdatePayload}；保留 Record 以兼容 spread 调用。 */
  static async updateSegment(
    projectName: string,
    segmentId: string,
    updates: Record<string, unknown>
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_update_segment", {
      pathParams: { name: projectName, segment_id: segmentId },
      body: jsonBody(updates),
    });
  }

  // ==================== 文件管理 ====================

  static async uploadFile(
    projectName: string,
    uploadType: string,
    file: UploadFileInput,
    name: string | null = null,
    options: { onConflict?: "fail" | "replace" | "rename" } = {}
  ): Promise<{
    success: boolean;
    path: string;
    url: string;
    filename?: string;
    normalized?: boolean;
    original_kept?: boolean;
    original_filename?: string;
    used_encoding?: string | null;
    chapter_count?: number;
  }> {
    const result = await callManjuFileApiResult("manju_api_upload_file", {
      pathParams: { project_name: projectName, upload_type: uploadType },
      query: {
        name,
        on_conflict: uploadType === "source" ? options.onConflict : undefined,
      },
      files: [{ fieldName: "file", file }],
    });

    if (result.success === false && statusFromDesktopError(result.error?.code) === 409) {
      let detail: { existing?: string; suggested_name?: string; message?: string } | null = null;
      const body = desktopContentValue(result.content) as { detail?: { existing?: string; suggested_name?: string; message?: string } };
      if (body && typeof body === "object") {
        detail = body.detail ?? null;
      }
      // 后端 SourceLoader 的 ConflictError 必然携带 existing + suggested_name；
      // 若 detail 缺字段则视为协议异常，抛通用错误（带文件名标识）而非手搓 fallback —
      // 避免前端"猜"一个可能与后端命名规则不一致的 suggested_name 误导用户
      if (!detail?.existing || !detail?.suggested_name) {
        throw new Error(`上传 "${getUploadFileName(file)}" 失败：服务端返回 409 但 detail 字段不完整`);
      }
      throw new ConflictError(
        detail.existing,
        detail.suggested_name,
        detail.message ?? "conflict",
      );
    }

    if (result.success === false) {
      throwManjuApiError(result, "上传失败");
    }
    return desktopContentValue(result.content) as {
      success: boolean;
      path: string;
      url: string;
      filename?: string;
      normalized?: boolean;
      original_kept?: boolean;
      original_filename?: string;
      used_encoding?: string | null;
      chapter_count?: number;
    };
  }

  static async listFiles(
    projectName: string
  ): Promise<{
    files: {
      source?: { name: string; size: number; url: string; raw_filename?: string | null }[];
      characters?: { name: string; size: number; url: string }[];
      scenes?: { name: string; size: number; url: string }[];
      props?: { name: string; size: number; url: string }[];
      storyboards?: { name: string; size: number; url: string }[];
      videos?: { name: string; size: number; url: string }[];
      output?: { name: string; size: number; url: string }[];
    };
  }> {
    return callManjuApi("manju_api_list_files", {
      pathParams: { project_name: projectName },
    });
  }

  static getFileUrl(
    projectName: string,
    path: string,
    cacheBust?: number | string | null
  ): string {
    const localUrl = projectFileToLocalUrl(projectName, path, cacheBust);
    if (localUrl) return localUrl;
    void ensureLocalAssetRoots();
    return appendCacheParam(path, "v", cacheBust);
  }

  static async getProjectFileLocalPath(
    projectName: string,
    path: string,
  ): Promise<string | null> {
    await ensureLocalAssetRoots();
    if (isAbsoluteLocalPath(path)) return path;
    if (!localAssetRoots?.projects_root) return null;
    return joinLocalPath(localAssetRoots.projects_root, projectName, path);
  }

  static async getGlobalAssetLocalPath(path: string | null): Promise<string | null> {
    if (!path) return null;
    await ensureLocalAssetRoots();
    return globalAssetToLocalPath(path);
  }

  // ==================== Source 文件管理 ====================

  /**
   * 获取 source 文件内容
   */
  static async getSourceContent(
    projectName: string,
    filename: string
  ): Promise<string> {
    return callManjuApi("manju_api_get_source_content", {
      pathParams: { project_name: projectName, filename },
    }, "获取文件内容失败");
  }

  /**
   * 保存 source 文件（新建或更新）
   */
  static async saveSourceFile(
    projectName: string,
    filename: string,
    content: string
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_save_source_file", {
      pathParams: { project_name: projectName, filename },
      body: textBody(content),
    }, "保存文件失败");
  }

  /**
   * 删除 source 文件
   */
  static async deleteSourceFile(
    projectName: string,
    filename: string
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_delete_source_file", {
      pathParams: { project_name: projectName, filename },
    }, "删除文件失败");
  }

  // ==================== 草稿文件管理 ====================

  /**
   * 获取项目的所有草稿
   */
  static async listDrafts(
    projectName: string
  ): Promise<{ drafts: DraftInfo[] }> {
    return callManjuApi("manju_api_list_drafts", {
      pathParams: { project_name: projectName },
    });
  }

  /**
   * 获取草稿内容
   */
  static async getDraftContent(
    projectName: string,
    episode: number,
    stepNum: number
  ): Promise<string> {
    return callManjuApi("manju_api_get_draft_content", {
      pathParams: { project_name: projectName, episode, step_num: stepNum },
    }, "获取草稿内容失败");
  }

  /**
   * 保存草稿内容
   */
  static async saveDraft(
    projectName: string,
    episode: number,
    stepNum: number,
    content: string
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_save_draft", {
      pathParams: { project_name: projectName, episode, step_num: stepNum },
      body: textBody(content),
    }, "保存草稿失败");
  }

  /**
   * 删除草稿
   */
  static async deleteDraft(
    projectName: string,
    episode: number,
    stepNum: number
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_delete_draft", {
      pathParams: { project_name: projectName, episode, step_num: stepNum },
    });
  }

  // ==================== 项目概述管理 ====================

  /**
   * 使用 AI 生成项目概述
   */
  static async generateOverview(
    projectName: string
  ): Promise<{ success: boolean; overview: ProjectOverview }> {
    return callManjuApi("manju_api_generate_overview", {
      pathParams: { name: projectName },
    });
  }

  /**
   * 更新项目概述（手动编辑）
   */
  static async updateOverview(
    projectName: string,
    updates: Partial<ProjectOverview>
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_update_overview", {
      pathParams: { name: projectName },
      body: jsonBody(updates),
    });
  }

  // ==================== 生成 API ====================

  static async getExternalGenerationPackage(
    projectName: string,
    segmentId: string,
    scriptFile: string,
  ): Promise<ExternalGenerationPackage> {
    return callManjuApi("manju_api_get_external_generation_package", {
      pathParams: { project_name: projectName, segment_id: segmentId },
      query: { script_file: scriptFile },
    });
  }

  /**
   * 生成分镜图
   * @param projectName - 项目名称
   * @param segmentId - 片段/场景 ID
   * @param prompt - 图片生成 prompt（支持字符串或结构化对象）
   * @param scriptFile - 剧本文件名
   */
  static async generateStoryboard(
    projectName: string,
    segmentId: string,
    prompt: string | Record<string, unknown>,
    scriptFile: string,
    options: GenerationRequestOptions = {},
  ): Promise<{ success: boolean; task_id: string; message: string }> {
    return callManjuApi("manju_api_generate_storyboard", {
      pathParams: { project_name: projectName, segment_id: segmentId },
      body: jsonBody({ prompt, script_file: scriptFile, ...compactGenerationOptions(options) }),
    });
  }

  /**
   * 生成视频
   * @param projectName - 项目名称
   * @param segmentId - 片段/场景 ID
   * @param prompt - 视频生成 prompt（支持字符串或结构化对象）
   * @param scriptFile - 剧本文件名
   * @param durationSeconds - 时长（秒）
   */
  static async generateVideo(
    projectName: string,
    segmentId: string,
    prompt: string | Record<string, unknown>,
    scriptFile: string,
    durationSeconds?: number | null,
    options: GenerationRequestOptions = {},
  ): Promise<{ success: boolean; task_id: string; message: string }> {
    return callManjuApi("manju_api_generate_video", {
      pathParams: { project_name: projectName, segment_id: segmentId },
      body: jsonBody({
        prompt,
        script_file: scriptFile,
        ...compactGenerationOptions({
          ...options,
          duration_seconds: durationSeconds ?? options.duration_seconds,
        }),
      }),
    });
  }

  static async finalizeEpisode(
    projectName: string,
    episode: number,
  ): Promise<FinalizeEpisodeResponse> {
    return callManjuApi("manju_api_finalize_episode", {
      pathParams: { project_name: projectName, episode },
    });
  }

  /**
   * 生成角色设计图
   * @param projectName - 项目名称
   * @param charName - 角色名称
   * @param prompt - 角色描述 prompt
   */
  static async generateCharacter(
    projectName: string,
    charName: string,
    prompt: string,
    options: GenerationRequestOptions = {},
  ): Promise<{
    success: boolean;
    task_id: string;
    message: string;
  }> {
    return callManjuApi("manju_api_generate_character", {
      pathParams: { project_name: projectName, char_name: charName },
      body: jsonBody({ prompt, ...compactGenerationOptions(options) }),
    });
  }

  /**
   * 生成场景设计图
   * @param projectName - 项目名称
   * @param sceneName - 场景名称
   * @param prompt - 场景描述 prompt
   */
  static async generateProjectScene(
    projectName: string,
    sceneName: string,
    prompt: string,
    options: GenerationRequestOptions = {},
  ): Promise<{
    success: boolean;
    task_id: string;
    message: string;
  }> {
    return callManjuApi("manju_api_generate_project_scene", {
      pathParams: { project_name: projectName, scene_name: sceneName },
      body: jsonBody({ prompt, ...compactGenerationOptions(options) }),
    });
  }

  /**
   * 生成道具设计图
   * @param projectName - 项目名称
   * @param propName - 道具名称
   * @param prompt - 道具描述 prompt
   */
  static async generateProjectProp(
    projectName: string,
    propName: string,
    prompt: string,
    options: GenerationRequestOptions = {},
  ): Promise<{
    success: boolean;
    task_id: string;
    message: string;
  }> {
    return callManjuApi("manju_api_generate_project_prop", {
      pathParams: { project_name: projectName, prop_name: propName },
      body: jsonBody({ prompt, ...compactGenerationOptions(options) }),
    });
  }

  // ==================== 任务队列 API ====================

  static async getTask(taskId: string): Promise<TaskItem> {
    return callManjuApi("manju_api_get_task", { pathParams: { task_id: taskId } });
  }

  static async listTasks(
    filters: TaskListFilters = {}
  ): Promise<{ items: TaskItem[]; total: number; page: number; page_size: number }> {
    return callManjuApi("manju_api_list_tasks", {
      query: {
        project_name: filters.projectName,
        status: filters.status,
        task_type: filters.taskType,
        source: filters.source,
        page: filters.page,
        page_size: filters.pageSize,
      },
    });
  }

  static async listProjectTasks(
    projectName: string,
    filters: Omit<TaskListFilters, "projectName"> = {}
  ): Promise<{ items: TaskItem[]; total: number; page: number; page_size: number }> {
    return callManjuApi("manju_api_list_project_tasks", {
      pathParams: { project_name: projectName },
      query: {
        status: filters.status,
        task_type: filters.taskType,
        source: filters.source,
        page: filters.page,
        page_size: filters.pageSize,
      },
    });
  }

  static async getTaskStats(
    projectName: string | null = null
  ): Promise<{ stats: TaskStats }> {
    return callManjuApi("manju_api_get_task_stats", { query: { project_name: projectName } });
  }

  // ==================== 任务取消 API ====================

  static async cancelPreview(
    taskId: string
  ): Promise<{
    task: { task_id: string; task_type: string; resource_id: string; status: string };
    cascaded: { task_id: string; task_type: string; resource_id: string }[];
  }> {
    return callManjuApi("manju_api_cancel_preview", { pathParams: { task_id: taskId } });
  }

  static async cancelTask(
    taskId: string
  ): Promise<{
    cancelled: TaskItem[];
    cancelling: string[];
    skipped_terminal: TaskItem[];
  }> {
    return callManjuApi("manju_api_cancel_task", { pathParams: { task_id: taskId } });
  }

  static async cancelAllPreview(
    projectName: string
  ): Promise<{ queued_count: number }> {
    return callManjuApi("manju_api_cancel_all_preview", {
      pathParams: { project_name: projectName },
    });
  }

  static async cancelAllQueued(
    projectName: string
  ): Promise<{ cancelled_count: number; skipped_running_count: number }> {
    return callManjuApi("manju_api_cancel_all_queued", {
      pathParams: { project_name: projectName },
    });
  }

  static openTaskStream(options: TaskStreamOptions = {}): ApiEventSource {
    const parsedLastEventId = Number(options.lastEventId);
    const lastEventId = Number.isFinite(parsedLastEventId) && parsedLastEventId > 0 ? parsedLastEventId : undefined;
    const source: ApiEventSource = new PluginApiEventSource(
      "tasks/stream",
      { project_name: options.projectName, last_event_id: lastEventId },
    );

    const parsePayload = (event: MessageEvent): unknown => {
      try {
        return JSON.parse((event.data as string) || "{}");
      } catch (err) {
        console.error("解析 SSE 数据失败:", err, event.data);
        return null;
      }
    };

    source.addEventListener("snapshot", (event) => {
      const payload = parsePayload(event);
      if (payload && typeof options.onSnapshot === "function") {
        options.onSnapshot(
          payload as TaskStreamSnapshotPayload,
          event
        );
      }
    });

    source.addEventListener("task", (event) => {
      const payload = parsePayload(event);
      if (payload && typeof options.onTask === "function") {
        options.onTask(
          payload as TaskStreamTaskPayload,
          event
        );
      }
    });

    source.onerror = (event: Event) => {
      if (typeof options.onError === "function") {
        options.onError(event);
      }
    };

    return source;
  }

  static openProjectEventStream(options: ProjectEventStreamOptions): ApiEventSource {
    const stream = `projects/${encodeURIComponent(options.projectName)}/events/stream`;
    const source: ApiEventSource = new PluginApiEventSource(stream);

    const parsePayload = (event: MessageEvent): unknown => {
      try {
        return JSON.parse((event.data as string) || "{}");
      } catch (err) {
        console.error("解析项目事件 SSE 数据失败:", err, event.data);
        return null;
      }
    };

    const createHandler = <T>(
      callback?: (payload: T, event: MessageEvent) => void
    ) => {
      return (event: Event) => {
        if (typeof callback !== "function") return;
        const payload = parsePayload(event as MessageEvent);
        if (payload) {
          callback(payload as T, event as MessageEvent);
        }
      };
    };

    source.addEventListener("snapshot", createHandler(options.onSnapshot));
    source.addEventListener("changes", createHandler(options.onChanges));

    source.onerror = (event: Event) => {
      if (typeof options.onError === "function") {
        options.onError(event);
      }
    };

    return source;
  }

  // ==================== 版本管理 API ====================

  /**
   * 获取资源版本列表
   * @param projectName - 项目名称
   * @param resourceType - 资源类型 (storyboards, videos, characters, scenes, props)
   * @param resourceId - 资源 ID
   */
  static async getVersions(
    projectName: string,
    resourceType: VersionResourceType,
    resourceId: string
  ): Promise<{
    resource_type: VersionResourceType;
    resource_id: string;
    current_version: number;
    versions: VersionInfo[];
  }> {
    await ensureLocalAssetRoots();
    const result = await callManjuApi<{
      resource_type: VersionResourceType;
      resource_id: string;
      current_version: number;
      versions: VersionInfo[];
    }>("manju_api_get_versions", {
      pathParams: { project_name: projectName, resource_type: resourceType, resource_id: resourceId },
    });
    return {
      ...result,
      versions: result.versions.map(normalizeVersionUrls),
    };
  }

  /**
   * 还原到指定版本
   * @param projectName - 项目名称
   * @param resourceType - 资源类型
   * @param resourceId - 资源 ID
   * @param version - 要还原的版本号
   */
  static async restoreVersion(
    projectName: string,
    resourceType: VersionResourceType,
    resourceId: string,
    version: number
  ): Promise<SuccessResponse & { file_path?: string; asset_fingerprints?: Record<string, number> }> {
    return callManjuApi("manju_api_restore_version", {
      pathParams: { project_name: projectName, resource_type: resourceType, resource_id: resourceId, version },
    });
  }

  static async getDesignResourceUsage(
    projectName: string,
    resourceType: DesignResourceType,
    resourceId: string,
  ): Promise<{
    resource_type: DesignResourceType;
    resource_id: string;
    in_use: boolean;
    usages: DesignResourceUsage[];
  }> {
    return callManjuApi("manju_api_get_design_resource_usage", {
      pathParams: { project_name: projectName, resource_type: resourceType, resource_id: resourceId },
    });
  }

  static async deleteDesignResource(
    projectName: string,
    resourceType: DesignResourceType,
    resourceId: string,
  ): Promise<SuccessResponse & {
    deleted_versions?: number;
    deleted_files?: string[];
    failed_files?: string[];
    file_delete_errors?: FileDeleteError[];
    asset_fingerprints?: Record<string, number>;
  }> {
    return callManjuApi("manju_api_delete_design_resource", {
      pathParams: { project_name: projectName, resource_type: resourceType, resource_id: resourceId },
    });
  }

  static async deleteVersion(
    projectName: string,
    resourceType: VersionResourceType,
    resourceId: string,
    version: number,
  ): Promise<SuccessResponse & {
    deleted_version?: number;
    deleted_file?: string;
    failed_files?: string[];
    file_delete_errors?: FileDeleteError[];
    asset_fingerprints?: Record<string, number>;
  }> {
    return callManjuApi("manju_api_delete_version", {
      pathParams: { project_name: projectName, resource_type: resourceType, resource_id: resourceId, version },
    });
  }

  static async uploadExternalMediaVersion(
    projectName: string,
    resourceType: "storyboards" | "videos",
    resourceId: string,
    file: UploadFileInput,
    options: { scriptFile: string },
  ): Promise<SuccessResponse & {
    resource_type: "storyboards" | "videos";
    resource_id: string;
    version: number;
    created_at?: string | null;
    file_path?: string;
    asset_fingerprints?: Record<string, number>;
  }> {
    return callManjuFileApi("manju_api_upload_external_media_version", {
      pathParams: { project_name: projectName, resource_type: resourceType, resource_id: resourceId },
      fields: {
        script_file: options.scriptFile,
      },
      files: [{ fieldName: "file", file }],
    }, "上传外部生成结果失败");
  }

  // ==================== 风格参考图 API ====================

  /**
   * 上传风格参考图
   * @param projectName - 项目名称
   * @param file - 图片文件
   * @param options.styleDescription - 手动填写或预分析得到的风格提示词；为空则后端自动分析
   * @returns 包含 style_image, style_description, url 的结果
   */
  static async uploadStyleImage(
    projectName: string,
    file: UploadFileInput,
    options: { styleDescription?: string | null } = {},
  ): Promise<{
    success: boolean;
    style_image: string;
    style_description: string;
    url: string;
    style_analysis_error?: string;
  }> {
    const styleDescription = options.styleDescription?.trim();
    const result = await callManjuFileApi<{
      success: boolean;
      style_image: string;
      style_description: string;
      url: string;
      style_analysis_error?: string;
    }>("manju_api_upload_style_image", {
      pathParams: { project_name: projectName },
      fields: styleDescription ? { style_description: styleDescription } : {},
      files: [{ fieldName: "file", file }],
    }, "上传失败");
    await ensureLocalAssetRoots();
    return {
      ...result,
      url: resolveLocalMediaUrl(result.url) ?? result.url,
    };
  }

  static async analyzeStyleImage(
    file: UploadFileInput,
  ): Promise<{ success: boolean; style_description: string }> {
    return callManjuFileApi("manju_api_analyze_style_image", {
      files: [{ fieldName: "file", file }],
    }, "风格分析失败");
  }

  // ==================== 助手会话 API ====================

  private static assistantStream(projectName: string, sessionId: string): string {
    return `projects/${encodeURIComponent(projectName)}/assistant/sessions/${encodeURIComponent(sessionId)}/stream`;
  }

  static async listAssistantSessions(
    projectName: string,
    status: string | null = null
  ): Promise<{ sessions: SessionMeta[] }> {
    return callManjuApi("manju_api_list_assistant_sessions", {
      pathParams: { project_name: projectName },
      query: { status },
    });
  }

  static async getAssistantSession(
    projectName: string,
    sessionId: string
  ): Promise<{ session: SessionMeta }> {
    return callManjuApi("manju_api_get_assistant_session", {
      pathParams: { project_name: projectName, session_id: sessionId },
    });
  }

  static async getAssistantSnapshot(
    projectName: string,
    sessionId: string
  ): Promise<AssistantSnapshot> {
    return callManjuApi("manju_api_get_assistant_snapshot", {
      pathParams: { project_name: projectName, session_id: sessionId },
    });
  }

  static async sendAssistantMessage(
    projectName: string,
    content: string,
    sessionId?: string | null,
    images?: Array<{ data: string; media_type: string }>
  ): Promise<{ session_id: string; status: string }> {
    return callManjuApi("manju_api_send_assistant_message", {
      pathParams: { project_name: projectName },
      body: jsonBody({
        content,
        session_id: sessionId || undefined,
        images: images || [],
      }),
    });
  }

  static async interruptAssistantSession(
    projectName: string,
    sessionId: string
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_interrupt_assistant_session", {
      pathParams: { project_name: projectName, session_id: sessionId },
    });
  }

  static async answerAssistantQuestion(
    projectName: string,
    sessionId: string,
    questionId: string,
    answers: Record<string, string>
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_answer_assistant_question", {
      pathParams: { project_name: projectName, session_id: sessionId, question_id: questionId },
      body: jsonBody({ answers }),
    });
  }

  static openAssistantStream(projectName: string, sessionId: string): ApiEventSource {
    return new PluginApiEventSource(this.assistantStream(projectName, sessionId));
  }

  static async listAssistantSkills(
    projectName: string
  ): Promise<{ skills: SkillInfo[] }> {
    return callManjuApi("manju_api_list_assistant_skills", {
      pathParams: { project_name: projectName },
    });
  }

  static async deleteAssistantSession(
    projectName: string,
    sessionId: string
  ): Promise<SuccessResponse> {
    return callManjuApi("manju_api_delete_assistant_session", {
      pathParams: { project_name: projectName, session_id: sessionId },
    });
  }

  // ==================== 费用统计 API ====================

  /**
   * 获取统计摘要
   * @param filters - 筛选条件
   */
  static async getUsageStats(
    filters: UsageStatsFilters = {}
  ): Promise<Record<string, unknown>> {
    return callManjuApi("manju_api_get_usage_stats", {
      query: {
        project_name: filters.projectName,
        start_date: filters.startDate,
        end_date: filters.endDate,
      },
    });
  }

  /**
   * 获取调用记录列表
   * @param filters - 筛选条件
   */
  static async getUsageCalls(
    filters: UsageCallsFilters = {}
  ): Promise<Record<string, unknown>> {
    return callManjuApi("manju_api_get_usage_calls", {
      query: {
        project_name: filters.projectName,
        call_type: filters.callType,
        status: filters.status,
        start_date: filters.startDate,
        end_date: filters.endDate,
        page: filters.page,
        page_size: filters.pageSize,
      },
    });
  }

  /**
   * 获取有调用记录的项目列表
   */
  static async getUsageProjects(): Promise<{ projects: string[] }> {
    return callManjuApi("manju_api_get_usage_projects");
  }

  static async getProviderRecommendations(
    filters: { projectName?: string; callType?: string; minCalls?: number; limit?: number } = {},
  ): Promise<{
    recommendations: ProviderRecommendation[];
    min_calls: number;
    project_name?: string | null;
    call_type?: string | null;
  }> {
    return callManjuApi("manju_api_get_provider_recommendations", {
      query: {
        project_name: filters.projectName,
        call_type: filters.callType,
        min_calls: filters.minCalls,
        limit: filters.limit,
      },
    });
  }

  static async upsertQualityRating(
    projectName: string,
    payload: QualityRatingRequest,
  ): Promise<{ rating: Record<string, unknown> }> {
    return callManjuApi("manju_api_upsert_quality_rating", {
      pathParams: { project_name: projectName },
      body: jsonBody(payload),
    });
  }

  static async getQualityRatings(
    projectName: string,
    filters: { resourceType?: string; resourceId?: string; version?: number } = {},
  ): Promise<{ ratings: Array<Record<string, unknown>> }> {
    return callManjuApi("manju_api_get_quality_ratings", {
      pathParams: { project_name: projectName },
      query: {
        resource_type: filters.resourceType,
        resource_id: filters.resourceId,
        version: filters.version,
      },
    });
  }

  static async getQualityStats(projectName: string): Promise<QualityStatsResponse> {
    return callManjuApi("manju_api_get_quality_stats", { pathParams: { project_name: projectName } });
  }

  static async getQualityAnalysis(): Promise<QualityAnalysisResponse> {
    return callManjuApi("manju_api_get_quality_analysis");
  }

  static async getFinalizationReport(
    projectName: string,
    limit = 100,
  ): Promise<FinalizationTaskReportResponse> {
    return callManjuApi("manju_api_get_finalization_report", {
      pathParams: { project_name: projectName },
      query: { limit },
    });
  }

  // ==================== Provider 管理 API ====================

  /** 获取所有 provider 列表及状态。 */
  static async getProviders(): Promise<{ providers: ProviderInfo[] }> {
    return callManjuApi("manju_api_get_providers");
  }

  /** 获取指定 provider 的配置详情（含字段列表）。 */
  static async getProviderConfig(id: string): Promise<ProviderConfigDetail> {
    return callManjuApi("manju_api_get_provider_config", { pathParams: { provider_id: id } });
  }

  /** 更新指定 provider 的配置字段。 */
  static async patchProviderConfig(
    id: string,
    patch: Record<string, string | null>
  ): Promise<void> {
    return callManjuApi("manju_api_patch_provider_config", {
      pathParams: { provider_id: id },
      body: jsonBody(patch),
    });
  }

  /** 测试指定 provider 的连接。 */
  static async testProviderConnection(id: string, credentialId?: number): Promise<ProviderTestResult> {
    return callManjuApi("manju_api_test_provider_connection", {
      pathParams: { provider_id: id },
      query: { credential_id: credentialId },
    });
  }

  // ==================== Provider 凭证管理 API ====================

  static async listCredentials(providerId: string): Promise<{ credentials: ProviderCredential[] }> {
    return callManjuApi("manju_api_list_credentials", { pathParams: { provider_id: providerId } });
  }

  static async createCredential(
    providerId: string,
    data: { name: string; api_key?: string; base_url?: string },
  ): Promise<ProviderCredential> {
    return callManjuApi("manju_api_create_credential", {
      pathParams: { provider_id: providerId },
      body: jsonBody(data),
    });
  }

  static async updateCredential(
    providerId: string,
    credId: number,
    data: { name?: string; api_key?: string; base_url?: string },
  ): Promise<void> {
    return callManjuApi("manju_api_update_credential", {
      pathParams: { provider_id: providerId, cred_id: credId },
      body: jsonBody(data),
    });
  }

  static async deleteCredential(providerId: string, credId: number): Promise<void> {
    return callManjuApi("manju_api_delete_credential", {
      pathParams: { provider_id: providerId, cred_id: credId },
    });
  }

  static async activateCredential(providerId: string, credId: number): Promise<void> {
    return callManjuApi("manju_api_activate_credential", {
      pathParams: { provider_id: providerId, cred_id: credId },
    });
  }

  static async uploadVertexCredential(name: string, file: UploadFileInput): Promise<ProviderCredential> {
    return callManjuFileApi("manju_api_upload_vertex_credential", {
      query: { name },
      files: [{ fieldName: "file", file }],
    }, "上传凭证失败");
  }

  // ==================== Agent 配置 / 凭证 API ====================

  static async listAgentPresetProviders(): Promise<PresetProvidersResponse> {
    return callManjuApi("manju_api_list_agent_preset_providers");
  }

  static async listAgentCredentials(): Promise<{ credentials: AgentCredential[] }> {
    return callManjuApi("manju_api_list_agent_credentials");
  }

  static async createAgentCredential(
    data: CreateAgentCredentialRequest,
  ): Promise<AgentCredential> {
    return callManjuApi("manju_api_create_agent_credential", { body: jsonBody(data) });
  }

  static async updateAgentCredential(
    id: number,
    data: UpdateAgentCredentialRequest,
  ): Promise<AgentCredential> {
    return callManjuApi("manju_api_update_agent_credential", {
      pathParams: { cred_id: id },
      body: jsonBody(data),
    });
  }

  static async deleteAgentCredential(id: number): Promise<void> {
    return callManjuApi("manju_api_delete_agent_credential", { pathParams: { cred_id: id } });
  }

  static async activateAgentCredential(id: number): Promise<{ active_id: number }> {
    return callManjuApi("manju_api_activate_agent_credential", { pathParams: { cred_id: id } });
  }

  static async testAgentCredential(id: number): Promise<TestConnectionResponse> {
    return callManjuApi("manju_api_test_agent_credential", { pathParams: { cred_id: id } });
  }

  static async testAgentConnectionDraft(
    data: TestConnectionRequest,
  ): Promise<TestConnectionResponse> {
    return callManjuApi("manju_api_test_agent_connection_draft", { body: jsonBody(data) });
  }

  // ==================== 自定义供应商 API ====================

  static async listCustomProviders(): Promise<{ providers: CustomProviderInfo[] }> {
    return callManjuApi("manju_api_list_custom_providers");
  }

  static async listEndpointCatalog(): Promise<{ endpoints: EndpointDescriptor[] }> {
    return callManjuApi("manju_api_list_endpoint_catalog");
  }

  static async createCustomProvider(data: CustomProviderCreateRequest): Promise<CustomProviderInfo> {
    return callManjuApi("manju_api_create_custom_provider", { body: jsonBody(data) });
  }

  static async getCustomProvider(id: number): Promise<CustomProviderInfo> {
    return callManjuApi("manju_api_get_custom_provider", { pathParams: { provider_id: id } });
  }

  static async updateCustomProvider(id: number, data: Partial<Omit<CustomProviderCreateRequest, "discovery_format" | "models">>): Promise<void> {
    return callManjuApi("manju_api_update_custom_provider", {
      pathParams: { provider_id: id },
      body: jsonBody(data),
    });
  }

  static async fullUpdateCustomProvider(id: number, data: { display_name: string; base_url: string; api_key?: string; models: CustomProviderModelInput[] }): Promise<CustomProviderInfo> {
    return callManjuApi("manju_api_full_update_custom_provider", {
      pathParams: { provider_id: id },
      body: jsonBody(data),
    });
  }

  static async deleteCustomProvider(id: number): Promise<void> {
    return callManjuApi("manju_api_delete_custom_provider", { pathParams: { provider_id: id } });
  }

  static async replaceCustomProviderModels(id: number, models: CustomProviderModelInput[]): Promise<CustomProviderModelInfo[]> {
    return callManjuApi("manju_api_replace_custom_provider_models", {
      pathParams: { provider_id: id },
      body: jsonBody({ models }),
    });
  }

  static async discoverModels(data: { discovery_format: string; base_url: string; api_key: string }): Promise<{ models: DiscoveredModel[] }> {
    return callManjuApi("manju_api_discover_models", { body: jsonBody(data) });
  }

  static async discoverModelsForProvider(id: number): Promise<{ models: DiscoveredModel[] }> {
    return callManjuApi("manju_api_discover_models_for_provider", { pathParams: { provider_id: id } });
  }

  static async testCustomConnection(data: { discovery_format: string; base_url: string; api_key: string }): Promise<{ success: boolean; message: string }> {
    return callManjuApi("manju_api_test_custom_connection", { body: jsonBody(data) });
  }

  static async testCustomConnectionById(id: number): Promise<{ success: boolean; message: string }> {
    return callManjuApi("manju_api_test_custom_connection_by_id", { pathParams: { provider_id: id } });
  }

  static async getCustomProviderCredentials(id: number): Promise<CustomProviderCredentials> {
    return callManjuApi("manju_api_get_custom_provider_credentials", { pathParams: { provider_id: id } });
  }

  static async discoverAnthropicModels(
    data: AnthropicDiscoverRequest,
    options: { signal?: AbortSignal } = {},
  ): Promise<AnthropicDiscoverResponse> {
    assertNotAborted(options.signal);
    return callManjuApi("manju_api_discover_anthropic_models", { body: jsonBody(data) });
  }

  // ==================== 用量统计（按 provider 分组）API ====================

  /**
   * 获取按 provider 分组的用量统计。
   * @param params - 可选筛选：provider、start、end（ISO 日期字符串）
   */
  static async getUsageStatsGrouped(
    params: { provider?: string; start?: string; end?: string } = {}
  ): Promise<UsageStatsResponse> {
    return callManjuApi("manju_api_get_usage_stats_grouped", {
      query: {
        group_by: "provider",
        provider: params.provider,
        start_date: params.start,
        end_date: params.end,
      },
    });
  }

  // ==================== 费用估算 API ====================

  /**
   * 获取项目费用估算。
   * @param projectName - 项目名称
   */
  static async getCostEstimate(projectName: string): Promise<CostEstimateResponse> {
    return callManjuApi("manju_api_get_cost_estimate", { pathParams: { project_name: projectName } });
  }

  // ==================== Grid 图生视频 API ====================

  /**
   * 生成 Grid 图像（多场景网格）
   * @param projectName - 项目名称
   * @param episode - 剧集编号
   * @param scriptFile - 剧本文件名
   * @param sceneIds - 可选，指定场景 ID 列表
   */
  static async generateGrid(
    projectName: string,
    episode: number,
    scriptFile: string,
    sceneIds?: string[]
  ): Promise<{ success: boolean; grid_ids: string[]; task_ids: string[]; message: string }> {
    return callManjuApi("manju_api_generate_grid", {
      pathParams: { project_name: projectName, episode },
      body: jsonBody({ script_file: scriptFile, scene_ids: sceneIds, quality: "final" }),
    });
  }

  /**
   * 列出项目所有 Grid 记录
   * @param projectName - 项目名称
   */
  static async listGrids(projectName: string): Promise<GridGeneration[]> {
    return callManjuApi("manju_api_list_grids", { pathParams: { project_name: projectName } });
  }

  /**
   * 获取单个 Grid 详情
   * @param projectName - 项目名称
   * @param gridId - Grid ID
   */
  static async getGrid(projectName: string, gridId: string): Promise<GridGeneration> {
    return callManjuApi("manju_api_get_grid", {
      pathParams: { project_name: projectName, grid_id: gridId },
    });
  }

  /**
   * 重新生成 Grid 图像
   * @param projectName - 项目名称
   * @param gridId - Grid ID
   */
  static async regenerateGrid(
    projectName: string,
    gridId: string
  ): Promise<{ success: boolean; task_id: string }> {
    return callManjuApi("manju_api_regenerate_grid", {
      pathParams: { project_name: projectName, grid_id: gridId },
    });
  }

  // ==================== Global Asset Library ====================

  static async listAssets(
    params: { type?: AssetType; q?: string; limit?: number; offset?: number } = {},
    options: { signal?: AbortSignal } = {},
  ) {
    assertNotAborted(options.signal);
    await ensureLocalAssetRoots();
    return callManjuApi<{ items: Asset[]; total?: number }>("manju_api_list_assets", {
      query: {
        type: params.type,
        q: params.q,
        limit: params.limit,
        offset: params.offset,
      },
    });
  }

  static async getAsset(id: string) {
    await ensureLocalAssetRoots();
    return callManjuApi<{ asset: Asset }>("manju_api_get_asset", { pathParams: { asset_id: id } });
  }

  static async createAsset(payload: AssetCreatePayload & { image?: UploadFileInput }) {
    const fields = {
      type: payload.type,
      name: payload.name,
      description: payload.description ?? "",
      voice_style: payload.voice_style ?? "",
    };
    return callManjuFileApi<{ asset: Asset }>("manju_api_create_asset", {
      fields,
      files: payload.image
        ? [{ fieldName: "image", file: payload.image }]
        : [],
    });
  }

  static async updateAsset(id: string, patch: AssetUpdatePayload) {
    return callManjuApi<{ asset: Asset }>("manju_api_update_asset", {
      pathParams: { asset_id: id },
      body: jsonBody(patch),
    });
  }

  static async replaceAssetImage(id: string, image: UploadFileInput) {
    return callManjuFileApi<{ asset: Asset }>("manju_api_replace_asset_image", {
      pathParams: { asset_id: id },
      files: [{ fieldName: "image", file: image }],
    });
  }

  static async deleteAsset(id: string): Promise<void> {
    return callManjuApi("manju_api_delete_asset", { pathParams: { asset_id: id } });
  }

  static async addAssetFromProject(payload: {
    project_name: string;
    resource_type: AssetType;
    resource_id: string;
    override_name?: string;
    overwrite?: boolean;
  }) {
    return callManjuApi<{ asset: Asset }>("manju_api_add_asset_from_project", { body: jsonBody(payload) });
  }

  static async applyAssetsToProject(payload: {
    asset_ids: string[];
    target_project: string;
    conflict_policy: "skip" | "overwrite" | "rename";
  }) {
    return callManjuApi<{
      succeeded: Array<{ id: string; name: string }>;
      skipped: Array<{ id: string; name: string }>;
      failed: Array<{ id: string; reason: string }>;
    }>("manju_api_apply_assets_to_project", { body: jsonBody(payload) });
  }

  static getGlobalAssetUrl(path: string | null, fp?: string | null): string | null {
    if (!path) return null;
    const localUrl = globalAssetToLocalUrl(path, fp);
    if (localUrl) return localUrl;
    void ensureLocalAssetRoots();

    const parts = path.split("/");
    if (parts.length < 3 || parts[0] !== "_global_assets") return null;
    if (!parts[1] || !parts.slice(2).join("/")) return null;
    return appendCacheParam(path, "fp", fp);
  }

  // ==================== Reference-to-Video API ====================

  /** List reference-video units for an episode. */
  static async listReferenceVideoUnits(
    projectName: string,
    episode: number,
  ): Promise<{ units: ReferenceVideoUnit[] }> {
    return callManjuApi("manju_api_list_reference_video_units", {
      pathParams: { project_name: projectName, episode },
    });
  }

  /** Create a new reference-video unit. */
  static async addReferenceVideoUnit(
    projectName: string,
    episode: number,
    payload: {
      prompt: string;
      references: ReferenceResource[];
      duration_seconds?: number;
      transition_to_next?: TransitionType;
      note?: string | null;
    },
  ): Promise<{ unit: ReferenceVideoUnit }> {
    return callManjuApi("manju_api_add_reference_video_unit", {
      pathParams: { project_name: projectName, episode },
      body: jsonBody(payload),
    });
  }

  /** Patch prompt/references/duration/transition/note on an existing unit. */
  static async patchReferenceVideoUnit(
    projectName: string,
    episode: number,
    unitId: string,
    patch: {
      prompt?: string;
      references?: ReferenceResource[];
      duration_seconds?: number;
      transition_to_next?: TransitionType;
      note?: string | null;
    },
  ): Promise<{ unit: ReferenceVideoUnit }> {
    return callManjuApi("manju_api_patch_reference_video_unit", {
      pathParams: { project_name: projectName, episode, unit_id: unitId },
      body: jsonBody(patch),
    });
  }

  /** Delete a unit. Returns void on 204. */
  static async deleteReferenceVideoUnit(
    projectName: string,
    episode: number,
    unitId: string,
  ): Promise<void> {
    return callManjuApi("manju_api_delete_reference_video_unit", {
      pathParams: { project_name: projectName, episode, unit_id: unitId },
    });
  }

  /** Reorder units by providing the full ordered unit_id list. */
  static async reorderReferenceVideoUnits(
    projectName: string,
    episode: number,
    unitIds: string[],
  ): Promise<{ units: ReferenceVideoUnit[] }> {
    return callManjuApi("manju_api_reorder_reference_video_units", {
      pathParams: { project_name: projectName, episode },
      body: jsonBody({ unit_ids: unitIds }),
    });
  }

  /** Enqueue generation; returns 202 with task_id. */
  static async generateReferenceVideoUnit(
    projectName: string,
    episode: number,
    unitId: string,
    options: GenerationRequestOptions = {},
  ): Promise<{ task_id: string; deduped: boolean }> {
    return callManjuApi("manju_api_generate_reference_video_unit", {
      pathParams: { project_name: projectName, episode, unit_id: unitId },
      body: jsonBody(compactGenerationOptions(options)),
    });
  }
}

export { API };


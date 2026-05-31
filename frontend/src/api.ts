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
  ImportProjectResponse,
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
}

export interface StyleTemplateInfo {
  id: string;
  category: StyleCategory;
  prompt: string;
  thumbnail_file: string;
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

const API_BASE = "/api/v1";

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
      const roots = await PluginSDK.callBackend<Partial<LocalAssetRoots>>("arcreel_asset_roots", {});
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
      // Browser-only tests or early startup can keep the legacy API URL fallback.
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

function normalizeVersionUrls(version: VersionInfo): VersionInfo {
  return {
    ...version,
    file_url: version.file_url ? resolveLocalMediaUrl(version.file_url) ?? version.file_url : version.file_url,
  };
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

export type ExportTaskKind = "project_archive" | "jianying_draft";
export type ExportTaskStatus = "queued" | "running" | "completed" | "failed";

export interface ExportTaskStartResponse {
  ok?: boolean;
  detail?: string;
  taskId?: string;
  status?: ExportTaskStatus;
  exportPath?: string;
  draftPath?: string;
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
  error?: string;
  updatedAt?: string;
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

function base64ToBytes(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
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

function desktopContentToBody(content: DesktopContent | undefined): {
  body: BodyInit;
  mimeType: string;
  empty: boolean;
} {
  if (!content || content.kind === "empty") {
    return { body: "", mimeType: "text/plain;charset=utf-8", empty: true };
  }
  if (content.kind === "json") {
    return { body: JSON.stringify(content.value ?? null), mimeType: "application/json;charset=utf-8", empty: false };
  }
  if (content.kind === "binary") {
    const bytes = base64ToBytes(content.base64);
    const arrayBuffer = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(arrayBuffer).set(bytes);
    return {
      body: new Blob([arrayBuffer]),
      mimeType: content.mimeType || "application/octet-stream",
      empty: false,
    };
  }
  return { body: content.text, mimeType: content.mimeType || "text/plain;charset=utf-8", empty: false };
}

function desktopResultToResponse(result: DesktopResourceResult): Response {
  const success = result.success !== false;
  const content = success
    ? result.content
    : result.content ?? { kind: "json" as const, value: { detail: result.error?.message || "请求失败" } };
  const { body, mimeType, empty } = desktopContentToBody(content);
  return new Response(body, {
    status: success ? (empty ? 204 : 200) : statusFromDesktopError(result.error?.code),
    headers: { "content-type": mimeType },
  });
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

function apiResourceFromUrl(url: string): {
  resource: string;
  query: Record<string, string[]>;
} {
  const parsed = new URL(url, window.location.href);
  const resource = parsed.pathname
    .replace(/^\/api\/v1\/?/, "")
    .replace(/^\/api\/?/, "")
    .replace(/^\/+/, "");
  const query: Record<string, string[]> = {};
  parsed.searchParams.forEach((value, key) => {
    query[key] = [...(query[key] ?? []), value];
  });
  return { resource: resource || "root", query };
}

async function requestWithLocalFiles(
  url: string,
  fields: Record<string, string | number | boolean | null | undefined>,
  files: Array<{ fieldName: string; file: UploadFileInput }>,
): Promise<Response> {
  const result = await PluginSDK.callBackend<DesktopResourceResult>("arcreel_local_file_request", {
    operation: "create",
    ...apiResourceFromUrl(url),
    locale: i18n.language || "zh",
    fields,
    files: await Promise.all(files.map(({ fieldName, file }) => localFileDescriptor(fieldName, file))),
  });
  return desktopResultToResponse(result);
}

/**
 * 检查 fetch 响应状态，抛出包含后端错误信息的 Error。
 * 用于不经过 API.request() 的自定义 fetch 调用。
 */
async function throwIfNotOk(response: Response, fallbackMsg: string): Promise<void> {
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: response.statusText })) as ErrorResponse;
    const detail = error.detail;
    throw new Error(typeof detail === "string" ? detail || fallbackMsg : fallbackMsg);
  }
}

/** 为本地插件请求注入语言等桌面客户端 header。 */
function withPluginHeaders(options: RequestInit = {}): RequestInit {
  const headers = new Headers(options.headers);
  headers.set("Accept-Language", i18n.language || "zh");
  return { ...options, headers };
}

class API {
  /**
   * 通用请求方法
   */
  static async request<T = unknown>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${API_BASE}${endpoint}`;
    const defaultOptions: RequestInit = {
      headers: {
        "Content-Type": "application/json",
      },
    };

    const response = await fetch(url, withPluginHeaders({ ...defaultOptions, ...options }));

    if (!response.ok) {
      const error = await response
        .json()
        .catch(() => ({ detail: response.statusText })) as ErrorResponse;
      let message = "请求失败";
      if (typeof error.detail === "string") {
        message = error.detail;
      } else if (Array.isArray(error.detail) && error.detail.length > 0) {
        message = error.detail.map((e) => (typeof e === "string" ? e : e?.msg)).filter(Boolean).join("; ") || message;
      }
      throw new Error(message);
    }

    if (response.status === 204) {
      return undefined as T;
    }
    return response.json() as Promise<T>;
  }

  // ==================== 系统配置 ====================

  static async getSystemConfig(): Promise<GetSystemConfigResponse> {
    return this.request("/system/config");
  }

  static async updateSystemConfig(
    patch: SystemConfigPatch,
  ): Promise<GetSystemConfigResponse> {
    return this.request("/system/config", {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
  }

  static async getStyleTemplates(): Promise<{ success: boolean; templates: StyleTemplateInfo[] }> {
    return this.request("/style-templates");
  }


  // ==================== 项目管理 ====================

  static async listProjects(
    params: { check_extmodel?: boolean } = {},
  ): Promise<{ projects: ProjectSummary[] }> {
    await ensureLocalAssetRoots();
    const searchParams = new URLSearchParams();
    if (params.check_extmodel !== undefined) {
      searchParams.set("check_extmodel", String(params.check_extmodel));
    }
    const query = searchParams.toString();
    const result = await this.request<{ projects: ProjectSummary[] }>(
      `/projects${query ? `?${query}` : ""}`,
    );
    return {
      ...result,
      projects: result.projects.map(normalizeProjectSummaryUrls),
    };
  }

  static async createProject(
    payload: CreateProjectPayload,
  ): Promise<{ success: boolean; name: string; project: ProjectData }> {
    return this.request("/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  static async getProject(
    name: string
  ): Promise<{
    project: ProjectData;
    scripts: Record<string, EpisodeScript>;
    asset_fingerprints?: Record<string, number>;
  }> {
    await ensureLocalAssetRoots();
    return this.request(`/projects/${encodeURIComponent(name)}`);
  }

  static async updateProject(
    name: string,
    updates: Partial<ProjectData> & { clear_style_image?: boolean }
  ): Promise<{ success: boolean; project: ProjectData }> {
    if ("content_mode" in updates) {
      throw new Error("项目创建后不支持修改 content_mode");
    }
    return this.request(`/projects/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    });
  }

  static async deleteProject(name: string): Promise<SuccessResponse> {
    return this.request(`/projects/${encodeURIComponent(name)}`, {
      method: "DELETE",
    });
  }

  /** 三级解析（项目 > 系统设置 > 系统默认）后的视频模型能力。 */
  static async getVideoCapabilities(name: string): Promise<{
    provider_id: string;
    model: string;
    supported_durations: number[];
    max_duration: number;
    max_reference_images: number;
    source: "registry" | "custom";
    default_duration?: number | null;
    content_mode?: string | null;
    generation_mode?: string | null;
  }> {
    return this.request(`/projects/${encodeURIComponent(name)}/video-capabilities`);
  }

  static async startProjectArchiveExport(
    projectName: string,
    scope: "full" | "current",
    exportPath: string,
  ): Promise<{ taskId: string; status: ExportTaskStatus; exportPath?: string }> {
    const result = await PluginSDK.callBackend<ExportTaskStartResponse>("arcreel_start_project_archive_export", {
      projectName,
      scope,
      exportPath,
    });
    return ensureExportTaskStarted(result);
  }

  static async getExportTaskStatus(taskId: string): Promise<ExportTaskEvent | null> {
    const result = await PluginSDK.callBackend<ExportTaskStatusResponse>("arcreel_export_task_status", {
      taskId,
    });
    if (!result.ok || !result.task) return null;
    return result.task;
  }

  static async openDesktopPath(path: string): Promise<void> {
    const result = await PluginSDK.callBackend<OpenDesktopPathResponse>("arcreel_open_desktop_path", {
      path,
    });
    if (!result.ok) {
      throw new Error(result.detail || "打开保存位置失败");
    }
  }

  static async saveDiagnosticsArchive(exportPath: string): Promise<{ path: string; filename?: string }> {
    const result = await PluginSDK.callBackend<SaveDiagnosticsResponse>("arcreel_save_diagnostics", {
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
    const result = await PluginSDK.callBackend<ExportTaskStartResponse>("arcreel_start_jianying_draft_export", {
      projectName,
      episode,
      draftPath,
      jianyingVersion,
    });
    return ensureExportTaskStarted(result);
  }

  static async detectJianyingDraftRoot(): Promise<string> {
    const result = await PluginSDK.callBackend<DetectJianyingDraftRootResponse>(
      "arcreel_detect_jianying_draft_root",
      {},
    );
    if (!result.ok) return "";
    return result.path || "";
  }

  static async importProject(
    file: UploadFileInput,
    conflictPolicy: ImportConflictPolicy = "prompt"
  ): Promise<ImportProjectResponse> {
    const response = await requestWithLocalFiles(
      `${API_BASE}/projects/import`,
      { conflict_policy: conflictPolicy },
      [{ fieldName: "file", file }],
    );

    if (!response.ok) {
      const payload = await response
        .json()
        .catch(() => ({ detail: response.statusText, errors: [], warnings: [] })) as ImportErrorPayload;
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
      error.status = response.status;
      error.detail = typeof payload.detail === "string" ? payload.detail : "导入失败";
      error.errors = Array.isArray(payload.errors) ? payload.errors : [];
      error.warnings = Array.isArray(payload.warnings) ? payload.warnings : [];
      if (typeof payload.conflict_project_name === "string") {
        error.conflict_project_name = payload.conflict_project_name;
      }
      error.diagnostics = normalizeImportFailureDiagnostics(payload.diagnostics);
      throw error;
    }

    const payload = await response.json() as ImportProjectResponse & { diagnostics?: { auto_fixed?: unknown[]; warnings?: unknown[] } };
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
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/characters`,
      {
        method: "POST",
        body: JSON.stringify({
          name,
          description,
          voice_style: voiceStyle,
        }),
      }
    );
  }

  static async updateCharacter(
    projectName: string,
    charName: string,
    updates: Record<string, unknown>
  ): Promise<SuccessResponse> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/characters/${encodeURIComponent(charName)}`,
      {
        method: "PATCH",
        body: JSON.stringify(updates),
      }
    );
  }

  static async deleteCharacter(
    projectName: string,
    charName: string
  ): Promise<SuccessResponse> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/characters/${encodeURIComponent(charName)}`,
      {
        method: "DELETE",
      }
    );
  }

  // ==================== 项目场景管理 ====================

  static async addProjectScene(
    projectName: string,
    name: string,
    description: string
  ): Promise<SuccessResponse> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/scenes`,
      {
        method: "POST",
        body: JSON.stringify({ name, description }),
      }
    );
  }

  static async updateProjectScene(
    projectName: string,
    sceneName: string,
    updates: Record<string, unknown>
  ): Promise<SuccessResponse> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/scenes/${encodeURIComponent(sceneName)}`,
      {
        method: "PATCH",
        body: JSON.stringify(updates),
      }
    );
  }

  static async deleteProjectScene(
    projectName: string,
    sceneName: string
  ): Promise<SuccessResponse> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/scenes/${encodeURIComponent(sceneName)}`,
      {
        method: "DELETE",
      }
    );
  }

  // ==================== 项目道具管理 ====================

  static async addProjectProp(
    projectName: string,
    name: string,
    description: string
  ): Promise<SuccessResponse> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/props`,
      {
        method: "POST",
        body: JSON.stringify({ name, description }),
      }
    );
  }

  static async updateProjectProp(
    projectName: string,
    propName: string,
    updates: Record<string, unknown>
  ): Promise<SuccessResponse> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/props/${encodeURIComponent(propName)}`,
      {
        method: "PATCH",
        body: JSON.stringify(updates),
      }
    );
  }

  static async deleteProjectProp(
    projectName: string,
    propName: string
  ): Promise<SuccessResponse> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/props/${encodeURIComponent(propName)}`,
      {
        method: "DELETE",
      }
    );
  }

  // ==================== 场景管理 ====================

  static async getScript(
    projectName: string,
    scriptFile: string
  ): Promise<EpisodeScript> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/scripts/${encodeURIComponent(scriptFile)}`
    );
  }

  static async updateScene(
    projectName: string,
    sceneId: string,
    scriptFile: string,
    updates: Record<string, unknown>
  ): Promise<SuccessResponse> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/script-scenes/${encodeURIComponent(sceneId)}`,
      {
        method: "PATCH",
        body: JSON.stringify({ script_file: scriptFile, updates }),
      }
    );
  }

  // ==================== 片段管理（说书模式） ====================

  /** `updates` 字段形状参见 {@link SegmentUpdatePayload}；保留 Record 以兼容 spread 调用。 */
  static async updateSegment(
    projectName: string,
    segmentId: string,
    updates: Record<string, unknown>
  ): Promise<SuccessResponse> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/segments/${encodeURIComponent(segmentId)}`,
      {
        method: "PATCH",
        body: JSON.stringify(updates),
      }
    );
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
    const qsParts: string[] = [];
    if (name) qsParts.push(`name=${encodeURIComponent(name)}`);
    if (uploadType === "source" && options.onConflict) {
      qsParts.push(`on_conflict=${encodeURIComponent(options.onConflict)}`);
    }
    const qs = qsParts.join("&");
    const url = `/projects/${encodeURIComponent(projectName)}/upload/${uploadType}${qs ? "?" + qs : ""}`;

    const response = await requestWithLocalFiles(
      `${API_BASE}${url}`,
      {},
      [{ fieldName: "file", file }],
    );

    if (response.status === 409) {
      let detail: { existing?: string; suggested_name?: string; message?: string } | null = null;
      try {
        const body = (await response.json()) as { detail?: { existing?: string; suggested_name?: string; message?: string } };
        detail = body?.detail ?? null;
      } catch {
        /* ignore */
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

    await throwIfNotOk(response, "上传失败");
    return (await response.json()) as {
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
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/files`
    );
  }

  static getFileUrl(
    projectName: string,
    path: string,
    cacheBust?: number | string | null
  ): string {
    const localUrl = projectFileToLocalUrl(projectName, path, cacheBust);
    if (localUrl) return localUrl;
    void ensureLocalAssetRoots();

    const base = `${API_BASE}/files/${encodeURIComponent(projectName)}/${path}`;
    if (cacheBust == null || cacheBust === "") {
      return base;
    }

    return `${base}?v=${encodeURIComponent(String(cacheBust))}`;
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
    const response = await fetch(
      `${API_BASE}/projects/${encodeURIComponent(projectName)}/source/${encodeURIComponent(filename)}`,
      withPluginHeaders()
    );
    await throwIfNotOk(response, "获取文件内容失败");
    return response.text();
  }

  /**
   * 保存 source 文件（新建或更新）
   */
  static async saveSourceFile(
    projectName: string,
    filename: string,
    content: string
  ): Promise<SuccessResponse> {
    const response = await fetch(
      `${API_BASE}/projects/${encodeURIComponent(projectName)}/source/${encodeURIComponent(filename)}`,
      withPluginHeaders({
        method: "PUT",
        headers: { "Content-Type": "text/plain" },
        body: content,
      })
    );
    await throwIfNotOk(response, "保存文件失败");
    return response.json() as Promise<SuccessResponse>;
  }

  /**
   * 删除 source 文件
   */
  static async deleteSourceFile(
    projectName: string,
    filename: string
  ): Promise<SuccessResponse> {
    const response = await fetch(
      `${API_BASE}/projects/${encodeURIComponent(projectName)}/source/${encodeURIComponent(filename)}`,
      withPluginHeaders({
        method: "DELETE",
      })
    );
    await throwIfNotOk(response, "删除文件失败");
    return response.json() as Promise<SuccessResponse>;
  }

  // ==================== 草稿文件管理 ====================

  /**
   * 获取项目的所有草稿
   */
  static async listDrafts(
    projectName: string
  ): Promise<{ drafts: DraftInfo[] }> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/drafts`
    );
  }

  /**
   * 获取草稿内容
   */
  static async getDraftContent(
    projectName: string,
    episode: number,
    stepNum: number
  ): Promise<string> {
    const response = await fetch(
      `${API_BASE}/projects/${encodeURIComponent(projectName)}/drafts/${episode}/step${stepNum}`,
      withPluginHeaders()
    );
    await throwIfNotOk(response, "获取草稿内容失败");
    return response.text();
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
    const response = await fetch(
      `${API_BASE}/projects/${encodeURIComponent(projectName)}/drafts/${episode}/step${stepNum}`,
      withPluginHeaders({
        method: "PUT",
        headers: { "Content-Type": "text/plain" },
        body: content,
      })
    );
    await throwIfNotOk(response, "保存草稿失败");
    return response.json() as Promise<SuccessResponse>;
  }

  /**
   * 删除草稿
   */
  static async deleteDraft(
    projectName: string,
    episode: number,
    stepNum: number
  ): Promise<SuccessResponse> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/drafts/${episode}/step${stepNum}`,
      { method: "DELETE" }
    );
  }

  // ==================== 项目概述管理 ====================

  /**
   * 使用 AI 生成项目概述
   */
  static async generateOverview(
    projectName: string
  ): Promise<{ success: boolean; overview: ProjectOverview }> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/generate-overview`,
      {
        method: "POST",
      }
    );
  }

  /**
   * 更新项目概述（手动编辑）
   */
  static async updateOverview(
    projectName: string,
    updates: Partial<ProjectOverview>
  ): Promise<SuccessResponse> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/overview`,
      {
        method: "PATCH",
        body: JSON.stringify(updates),
      }
    );
  }

  // ==================== 生成 API ====================

  static async getExternalGenerationPackage(
    projectName: string,
    segmentId: string,
    scriptFile: string,
  ): Promise<ExternalGenerationPackage> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/generate/external-package/${encodeURIComponent(segmentId)}?script_file=${encodeURIComponent(scriptFile)}`,
    );
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
    scriptFile: string
  ): Promise<{ success: boolean; task_id: string; message: string }> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/generate/storyboard/${encodeURIComponent(segmentId)}`,
      {
        method: "POST",
        body: JSON.stringify({ prompt, script_file: scriptFile }),
      }
    );
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
    durationSeconds: number = 4
  ): Promise<{ success: boolean; task_id: string; message: string }> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/generate/video/${encodeURIComponent(segmentId)}`,
      {
        method: "POST",
        body: JSON.stringify({
          prompt,
          script_file: scriptFile,
          duration_seconds: durationSeconds,
        }),
      }
    );
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
    prompt: string
  ): Promise<{
    success: boolean;
    task_id: string;
    message: string;
  }> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/generate/character/${encodeURIComponent(charName)}`,
      {
        method: "POST",
        body: JSON.stringify({ prompt }),
      }
    );
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
    prompt: string
  ): Promise<{
    success: boolean;
    task_id: string;
    message: string;
  }> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/generate/scene/${encodeURIComponent(sceneName)}`,
      {
        method: "POST",
        body: JSON.stringify({ prompt }),
      }
    );
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
    prompt: string
  ): Promise<{
    success: boolean;
    task_id: string;
    message: string;
  }> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/generate/prop/${encodeURIComponent(propName)}`,
      {
        method: "POST",
        body: JSON.stringify({ prompt }),
      }
    );
  }

  // ==================== 任务队列 API ====================

  static async getTask(taskId: string): Promise<TaskItem> {
    return this.request(`/tasks/${encodeURIComponent(taskId)}`);
  }

  static async listTasks(
    filters: TaskListFilters = {}
  ): Promise<{ items: TaskItem[]; total: number; page: number; page_size: number }> {
    const params = new URLSearchParams();
    if (filters.projectName) params.append("project_name", filters.projectName);
    if (filters.status) params.append("status", filters.status);
    if (filters.taskType) params.append("task_type", filters.taskType);
    if (filters.source) params.append("source", filters.source);
    if (filters.page) params.append("page", String(filters.page));
    if (filters.pageSize) params.append("page_size", String(filters.pageSize));
    const query = params.toString();
    return this.request(`/tasks${query ? "?" + query : ""}`);
  }

  static async listProjectTasks(
    projectName: string,
    filters: Omit<TaskListFilters, "projectName"> = {}
  ): Promise<{ items: TaskItem[]; total: number; page: number; page_size: number }> {
    const params = new URLSearchParams();
    if (filters.status) params.append("status", filters.status);
    if (filters.taskType) params.append("task_type", filters.taskType);
    if (filters.source) params.append("source", filters.source);
    if (filters.page) params.append("page", String(filters.page));
    if (filters.pageSize) params.append("page_size", String(filters.pageSize));
    const query = params.toString();
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/tasks${query ? "?" + query : ""}`
    );
  }

  static async getTaskStats(
    projectName: string | null = null
  ): Promise<{ stats: TaskStats }> {
    const params = new URLSearchParams();
    if (projectName) params.append("project_name", projectName);
    const query = params.toString();
    return this.request(`/tasks/stats${query ? "?" + query : ""}`);
  }

  // ==================== 任务取消 API ====================

  static async cancelPreview(
    taskId: string
  ): Promise<{
    task: { task_id: string; task_type: string; resource_id: string; status: string };
    cascaded: { task_id: string; task_type: string; resource_id: string }[];
  }> {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/cancel-preview`);
  }

  static async cancelTask(
    taskId: string
  ): Promise<{
    cancelled: TaskItem[];
    cancelling: string[];
    skipped_terminal: TaskItem[];
  }> {
    return this.request(`/tasks/${encodeURIComponent(taskId)}/cancel`, {
      method: "POST",
    });
  }

  static async cancelAllPreview(
    projectName: string
  ): Promise<{ queued_count: number }> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/tasks/cancel-all-preview`
    );
  }

  static async cancelAllQueued(
    projectName: string
  ): Promise<{ cancelled_count: number; skipped_running_count: number }> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/tasks/cancel-all`,
      { method: "POST" }
    );
  }

  static openTaskStream(options: TaskStreamOptions = {}): EventSource {
    const params = new URLSearchParams();
    if (options.projectName)
      params.append("project_name", options.projectName);
    const parsedLastEventId = Number(options.lastEventId);
    if (Number.isFinite(parsedLastEventId) && parsedLastEventId > 0) {
      params.append("last_event_id", String(parsedLastEventId));
    }

    const query = params.toString();
    const url = `${API_BASE}/tasks/stream${query ? "?" + query : ""}`;
    const source = new EventSource(url);

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

  static openProjectEventStream(options: ProjectEventStreamOptions): EventSource {
    const url = `${API_BASE}/projects/${encodeURIComponent(options.projectName)}/events/stream`;
    const source = new EventSource(url);

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
    const result = await this.request<{
      resource_type: VersionResourceType;
      resource_id: string;
      current_version: number;
      versions: VersionInfo[];
    }>(
      `/projects/${encodeURIComponent(projectName)}/versions/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}`
    );
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
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/versions/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}/restore/${version}`,
      {
        method: "POST",
      }
    );
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
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/versions/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}/usage`,
    );
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
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/versions/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}`,
      { method: "DELETE" },
    );
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
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/versions/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}/${version}`,
      { method: "DELETE" },
    );
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
    const url = `${API_BASE}/projects/${encodeURIComponent(projectName)}/versions/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}/upload`;
    const response = await requestWithLocalFiles(
      url,
      {
        script_file: options.scriptFile,
      },
      [{ fieldName: "file", file }],
    );
    await throwIfNotOk(response, "上传外部生成结果失败");
    return (await response.json()) as SuccessResponse & {
      resource_type: "storyboards" | "videos";
      resource_id: string;
      version: number;
      created_at?: string | null;
      file_path?: string;
      asset_fingerprints?: Record<string, number>;
    };
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
    const url = `${API_BASE}/projects/${encodeURIComponent(projectName)}/style-image`;
    const styleDescription = options.styleDescription?.trim();
    const response = await requestWithLocalFiles(
      url,
      styleDescription ? { style_description: styleDescription } : {},
      [{ fieldName: "file", file }],
    );

    await throwIfNotOk(response, "上传失败");

    await ensureLocalAssetRoots();
    const result = await response.json() as {
      success: boolean;
      style_image: string;
      style_description: string;
      url: string;
      style_analysis_error?: string;
    };
    return {
      ...result,
      url: resolveLocalMediaUrl(result.url) ?? result.url,
    };
  }

  static async analyzeStyleImage(
    file: UploadFileInput,
  ): Promise<{ success: boolean; style_description: string }> {
    const url = `${API_BASE}/style-image/analyze`;
    const response = await requestWithLocalFiles(
      url,
      {},
      [{ fieldName: "file", file }],
    );
    await throwIfNotOk(response, "风格分析失败");
    return response.json() as Promise<{ success: boolean; style_description: string }>;
  }

  // ==================== 助手会话 API ====================

  /** Build the project-scoped assistant base path. */
  private static assistantBase(projectName: string): string {
    return `/projects/${encodeURIComponent(projectName)}/assistant`;
  }

  static async listAssistantSessions(
    projectName: string,
    status: string | null = null
  ): Promise<{ sessions: SessionMeta[] }> {
    const params = new URLSearchParams();
    if (status) params.append("status", status);
    const query = params.toString();
    return this.request(
      `${this.assistantBase(projectName)}/sessions${query ? "?" + query : ""}`
    );
  }

  static async getAssistantSession(
    projectName: string,
    sessionId: string
  ): Promise<{ session: SessionMeta }> {
    return this.request(
      `${this.assistantBase(projectName)}/sessions/${encodeURIComponent(sessionId)}`
    );
  }

  static async getAssistantSnapshot(
    projectName: string,
    sessionId: string
  ): Promise<AssistantSnapshot> {
    return this.request(
      `${this.assistantBase(projectName)}/sessions/${encodeURIComponent(sessionId)}/snapshot`
    );
  }

  static async sendAssistantMessage(
    projectName: string,
    content: string,
    sessionId?: string | null,
    images?: Array<{ data: string; media_type: string }>
  ): Promise<{ session_id: string; status: string }> {
    return this.request(`${this.assistantBase(projectName)}/sessions/send`, {
      method: "POST",
      body: JSON.stringify({
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
    return this.request(
      `${this.assistantBase(projectName)}/sessions/${encodeURIComponent(sessionId)}/interrupt`,
      {
        method: "POST",
      }
    );
  }

  static async answerAssistantQuestion(
    projectName: string,
    sessionId: string,
    questionId: string,
    answers: Record<string, string>
  ): Promise<SuccessResponse> {
    return this.request(
      `${this.assistantBase(projectName)}/sessions/${encodeURIComponent(sessionId)}/questions/${encodeURIComponent(questionId)}/answer`,
      {
        method: "POST",
        body: JSON.stringify({ answers }),
      }
    );
  }

  static getAssistantStreamUrl(projectName: string, sessionId: string): string {
    return `${API_BASE}${this.assistantBase(projectName)}/sessions/${encodeURIComponent(sessionId)}/stream`;
  }

  static async listAssistantSkills(
    projectName: string
  ): Promise<{ skills: SkillInfo[] }> {
    return this.request(
      `${this.assistantBase(projectName)}/skills`
    );
  }

  static async deleteAssistantSession(
    projectName: string,
    sessionId: string
  ): Promise<SuccessResponse> {
    return this.request(
      `${this.assistantBase(projectName)}/sessions/${encodeURIComponent(sessionId)}`,
      {
        method: "DELETE",
      }
    );
  }

  // ==================== 费用统计 API ====================

  /**
   * 获取统计摘要
   * @param filters - 筛选条件
   */
  static async getUsageStats(
    filters: UsageStatsFilters = {}
  ): Promise<Record<string, unknown>> {
    const params = new URLSearchParams();
    if (filters.projectName)
      params.append("project_name", filters.projectName);
    if (filters.startDate) params.append("start_date", filters.startDate);
    if (filters.endDate) params.append("end_date", filters.endDate);
    const query = params.toString();
    return this.request(`/usage/stats${query ? "?" + query : ""}`);
  }

  /**
   * 获取调用记录列表
   * @param filters - 筛选条件
   */
  static async getUsageCalls(
    filters: UsageCallsFilters = {}
  ): Promise<Record<string, unknown>> {
    const params = new URLSearchParams();
    if (filters.projectName)
      params.append("project_name", filters.projectName);
    if (filters.callType) params.append("call_type", filters.callType);
    if (filters.status) params.append("status", filters.status);
    if (filters.startDate) params.append("start_date", filters.startDate);
    if (filters.endDate) params.append("end_date", filters.endDate);
    if (filters.page) params.append("page", String(filters.page));
    if (filters.pageSize) params.append("page_size", String(filters.pageSize));
    const query = params.toString();
    return this.request(`/usage/calls${query ? "?" + query : ""}`);
  }

  /**
   * 获取有调用记录的项目列表
   */
  static async getUsageProjects(): Promise<{ projects: string[] }> {
    return this.request("/usage/projects");
  }

  // ==================== Provider 管理 API ====================

  /** 获取所有 provider 列表及状态。 */
  static async getProviders(): Promise<{ providers: ProviderInfo[] }> {
    return this.request("/providers");
  }

  /** 获取指定 provider 的配置详情（含字段列表）。 */
  static async getProviderConfig(id: string): Promise<ProviderConfigDetail> {
    return this.request(`/providers/${encodeURIComponent(id)}/config`);
  }

  /** 更新指定 provider 的配置字段。 */
  static async patchProviderConfig(
    id: string,
    patch: Record<string, string | null>
  ): Promise<void> {
    return this.request(`/providers/${encodeURIComponent(id)}/config`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
  }

  /** 测试指定 provider 的连接。 */
  static async testProviderConnection(id: string, credentialId?: number): Promise<ProviderTestResult> {
    const params = credentialId != null ? `?credential_id=${credentialId}` : "";
    return this.request(`/providers/${encodeURIComponent(id)}/test${params}`, {
      method: "POST",
    });
  }

  // ==================== Provider 凭证管理 API ====================

  static async listCredentials(providerId: string): Promise<{ credentials: ProviderCredential[] }> {
    return this.request(`/providers/${encodeURIComponent(providerId)}/credentials`);
  }

  static async createCredential(
    providerId: string,
    data: { name: string; api_key?: string; base_url?: string },
  ): Promise<ProviderCredential> {
    return this.request(`/providers/${encodeURIComponent(providerId)}/credentials`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  static async updateCredential(
    providerId: string,
    credId: number,
    data: { name?: string; api_key?: string; base_url?: string },
  ): Promise<void> {
    return this.request(
      `/providers/${encodeURIComponent(providerId)}/credentials/${credId}`,
      { method: "PATCH", body: JSON.stringify(data) },
    );
  }

  static async deleteCredential(providerId: string, credId: number): Promise<void> {
    return this.request(
      `/providers/${encodeURIComponent(providerId)}/credentials/${credId}`,
      { method: "DELETE" },
    );
  }

  static async activateCredential(providerId: string, credId: number): Promise<void> {
    return this.request(
      `/providers/${encodeURIComponent(providerId)}/credentials/${credId}/activate`,
      { method: "POST" },
    );
  }

  static async uploadVertexCredential(name: string, file: UploadFileInput): Promise<ProviderCredential> {
    const url = `${API_BASE}/providers/gemini-vertex/credentials/upload?name=${encodeURIComponent(name)}`;
    const response = await requestWithLocalFiles(
      url,
      {},
      [{ fieldName: "file", file }],
    );
    await throwIfNotOk(response, "上传凭证失败");
    return response.json() as Promise<ProviderCredential>;
  }

  // ==================== Agent 配置 / 凭证 API ====================

  static async listAgentPresetProviders(): Promise<PresetProvidersResponse> {
    return this.request("/agent/preset-providers");
  }

  static async listAgentCredentials(): Promise<{ credentials: AgentCredential[] }> {
    return this.request("/agent/credentials");
  }

  static async createAgentCredential(
    data: CreateAgentCredentialRequest,
  ): Promise<AgentCredential> {
    return this.request("/agent/credentials", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  static async updateAgentCredential(
    id: number,
    data: UpdateAgentCredentialRequest,
  ): Promise<AgentCredential> {
    return this.request(`/agent/credentials/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  static async deleteAgentCredential(id: number): Promise<void> {
    return this.request(`/agent/credentials/${id}`, { method: "DELETE" });
  }

  static async activateAgentCredential(id: number): Promise<{ active_id: number }> {
    return this.request(`/agent/credentials/${id}/activate`, { method: "POST" });
  }

  static async testAgentCredential(id: number): Promise<TestConnectionResponse> {
    return this.request(`/agent/credentials/${id}/test`, { method: "POST" });
  }

  static async testAgentConnectionDraft(
    data: TestConnectionRequest,
  ): Promise<TestConnectionResponse> {
    return this.request("/agent/test-connection", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  // ==================== 自定义供应商 API ====================

  static async listCustomProviders(): Promise<{ providers: CustomProviderInfo[] }> {
    return this.request("/custom-providers");
  }

  static async listEndpointCatalog(): Promise<{ endpoints: EndpointDescriptor[] }> {
    return this.request("/custom-providers/endpoints");
  }

  static async createCustomProvider(data: CustomProviderCreateRequest): Promise<CustomProviderInfo> {
    return this.request("/custom-providers", { method: "POST", body: JSON.stringify(data) });
  }

  static async getCustomProvider(id: number): Promise<CustomProviderInfo> {
    return this.request(`/custom-providers/${id}`);
  }

  static async updateCustomProvider(id: number, data: Partial<Omit<CustomProviderCreateRequest, "discovery_format" | "models">>): Promise<void> {
    return this.request(`/custom-providers/${id}`, { method: "PATCH", body: JSON.stringify(data) });
  }

  static async fullUpdateCustomProvider(id: number, data: { display_name: string; base_url: string; api_key?: string; models: CustomProviderModelInput[] }): Promise<CustomProviderInfo> {
    return this.request(`/custom-providers/${id}`, { method: "PUT", body: JSON.stringify(data) });
  }

  static async deleteCustomProvider(id: number): Promise<void> {
    return this.request(`/custom-providers/${id}`, { method: "DELETE" });
  }

  static async replaceCustomProviderModels(id: number, models: CustomProviderModelInput[]): Promise<CustomProviderModelInfo[]> {
    return this.request(`/custom-providers/${id}/models`, { method: "PUT", body: JSON.stringify({ models }) });
  }

  static async discoverModels(data: { discovery_format: string; base_url: string; api_key: string }): Promise<{ models: DiscoveredModel[] }> {
    return this.request("/custom-providers/discover", { method: "POST", body: JSON.stringify(data) });
  }

  static async discoverModelsForProvider(id: number): Promise<{ models: DiscoveredModel[] }> {
    return this.request(`/custom-providers/${id}/discover`, { method: "POST" });
  }

  static async testCustomConnection(data: { discovery_format: string; base_url: string; api_key: string }): Promise<{ success: boolean; message: string }> {
    return this.request("/custom-providers/test", { method: "POST", body: JSON.stringify(data) });
  }

  static async testCustomConnectionById(id: number): Promise<{ success: boolean; message: string }> {
    return this.request(`/custom-providers/${id}/test`, { method: "POST" });
  }

  static async getCustomProviderCredentials(id: number): Promise<CustomProviderCredentials> {
    return this.request(`/custom-providers/${id}/credentials`);
  }

  static async discoverAnthropicModels(
    data: AnthropicDiscoverRequest,
    options: { signal?: AbortSignal } = {},
  ): Promise<AnthropicDiscoverResponse> {
    return this.request("/custom-providers/discover-anthropic", {
      method: "POST",
      body: JSON.stringify(data),
      signal: options.signal,
    });
  }

  // ==================== 用量统计（按 provider 分组）API ====================

  /**
   * 获取按 provider 分组的用量统计。
   * @param params - 可选筛选：provider、start、end（ISO 日期字符串）
   */
  static async getUsageStatsGrouped(
    params: { provider?: string; start?: string; end?: string } = {}
  ): Promise<UsageStatsResponse> {
    const searchParams = new URLSearchParams();
    searchParams.append("group_by", "provider");
    if (params.provider) searchParams.append("provider", params.provider);
    if (params.start) searchParams.append("start_date", params.start);
    if (params.end) searchParams.append("end_date", params.end);
    return this.request(`/usage/stats?${searchParams.toString()}`);
  }

  // ==================== 费用估算 API ====================

  /**
   * 获取项目费用估算。
   * @param projectName - 项目名称
   */
  static async getCostEstimate(projectName: string): Promise<CostEstimateResponse> {
    return this.request(`/projects/${encodeURIComponent(projectName)}/cost-estimate`);
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
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/generate/grid/${episode}`,
      { method: "POST", body: JSON.stringify({ script_file: scriptFile, scene_ids: sceneIds }) }
    );
  }

  /**
   * 列出项目所有 Grid 记录
   * @param projectName - 项目名称
   */
  static async listGrids(projectName: string): Promise<GridGeneration[]> {
    return this.request(`/projects/${encodeURIComponent(projectName)}/grids`);
  }

  /**
   * 获取单个 Grid 详情
   * @param projectName - 项目名称
   * @param gridId - Grid ID
   */
  static async getGrid(projectName: string, gridId: string): Promise<GridGeneration> {
    return this.request(`/projects/${encodeURIComponent(projectName)}/grids/${encodeURIComponent(gridId)}`);
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
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/grids/${encodeURIComponent(gridId)}/regenerate`,
      { method: "POST" }
    );
  }

  // ==================== Global Asset Library ====================

  static async listAssets(
    params: { type?: AssetType; q?: string; limit?: number; offset?: number } = {},
    options: RequestInit = {},
  ) {
    await ensureLocalAssetRoots();
    const usp = new URLSearchParams();
    if (params.type) usp.set("type", params.type);
    if (params.q) usp.set("q", params.q);
    if (params.limit) usp.set("limit", String(params.limit));
    if (params.offset) usp.set("offset", String(params.offset));
    return this.request<{ items: Asset[]; total?: number }>(`/assets?${usp.toString()}`, options);
  }

  static async getAsset(id: string) {
    await ensureLocalAssetRoots();
    return this.request<{ asset: Asset }>(`/assets/${encodeURIComponent(id)}`);
  }

  static async createAsset(payload: AssetCreatePayload & { image?: UploadFileInput }) {
    const fields = {
      type: payload.type,
      name: payload.name,
      description: payload.description ?? "",
      voice_style: payload.voice_style ?? "",
    };
    const url = `${API_BASE}/assets`;
    const response = await requestWithLocalFiles(
      url,
      fields,
      payload.image
        ? [{ fieldName: "image", file: payload.image }]
        : [],
    );
    if (!response.ok) {
      const error = (await response.json().catch(() => ({ detail: response.statusText }))) as {
        detail?: string;
      };
      throw new Error(typeof error.detail === "string" ? error.detail : "请求失败");
    }
    return response.json() as Promise<{ asset: Asset }>;
  }

  static async updateAsset(id: string, patch: AssetUpdatePayload) {
    return this.request<{ asset: Asset }>(`/assets/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
  }

  static async replaceAssetImage(id: string, image: UploadFileInput) {
    const url = `${API_BASE}/assets/${encodeURIComponent(id)}/image`;
    const response = await requestWithLocalFiles(
      url,
      {},
      [{ fieldName: "image", file: image }],
    );
    if (!response.ok) {
      const error = (await response.json().catch(() => ({ detail: response.statusText }))) as {
        detail?: string;
      };
      throw new Error(typeof error.detail === "string" ? error.detail : "请求失败");
    }
    return response.json() as Promise<{ asset: Asset }>;
  }

  static async deleteAsset(id: string): Promise<void> {
    return this.request(`/assets/${encodeURIComponent(id)}`, { method: "DELETE" });
  }

  static async addAssetFromProject(payload: {
    project_name: string;
    resource_type: AssetType;
    resource_id: string;
    override_name?: string;
    overwrite?: boolean;
  }) {
    return this.request<{ asset: Asset }>(`/assets/from-project`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  static async applyAssetsToProject(payload: {
    asset_ids: string[];
    target_project: string;
    conflict_policy: "skip" | "overwrite" | "rename";
  }) {
    return this.request<{
      succeeded: Array<{ id: string; name: string }>;
      skipped: Array<{ id: string; name: string }>;
      failed: Array<{ id: string; reason: string }>;
    }>(`/assets/apply-to-project`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  static getGlobalAssetUrl(path: string | null, fp?: string | null): string | null {
    if (!path) return null;
    const localUrl = globalAssetToLocalUrl(path, fp);
    if (localUrl) return localUrl;
    void ensureLocalAssetRoots();

    const parts = path.split("/");
    if (parts.length < 3 || parts[0] !== "_global_assets") return null;
    const type = parts[1];
    const filename = parts.slice(2).join("/");
    const qs = fp ? `?fp=${encodeURIComponent(fp)}` : "";
    return `${API_BASE}/global-assets/${type}/${filename}${qs}`;
  }

  // ==================== Reference-to-Video API ====================

  /** List reference-video units for an episode. */
  static async listReferenceVideoUnits(
    projectName: string,
    episode: number,
  ): Promise<{ units: ReferenceVideoUnit[] }> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/reference-videos/episodes/${episode}/units`,
    );
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
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/reference-videos/episodes/${episode}/units`,
      { method: "POST", body: JSON.stringify(payload) },
    );
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
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/reference-videos/episodes/${episode}/units/${encodeURIComponent(unitId)}`,
      { method: "PATCH", body: JSON.stringify(patch) },
    );
  }

  /** Delete a unit. Returns void on 204. */
  static async deleteReferenceVideoUnit(
    projectName: string,
    episode: number,
    unitId: string,
  ): Promise<void> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/reference-videos/episodes/${episode}/units/${encodeURIComponent(unitId)}`,
      { method: "DELETE" },
    );
  }

  /** Reorder units by providing the full ordered unit_id list. */
  static async reorderReferenceVideoUnits(
    projectName: string,
    episode: number,
    unitIds: string[],
  ): Promise<{ units: ReferenceVideoUnit[] }> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/reference-videos/episodes/${episode}/units/reorder`,
      { method: "POST", body: JSON.stringify({ unit_ids: unitIds }) },
    );
  }

  /** Enqueue generation; returns 202 with task_id. */
  static async generateReferenceVideoUnit(
    projectName: string,
    episode: number,
    unitId: string,
  ): Promise<{ task_id: string; deduped: boolean }> {
    return this.request(
      `/projects/${encodeURIComponent(projectName)}/reference-videos/episodes/${episode}/units/${encodeURIComponent(unitId)}/generate`,
      { method: "POST" },
    );
  }
}

export { API };

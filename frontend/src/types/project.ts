/**
 * Project-related type definitions.
 *
 * Maps to backend models in:
 * - lib/project_manager.py (ProjectOverview, project.json structure)
 * - lib/status_calculator.py (ProjectStatus, EpisodeMeta computed fields)
 * - server/routers/projects.py (ProjectSummary list response)
 */

import type { ShotTier } from "./script";

export type VideoContinuityPolicy = "auto" | "start_only" | "end_frame" | "reference_assisted";

export interface ProjectOverview {
  synopsis: string;
  genre: string;
  theme: string;
  world_setting: string;
  language?: "zh" | "en" | "vi";
  generated_at?: string;
}

export interface Character {
  description: string;
  character_sheet?: string;
  voice_style?: string;
  reference_image?: string;
}

export interface Scene {
  description: string;
  scene_sheet?: string;
}

export interface Prop {
  description: string;
  prop_sheet?: string;
}

export interface AspectRatio {
  characters?: string;
  scenes?: string;
  props?: string;
  storyboard?: string;
  video?: string;
}

export interface ProgressCategory {
  total: number;
  completed: number;
}

export interface EpisodesSummary {
  total: number;
  scripted: number;
  in_production: number;
  completed: number;
}

export const PHASE_ORDER = [
  "setup",
  "worldbuilding",
  "scripting",
  "production",
  "completed",
] as const;

export type Phase = (typeof PHASE_ORDER)[number];

/** Injected by StatusCalculator.calculate_project_status at read time */
export interface ProjectStatus {
  current_phase: Phase;
  phase_progress: number;
  characters: ProgressCategory;
  scenes: ProgressCategory;
  props: ProgressCategory;
  episodes_summary: EpisodesSummary;
}

export interface EpisodeMeta {
  episode: number;
  title: string;
  script_file: string;
  /** Injected by StatusCalculator at read time */
  scenes_count?: number;
  /** Injected by StatusCalculator at read time */
  script_status?: "none" | "segmented" | "generated";
  /** Injected by StatusCalculator at read time */
  status?: "draft" | "scripted" | "in_production" | "completed" | "missing";
  /** Injected by StatusCalculator at read time */
  duration_seconds?: number;
  /** Injected by StatusCalculator at read time */
  storyboards?: ProgressCategory;
  /** Injected by StatusCalculator at read time */
  videos?: ProgressCategory;
  /** Injected by StatusCalculator at read time (reference_video mode only) */
  units_count?: number;
}

export interface ModelSettingEntry {
  resolution?: string | null;
}

export type GenerationQuality = "draft" | "final" | "custom";

export interface ImageGenerationProfile {
  image_provider_t2i?: string | null;
  image_provider_i2i?: string | null;
  resolution?: string | null;
}

export interface VideoGenerationProfile {
  video_backend?: string | null;
  resolution?: string | null;
  duration_seconds?: number | null;
  generate_audio?: boolean | null;
  service_tier?: string | null;
}

export interface GenerationProfiles {
  asset?: ImageGenerationProfile;
  storyboard_draft?: ImageGenerationProfile;
  storyboard_final?: ImageGenerationProfile;
  grid?: ImageGenerationProfile;
  video_draft?: VideoGenerationProfile;
  video_final?: VideoGenerationProfile;
  reference_video_draft?: VideoGenerationProfile;
  reference_video_final?: VideoGenerationProfile;
}

export interface ShotTierProfile {
  label?: string | null;
  retry_budget?: number | null;
  reference_image_policy?: string | null;
  video_continuity_policy?: VideoContinuityPolicy | null;
  prefer_final_storyboard_source?: boolean | null;
  profiles?: Partial<Record<keyof GenerationProfiles, ImageGenerationProfile | VideoGenerationProfile>>;
}

export interface ProjectData {
  title: string;
  content_mode: "narration" | "drama";
  style: string;
  style_template_id?: string | null;
  style_image?: string;
  style_description?: string;
  overview?: ProjectOverview;
  source_language?: "zh" | "en" | "vi";
  episode_target_units?: number | null;
  aspect_ratio?: string | AspectRatio;  // 新项目为 string，旧项目可能为 dict
  default_duration?: number | null;     // 新增
  schema_version?: number;
  episodes: EpisodeMeta[];
  characters: Record<string, Character>;
  scenes?: Record<string, Scene>;
  props?: Record<string, Prop>;
  /** Injected by StatusCalculator.enrich_project at read time */
  status?: ProjectStatus;
  video_backend?: string | null;
  image_backend?: string | null;
  image_provider_t2i?: string | null;
  image_provider_i2i?: string | null;
  /** Canonical values: storyboard | grid | reference_video. "single" is legacy-only. */
  generation_mode?: "storyboard" | "grid" | "reference_video" | "single";
  video_generate_audio?: boolean | null;
  text_backend_script?: string | null;
  text_backend_overview?: string | null;
  text_backend_style?: string | null;
  model_settings?: Record<string, ModelSettingEntry>;
  generation_profiles?: GenerationProfiles;
  shot_tier_profiles?: Partial<Record<ShotTier, ShotTierProfile>>;
  video_continuity_policy?: VideoContinuityPolicy | null;
  /** Legacy field: keyed by model_id only (before composite key refactor). Read-only at UI layer. */
  video_model_settings?: Record<string, { resolution?: string | null }>;
  metadata?: {
    created_at: string;
    updated_at: string;
  };
}

/**
 * Summary shape returned by GET /api/v1/projects (list endpoint).
 *
 * Note: `status` may be an empty object `{}` when the project
 * has no project.json or encounters an error during loading.
 */
export interface ProjectSummary {
  name: string;
  title: string;
  style: string;
  style_template_id?: string | null;
  style_image?: string | null;
  thumbnail: string | null;
  status: ProjectStatus | Record<string, never>;
}

export type ImportConflictPolicy = "prompt" | "rename" | "overwrite";

export interface ArchiveDiagnostic {
  code: string;
  message: string;
  location?: string;
}

export interface ImportSuccessDiagnostics {
  auto_fixed: ArchiveDiagnostic[];
  warnings: ArchiveDiagnostic[];
}

export interface ImportFailureDiagnostics {
  blocking: ArchiveDiagnostic[];
  auto_fixable: ArchiveDiagnostic[];
  warnings: ArchiveDiagnostic[];
}

export interface ExportDiagnostics {
  blocking: ArchiveDiagnostic[];
  auto_fixed: ArchiveDiagnostic[];
  warnings: ArchiveDiagnostic[];
}

export interface ImportProjectResponse {
  success: boolean;
  import_type?: "project";
  project_name: string;
  project: ProjectData;
  warnings: string[];
  conflict_resolution: "none" | "renamed" | "overwritten";
  diagnostics: ImportSuccessDiagnostics;
}

export interface ImportAssetArchiveResponse {
  success: boolean;
  import_type: "asset_archive";
  summary: {
    assets?: number;
    asset_files?: number;
    style_favorites_files?: number;
    global_config?: boolean;
    global_config_rows?: Record<string, number>;
    global_config_files?: number;
  };
  warnings: string[];
  diagnostics: ImportSuccessDiagnostics;
}

export type ImportArchiveResponse = ImportProjectResponse | ImportAssetArchiveResponse;

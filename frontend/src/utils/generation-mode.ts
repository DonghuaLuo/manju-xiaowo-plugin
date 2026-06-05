/**
 * Generation mode helpers — mirrors lib/project_manager.py:effective_mode().
 *
 * Canonical values: "storyboard" | "grid" | "reference_video".
 * Legacy value "single" (old projects) is normalized to "storyboard".
 */

export type GenerationMode = "storyboard" | "grid" | "reference_video";

export const GENERATION_MODES = ["storyboard", "reference_video", "grid"] as const satisfies readonly GenerationMode[];

type Translate = (key: string, options?: Record<string, unknown>) => string;

const CANONICAL: readonly GenerationMode[] = GENERATION_MODES;

/** All recognized input strings (canonical + legacy alias). */
const RECOGNIZED = new Set<string>(["single", ...CANONICAL]);

function isCanonical(v: string): v is GenerationMode {
  return (CANONICAL as readonly string[]).includes(v);
}

export function normalizeMode(value: unknown): GenerationMode {
  if (value === "single") return "storyboard";
  if (typeof value === "string" && isCanonical(value)) return value;
  return "storyboard";
}

export function effectiveMode(
  project: { generation_mode?: string | null } | null | undefined,
  episode?: unknown,
): GenerationMode {
  // Generation mode is fixed at project creation. The episode argument stays
  // in the signature so existing route calls do not need extra adapter code.
  void episode;
  const proj = project?.generation_mode;
  if (typeof proj === "string" && RECOGNIZED.has(proj)) return normalizeMode(proj);
  return "storyboard";
}

export function generationModeLabel(mode: GenerationMode, t: Translate): string {
  if (mode === "storyboard") {
    return t("mode_storyboard", { defaultValue: "图生视频" });
  }
  if (mode === "grid") {
    return t("mode_grid", { defaultValue: "宫格分镜" });
  }
  return t("mode_reference_video", { defaultValue: "参考视频" });
}

export function generationModeDescription(mode: GenerationMode, t: Translate): string {
  if (mode === "storyboard") {
    return t("mode_storyboard_desc", {
      defaultValue: "推荐正式成片：先生成分镜图，再逐镜头图生视频。",
    });
  }
  if (mode === "grid") {
    return t("mode_grid_desc", {
      defaultValue: "快速批量生成宫格分镜，适合先看整体画风和节奏。",
    });
  }
  return t("mode_reference_video_desc", {
    defaultValue: "跳过分镜，用角色/场景/道具参考图直接生成片段。",
  });
}

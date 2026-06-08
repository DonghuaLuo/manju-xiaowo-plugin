import { useCallback, useEffect, useMemo, useState } from "react";
import { Sparkles, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { EpisodeHeader } from "../timeline/EpisodeHeader";
import { PreprocessingView } from "../timeline/PreprocessingView";
import { ShotSplitView } from "../timeline/ShotSplitView";
import { GridPreviewView } from "./GridPreviewView";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useAppStore } from "@/stores/app-store";
import { useCostStore } from "@/stores/cost-store";
import { useTasksStore } from "@/stores/tasks-store";
import { useScrollTarget } from "@/hooks/useScrollTarget";
import type {
  EpisodeScript,
  NarrationEpisodeScript,
  DramaEpisodeScript,
  NarrationSegment,
  DramaScene,
  ProjectData,
  GenerationQuality,
  StoryboardFinalGenerationMode,
  VideoContinuityPolicy,
} from "@/types";
import type { VideoContinuitySupport } from "@/utils/provider-models";

type Segment = NarrationSegment | DramaScene;
type GridTab = "preprocessing" | "grid_preview" | "units";

function getSegmentId(seg: Segment, mode: "narration" | "drama"): string {
  return mode === "narration"
    ? (seg as NarrationSegment).segment_id
    : (seg as DramaScene).scene_id;
}

interface GridImageToVideoCanvasProps {
  projectName: string;
  episode: number;
  episodeTitle?: string;
  hasDraft?: boolean;
  episodeScript: EpisodeScript | null;
  scriptFile?: string;
  projectData: ProjectData | null;
  durationOptions?: number[];
  videoContinuitySupport?: VideoContinuitySupport | null;
  onUpdatePrompt?: (
    segmentId: string,
    fieldOrPatch: string | Record<string, unknown>,
    value?: unknown,
    scriptFile?: string,
  ) => void | Promise<void>;
  onGenerateStoryboard?: (
    segmentId: string,
    scriptFile?: string,
    quality?: GenerationQuality,
    options?: { finalGenerationMode?: StoryboardFinalGenerationMode },
  ) => void;
  onGenerateVideo?: (
    segmentId: string,
    scriptFile?: string,
    quality?: GenerationQuality,
    options?: { videoContinuityPolicy?: VideoContinuityPolicy },
  ) => void;
  onGenerateGrid?: (
    episode: number,
    scriptFile: string,
    sceneIds?: string[],
  ) => Promise<void> | void;
  onRestoreStoryboard?: () => Promise<void> | void;
  onRestoreVideo?: () => Promise<void> | void;
}

export function GridImageToVideoCanvas({
  projectName,
  episode,
  episodeTitle,
  hasDraft,
  episodeScript,
  scriptFile,
  projectData,
  durationOptions,
  videoContinuitySupport,
  onUpdatePrompt,
  onGenerateStoryboard,
  onGenerateVideo,
  onGenerateGrid,
  onRestoreStoryboard,
  onRestoreVideo,
}: GridImageToVideoCanvasProps) {
  const { t } = useTranslation("dashboard");
  const contentMode = projectData?.content_mode ?? "narration";

  const hasScript = Boolean(episodeScript);
  const showTabs = Boolean(hasDraft);
  const defaultTab: GridTab = hasScript ? "units" : "preprocessing";
  const [activeTab, setActiveTab] = useState<GridTab>(defaultTab);
  const [batchingVideos, setBatchingVideos] = useState(false);
  const [batchConfirmAction, setBatchConfirmAction] = useState<"all-grids" | "videos" | null>(
    null,
  );
  const prepareGridScrollTarget = useCallback(() => {
    setActiveTab("grid_preview");
    return true;
  }, []);

  useScrollTarget("grid", { prepareTarget: prepareGridScrollTarget });

  useEffect(() => {
    // 剧本加载完成后切到 units 标签页，由 hasScript 状态变化驱动
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (hasScript) setActiveTab("units");
  }, [hasScript]);

  const episodeCost = useCostStore((s) =>
    episodeScript ? s.getEpisodeCost(episodeScript.episode) : undefined,
  );
  const debouncedFetch = useCostStore((s) => s.debouncedFetch);
  useEffect(() => {
    if (!projectName) return;
    debouncedFetch(projectName);
  }, [projectName, episodeScript?.episode, debouncedFetch]);

  const rawAspect =
    typeof projectData?.aspect_ratio === "string"
      ? projectData.aspect_ratio
      : (projectData?.aspect_ratio?.storyboard ??
        (contentMode === "narration" ? "9:16" : "16:9"));
  const aspectRatio: "9:16" | "16:9" =
    rawAspect === "9:16" || rawAspect === "16:9" ? rawAspect : "16:9";

  const segments = useMemo<Segment[]>(
    () =>
      !episodeScript || !projectData
        ? []
        : contentMode === "narration"
          ? ((episodeScript as NarrationEpisodeScript).segments ?? [])
          : ((episodeScript as DramaEpisodeScript).scenes ?? []),
    [contentMode, episodeScript, projectData],
  );

  const tasks = useTasksStore((s) => s.tasks);
  const isGenerating = useCallback(
    (taskType: "storyboard" | "video", segmentId: string): boolean =>
      tasks.some(
        (tk) =>
          tk.task_type === taskType &&
          tk.project_name === projectName &&
          tk.resource_id === segmentId &&
          (tk.status === "queued" || tk.status === "running"),
      ),
    [tasks, projectName],
  );
  const generatingStoryboard = useCallback(
    (segId: string) => isGenerating("storyboard", segId),
    [isGenerating],
  );
  const generatingVideo = useCallback(
    (segId: string) => isGenerating("video", segId),
    [isGenerating],
  );

  const invalidateGrids = useAppStore((s) => s.invalidateGrids);
  const [generatingAllGrids, setGeneratingAllGrids] = useState(false);
  const handleGenerateAllGrids = useCallback(async () => {
    if (!onGenerateGrid || !scriptFile) return;
    setGeneratingAllGrids(true);
    try {
      await onGenerateGrid(episode, scriptFile);
    } finally {
      setGeneratingAllGrids(false);
      invalidateGrids();
    }
  }, [onGenerateGrid, scriptFile, episode, invalidateGrids]);

  if (!projectData || (!episodeScript && !hasDraft)) {
    return (
      <div
        className="flex h-full items-center justify-center"
        style={{ color: "var(--color-text-4)" }}
      >
        {t("select_episode_hint")}
      </div>
    );
  }

  const epDur = episodeScript?.duration_seconds;
  const totalDuration =
    typeof epDur === "number" && Number.isFinite(epDur)
      ? epDur
      : segments.reduce((sum, s) => {
          const d = s.duration_seconds;
          return sum + (typeof d === "number" && Number.isFinite(d) ? d : 0);
        }, 0);

  const currentEpisodeMeta = projectData?.episodes?.find((e) => e.episode === episode);
  const epMeta =
    currentEpisodeMeta ??
    ({
      episode,
      title: episodeTitle ?? episodeScript?.title ?? "",
      script_file: scriptFile ?? "",
      scenes_count: segments.length,
      duration_seconds: totalDuration,
      status: hasScript ? "in_production" : "draft",
    } as const);

  const handleUpdatePrompt = (
    segId: string,
    fieldOrPatch: string | Record<string, unknown>,
    value?: unknown,
  ) => onUpdatePrompt?.(segId, fieldOrPatch, value, scriptFile);
  const handleGenSb = (
    segId: string,
    quality?: GenerationQuality,
    options?: { finalGenerationMode?: StoryboardFinalGenerationMode },
  ) =>
    onGenerateStoryboard?.(segId, scriptFile, quality, options);
  const handleGenVid = (
    segId: string,
    quality?: GenerationQuality,
    options?: { videoContinuityPolicy?: VideoContinuityPolicy },
  ) =>
    onGenerateVideo?.(segId, scriptFile, quality, options);

  const handleBatchGenerateVideos = async () => {
    if (!hasScript || batchingVideos) return;
    setBatchingVideos(true);
    try {
      for (const segment of segments) {
        const segId = getSegmentId(segment, contentMode);
        if (!segment.generated_assets?.storyboard_image) continue;
        await Promise.resolve(handleGenVid(segId));
      }
    } finally {
      setBatchingVideos(false);
    }
  };

  const videoBatchCount = segments.filter((segment) => segment.generated_assets?.storyboard_image).length;

  const handleConfirmBatchGenerate = async () => {
    if (batchConfirmAction === "all-grids") {
      try {
        await handleGenerateAllGrids();
      } finally {
        setBatchConfirmAction(null);
      }
      return;
    }
    if (batchConfirmAction === "videos") {
      try {
        await handleBatchGenerateVideos();
      } finally {
        setBatchConfirmAction(null);
      }
    }
  };

  const renderTabButton = (key: GridTab, label: string, disabled = false) => (
    <button
      type="button"
      role="tab"
      aria-selected={activeTab === key}
      onClick={() => !disabled && setActiveTab(key)}
      disabled={disabled}
      className="focus-ring relative px-3.5 py-2.5 text-[12.5px] font-medium transition-colors disabled:cursor-not-allowed"
      style={{
        color:
          activeTab === key
            ? "var(--color-text)"
            : disabled
              ? "var(--color-text-4)"
              : "var(--color-text-3)",
      }}
    >
      {label}
      {activeTab === key && (
        <span
          aria-hidden="true"
          className="absolute -bottom-px left-2.5 right-2.5 h-0.5 rounded"
          style={{ background: "var(--color-accent)" }}
        />
      )}
    </button>
  );

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <EpisodeHeader
        ep={epMeta}
        segmentCount={segments.length}
        totalDuration={totalDuration}
        episodeCost={episodeCost ?? undefined}
      />

      <div
        role="tablist"
        aria-label={t("grid_canvas_tab_aria")}
        className="flex items-center gap-0.5 px-5"
        style={{
          borderBottom: "1px solid var(--color-hairline)",
          background: "oklch(0.19 0.012 250 / 0.5)",
        }}
      >
        {showTabs && renderTabButton("preprocessing", t("tab_preprocessing"))}
        {renderTabButton("grid_preview", t("tab_grid_preview"))}
        {renderTabButton("units", t("tab_timeline"), !hasScript)}
        <span className="flex-1" />

        {activeTab === "grid_preview" && hasScript && onGenerateGrid && scriptFile && (
          <div className="mr-1 inline-flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setBatchConfirmAction("all-grids")}
              disabled={generatingAllGrids}
              className="sv-navbtn inline-flex items-center gap-1.5"
            >
              {generatingAllGrids ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Sparkles className="h-3 w-3" />
              )}
              <span>{generatingAllGrids ? t("submitting") : t("generate_all_grids")}</span>
            </button>
          </div>
        )}

        {activeTab === "units" && hasScript && (
          <div className="mr-1 inline-flex items-center gap-1.5">
            <button
              type="button"
              className="sv-navbtn inline-flex items-center gap-1.5"
              disabled={batchingVideos || !onGenerateVideo}
              title={t("batch_generate_videos")}
              aria-label={t("batch_generate_videos")}
              onClick={() => {
                if (videoBatchCount <= 0) return;
                setBatchConfirmAction("videos");
              }}
            >
              {batchingVideos ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Sparkles className="h-3 w-3" />
              )}
              <span>{t("batch_generate_videos")}</span>
            </button>
          </div>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        {activeTab === "preprocessing" && hasDraft ? (
          <div className="h-full min-w-0 overflow-auto p-4">
            <PreprocessingView
              projectName={projectName}
              episode={episode}
              contentMode={contentMode}
            />
          </div>
        ) : activeTab === "grid_preview" ? (
          <GridPreviewView
            projectName={projectName}
            episode={episode}
            scriptFile={scriptFile}
            segments={segments}
            contentMode={contentMode}
            aspectRatio={aspectRatio}
            onGenerateGrid={onGenerateGrid}
          />
        ) : episodeScript && segments.length > 0 ? (
          <ShotSplitView
            segments={segments}
            contentMode={contentMode}
            aspectRatio={aspectRatio}
            projectName={projectName}
            scriptFile={scriptFile}
            onUpdatePrompt={handleUpdatePrompt}
            onGenerateStoryboard={handleGenSb}
            onGenerateVideo={handleGenVid}
            onRestoreStoryboard={onRestoreStoryboard}
            onRestoreVideo={onRestoreVideo}
            generatingStoryboard={generatingStoryboard}
            generatingVideo={generatingVideo}
            durationOptions={durationOptions}
            videoContinuitySupport={videoContinuitySupport}
          />
        ) : null}
      </div>

      <ConfirmDialog
        open={batchConfirmAction !== null}
        title={
          batchConfirmAction === "all-grids"
            ? t("generate_all_grids")
            : t("batch_generate_videos")
        }
        description={
          batchConfirmAction === "all-grids"
            ? t("generate_all_grids_confirm_desc")
            : t("batch_generate_videos_confirm_desc", { count: videoBatchCount })
        }
        confirmLabel={t("common:confirm")}
        loadingLabel={t("submitting")}
        loading={
          batchConfirmAction === "all-grids"
            ? generatingAllGrids
            : batchConfirmAction === "videos"
              ? batchingVideos
              : false
        }
        onConfirm={() => void handleConfirmBatchGenerate()}
        onCancel={() => setBatchConfirmAction(null)}
      />
    </div>
  );
}

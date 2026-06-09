import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useAppStore } from "@/stores/app-store";
import { groupBySegmentBreak, computeGridSize, matchGridsForGroup } from "@/utils/grid-layout";
import { GridPreviewPanel } from "@/components/canvas/timeline/GridPreviewPanel";
import type { GridGeneration } from "@/types/grid";
import type {
  DramaScene,
  GenerationQuality,
  NarrationSegment,
  StoryboardFinalGenerationMode,
} from "@/types";

type Segment = NarrationSegment | DramaScene;

interface GridPreviewViewProps {
  projectName: string;
  episode: number;
  scriptFile?: string;
  segments: Segment[];
  contentMode: "narration" | "drama";
  aspectRatio: "9:16" | "16:9";
  onGenerateGrid?: (
    episode: number,
    scriptFile: string,
    sceneIds?: string[],
  ) => Promise<void> | void;
  onGenerateStoryboard?: (
    segmentId: string,
    quality?: GenerationQuality,
    options?: { finalGenerationMode?: StoryboardFinalGenerationMode },
  ) => Promise<void> | void;
}

function getSegmentId(seg: Segment, mode: "narration" | "drama"): string {
  return mode === "narration"
    ? (seg as NarrationSegment).segment_id
    : (seg as DramaScene).scene_id;
}

export function GridPreviewView({
  projectName,
  episode,
  scriptFile,
  segments,
  contentMode,
  aspectRatio,
  onGenerateGrid,
  onGenerateStoryboard,
}: GridPreviewViewProps) {
  const { t } = useTranslation("dashboard");
  const gridsRevision = useAppStore((s) => s.gridsRevision);
  const [grids, setGrids] = useState<GridGeneration[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [generatingGroups, setGeneratingGroups] = useState<Set<string>>(new Set());
  const [pendingGroup, setPendingGroup] = useState<{ key: string; segments: Segment[] } | null>(
    null,
  );

  const groups = useMemo(() => groupBySegmentBreak(segments), [segments]);

  const refreshGrids = useCallback(() => {
    if (!projectName) return;
    API.listGrids(projectName)
      .then((data) => {
        setGrids(data);
        setRefreshKey((v) => v + 1);
      })
      .catch(() => {});
  }, [projectName]);

  useEffect(() => {
    refreshGrids();
  }, [refreshGrids, gridsRevision]);

  const getGridIdsForGroup = useCallback(
    (groupSegs: Segment[]): string[] =>
      matchGridsForGroup(
        grids,
        groupSegs.map((s) => getSegmentId(s, contentMode)),
        episode,
      ).map((g) => g.id),
    [grids, episode, contentMode],
  );

  const handleGenerateGroup = useCallback(
    // group key 用 sceneIds 排序后 join，分组重排时 spinner 不会挂错卡片
    async (groupKey: string, group: Segment[]) => {
      if (!scriptFile) return;
      const sceneIds = group.map((s) => getSegmentId(s, contentMode));
      setGeneratingGroups((prev) => new Set(prev).add(groupKey));
      try {
        if (sceneIds.length === 1) {
          await onGenerateStoryboard?.(sceneIds[0]);
        } else {
          await onGenerateGrid?.(episode, scriptFile, sceneIds);
        }
      } finally {
        setGeneratingGroups((prev) => {
          const next = new Set(prev);
          next.delete(groupKey);
          return next;
        });
        refreshGrids();
      }
    },
    [onGenerateGrid, onGenerateStoryboard, scriptFile, contentMode, episode, refreshGrids],
  );

  const stats = useMemo(() => {
    const batches = groups.reduce((sum, group) => {
      if (group.length === 1) return sum + 1;
      return sum + computeGridSize(group.length, aspectRatio).batchCount;
    }, 0);
    const cells = segments.length;
    const readyBatches = groups.reduce((sum, group) => {
      if (group.length === 1) {
        return sum + (group[0]?.generated_assets?.storyboard_image ? 1 : 0);
      }
      const expectedBatches = computeGridSize(group.length, aspectRatio).batchCount;
      const sceneIds = group.map((s) => getSegmentId(s, contentMode));
      const groupGrids = matchGridsForGroup(grids, sceneIds, episode);
      const completedBatches = groupGrids.filter((g) => g.status === "completed").length;
      return sum + Math.min(completedBatches, expectedBatches);
    }, 0);
    const percent = batches > 0 ? Math.round((readyBatches / batches) * 100) : 0;
    return { batches, cells, percent };
  }, [groups, segments, grids, episode, contentMode, aspectRatio]);

  if (segments.length === 0) {
    return (
      <div
        className="flex h-full items-center justify-center text-sm"
        style={{ color: "var(--color-text-4)" }}
      >
        {t("grid_preview_empty_episode")}
      </div>
    );
  }

  const canGenerate = Boolean((onGenerateGrid || onGenerateStoryboard) && scriptFile);
  const pendingUsesStoryboard = pendingGroup?.segments.length === 1;

  return (
    <>
      <div className="h-full overflow-y-auto px-5 py-4">
        <div
          className="mb-4 flex flex-wrap items-center gap-2 rounded-md border px-3.5 py-2.5"
          style={{
            borderColor: "var(--color-hairline-soft)",
            background: "oklch(0.18 0.010 265 / 0.5)",
          }}
        >
          <span
            className="num text-[11.5px] tabular-nums"
            style={{ color: "var(--color-text-3)", fontFamily: "var(--font-mono)" }}
          >
            {t("grid_preview_summary", stats)}
          </span>
        </div>

        <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr))]">
          {groups.map((group, idx) => {
            const layout = computeGridSize(group.length, aspectRatio);
            const ids = getGridIdsForGroup(group);
            const usesStoryboard = group.length === 1;
            const title = usesStoryboard
              ? t("grid_preview_single_card_title", { index: idx + 1 })
              : layout.batchCount > 1
                ? t("grid_preview_batch_card_title_split", {
                    index: idx + 1,
                    shotCount: group.length,
                    batchCount: layout.batchCount,
                    chunks: layout.chunkSizes.join("+"),
                  })
                : t("grid_preview_batch_card_title", {
                    index: idx + 1,
                    cellCount: group.length,
                    rows: layout.rows,
                    cols: layout.cols,
                  });
            const groupKey = group
              .map((s) => getSegmentId(s, contentMode))
              .sort()
              .join(",");
            const generating = generatingGroups.has(groupKey);
            return (
              <div
                key={groupKey || idx}
                data-workspace-focus-surface
                className="overflow-hidden rounded-md border"
                style={{
                  borderColor: "var(--color-hairline-soft)",
                  background: "oklch(0.20 0.011 265 / 0.35)",
                }}
              >
                {ids.map((gridId) => (
                  <span
                    key={gridId}
                    id={`grid-${gridId}`}
                    className="sr-only"
                    aria-hidden="true"
                  />
                ))}
                <div
                  className="flex items-center gap-2 px-4 py-2"
                  style={{ borderBottom: "1px solid var(--color-hairline-soft)" }}
                >
                  <span
                    className="num text-[11px] font-semibold uppercase tracking-wider"
                    style={{
                      color: "var(--color-text-3)",
                      fontFamily: "var(--font-mono)",
                      letterSpacing: "0.6px",
                    }}
                  >
                    {title}
                  </span>
                  <span className="flex-1" />
                  {canGenerate && (
                    <button
                      type="button"
                      onClick={() => setPendingGroup({ key: groupKey, segments: group })}
                      disabled={generating || (usesStoryboard ? !onGenerateStoryboard : !onGenerateGrid)}
                      className="sv-navbtn inline-flex items-center gap-1.5"
                    >
                      {generating ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Sparkles className="h-3 w-3" />
                      )}
                      <span>
                        {generating
                          ? t("submitting")
                          : usesStoryboard
                            ? t("media_generate_storyboard", { defaultValue: "生成分镜" })
                          : ids.length > 0
                            ? t("grid_regenerate_btn")
                            : t("grid_preview_batch_generate")}
                      </span>
                    </button>
                  )}
                </div>
                {usesStoryboard ? (
                  <div className="px-4 py-3 text-xs" style={{ color: "var(--color-text-4)" }}>
                    {group[0]?.generated_assets?.storyboard_image
                      ? t("grid_single_storyboard_ready", { defaultValue: "单镜头已使用普通分镜生成，不创建宫格。" })
                      : t("grid_single_storyboard_hint", { defaultValue: "单镜头使用普通分镜生成，不创建宫格。" })}
                  </div>
                ) : (
                  <GridPreviewPanel
                    projectName={projectName}
                    gridIds={ids}
                    onRegenerated={refreshGrids}
                    refreshKey={refreshKey}
                    defaultExpanded
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>

      <ConfirmDialog
        open={pendingGroup !== null}
        title={
          pendingUsesStoryboard
            ? t("media_generate_storyboard", { defaultValue: "生成分镜" })
            : t("grid_preview_batch_generate")
        }
        description={
          pendingUsesStoryboard
            ? t("grid_single_storyboard_generate_confirm_desc", {
                defaultValue: "即将为这一个镜头提交普通分镜生成任务，不创建宫格，确定继续吗？",
              })
            : t("grid_preview_batch_generate_confirm_desc", {
                count: pendingGroup?.segments.length ?? 0,
              })
        }
        confirmLabel={t("common:confirm")}
        loadingLabel={t("submitting")}
        loading={pendingGroup ? generatingGroups.has(pendingGroup.key) : false}
        onConfirm={async () => {
          if (!pendingGroup) return;
          try {
            await handleGenerateGroup(pendingGroup.key, pendingGroup.segments);
          } finally {
            setPendingGroup(null);
          }
        }}
        onCancel={() => setPendingGroup(null)}
      />
    </>
  );
}

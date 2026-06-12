import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useAppStore } from "@/stores/app-store";
import { groupBySegmentBreak, computeGridSize, matchGridsForGroup } from "@/utils/grid-layout";
import { GridPreviewPanel } from "@/components/canvas/timeline/GridPreviewPanel";
import type { GridGeneration } from "@/types/grid";
import type { DramaScene, NarrationSegment } from "@/types";

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

  const getGridsForGroup = useCallback(
    (groupSegs: Segment[]): GridGeneration[] =>
      matchGridsForGroup(
        grids,
        groupSegs.map((s) => getSegmentId(s, contentMode)),
        episode,
      ),
    [grids, episode, contentMode],
  );

  const handleGenerateGroup = useCallback(
    // group key 用 sceneIds 排序后 join，分组重排时 spinner 不会挂错卡片
    async (groupKey: string, group: Segment[]) => {
      if (!scriptFile || !onGenerateGrid) return;
      const sceneIds = group.map((s) => getSegmentId(s, contentMode));
      setGeneratingGroups((prev) => new Set(prev).add(groupKey));
      try {
        await onGenerateGrid(episode, scriptFile, sceneIds);
      } finally {
        setGeneratingGroups((prev) => {
          const next = new Set(prev);
          next.delete(groupKey);
          return next;
        });
        refreshGrids();
      }
    },
    [onGenerateGrid, scriptFile, contentMode, episode, refreshGrids],
  );

  const stats = useMemo(() => {
    const batches = groups.reduce((sum, group) => {
      return sum + computeGridSize(group.length, aspectRatio).batchCount;
    }, 0);
    const cells = segments.length;
    const readyBatches = groups.reduce((sum, group) => {
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

  const canGenerate = Boolean(onGenerateGrid && scriptFile);

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
          {groups.flatMap((group, idx) => {
            const layout = computeGridSize(group.length, aspectRatio);
            const groupSceneIds = group.map((s) => getSegmentId(s, contentMode));
            const groupGrids = getGridsForGroup(group);
            const renderCard = (
              title: string,
              gridId: string | null,
              keySuffix: string,
              showGenerateButton: boolean,
              generateSegments: Segment[],
            ) => {
              const generateKey = generateSegments
                .map((s) => getSegmentId(s, contentMode))
                .sort()
                .join(",");
              const generating = generatingGroups.has(generateKey);
              return (
                <div
                  key={`${groupSceneIds.join(",") || idx}-${keySuffix}`}
                  data-workspace-focus-surface
                  className="overflow-hidden rounded-md border"
                  style={{
                    borderColor: "var(--color-hairline-soft)",
                    background: "oklch(0.20 0.011 265 / 0.35)",
                  }}
                >
                  {gridId && (
                    <span
                      id={`grid-${gridId}`}
                      className="sr-only"
                      aria-hidden="true"
                    />
                  )}
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
                    {canGenerate && showGenerateButton && (
                      <button
                        type="button"
                        onClick={() =>
                          setPendingGroup({
                            key: generateKey,
                            segments: generateSegments,
                          })
                        }
                        disabled={generating || !onGenerateGrid}
                        className="sv-navbtn inline-flex items-center gap-1.5"
                      >
                        {generating ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Sparkles className="h-3 w-3" />
                        )}
                        <span>
                          {generating ? t("submitting") : t("grid_preview_batch_generate")}
                        </span>
                      </button>
                    )}
                  </div>
                  <GridPreviewPanel
                    projectName={projectName}
                    gridId={gridId}
                    onRegenerated={refreshGrids}
                    refreshKey={refreshKey}
                    defaultExpanded
                  />
                </div>
              );
            };

            const remainingGrids = [...groupGrids];
            let offset = 0;
            const plannedCards = layout.chunkSizes.map((chunkSize, batchIdx) => {
              const chunk = group.slice(offset, offset + chunkSize);
              offset += chunkSize;
              const chunkIds = chunk.map((s) => getSegmentId(s, contentMode));
              const chunkIdSet = new Set(chunkIds);
              const matchedIdx = remainingGrids.findIndex((grid) =>
                grid.scene_ids.some((id) => chunkIdSet.has(id)),
              );
              const grid = matchedIdx >= 0 ? remainingGrids.splice(matchedIdx, 1)[0] : null;
              const coveredIds = new Set(
                groupGrids.flatMap((candidate) =>
                  candidate.scene_ids.filter((id) => chunkIdSet.has(id)),
                ),
              );
              const missingSegments = chunk.filter(
                (s) => !coveredIds.has(getSegmentId(s, contentMode)),
              );
              const gridLayout = computeGridSize(grid?.scene_ids.length ?? chunk.length, aspectRatio);
              const title = t("grid_preview_batch_card_title", {
                index: layout.batchCount > 1 ? `${idx + 1}.${batchIdx + 1}` : idx + 1,
                cellCount: gridLayout.cellCount,
                rows: gridLayout.rows,
                cols: gridLayout.cols,
              });
              return renderCard(
                title,
                grid?.id ?? null,
                grid?.id ?? `empty-${batchIdx}`,
                !grid || missingSegments.length > 0,
                missingSegments.length > 0 ? missingSegments : chunk,
              );
            });

            const extraCards = remainingGrids.map((grid, extraIdx) => {
              const gridLayout = computeGridSize(grid.scene_ids.length, aspectRatio);
              const title = t("grid_preview_batch_card_title", {
                index:
                  layout.batchCount > 1
                    ? `${idx + 1}.${layout.chunkSizes.length + extraIdx + 1}`
                    : idx + 1,
                cellCount: gridLayout.cellCount,
                rows: gridLayout.rows,
                cols: gridLayout.cols,
              });
              return renderCard(title, grid.id, grid.id, false, group);
            });

            return [...plannedCards, ...extraCards];
          })}
        </div>
      </div>

      <ConfirmDialog
        open={pendingGroup !== null}
        title={t("grid_preview_batch_generate")}
        description={t("grid_preview_batch_generate_confirm_desc", {
          count: pendingGroup?.segments.length ?? 0,
        })}
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

import { useState, useEffect } from "react";
import {
  ChevronRight,
  RefreshCw,
  Loader2,
  Grid2x2,
  Film,
  AlertCircle,
  CheckCircle2,
  Clock,
  Scissors,
  User,
  Search,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { errMsg } from "@/utils/async";
import { summarizeUserFacingError } from "@/utils/error-summary";
import { useProjectsStore } from "@/stores/projects-store";
import { useAppStore } from "@/stores/app-store";
import { ImageLightbox } from "@/components/ui/ImageLightbox";
import type { GridGeneration, ReferenceImage } from "@/types/grid";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface GridPreviewPanelProps {
  projectName: string;
  gridIds: string[];
  /** Called after a regeneration is submitted (for parent to refresh grids list). */
  onRegenerated?: () => void;
  /** Changed when grids list is refreshed, triggers re-fetch of panel data. */
  refreshKey?: number;
  /** Render in expanded state on first mount. Used by the dedicated grid preview tab. */
  defaultExpanded?: boolean;
}

// ---------------------------------------------------------------------------
// StatusBadge
// ---------------------------------------------------------------------------

type GridStatus = GridGeneration["status"];

function StatusBadge({ status, t }: { status: GridStatus; t: (key: string) => string }) {
  const STATUS_KEY: Record<GridStatus, string> = {
    pending: "grid_status_pending",
    generating: "grid_status_generating",
    splitting: "grid_status_splitting",
    completed: "grid_status_completed",
    failed: "grid_status_failed",
  };

  const configs: Record<
    GridStatus,
    { icon: React.ReactNode; cls: string }
  > = {
    pending: {
      icon: <Clock className="h-3 w-3" />,
      cls: "bg-gray-800/80 text-gray-400 border-gray-700/50",
    },
    generating: {
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
      cls: "bg-blue-950/60 text-blue-300 border-blue-700/40",
    },
    splitting: {
      icon: <Scissors className="h-3 w-3" />,
      cls: "bg-violet-950/60 text-violet-300 border-violet-700/40",
    },
    completed: {
      icon: <CheckCircle2 className="h-3 w-3" />,
      cls: "bg-emerald-950/60 text-emerald-400 border-emerald-700/40",
    },
    failed: {
      icon: <AlertCircle className="h-3 w-3" />,
      cls: "bg-red-950/60 text-red-400 border-red-700/40",
    },
  };

  const { icon, cls } = configs[status];
  const label = t(STATUS_KEY[status]);

  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium tracking-wide ${cls}`}
    >
      {icon}
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// ReferenceImageStrip
// ---------------------------------------------------------------------------

function ReferenceImageStrip({
  references,
  projectName,
  refreshKey,
  onPreview,
}: {
  references: ReferenceImage[];
  projectName: string;
  refreshKey: number;
  onPreview: (preview: { src: string; path: string; alt: string }) => void;
}) {
  const fingerprints = useProjectsStore((s) => s.assetFingerprints);
  return (
    <div className="flex gap-2.5 overflow-x-auto pb-1 scrollbar-thin">
      {references.map((ref, idx) => {
        const isChar = ref.ref_type === "character";
        const cacheBust = fingerprints[ref.path] ?? refreshKey;
        const imageUrl = API.getFileUrl(projectName, ref.path, cacheBust);
        return (
          <motion.div
            key={ref.path}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.05, duration: 0.2 }}
            className="group flex w-14 shrink-0 flex-col items-center gap-1"
          >
            <button
              type="button"
              onClick={() => onPreview({ src: imageUrl, path: ref.path, alt: ref.name })}
              aria-label={`${ref.name} 全屏预览`}
              className={`w-full cursor-zoom-in overflow-hidden rounded border bg-gray-900/50 transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/60 ${
                isChar
                  ? "border-amber-800/30 group-hover:border-amber-500/50"
                  : "border-sky-800/30 group-hover:border-sky-500/50"
              }`}
            >
              <img
                src={imageUrl}
                alt={ref.name}
                className="block aspect-square w-full object-cover transition-transform duration-200 group-hover:scale-105"
              />
            </button>
            <div className="flex max-w-full items-center gap-0.5">
              {isChar ? (
                <User className="h-2 w-2 shrink-0 text-amber-500/50" />
              ) : (
                <Search className="h-2 w-2 shrink-0 text-sky-500/50" />
              )}
              <span
                className={`truncate text-[8px] leading-tight ${
                  isChar ? "text-amber-400/50" : "text-sky-400/50"
                }`}
                title={ref.name}
              >
                {ref.name}
              </span>
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// GridPreviewPanel
// ---------------------------------------------------------------------------

export function GridPreviewPanel({
  projectName,
  gridIds,
  onRegenerated,
  refreshKey = 0,
  defaultExpanded = false,
}: GridPreviewPanelProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [grid, setGrid] = useState<GridGeneration | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const [previewImage, setPreviewImage] = useState<{ src: string; path: string; alt: string } | null>(null);
  const { t } = useTranslation("dashboard");

  const hasGrids = gridIds.length > 0;
  const multipleGrids = gridIds.length > 1;
  const safeIdx = Math.min(selectedIdx, Math.max(0, gridIds.length - 1));
  const selectedGridId = gridIds[safeIdx] ?? null;

  // 直接订阅全局 grid 变更信号作为唯一 refetch 触发源；
  // parent 透传的 refreshKey 是同一事件流（gridsRevision → listGrids → setRefreshKey）
  // 的下游产物，加入 deps 会导致每次事件多发一次冗余 GET /grids/{id}。
  const gridsRevision = useAppStore((s) => s.gridsRevision);

  // safeIdx already clamps selectedIdx to valid range; no effect needed

  // Fetch grid data when expanded and selectedGridId is available
  useEffect(() => {
    if (!expanded || !selectedGridId) return;

    let cancelled = false;
    // Clear stale data and show spinner when switching batches
    if (!grid || grid.id !== selectedGridId) {
      // 切换批次时清空旧数据并展示加载状态，再触发异步 fetch
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLoading(true);
      setGrid(null);
    }
    setError(null);

    API.getGrid(projectName, selectedGridId)
      .then((data) => {
        if (!cancelled) {
          setGrid(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(errMsg(err, t("grid_load_failed")));
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- grid 仅用于切换批次判断；refreshKey 与 gridsRevision 同源，仅保留后者避免双触发；t 稳定
  }, [expanded, selectedGridId, projectName, gridsRevision]);

  const isInProgress =
    grid?.status === "pending" || grid?.status === "generating" || grid?.status === "splitting";

  // 优先使用持久化的 mtime 指纹做 cache-bust，跨页面刷新仍然有效；
  // 回退到 refreshKey 仅用于指纹尚未送达前的当次会话。
  const assetFingerprints = useProjectsStore((s) => s.assetFingerprints);
  const gridFp = grid?.grid_image_path ? (assetFingerprints[grid.grid_image_path] ?? null) : null;
  const imageUrl =
    grid?.grid_image_path
      ? API.getFileUrl(projectName, grid.grid_image_path, gridFp ?? refreshKey)
      : null;
  const displayedGridError = summarizeUserFacingError(t, grid?.error_message);

  const refs = grid?.reference_images ?? [];
  const mosaicCells = grid
    ? Array.from({ length: Math.max(grid.rows * grid.cols, grid.cell_count, grid.frame_chain.length) }, (_, idx) => {
        const byIndex = grid.frame_chain.find((cell) => cell.index === idx);
        return byIndex ?? {
          index: idx,
          row: Math.floor(idx / Math.max(1, grid.cols)),
          col: idx % Math.max(1, grid.cols),
          frame_type: "placeholder" as const,
          prev_scene_id: null,
          next_scene_id: null,
          image_path: null,
        };
      })
    : [];
  const hasMosaicImages = mosaicCells.some((cell) => Boolean(cell.image_path));

  return (
    <div>
      {/* Toggle header */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 border-t border-amber-800/20 px-4 py-1.5 text-left transition-colors hover:bg-amber-900/10 focus-ring"
      >
        <motion.span
          animate={{ rotate: expanded ? 90 : 0 }}
          transition={{ duration: 0.18, ease: "easeInOut" }}
          className="text-amber-600/70"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </motion.span>

        <Film className="h-3.5 w-3.5 text-amber-500/60" />

        <span className="text-xs font-medium text-amber-400/70">{t("grid_preview_title")}</span>

        {!hasGrids && (
          <span className="ml-1 text-[10px] text-gray-600">{t("grid_not_generated")}</span>
        )}

        {multipleGrids && !expanded && (
          <span className="ml-1 text-[10px] text-gray-600">
            {t("grid_batch_unit", { count: gridIds.length })}
          </span>
        )}
      </button>

      {/* Collapsible content */}
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            key="panel-content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-3 pt-2">
              {/* No grid yet */}
              {!hasGrids ? (
                <div className="flex flex-col items-center gap-2 py-6 text-center">
                  <Grid2x2 className="h-8 w-8 text-gray-700" />
                  <p className="text-xs text-gray-600">{t("grid_no_grids_yet")}</p>
                  <p className="text-[10px] text-gray-700">
                    {t("grid_generate_instruction")}
                  </p>
                </div>
              ) : loading && !grid ? (
                /* Loading state (initial) */
                <div className="flex items-center justify-center gap-2 py-8">
                  <Loader2 className="h-4 w-4 animate-spin text-amber-500/50" />
                  <span className="text-xs text-gray-600">{t("grid_loading_data")}</span>
                </div>
              ) : error ? (
                /* Error state */
                <div className="flex items-center gap-2 rounded-md border border-red-900/30 bg-red-950/20 px-3 py-2.5">
                  <AlertCircle className="h-4 w-4 shrink-0 text-red-500/70" />
                  <span className="text-xs text-red-400/80">{error}</span>
                </div>
              ) : grid ? (
                /* Grid loaded */
                <div className="flex flex-col gap-3">
                  {/* Top bar: batch pills + status + regen */}
                  <div className="flex items-center gap-2">
                    {multipleGrids && (
                      <div className="flex items-center gap-0.5 rounded-md bg-gray-900/50 p-0.5">
                        {gridIds.map((_, idx) => (
                          <button
                            key={idx}
                            type="button"
                            onClick={() => setSelectedIdx(idx)}
                            className={`inline-flex h-5 min-w-[1.375rem] items-center justify-center rounded px-1 text-[10px] font-medium tabular-nums transition-all duration-150 ${
                              idx === safeIdx
                                ? "bg-amber-700/50 text-amber-200 shadow-sm"
                                : "text-gray-500 hover:text-gray-300 hover:bg-gray-800/60"
                            }`}
                          >
                            {idx + 1}
                          </button>
                        ))}
                      </div>
                    )}

                    <StatusBadge status={grid.status} t={t} />

                    <span className="text-[10px] text-gray-600">
                      {grid.model}
                    </span>

                    {displayedGridError && (
                      <span
                        className="truncate text-[10px] text-red-400/70"
                        title={displayedGridError}
                      >
                        {displayedGridError}
                      </span>
                    )}

                    <motion.button
                      type="button"
                      disabled={regenerating || isInProgress}
                      onClick={() => {
                        if (!selectedGridId || regenerating || isInProgress) return;
                        setRegenerating(true);
                        API.regenerateGrid(projectName, selectedGridId)
                          .then(() => {
                            setGrid((prev) => prev ? { ...prev, status: "pending" } : prev);
                            onRegenerated?.();
                          })
                          .catch((err: unknown) => {
                            setError(errMsg(err, t("grid_regenerate_failed")));
                          })
                          .finally(() => setRegenerating(false));
                      }}
                      className={`ml-auto shrink-0 whitespace-nowrap inline-flex items-center gap-1 rounded border border-amber-800/30 bg-amber-950/30 px-2 py-1 text-[10px] font-medium text-amber-400/80 transition-colors ${
                        regenerating || isInProgress ? "opacity-50 cursor-not-allowed" : "hover:bg-amber-900/40 hover:text-amber-300"
                      }`}
                      whileTap={regenerating || isInProgress ? {} : { scale: 0.95 }}
                    >
                      <RefreshCw className={`h-3 w-3 ${regenerating || isInProgress ? "animate-spin" : ""}`} />
                      {regenerating ? t("grid_regenerating") : isInProgress ? t("generating_grid") : t("grid_regenerate_btn")}
                    </motion.button>
                  </div>

                  {/* Current storyboard mosaic + original grid fallback */}
                  {hasMosaicImages && grid ? (
                    <div className="overflow-hidden rounded-md border border-gray-800/50 bg-gray-900/40">
                      <div
                        className="grid gap-1.5 p-1.5"
                        style={{
                          gridTemplateColumns: `repeat(${Math.max(1, grid.cols)}, minmax(0, 1fr))`,
                        }}
                        role="group"
                        aria-label={t("grid_storyboard_mosaic_alt", {
                          defaultValue: "宫格切片分镜预览",
                        })}
                      >
                        {mosaicCells.map((cell) => {
                          const cellPath = cell.image_path;
                          const cellUrl = cellPath
                            ? API.getFileUrl(projectName, cellPath, assetFingerprints[cellPath] ?? refreshKey)
                            : null;
                          const cellLabel = cell.next_scene_id
                            ? t("grid_cell_storyboard_label", {
                                defaultValue: "第 {{index}} 格 · {{id}}",
                                index: cell.index + 1,
                                id: cell.next_scene_id,
                              })
                            : t("grid_cell_placeholder_label", {
                                defaultValue: "第 {{index}} 格 · 占位",
                                index: cell.index + 1,
                              });
                          return cellUrl && cellPath ? (
                            <button
                              key={cell.index}
                              type="button"
                              onClick={() => {
                                setPreviewImage({ src: cellUrl, path: cellPath, alt: cellLabel });
                              }}
                              aria-label={`${cellLabel} 全屏预览`}
                              title={cellLabel}
                              className="group aspect-video min-w-0 cursor-zoom-in overflow-hidden rounded border border-gray-800/70 bg-black/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/60"
                            >
                              <img
                                src={cellUrl}
                                alt={cellLabel}
                                className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.03]"
                                loading="lazy"
                              />
                            </button>
                          ) : (
                            <div
                              key={cell.index}
                              className="flex aspect-video min-w-0 items-center justify-center rounded border border-dashed border-gray-800/60 bg-black/20"
                              title={cellLabel}
                            >
                              <span className="font-mono text-[9px] text-gray-700">
                                {cell.index + 1}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                      <div className="flex items-center gap-2 border-t border-gray-800/50 px-2.5 py-1.5">
                        <span className="font-mono text-[10px] text-gray-500">
                          {t("grid_cell_info", { count: grid.cell_count, size: grid.grid_size })}
                        </span>
                        <span className="text-[10px] text-gray-700">
                          {grid.rows}×{grid.cols}
                        </span>
                        {imageUrl && grid.grid_image_path && (
                          <button
                            type="button"
                            onClick={() => {
                              setPreviewImage({
                                src: imageUrl,
                                path: grid.grid_image_path ?? "",
                                alt: t("grid_composite_image_alt"),
                              });
                            }}
                            className="ml-auto rounded border border-gray-800/70 px-2 py-0.5 text-[10px] text-gray-500 transition-colors hover:border-amber-800/50 hover:text-amber-300"
                          >
                            {t("grid_original_image_btn", { defaultValue: "原始宫格图" })}
                          </button>
                        )}
                      </div>
                    </div>
                  ) : imageUrl ? (
                    <div className="overflow-hidden rounded-md border border-gray-800/50 bg-gray-900/40">
                      <button
                        type="button"
                        onClick={() => {
                          if (grid.grid_image_path) {
                            setPreviewImage({
                              src: imageUrl,
                              path: grid.grid_image_path,
                              alt: t("grid_composite_image_alt"),
                            });
                          }
                        }}
                        aria-label={`${t("grid_composite_image_alt")} 全屏预览`}
                        className="block w-full cursor-zoom-in focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/60"
                      >
                        <img
                          src={imageUrl}
                          alt={t("grid_composite_image_alt")}
                          className="block max-h-[26rem] w-full object-contain bg-black/20"
                        />
                      </button>
                      <div className="flex items-center gap-2 border-t border-gray-800/50 px-2.5 py-1.5">
                        <span className="font-mono text-[10px] text-gray-500">
                          {t("grid_cell_info", { count: grid.cell_count, size: grid.grid_size })}
                        </span>
                        <span className="text-[10px] text-gray-700">
                          {grid.rows}×{grid.cols}
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div className="flex h-24 items-center justify-center rounded-md border border-gray-800/40 bg-gray-900/30">
                      <span className="text-[10px] text-gray-700">
                        {grid.status === "generating" || grid.status === "pending"
                          ? t("generating_grid")
                          : t("grid_no_image")}
                      </span>
                    </div>
                  )}

                  {/* Reference images strip */}
                  {refs.length > 0 && (
                    <div className="flex flex-col gap-1.5">
                      <span className="text-[9px] font-medium uppercase tracking-widest text-gray-600">
                        {t("grid_reference_images")}
                      </span>
                      <ReferenceImageStrip
                        references={refs}
                        projectName={projectName}
                        refreshKey={refreshKey}
                        onPreview={setPreviewImage}
                      />
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
      {previewImage && (
        <ImageLightbox
          src={previewImage.src}
          alt={previewImage.alt}
          downloadSource={{ kind: "project", projectName, path: previewImage.path }}
          onClose={() => setPreviewImage(null)}
        />
      )}
    </div>
  );
}

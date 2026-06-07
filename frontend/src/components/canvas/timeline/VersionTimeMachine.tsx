import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight, History, Trash2 } from "lucide-react";
import { API, type VersionInfo, type VersionResourceType } from "@/api";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { ImageLightbox } from "@/components/ui/ImageLightbox";
import { errMsg } from "@/utils/async";
import { videoContinuityMetadataToPlan } from "@/utils/video-continuity";

interface VersionTimeMachineProps {
  projectName: string;
  resourceType: VersionResourceType;
  resourceId: string;
  onRestore?: (version: number) => void | Promise<void>;
  allowDelete?: boolean;
  /** Icon-only trigger button: hides label and chevron for narrow card headers. */
  iconOnly?: boolean;
  currentVersionLabel?: string | null;
}

function getImagePreviewHeightClass(
  resourceType: VersionTimeMachineProps["resourceType"],
): string {
  if (resourceType === "characters") return "h-80";
  if (resourceType === "scenes" || resourceType === "props") return "h-56";
  return "h-64";
}

function qualityLabel(t: (key: string) => string, quality?: VersionInfo["generation_quality"]): string | null {
  if (quality === "draft") return t("episode_status_label_draft");
  if (quality === "final") return t("media_generate_video_final");
  if (quality === "custom") return "Custom";
  return null;
}

function versionMetaBadges(t: (key: string) => string, info: VersionInfo): string[] {
  const route = info.generation_route;
  const continuityPlan = videoContinuityMetadataToPlan(info.video_continuity);
  const continuityLabel = continuityPlan
    ? ({
        start_only: "仅首帧",
        end_frame: "首尾帧连续",
        reference_assisted: "参考图辅助",
      }[continuityPlan.effectivePolicy] ?? continuityPlan.effectivePolicy)
    : null;
  return [
    qualityLabel(t, info.generation_quality),
    route?.resolution,
    route?.duration_seconds != null ? `${route.duration_seconds}s` : null,
    route?.provider && route.model ? `${route.provider}/${route.model}` : null,
    route?.generate_audio === true ? t("generate_audio_label") : null,
    continuityLabel,
  ].filter((item): item is string => Boolean(item));
}

/** Find all scrollable ancestor elements. */
function getScrollParents(el: HTMLElement): HTMLElement[] {
  const parents: HTMLElement[] = [];
  let node: HTMLElement | null = el.parentElement;
  while (node) {
    const s = getComputedStyle(node);
    if (/(auto|scroll)/.test(s.overflow + s.overflowY)) parents.push(node);
    node = node.parentElement;
  }
  return parents;
}

export function VersionTimeMachine({
  projectName,
  resourceType,
  resourceId,
  onRestore,
  allowDelete = false,
  iconOnly = false,
  currentVersionLabel,
}: VersionTimeMachineProps) {
  const { t } = useTranslation("dashboard");
  const resourcePath =
    resourceType === "storyboards" ? `storyboards/scene_${resourceId}.png` :
    resourceType === "videos" ? `videos/scene_${resourceId}.mp4` :
    resourceType === "characters" ? `characters/${resourceId}.png` :
    resourceType === "scenes" ? `scenes/${resourceId}.png` :
    `props/${resourceId}.png`;
  const resourceFp = useProjectsStore((s) => s.getAssetFingerprint(resourcePath));
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const [open, setOpen] = useState(false);
  const [panelPos, setPanelPos] = useState<{ top: number; left: number } | null>(null);
  const [versions, setVersions] = useState<VersionInfo[]>([]);
  const [currentVersion, setCurrentVersion] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [restoringVersion, setRestoringVersion] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<VersionInfo | null>(null);
  const [deletingVersion, setDeletingVersion] = useState<number | null>(null);
  const [previewImage, setPreviewImage] = useState<{ src: string; alt: string; path?: string } | null>(null);

  // Reset version list when the underlying resource changes so it's re-fetched
  // on next open. Do NOT close the panel — if it's open and a new generation
  // completes, the user should stay in context and see the refreshed list.
  useEffect(() => {
    // 底层资源切换时重置版本列表与加载状态，等下次打开面板时重新拉取
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setVersions([]);
    setCurrentVersion(0);
    setLoading(false);
    setLoadedOnce(false);
    setSelectedVersion(null);
    setRestoringVersion(null);
    setDeleteTarget(null);
    setDeletingVersion(null);
    setPreviewImage(null);
  }, [resourceFp, projectName, resourceId, resourceType]);

  // Fetch versions once when panel first opens
  useEffect(() => {
    if (!open || loadedOnce || !resourceId) return;
    void loadVersions();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- loadVersions 是组件内普通函数，无法稳定化；加入 deps 会导致每次渲染重复触发
  }, [open, loadedOnce, resourceId]);

  async function loadVersions(): Promise<{ ok: boolean; message?: string }> {
    setLoading(true);
    try {
      const data = await API.getVersions(projectName, resourceType, resourceId);
      setVersions(data.versions);
      setCurrentVersion(data.current_version);
      setLoadedOnce(true);
      return { ok: true };
    } catch (err) {
      setVersions([]);
      return { ok: false, message: errMsg(err) };
    } finally {
      setLoading(false);
    }
  }

  async function handleRestore(version: number) {
    setRestoringVersion(version);
    try {
      const result = await API.restoreVersion(projectName, resourceType, resourceId, version);
      if (result.asset_fingerprints) {
        useProjectsStore.getState().updateAssetFingerprints(result.asset_fingerprints);
      }
      await onRestore?.(version);
      await loadVersions();
      setSelectedVersion(version);
      useAppStore.getState().pushToast(t("switched_to_version", { version }), "success");
    } catch (err) {
      useAppStore
        .getState()
        .pushToast(t("switch_version_failed", { message: errMsg(err) }), "error");
    } finally {
      setRestoringVersion(null);
    }
  }

  function requestDeleteVersion(versionInfo: VersionInfo) {
    if (versionInfo.is_current || versionInfo.version === currentVersion) {
      useAppStore.getState().pushToast(t("version_delete_current_blocked"), "warning");
      return;
    }
    if (versions.length <= 1) {
      useAppStore.getState().pushToast(t("version_delete_last_blocked"), "warning");
      return;
    }
    setDeleteTarget(versionInfo);
  }

  async function handleDeleteVersion() {
    if (!deleteTarget) return;
    setDeletingVersion(deleteTarget.version);
    try {
      const result = await API.deleteVersion(
        projectName,
        resourceType,
        resourceId,
        deleteTarget.version,
      );
      if (result.asset_fingerprints) {
        useProjectsStore.getState().updateAssetFingerprints(result.asset_fingerprints);
      }
      const deletedVersion = deleteTarget.version;
      const failedFileCount = Math.max(
        result.failed_files?.length ?? 0,
        result.file_delete_errors?.length ?? 0,
      );
      setDeleteTarget(null);
      setSelectedVersion((prev) => (prev === deletedVersion ? null : prev));
      if (failedFileCount > 0) {
        useAppStore
          .getState()
          .pushToast(t("delete_files_partial_failed", { count: failedFileCount }), "warning");
      } else {
        useAppStore
          .getState()
          .pushToast(t("version_deleted", { version: deletedVersion }), "success");
      }
      const reloadResult = await loadVersions();
      if (!reloadResult.ok) {
        useAppStore
          .getState()
          .pushToast(t("load_failed", { message: reloadResult.message ?? "" }), "error");
      }
    } catch (err) {
      const message = errMsg(err);
      const isCurrentBlocked = message.includes("当前版本") || message.includes("应用");
      const isLastBlocked = message.includes("保留至少一个版本");
      useAppStore
        .getState()
        .pushToast(
          isCurrentBlocked
            ? t("version_delete_current_blocked")
            : isLastBlocked
              ? t("version_delete_last_blocked")
              : t("version_delete_failed", { message }),
          isCurrentBlocked || isLastBlocked ? "warning" : "error",
        );
    } finally {
      setDeletingVersion(null);
    }
  }

  // Close the panel
  const close = useCallback(() => {
    setOpen(false);
    setDeleteTarget(null);
    setPreviewImage(null);
  }, []);

  // Compute ideal top position given the trigger rect and panel height
  const computeTop = useCallback(
    (triggerRect: DOMRect, panelHeight: number) => {
      const GAP = 8;
      return triggerRect.bottom + GAP + panelHeight > window.innerHeight
        ? Math.max(GAP, triggerRect.top - GAP - panelHeight)
        : triggerRect.bottom + GAP;
    },
    [],
  );

  // Re-position panel after it mounts or resizes
  const panelCallbackRef = useCallback(
    (node: HTMLDivElement | null) => {
      panelRef.current = node;
      if (!node || !triggerRef.current) return;
      const rect = triggerRef.current.getBoundingClientRect();
      const top = computeTop(rect, node.offsetHeight);
      setPanelPos((prev) =>
        prev && Math.abs(prev.top - top) > 1 ? { ...prev, top } : prev,
      );
    },
    [computeTop],
  );

  // Position panel & register dismiss listeners
  useEffect(() => {
    if (!open || !triggerRef.current) {
      setPanelPos(null);
      return;
    }
    const rect = triggerRef.current.getBoundingClientRect();
    // Use estimated height for initial placement; panelCallbackRef corrects after mount
    const top = computeTop(rect, 320);
    setPanelPos({ top, left: rect.right });

    // Close on scroll (any scrollable ancestor)
    const scrollParents = getScrollParents(triggerRef.current);
    for (const sp of scrollParents) {
      sp.addEventListener("scroll", close, { passive: true, once: true });
    }

    // Close on click outside
    function onMouseDown(e: MouseEvent) {
      const target = e.target;
      if (!(target instanceof Node)) return;
      if (
        panelRef.current?.contains(target) ||
        triggerRef.current?.contains(target)
      )
        return;
      if (target instanceof Element && target.closest('[role="dialog"]')) return;
      close();
    }
    document.addEventListener("mousedown", onMouseDown);

    return () => {
      for (const sp of scrollParents) sp.removeEventListener("scroll", close);
      document.removeEventListener("mousedown", onMouseDown);
    };
  }, [open, close, computeTop]);

  if (!resourceId) return null;

  // Derive the selected version's full info from the latest `versions` array
  const selectedInfo =
    selectedVersion != null
      ? versions.find((v) => v.version === selectedVersion) ?? null
      : null;
  const selectedMetaBadges = selectedInfo ? versionMetaBadges(t, selectedInfo) : [];

  return (
    <div>
      {iconOnly ? (
        <button
          ref={triggerRef}
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          title={t("version_mgmt")}
          aria-label={t("version_mgmt")}
          aria-haspopup="dialog"
          aria-expanded={open}
          className="focus-ring relative inline-flex h-7 min-w-7 items-center justify-center rounded-md px-1.5 transition-colors hover:bg-[oklch(1_0_0_/_0.05)]"
          style={{ color: "var(--color-text-3)" }}
        >
          <History className="h-3.5 w-3.5" />
          {currentVersionLabel ? (
            <span className="absolute -right-1 -top-1 text-[9px] font-mono leading-4 text-text-4">
              {currentVersionLabel}
            </span>
          ) : null}
        </button>
      ) : (
        <button
          ref={triggerRef}
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          aria-haspopup="dialog"
          aria-expanded={open}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-gray-400 transition-colors hover:bg-gray-800 hover:text-gray-200"
        >
          <History className="h-3 w-3" />
          <span>
            {t("version_mgmt")}
            {currentVersionLabel ? ` ${currentVersionLabel}` : ""}
          </span>
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </button>
      )}

      {open &&
        panelPos &&
        createPortal(
          <div
            ref={panelCallbackRef}
            style={{
              position: "fixed",
              top: panelPos.top,
              left: panelPos.left,
              transform: "translateX(-100%)",
            }}
            className="z-[9999] w-64 rounded-xl border border-gray-700 bg-gray-900/95 p-3 shadow-2xl shadow-black/40 backdrop-blur"
          >
            {loading ? (
              <span className="text-xs text-gray-500">{t("common:loading")}</span>
            ) : versions.length === 0 ? (
              <div className="space-y-1">
                <p className="text-[11px] font-medium text-gray-300">{t("no_history")}</p>
                <p className="text-[11px] leading-5 text-gray-500">
                  {t("history_hint")}
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {/* Header */}
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">
                    {t("history_versions")}
                  </span>
                  {currentVersion > 0 && (
                    <span className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-[10px] font-medium text-indigo-200">
                      {t("current_version", { version: currentVersion })}
                    </span>
                  )}
                </div>

                {/* Version pills */}
                <div className="flex flex-wrap gap-1.5">
                  {versions.map((v) => {
                    const isCurrent = v.is_current;
                    const isSelected = selectedVersion === v.version;
                    return (
                      <button
                        key={v.version}
                        type="button"
                        onClick={() =>
                          setSelectedVersion((prev) =>
                            prev === v.version ? null : v.version,
                          )
                        }
                        className={
                          "rounded-full px-2.5 py-1 text-[10px] font-medium transition-colors " +
                          (isSelected
                            ? "bg-indigo-600 text-white ring-1 ring-indigo-400"
                            : isCurrent
                              ? "bg-indigo-500/15 text-indigo-300 ring-1 ring-indigo-500/30"
                              : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white")
                        }
                      >
                        v{v.version}
                      </button>
                    );
                  })}
                </div>

                {!selectedInfo && (
                  <p className="text-[10px] leading-4 text-gray-400">
                    {t("version_click_hint")}
                  </p>
                )}

                {/* Preview area */}
                {selectedInfo && (
                  <div className="rounded-xl border border-gray-700 bg-gray-950/80 p-2.5">
                    {selectedMetaBadges.length > 0 && (
                      <div className="mb-2 flex flex-wrap gap-1.5">
                        {selectedMetaBadges.map((badge) => (
                          <span
                            key={badge}
                            className="max-w-full truncate rounded-full border border-gray-700 bg-gray-800/75 px-2 py-0.5 text-[10px] font-medium text-gray-300"
                            title={badge}
                          >
                            {badge}
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span className="text-[11px] font-medium text-gray-200">
                        v{selectedInfo.version}
                        <span className="ml-1.5 text-[10px] font-normal text-gray-500">
                          {selectedInfo.created_at}
                        </span>
                      </span>
                      <div className="flex shrink-0 items-center gap-1">
                        {selectedInfo.is_current ? (
                          <span className="rounded-full bg-indigo-500/10 px-2 py-0.5 text-[10px] font-medium text-indigo-300">
                            {t("current_version_badge")}
                          </span>
                        ) : (
                          <button
                            type="button"
                            disabled={restoringVersion !== null || deletingVersion !== null}
                            onClick={() => void handleRestore(selectedInfo.version)}
                            className="rounded-full bg-indigo-600 px-2.5 py-0.5 text-[10px] font-medium text-white transition-colors hover:bg-indigo-500 disabled:opacity-50"
                          >
                            {restoringVersion === selectedInfo.version ? t("switching_version") : t("switch_to_version")}
                          </button>
                        )}
                        {allowDelete && !selectedInfo.is_current && (
                          <button
                            type="button"
                            disabled={restoringVersion !== null || deletingVersion !== null}
                            onClick={() => requestDeleteVersion(selectedInfo)}
                            title={t("delete_version")}
                            aria-label={t("delete_version")}
                            className="focus-ring inline-flex h-5 w-5 items-center justify-center rounded-full text-gray-500 transition-colors hover:bg-red-500/15 hover:text-red-300 disabled:opacity-50"
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Media preview */}
                    {selectedInfo.file_url &&
                      (resourceType === "videos" ? (
                        // eslint-disable-next-line jsx-a11y/media-has-caption -- 生成式预览视频暂无字幕源，将来如引入字幕生成则移除此 disable
                        <video
                          src={selectedInfo.file_url}
                          className="mb-2 w-full rounded-lg border border-gray-800 bg-black object-contain"
                          controls
                          playsInline
                          preload="none"
                        />
                      ) : (
                        <button
                          type="button"
                          onClick={() =>
                            setPreviewImage({
                              src: selectedInfo.file_url!,
                              alt: t("version_preview_alt", {
                                version: selectedInfo.version,
                              }),
                              path: selectedInfo.file,
                            })
                          }
                          aria-label={`${t("version_preview_alt", { version: selectedInfo.version })} 全屏预览`}
                          className={`mb-2 flex w-full items-center justify-center rounded-lg border border-gray-800 bg-gray-900/70 p-2 ${getImagePreviewHeightClass(resourceType)}`}
                        >
                          <img
                            src={selectedInfo.file_url}
                            alt={t("version_preview_alt", { version: selectedInfo.version })}
                            className="max-h-full w-full object-contain"
                          />
                        </button>
                      ))}

                    {/* Prompt text */}
                    <p className="line-clamp-4 text-[11px] leading-5 text-gray-400">
                      {selectedInfo.prompt || t("version_no_notes")}
                    </p>


                  </div>
                )}

              </div>
            )}
          </div>,
          document.body,
        )}
      {previewImage && (
        <ImageLightbox
          src={previewImage.src}
          alt={previewImage.alt}
          downloadSource={
            previewImage.path
              ? { kind: "project", projectName, path: previewImage.path }
              : undefined
          }
          onClose={() => setPreviewImage(null)}
        />
      )}
      <ConfirmDialog
        open={deleteTarget !== null}
        title={t("confirm_delete_version_title")}
        description={
          deleteTarget
            ? t("confirm_delete_version_desc", { version: deleteTarget.version })
            : undefined
        }
        confirmLabel={t("delete_version")}
        loadingLabel={t("deleting_version")}
        tone="danger"
        loading={deletingVersion !== null}
        onConfirm={handleDeleteVersion}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

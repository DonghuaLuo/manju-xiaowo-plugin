import { useEffect, useState } from "react";
import { PluginSDK } from "xiaowo-sdk";
import { Sparkles, Download, ImageIcon, Film, Loader2, Maximize2, Star, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API, type VersionInfo, type VersionResourceType } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { AspectFrame } from "@/components/ui/AspectFrame";
import { ImageFlipReveal } from "@/components/ui/ImageFlipReveal";
import { PreviewableImageFrame } from "@/components/ui/PreviewableImageFrame";
import { SelectMenu } from "@/components/ui/SelectMenu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/Tooltip";
import { VideoLightbox } from "@/components/ui/VideoLightbox";
import { formatCost } from "@/utils/cost-format";
import { errMsg } from "@/utils/async";
import { pickDesktopFile } from "@/utils/desktop-file";
import { downloadProjectVideoWithDialog } from "@/utils/video-export";
import type { CostBreakdown, GenerationQuality } from "@/types";
import { VersionTimeMachine } from "./VersionTimeMachine";

type MediaKind = "storyboard" | "video";
type ArrayItem<T> = T extends Array<infer Item> ? Item : T;
type ProviderInputImageItem = NonNullable<
  ArrayItem<NonNullable<VersionInfo["provider_input_images"]>[string]>
>;
type QualityRatingState = {
  version: number;
  rating: number | null;
  dimensions: Record<string, number>;
};

interface MediaCardProps {
  kind: MediaKind;
  projectName: string;
  segmentId: string;
  /** 资产相对路径，如 storyboards/E1S2_v1.png */
  assetPath: string | null;
  /** 当前剧集脚本文件名，用于外部上传后回写 generated_assets */
  scriptFile?: string;
  /** 视频海报缩略图（仅 kind=video 用） */
  posterPath?: string | null;
  /** 渲染比例 */
  aspectRatio: "9:16" | "16:9";
  /** 是否在 grid 模式下隐藏单独生成按钮 */
  hideGenerateButton?: boolean;
  /** 生成按钮是否禁用（视频生成需要先有分镜图） */
  generateDisabled?: boolean;
  /** 外部上传按钮是否禁用（通常仅在当前提示词有未保存编辑时禁用） */
  uploadDisabled?: boolean;
  /** 自定义禁用 tooltip，未提供时使用默认（"分镜图未生成"）的视频禁用提示 */
  generateDisabledHint?: string;
  /** 进行中状态 */
  generating?: boolean;
  /** 估算费用（按币种 breakdown，例如 {USD: 0.12} 或 {CNY: 5.25}） */
  estimatedCost?: CostBreakdown;
  /** 触发生成 */
  onGenerate?: (quality: GenerationQuality) => void;
  /** 版本恢复回调 */
  onRestore?: () => Promise<void> | void;
  /** 外部上传成新版本后的回调 */
  onUploaded?: () => Promise<void> | void;
}

function qualityLabel(t: (key: string, options?: Record<string, unknown>) => string, quality?: VersionInfo["generation_quality"]): string | null {
  if (quality === "draft") return t("episode_status_label_draft");
  if (quality === "final") return t("media_generate_video_final");
  if (quality === "custom") return "Custom";
  return null;
}

function providerInputImageItems(info: VersionInfo | null): ProviderInputImageItem[] {
  const inputImages = info?.provider_input_images;
  if (!inputImages) return [];
  return Object.values(inputImages).flatMap((item) => {
    if (!item) return [];
    return Array.isArray(item) ? item.filter(Boolean) : [item];
  });
}

function providerInputStatusLabel(
  t: (key: string, options?: Record<string, unknown>) => string,
  info: VersionInfo | null,
): string | null {
  const items = providerInputImageItems(info);
  if (items.length === 0) return null;
  const optimized = items.some(
    (item) =>
      item.resized ||
      item.transcoded ||
      (
        typeof item.source_bytes === "number" &&
        typeof item.input_bytes === "number" &&
        item.input_bytes < item.source_bytes
      ),
  );
  return optimized
    ? t("media_input_optimized", { defaultValue: "已优化输入图" })
    : t("media_input_checked", { defaultValue: "输入图已校验" });
}

function sourceStoryboardLabel(
  t: (key: string, options?: Record<string, unknown>) => string,
  kind: MediaKind,
  info: VersionInfo | null,
): string | null {
  if (kind !== "video") return null;
  const quality = info?.source_storyboard_generation_quality;
  if (quality === "final") {
    return t("media_based_on_final_storyboard", { defaultValue: "基于最终分镜" });
  }
  if (quality === "draft") {
    return t("media_based_on_draft_storyboard", { defaultValue: "基于草稿分镜" });
  }
  if (quality === "custom") {
    return t("media_based_on_custom_storyboard", { defaultValue: "基于自定义分镜" });
  }
  if (quality === "grid") {
    return t("media_based_on_grid_storyboard", { defaultValue: "基于宫格镜头板" });
  }
  return null;
}

function currentVersionBadges(
  t: (key: string, options?: Record<string, unknown>) => string,
  kind: MediaKind,
  info: VersionInfo | null,
): string[] {
  const route = info?.generation_route;
  return [
    qualityLabel(t, info?.generation_quality),
    route?.resolution,
    route?.duration_seconds != null ? `${route.duration_seconds}s` : null,
    route?.provider && route.model ? `${route.provider}/${route.model}` : null,
    route?.generate_audio === true ? t("generate_audio_label") : null,
    providerInputStatusLabel(t, info),
    sourceStoryboardLabel(t, kind, info),
  ].filter((badge): badge is string => Boolean(badge));
}

function qualityDimensionsForKind(kind: MediaKind): Array<{ key: string; label: string }> {
  return kind === "video"
    ? [
        { key: "character_consistency", label: "角色一致" },
        { key: "motion_naturalness", label: "动作自然" },
        { key: "prompt_faithfulness", label: "贴合提示" },
      ]
    : [
        { key: "character_consistency", label: "角色一致" },
        { key: "composition", label: "构图" },
        { key: "prompt_faithfulness", label: "贴合提示" },
      ];
}

export function MediaCard({
  kind,
  projectName,
  segmentId,
  assetPath,
  scriptFile,
  posterPath,
  aspectRatio,
  hideGenerateButton,
  generateDisabled,
  uploadDisabled,
  generateDisabledHint,
  generating,
  estimatedCost,
  onGenerate,
  onRestore,
  onUploaded,
}: MediaCardProps) {
  const { t } = useTranslation(["dashboard", "common"]);
  const [videoLightboxOpen, setVideoLightboxOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [currentVersionInfo, setCurrentVersionInfo] = useState<VersionInfo | null>(null);
  const [qualityRatingInfo, setQualityRatingInfo] = useState<QualityRatingState | null>(null);
  const [ratingSaving, setRatingSaving] = useState(false);

  const assetFp = useProjectsStore((s) =>
    assetPath ? s.getAssetFingerprint(assetPath) : null,
  );
  const posterFp = useProjectsStore((s) =>
    posterPath ? s.getAssetFingerprint(posterPath) : null,
  );
  const assetUrl = assetPath ? API.getFileUrl(projectName, assetPath, assetFp) : null;
  const posterUrl = posterPath
    ? API.getFileUrl(projectName, posterPath, posterFp)
    : null;

  const Icon = kind === "storyboard" ? ImageIcon : Film;
  const title =
    kind === "storyboard" ? t("media_storyboard_title") : t("media_video_title");
  const draftGenerateLabel =
    kind === "storyboard"
      ? assetPath
        ? t("media_regenerate_storyboard_draft", {
            defaultValue: t("media_regenerate_storyboard"),
          })
        : t("media_generate_storyboard_draft", {
            defaultValue: t("media_generate_storyboard"),
          })
      : assetPath
        ? t("media_regenerate_video_draft", {
            defaultValue: t("media_regenerate_video"),
          })
        : t("media_generate_video_draft", {
            defaultValue: t("media_generate_video"),
          });
  const finalGenerateLabel =
    kind === "storyboard"
      ? t("media_generate_storyboard_final", { defaultValue: "最终版" })
      : t("media_generate_video_final", { defaultValue: "最终版" });
  const resourceType: VersionResourceType =
    kind === "storyboard" ? "storyboards" : "videos";
  const previewTitle = `${segmentId} ${title}`;
  const effectiveVersionInfo = assetPath ? currentVersionInfo : null;
  const currentVersionNumber = effectiveVersionInfo?.version ?? null;
  const effectiveQualityRating =
    qualityRatingInfo?.version === currentVersionNumber ? qualityRatingInfo.rating : null;
  const effectiveQualityDimensions =
    qualityRatingInfo?.version === currentVersionNumber ? qualityRatingInfo.dimensions : {};
  const metaBadges = currentVersionBadges(t, kind, effectiveVersionInfo);
  const qualityDimensions = qualityDimensionsForKind(kind);
  const dimensionHint = t("media_quality_dimension_hint", {
    defaultValue: "可选细项，不选不参与维度统计。",
  });
  const dimensionNeedsRatingHint = t("media_quality_dimension_needs_rating", {
    defaultValue: "请先设置总星级，再评价细项。",
  });

  useEffect(() => {
    if (!assetPath) {
      return;
    }
    let cancelled = false;
    API.getVersions(projectName, resourceType, segmentId)
      .then((data) => {
        if (cancelled) return;
        const current =
          data.versions.find((item) => item.is_current) ??
          data.versions.find((item) => item.version === data.current_version) ??
          data.versions.at(-1) ??
          null;
        setCurrentVersionInfo(current);
      })
      .catch(() => {
        if (!cancelled) setCurrentVersionInfo(null);
      });
    return () => {
      cancelled = true;
    };
  }, [assetFp, assetPath, projectName, resourceType, segmentId]);

  useEffect(() => {
    if (!assetPath || currentVersionNumber == null) {
      return;
    }
    let cancelled = false;
    API.getQualityRatings(projectName, {
      resourceType,
      resourceId: segmentId,
      version: currentVersionNumber,
    })
      .then((data) => {
        if (cancelled) return;
        const latest = data.ratings.at(-1);
        const rating = typeof latest?.rating === "number" ? latest.rating : null;
        const rawDimensions = latest?.dimensions;
        const dimensions =
          rawDimensions && typeof rawDimensions === "object" && !Array.isArray(rawDimensions)
            ? Object.fromEntries(
                Object.entries(rawDimensions).filter(([, value]) => typeof value === "number"),
              ) as Record<string, number>
            : {};
        setQualityRatingInfo({ version: currentVersionNumber, rating, dimensions });
      })
      .catch(() => {
        if (!cancelled) setQualityRatingInfo({ version: currentVersionNumber, rating: null, dimensions: {} });
      });
    return () => {
      cancelled = true;
    };
  }, [assetPath, currentVersionNumber, projectName, resourceType, segmentId]);

  const openVideoLightbox = async () => {
    try {
      await PluginSDK.maximize();
    } catch (error) {
      console.warn("Failed to maximize plugin window before video preview", error);
    }
    setVideoLightboxOpen(true);
  };

  const handleVideoDownload = async () => {
    if (downloading || kind !== "video" || !assetPath || !assetUrl) return;
    setDownloading(true);
    try {
      const savedPath = await downloadProjectVideoWithDialog(
        projectName,
        assetPath,
        `${segmentId} ${title}.mp4`,
      );
      if (savedPath) {
        useAppStore.getState().pushToast("视频已保存", "success");
      }
    } catch (err) {
      useAppStore.getState().pushToast(errMsg(err), "error");
    } finally {
      setDownloading(false);
    }
  };

  const handleExternalUpload = async () => {
    if (uploading) return;
    if (!scriptFile) {
      useAppStore.getState().pushToast("缺少剧本文件，无法上传外部生成结果", "error");
      return;
    }
    const file = await pickDesktopFile({
      title: kind === "storyboard" ? "上传外部分镜图" : "上传外部视频",
      filters:
        kind === "storyboard"
          ? [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp"] }]
          : [{ name: "MP4 Video", extensions: ["mp4"] }],
      preview: false,
    });
    if (!file) return;

    setUploading(true);
    try {
      const result = await API.uploadExternalMediaVersion(
        projectName,
        resourceType,
        segmentId,
        file,
        { scriptFile },
      );
      if (result.asset_fingerprints) {
        useProjectsStore.getState().updateAssetFingerprints(result.asset_fingerprints);
      }
      await onUploaded?.();
      useAppStore
        .getState()
        .pushToast(`已作为 v${result.version} 接入当前${title}`, "success");
    } catch (err) {
      useAppStore.getState().pushToast(errMsg(err), "error");
    } finally {
      setUploading(false);
    }
  };

  const saveQualityRating = async (rating: number, dimensions: Record<string, number>) => {
    if (!effectiveVersionInfo || ratingSaving) return;
    setRatingSaving(true);
    try {
      await API.upsertQualityRating(projectName, {
        resource_type: resourceType,
        resource_id: segmentId,
        version: effectiveVersionInfo.version,
        rating,
        dimensions,
        provider: effectiveVersionInfo.generation_route?.provider ?? null,
        model: effectiveVersionInfo.generation_route?.model ?? null,
        generation_quality: effectiveVersionInfo.generation_quality ?? null,
        shot_tier: effectiveVersionInfo.shot_tier ?? effectiveVersionInfo.generation_route?.shot_tier ?? null,
      });
      setQualityRatingInfo({ version: effectiveVersionInfo.version, rating, dimensions });
      useAppStore
        .getState()
        .pushToast(t("media_quality_rating_saved", { defaultValue: "质量评分已保存" }), "success");
    } catch (err) {
      useAppStore.getState().pushToast(errMsg(err), "error");
    } finally {
      setRatingSaving(false);
    }
  };

  const handleQualityRating = async (rating: number) => {
    await saveQualityRating(rating, effectiveQualityDimensions);
  };

  const handleDimensionRating = async (key: string, value: number | null) => {
    if (effectiveQualityRating == null) {
      useAppStore.getState().pushToast(dimensionNeedsRatingHint, "info");
      return;
    }
    const nextDimensions = { ...effectiveQualityDimensions };
    if (value == null) {
      delete nextDimensions[key];
    } else {
      nextDimensions[key] = value;
    }
    await saveQualityRating(effectiveQualityRating, nextDimensions);
  };

  return (
    <div>
      {/* Header */}
      <div className="mb-2 flex items-center gap-1.5">
        <Icon className="h-3.5 w-3.5" style={{ color: "var(--color-text-3)" }} />
        <span
          className="text-[12px] font-semibold"
          style={{ color: "var(--color-text-2)" }}
        >
          {title}
        </span>
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => void handleExternalUpload()}
          disabled={uploading || uploadDisabled}
          title={uploadDisabled ? generateDisabledHint : kind === "storyboard" ? "上传外部分镜图为新版本" : "上传外部视频为新版本"}
          aria-label={kind === "storyboard" ? "上传外部分镜图为新版本" : "上传外部视频为新版本"}
          className="focus-ring inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors hover:bg-[oklch(1_0_0_/_0.05)] disabled:cursor-not-allowed disabled:opacity-50"
          style={{ color: "var(--color-text-3)" }}
        >
          {uploading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Upload className="h-3.5 w-3.5" />
          )}
        </button>
        <VersionTimeMachine
          projectName={projectName}
          resourceType={resourceType}
          resourceId={segmentId}
          onRestore={onRestore}
        />
      </div>

      {/* Media */}
      {assetUrl ? (
        kind === "storyboard" ? (
          <PreviewableImageFrame
            src={assetUrl}
            alt={`${segmentId} ${title}`}
            downloadSource={
              assetPath ? { kind: "project", projectName, path: assetPath } : undefined
            }
          >
            <AspectFrame ratio={aspectRatio} className="relative">
              <ImageFlipReveal
                src={assetUrl}
                alt={`${segmentId} ${title}`}
                loading="lazy"
                className="h-full w-full object-cover"
                fallback={null}
              />
            </AspectFrame>
          </PreviewableImageFrame>
        ) : (
          <div
            className="group overflow-hidden rounded-[10px]"
            style={{
              boxShadow:
                "0 16px 40px -16px oklch(0 0 0 / 0.7), 0 0 0 1px var(--color-hairline)",
            }}
          >
            <AspectFrame ratio={aspectRatio} className="relative">
              {/* eslint-disable-next-line jsx-a11y/media-has-caption -- 生成式预览视频暂无字幕源 */}
              <video
                src={assetUrl}
                poster={posterUrl ?? undefined}
                controls
                controlsList="nofullscreen nodownload noremoteplayback"
                disablePictureInPicture
                playsInline
                // object-contain：卡片内容器比例一致时铺满，全屏到 16:9 屏幕时
                // 9:16 视频会带左右黑边，避免被裁剪。
                className="h-full w-full object-contain"
                preload="metadata"
              />
              <div className="absolute right-2 top-2 flex items-center gap-1.5 opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100 motion-reduce:transition-none">
                <button
                  type="button"
                  onClick={() => void handleVideoDownload()}
                  disabled={downloading}
                  aria-label="下载视频"
                  title="下载视频"
                  className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-white/10 bg-black/50 text-white/90 shadow-lg shadow-black/25 backdrop-blur transition-colors hover:bg-black/70 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/35"
                >
                  {downloading ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Download className="h-3.5 w-3.5" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => void openVideoLightbox()}
                  aria-label={t("common:titlebar.maximize")}
                  title={t("common:titlebar.maximize")}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-white/10 bg-black/50 text-white/90 shadow-lg shadow-black/25 backdrop-blur transition-colors hover:bg-black/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/35"
                >
                  <Maximize2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </AspectFrame>
          </div>
        )
      ) : (
        <AspectFrame ratio={aspectRatio}>
          <div
            className="flex h-full w-full flex-col items-center justify-center gap-2 rounded-[10px]"
            style={{
              border: "1px dashed var(--color-hairline)",
              background: "oklch(0.18 0.010 265 / 0.4)",
              color: "var(--color-text-4)",
            }}
          >
            <Icon className="h-5 w-5" />
            <span className="text-[11.5px]">{t("media_not_generated")}</span>
          </div>
        </AspectFrame>
      )}

      {metaBadges.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {metaBadges.map((badge) => (
            <span
              key={badge}
              className="max-w-full truncate rounded-full border px-2 py-0.5 text-[10px] font-medium"
              title={badge}
              style={{
                borderColor: "var(--color-hairline-soft)",
                background: "oklch(1 0 0 / 0.045)",
                color: "var(--color-text-3)",
              }}
            >
              {badge}
            </span>
          ))}
        </div>
      )}

      {assetPath && effectiveVersionInfo && (
        <div className="mt-2 space-y-1.5">
          <div className="flex items-center gap-1.5">
            {[1, 2, 3, 4, 5].map((rating) => {
              const active = effectiveQualityRating != null && rating <= effectiveQualityRating;
              return (
                <button
                  key={rating}
                  type="button"
                  onClick={() => void handleQualityRating(rating)}
                  disabled={ratingSaving}
                  className="focus-ring inline-flex h-6 w-6 items-center justify-center rounded-md text-text-4 transition-colors hover:bg-[oklch(1_0_0_/_0.06)] disabled:cursor-wait disabled:opacity-60"
                  aria-label={t("media_quality_rating_aria", {
                    defaultValue: "设置质量评分 {{rating}} 星",
                    rating,
                  })}
                  title={t("media_quality_rating_aria", {
                    defaultValue: "设置质量评分 {{rating}} 星",
                    rating,
                  })}
                >
                  <Star
                    className="h-3.5 w-3.5"
                    fill={active ? "currentColor" : "none"}
                    style={{ color: active ? "var(--color-accent-2)" : "var(--color-text-4)" }}
                  />
                </button>
              );
            })}
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            {qualityDimensions.map((dimension) => {
              const dimensionDisabled = ratingSaving || effectiveQualityRating == null;
              return (
                <label key={dimension.key} className="min-w-0">
                  <span className="mb-0.5 block truncate text-[10px] text-text-4">
                    {dimension.label}
                  </span>
                  <Tooltip>
                    <TooltipTrigger className="w-full">
                      <SelectMenu
                        value={String(effectiveQualityDimensions[dimension.key] ?? "")}
                        options={[
                          { value: "", label: "-" },
                          ...[1, 2, 3, 4, 5].map((score) => ({
                            value: String(score),
                            label: String(score),
                          })),
                        ]}
                        onChange={(raw) => {
                          void handleDimensionRating(dimension.key, raw ? Number(raw) : null);
                        }}
                        disabled={dimensionDisabled}
                        ariaLabel={dimension.label}
                        triggerSize="micro"
                        minPanelWidth={64}
                        className="h-6 w-full px-1.5 py-0 text-[10.5px]"
                      />
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      {effectiveQualityRating == null ? dimensionNeedsRatingHint : dimensionHint}
                    </TooltipContent>
                  </Tooltip>
                </label>
              );
            })}
          </div>
        </div>
      )}

      {/* Generate CTA */}
      {!hideGenerateButton && onGenerate && (
        <div className="mt-2.5 grid grid-cols-[minmax(0,1fr)_auto] gap-2">
          <button
            type="button"
            onClick={() => onGenerate("draft")}
            disabled={generateDisabled || generating}
            title={
              generateDisabled
                ? (generateDisabledHint ?? t("media_generate_video_disabled_hint"))
                : undefined
            }
            className="focus-ring inline-flex min-w-0 items-center justify-center gap-1.5 rounded-[10px] px-3.5 py-2.5 text-[13px] font-semibold transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              color: "oklch(0.14 0 0)",
              background: "linear-gradient(180deg, var(--color-accent-2), var(--color-accent))",
              boxShadow:
                "inset 0 1px 0 oklch(1 0 0 / 0.3), 0 4px 14px -4px var(--color-accent-glow)",
            }}
          >
            <Sparkles className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{draftGenerateLabel}</span>
            {estimatedCost && Object.values(estimatedCost).some((v) => v > 0) && (
              <span className="num ml-1 shrink-0 text-[11px] opacity-70">
                ~{formatCost(estimatedCost)}
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={() => onGenerate("final")}
            disabled={generateDisabled || generating}
            title={
              generateDisabled
                ? (generateDisabledHint ?? t("media_generate_video_disabled_hint"))
                : finalGenerateLabel
            }
            className="focus-ring inline-flex h-full items-center justify-center rounded-[10px] border px-3 text-[12px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              borderColor: "var(--color-hairline)",
              color: "var(--color-text-2)",
              background: "oklch(1 0 0 / 0.045)",
            }}
          >
            {finalGenerateLabel}
          </button>
        </div>
      )}
      {videoLightboxOpen && assetUrl && kind === "video" && (
        <VideoLightbox
          src={assetUrl}
          poster={posterUrl}
          title={previewTitle}
          downloading={downloading}
          onDownload={handleVideoDownload}
          onClose={() => setVideoLightboxOpen(false)}
        />
      )}
    </div>
  );
}

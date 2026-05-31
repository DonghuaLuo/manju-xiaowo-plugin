import { useState } from "react";
import { PluginSDK } from "xiaowo-sdk";
import { Sparkles, Download, ImageIcon, Film, Loader2, Maximize2, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { AspectFrame } from "@/components/ui/AspectFrame";
import { ImageFlipReveal } from "@/components/ui/ImageFlipReveal";
import { PreviewableImageFrame } from "@/components/ui/PreviewableImageFrame";
import { VideoLightbox } from "@/components/ui/VideoLightbox";
import { formatCost } from "@/utils/cost-format";
import { errMsg } from "@/utils/async";
import { pickDesktopFile } from "@/utils/desktop-file";
import { downloadProjectVideoWithDialog } from "@/utils/video-export";
import type { CostBreakdown } from "@/types";
import { VersionTimeMachine } from "./VersionTimeMachine";

type MediaKind = "storyboard" | "video";

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
  onGenerate?: () => void;
  /** 版本恢复回调 */
  onRestore?: () => Promise<void> | void;
  /** 外部上传成新版本后的回调 */
  onUploaded?: () => Promise<void> | void;
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
  const generateLabel =
    kind === "storyboard"
      ? assetPath
        ? t("media_regenerate_storyboard")
        : t("media_generate_storyboard")
      : assetPath
        ? t("media_regenerate_video")
        : t("media_generate_video");
  const resourceType: "storyboards" | "videos" =
    kind === "storyboard" ? "storyboards" : "videos";
  const previewTitle = `${segmentId} ${title}`;

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

      {/* Generate CTA */}
      {!hideGenerateButton && onGenerate && (
        <button
          type="button"
          onClick={onGenerate}
          disabled={generateDisabled || generating}
          title={
            generateDisabled
              ? (generateDisabledHint ?? t("media_generate_video_disabled_hint"))
              : undefined
          }
          className="mt-2.5 inline-flex w-full items-center justify-center gap-1.5 rounded-[10px] px-3.5 py-2.5 text-[13px] font-semibold transition-opacity focus-ring disabled:cursor-not-allowed disabled:opacity-50"
          style={{
            color: "oklch(0.14 0 0)",
            background: "linear-gradient(180deg, var(--color-accent-2), var(--color-accent))",
            boxShadow:
              "inset 0 1px 0 oklch(1 0 0 / 0.3), 0 4px 14px -4px var(--color-accent-glow)",
          }}
        >
          <Sparkles className="h-3.5 w-3.5" />
          <span>{generateLabel}</span>
          {estimatedCost && Object.values(estimatedCost).some((v) => v > 0) && (
            <span className="num ml-1 text-[11px] opacity-70">
              ~{formatCost(estimatedCost)}
            </span>
          )}
        </button>
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

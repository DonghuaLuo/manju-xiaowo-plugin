import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ImageIcon,
  Film,
  ChevronLeft,
  ChevronRight,
  Check,
  Copy,
  FolderDown,
  Loader2,
  Undo2,
} from "lucide-react";
import { API } from "@/api";
import type {
  NarrationSegment,
  DramaScene,
  ImagePrompt,
  VideoPrompt,
  Dialogue,
  GenerationQuality,
  ShotTier,
  ShotTierProfile,
  TransitionType,
  VideoContinuityPolicy,
} from "@/types";
import { useAppStore } from "@/stores/app-store";
import { ImagePromptEditor } from "./ImagePromptEditor";
import { VideoPromptEditor } from "./VideoPromptEditor";
import { DialogueListEditor } from "./DialogueListEditor";
import { ResponsiveDetailGrid } from "./ResponsiveDetailGrid";
import { MediaCard } from "./MediaCard";
import { NotesDrawer } from "./NotesDrawer";
import { ReferencesSection } from "./ReferencesSection";
import { StatusBadge, statusFromAssets } from "./StatusBadge";
import { Popover } from "@/components/ui/Popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/Tooltip";
import { useCostStore } from "@/stores/cost-store";
import {
  isStructuredImagePrompt,
  isStructuredVideoPrompt,
} from "@/utils/prompt-shape";
import { isContinuousIntegerRange } from "@/utils/duration_format";
import { copyText } from "@/utils/clipboard";
import { errMsg } from "@/utils/async";
import { pickDesktopDirectory } from "@/utils/desktop-file";
import { exportExternalGenerationPackage } from "@/utils/external-generation-export";
import { resolveExpectedShotVideoContinuity } from "@/utils/video-continuity";
import { normalizeShotTierProfiles } from "@/utils/generation-profiles";
import type { VideoContinuitySupport } from "@/utils/provider-models";

type Segment = NarrationSegment | DramaScene;
type ImagePromptValue = ImagePrompt | string;
type VideoPromptValue = VideoPrompt | string;

interface ShotDetailProps {
  segment: Segment;
  nextSegment?: Segment;
  segmentId: string;
  contentMode: "narration" | "drama";
  aspectRatio: "9:16" | "16:9";
  projectName: string;
  scriptFile?: string;
  isGridMode?: boolean;
  /** Total shot count for "1/N" indicator */
  selectedIndex: number;
  totalCount: number;
  onPrev: () => void;
  onNext: () => void;
  onUpdatePrompt?: (
    segmentId: string,
    fieldOrPatch: string | Record<string, unknown>,
    value?: unknown,
  ) => void | Promise<void>;
  onGenerateStoryboard?: (segmentId: string, quality?: GenerationQuality) => void;
  onGenerateVideo?: (segmentId: string, quality?: GenerationQuality) => void;
  onRestoreStoryboard?: () => Promise<void> | void;
  onRestoreVideo?: () => Promise<void> | void;
  generatingStoryboard?: boolean;
  generatingVideo?: boolean;
  durationOptions?: number[];
  videoContinuityPolicy?: VideoContinuityPolicy;
  videoContinuitySupport?: VideoContinuitySupport | null;
  shotTierProfiles?: Partial<Record<ShotTier, ShotTierProfile>>;
}

function getNovelText(seg: Segment, mode: "narration" | "drama"): string {
  if (mode === "narration") return (seg as NarrationSegment).novel_text || "";
  return "";
}

interface DraftState {
  image_prompt: ImagePromptValue;
  video_prompt: VideoPromptValue;
}

// 字段集合稳定（ImagePrompt/VideoPrompt/string），JSON.stringify 即可作等值签名：
// 任何字段顺序差异都来自我们自己的 setter 或上游同一构造路径，键序一致。
const stableSig = (value: unknown): string => JSON.stringify(value ?? null);

interface DurationPillProps {
  seconds: number;
  segmentId: string;
  durationOptions: number[];
  onUpdatePrompt?: ShotDetailProps["onUpdatePrompt"];
}

const SHOT_TIERS: ShotTier[] = ["S", "A", "B"];
const TRANSITION_TYPES: TransitionType[] = ["cut", "fade", "dissolve"];

function isShotTier(value: unknown): value is ShotTier {
  return value === "S" || value === "A" || value === "B";
}

function normalizeShotTier(value: unknown): ShotTier {
  return isShotTier(value) ? value : "A";
}

function ShotTierPill({
  tier,
  explicit,
  segmentId,
  onUpdatePrompt,
}: {
  tier: ShotTier;
  explicit: boolean;
  segmentId: string;
  onUpdatePrompt?: ShotDetailProps["onUpdatePrompt"];
}) {
  const { t } = useTranslation("dashboard");
  const editable = !!onUpdatePrompt;
  const label = t("shot_tier_label", { defaultValue: "镜头档位" });
  const tierHints: Record<ShotTier, string> = {
    S: t("shot_tier_hint_s", {
      defaultValue: "S 重点镜头：用于关键画面、主角特写或重要剧情点。",
    }),
    A: t("shot_tier_hint_a", {
      defaultValue: "A 标准镜头：默认档位，适合大多数普通分镜。",
    }),
    B: t("shot_tier_hint_b", {
      defaultValue: "B 辅助镜头：适合过渡、环境补充或次要镜头。",
    }),
  };

  if (!editable) {
    return (
      <span
        className="num inline-flex items-center rounded-md px-2 py-[3px] text-[11.5px] font-semibold"
        title={`${label} · ${tierHints[tier]}`}
        aria-label={`${label} · ${tierHints[tier]}`}
        style={{
          background: "oklch(0.22 0.011 265 / 0.6)",
          border: "1px solid var(--color-hairline-soft)",
          color: "var(--color-text-2)",
        }}
      >
        {tier}
      </span>
    );
  }

  return (
    <div
      className="inline-flex items-center rounded-md p-0.5"
      role="radiogroup"
      aria-label={label}
      style={{
        background: "oklch(0.22 0.011 265 / 0.6)",
        border: "1px solid var(--color-hairline-soft)",
      }}
    >
      {SHOT_TIERS.map((candidate) => {
        const active = candidate === tier;
        const hint = `${label} · ${tierHints[candidate]}`;
        return (
          <Tooltip key={candidate}>
            <TooltipTrigger>
              <button
                type="button"
                role="radio"
                aria-checked={active}
                aria-label={hint}
                onClick={() => {
                  if (!active || !explicit) void onUpdatePrompt?.(segmentId, "shot_tier", candidate);
                }}
                className="num rounded px-1.5 py-0.5 text-[11px] font-bold transition-colors focus-ring"
                style={{
                  minWidth: 22,
                  color: active ? "oklch(0.14 0 0)" : "var(--color-text-3)",
                  background: active
                    ? "linear-gradient(180deg, var(--color-accent-2), var(--color-accent))"
                    : "transparent",
                }}
              >
                {candidate}
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">{tierHints[candidate]}</TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}

function TransitionPill({
  value,
  segmentId,
  onUpdatePrompt,
}: {
  value: TransitionType | undefined;
  segmentId: string;
  onUpdatePrompt?: ShotDetailProps["onUpdatePrompt"];
}) {
  const { t } = useTranslation("dashboard");
  const editable = !!onUpdatePrompt;
  const transition = TRANSITION_TYPES.includes(value as TransitionType) ? value as TransitionType : "cut";
  const label = t("transition_to_next_label", { defaultValue: "转场" });
  const labels: Record<TransitionType, string> = {
    cut: t("transition_cut", { defaultValue: "硬切" }),
    fade: t("transition_fade", { defaultValue: "淡入淡出" }),
    dissolve: t("transition_dissolve", { defaultValue: "溶解" }),
  };
  const hints: Record<TransitionType, string> = {
    cut: t("transition_cut_hint", {
      defaultValue: "适合同一场景内的连续镜头，会优先保留首尾帧衔接机会。",
    }),
    fade: t("transition_fade_hint", {
      defaultValue: "适合跨场景或时间跳转，会让视频生成回退为仅首帧。",
    }),
    dissolve: t("transition_dissolve_hint", {
      defaultValue: "适合柔和过渡或回忆感镜头，会让视频生成回退为仅首帧。",
    }),
  };

  if (!editable) {
    return (
      <span
        className="inline-flex items-center rounded-md px-2 py-[3px] text-[11.5px] font-semibold"
        title={`${label} · ${hints[transition]}`}
        aria-label={`${label} · ${hints[transition]}`}
        style={{
          background: "oklch(0.22 0.011 265 / 0.6)",
          border: "1px solid var(--color-hairline-soft)",
          color: "var(--color-text-2)",
        }}
      >
        {labels[transition]}
      </span>
    );
  }

  return (
    <div
      className="inline-flex items-center gap-0.5 rounded-md p-0.5"
      role="radiogroup"
      aria-label={label}
      style={{
        background: "oklch(0.22 0.011 265 / 0.6)",
        border: "1px solid var(--color-hairline-soft)",
      }}
    >
      {TRANSITION_TYPES.map((candidate) => {
        const active = candidate === transition;
        return (
          <Tooltip key={candidate}>
            <TooltipTrigger>
              <button
                type="button"
                role="radio"
                aria-checked={active}
                aria-label={`${label} · ${labels[candidate]}`}
                onClick={() => {
                  if (!active) void onUpdatePrompt?.(segmentId, "transition_to_next", candidate);
                }}
                className="rounded px-2 py-0.5 text-[11px] font-semibold transition-colors focus-ring"
                style={{
                  minWidth: candidate === "cut" ? 34 : 46,
                  color: active ? "oklch(0.14 0 0)" : "var(--color-text-3)",
                  background: active
                    ? "linear-gradient(180deg, var(--color-accent-2), var(--color-accent))"
                    : "transparent",
                }}
              >
                {labels[candidate]}
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">{hints[candidate]}</TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}

function DurationPill({
  seconds,
  segmentId,
  durationOptions,
  onUpdatePrompt,
}: DurationPillProps) {
  const { t } = useTranslation("dashboard");
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLButtonElement>(null);

  // 拖动 slider 期间用本地 state 跟随；松手 / 失焦 / 键盘抬起时再提交一次
  // 避免 onChange 每像素一次 onUpdatePrompt 产生并发写请求 + 乱序落库
  const [draftSeconds, setDraftSeconds] = useState<number | null>(null);
  const displaySeconds = draftSeconds ?? seconds;
  const commitDraft = useCallback(() => {
    if (draftSeconds == null) return;
    if (draftSeconds !== seconds) {
      void onUpdatePrompt?.(segmentId, "duration_seconds", draftSeconds);
    }
    setDraftSeconds(null);
  }, [draftSeconds, seconds, segmentId, onUpdatePrompt]);

  const editable = !!onUpdatePrompt;
  const noOptions = durationOptions.length === 0;
  const isIncompatible =
    durationOptions.length > 0 && !durationOptions.includes(seconds);
  const incompatibleLabel = t("duration_incompatible_warning", {
    value: seconds,
    supported: durationOptions.join(", "),
  });
  const useSlider =
    isContinuousIntegerRange(durationOptions) && durationOptions.length >= 5;

  const baseClass =
    "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] text-[11.5px] focus-ring";
  const baseStyle: React.CSSProperties = {
    background: isIncompatible
      ? "oklch(0.32 0.10 75 / 0.35)"
      : "oklch(0.22 0.011 265 / 0.6)",
    border: isIncompatible
      ? "1px solid oklch(0.65 0.12 75 / 0.5)"
      : "1px solid var(--color-hairline-soft)",
    color: isIncompatible ? "oklch(0.85 0.12 80)" : "var(--color-text-2)",
  };

  if (!editable) {
    return (
      <span className={baseClass} style={baseStyle}>
        <span style={{ color: "var(--color-text-4)" }}>⏱</span>
        <span className="num">
          {t("duration_seconds_value_text", { value: seconds })}
        </span>
        {isIncompatible && (
          <span aria-label={incompatibleLabel} title={incompatibleLabel}>
            ⚠
          </span>
        )}
      </span>
    );
  }

  return (
    <>
      <button
        ref={ref}
        type="button"
        onClick={() => !noOptions && setOpen((o) => !o)}
        disabled={noOptions}
        aria-disabled={noOptions || undefined}
        title={noOptions ? t("duration_no_options") : undefined}
        className={`${baseClass} transition-colors disabled:cursor-not-allowed disabled:opacity-60`}
        style={baseStyle}
      >
        <span style={{ color: "var(--color-text-4)" }}>⏱</span>
        <span className="num">
          {t("duration_seconds_value_text", { value: seconds })}
        </span>
        {isIncompatible && (
          <span aria-label={incompatibleLabel} title={incompatibleLabel}>
            ⚠
          </span>
        )}
      </button>
      <Popover
        open={open}
        onClose={() => setOpen(false)}
        anchorRef={ref}
        width="w-auto"
        align="start"
        sideOffset={6}
        backgroundColor="oklch(0.21 0.012 265 / 0.98)"
        className="rounded-lg p-2"
        style={{
          border: "1px solid var(--color-hairline)",
          boxShadow:
            "0 24px 60px -20px oklch(0 0 0 / 0.7), 0 0 0 1px var(--color-hairline-soft)",
          backdropFilter: "blur(12px)",
          WebkitBackdropFilter: "blur(12px)",
        }}
      >
        {useSlider ? (
          <div className="flex items-center gap-2 px-1 py-1">
            <input
              type="range"
              aria-label={t("duration_selector_aria")}
              aria-valuetext={t("duration_seconds_value_text", { value: displaySeconds })}
              min={durationOptions[0]}
              max={durationOptions[durationOptions.length - 1]}
              step={1}
              value={displaySeconds}
              onChange={(e) => setDraftSeconds(parseInt(e.target.value, 10))}
              onPointerUp={commitDraft}
              onKeyUp={(e) => {
                if (
                  e.key === "ArrowLeft" ||
                  e.key === "ArrowRight" ||
                  e.key === "ArrowUp" ||
                  e.key === "ArrowDown" ||
                  e.key === "Home" ||
                  e.key === "End" ||
                  e.key === "PageUp" ||
                  e.key === "PageDown"
                ) {
                  commitDraft();
                }
              }}
              onBlur={commitDraft}
              className="theme-slider w-40"
            />
            <span
              className="num min-w-[2.25rem] text-right text-[11.5px]"
              style={{ color: "var(--color-text-2)" }}
            >
              {t("duration_seconds_value_text", { value: displaySeconds })}
            </span>
          </div>
        ) : (
          <div
            className="flex flex-wrap gap-1"
            role="radiogroup"
            aria-label={t("duration_selector_aria")}
          >
            {durationOptions.map((d) => {
              const checked = d === seconds;
              return (
                <button
                  key={d}
                  role="radio"
                  type="button"
                  aria-checked={checked}
                  onClick={() => {
                    void onUpdatePrompt(segmentId, "duration_seconds", d);
                    setOpen(false);
                  }}
                  className="num rounded-md px-2.5 py-1 text-[11.5px] font-medium transition-colors focus-ring"
                  style={
                    checked
                      ? {
                          background:
                            "linear-gradient(180deg, var(--color-accent-2), var(--color-accent))",
                          color: "oklch(0.14 0 0)",
                          boxShadow:
                            "inset 0 1px 0 oklch(1 0 0 / 0.25), 0 2px 6px -2px var(--color-accent-glow)",
                        }
                      : {
                          background: "oklch(0.22 0.011 265 / 0.5)",
                          color: "var(--color-text-2)",
                          border: "1px solid var(--color-hairline-soft)",
                        }
                  }
                >
                  {t("duration_seconds_value_text", { value: d })}
                </button>
              );
            })}
          </div>
        )}
      </Popover>
    </>
  );
}

export function ShotDetail({
  segment,
  nextSegment,
  segmentId,
  contentMode,
  aspectRatio,
  projectName,
  scriptFile,
  isGridMode,
  selectedIndex,
  totalCount,
  onPrev,
  onNext,
  onUpdatePrompt,
  onGenerateStoryboard,
  onGenerateVideo,
  onRestoreStoryboard,
  onRestoreVideo,
  generatingStoryboard,
  generatingVideo,
  durationOptions = [],
  videoContinuityPolicy,
  videoContinuitySupport,
  shotTierProfiles,
}: ShotDetailProps) {
  const { t } = useTranslation("dashboard");
  const status = statusFromAssets(segment.generated_assets?.status);
  const novelText = getNovelText(segment, contentMode);
  const shotTierExplicit = isShotTier(segment.shot_tier);
  const shotTier = normalizeShotTier(segment.shot_tier);
  const shotTierProfile = useMemo(
    () => normalizeShotTierProfiles(shotTierProfiles)[shotTier],
    [shotTier, shotTierProfiles],
  );
  const effectiveVideoContinuityPolicy =
    shotTierProfile.video_continuity_policy ?? videoContinuityPolicy;
  const segCost = useCostStore((s) => s.getSegmentCost(segmentId));
  const expectedVideoContinuity = useMemo(
    () =>
      resolveExpectedShotVideoContinuity({
        policy: effectiveVideoContinuityPolicy,
        support: videoContinuitySupport,
        currentSegment: segment,
        nextSegment,
      }),
    [effectiveVideoContinuityPolicy, nextSegment, segment, videoContinuitySupport],
  );

  const ip = segment.image_prompt;
  const vp = segment.video_prompt;
  const note = segment.note ?? "";

  // 草稿：本地编辑直到用户点击 Save。父级 ShotSplitView 通过 key={segmentId}
  // 在切镜头时硬重置整个组件，所以这里只需处理"上游同字段静默更新"的情况。
  // 备注不进入草稿，由 NotesDrawer 收起时直接落库。
  const [draft, setDraft] = useState<DraftState>(() => ({
    image_prompt: ip,
    video_prompt: vp,
  }));
  const [saving, setSaving] = useState(false);
  const [copyingPrompt, setCopyingPrompt] = useState<"storyboard" | "video" | null>(null);
  const [exportingRefs, setExportingRefs] = useState<"storyboard" | "video" | null>(null);

  const upstreamSig = useMemo(
    () => stableSig({ ip, vp }),
    [ip, vp],
  );
  const baselineSigRef = useRef(upstreamSig);
  const draftRef = useRef(draft);
  // 同步 draft 到 ref，供下方 effect 读取最新草稿而无需把 draft 加入 deps
  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  // 上游变更（保存完成 / agent 编辑）：草稿干净时静默跟随；脏时保留用户输入。
  // 把 draft 放到 ref 里读，避免每次 keystroke 都重跑 effect+stringify。
  useEffect(() => {
    if (baselineSigRef.current === upstreamSig) return;
    if (stableSig(draftRef.current) === baselineSigRef.current) {
      setDraft({ image_prompt: ip, video_prompt: vp });
    }
    baselineSigRef.current = upstreamSig;
  }, [upstreamSig, ip, vp]);

  // 引用相等优先：未编辑过的字段直接跳过 stringify。
  const dirtyPatch = useMemo<Record<string, unknown>>(() => {
    const patch: Record<string, unknown> = {};
    if (
      draft.image_prompt !== ip &&
      stableSig(draft.image_prompt) !== stableSig(ip)
    )
      patch.image_prompt = draft.image_prompt;
    if (
      draft.video_prompt !== vp &&
      stableSig(draft.video_prompt) !== stableSig(vp)
    )
      patch.video_prompt = draft.video_prompt;
    return patch;
  }, [draft, ip, vp]);

  const dirty = Object.keys(dirtyPatch).length > 0;


  const isStructIp = isStructuredImagePrompt(draft.image_prompt);
  const isStructVp = isStructuredVideoPrompt(draft.video_prompt);
  const imgDraft: ImagePrompt | null = isStructIp
    ? (draft.image_prompt as ImagePrompt)
    : null;
  const vidDraft: VideoPrompt | null = isStructVp
    ? (draft.video_prompt as VideoPrompt)
    : null;

  const handleImgUpdate = (patch: Partial<ImagePrompt>) => {
    setDraft((d) => {
      if (!isStructuredImagePrompt(d.image_prompt)) return d;
      const merged: ImagePrompt = {
        ...d.image_prompt,
        ...patch,
        composition: {
          ...d.image_prompt.composition,
          ...(patch.composition ?? {}),
        },
      };
      return { ...d, image_prompt: merged };
    });
  };

  const handleVidUpdate = (patch: Partial<VideoPrompt>) => {
    setDraft((d) => {
      if (!isStructuredVideoPrompt(d.video_prompt)) return d;
      const merged: VideoPrompt = { ...d.video_prompt, ...patch };
      return { ...d, video_prompt: merged };
    });
  };

  const handleDialogueChange = (dialogue: Dialogue[]) => {
    handleVidUpdate({ dialogue });
  };

  const handleImgStringChange = (val: string) => {
    setDraft((d) => ({ ...d, image_prompt: val }));
  };

  const handleVidStringChange = (val: string) => {
    setDraft((d) => ({ ...d, video_prompt: val }));
  };

  const handleNotesCommit = (value: string) => {
    if (value === note) return;
    void onUpdatePrompt?.(segmentId, "note", value);
  };

  const handleSave = async () => {
    if (!dirty || saving) return;
    setSaving(true);
    try {
      await onUpdatePrompt?.(segmentId, dirtyPatch);
      // 上游会刷新 → useEffect 检测到 baselineSig 变化 → 草稿等于新基线时保持干净
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (saving) return;
    setDraft({ image_prompt: ip, video_prompt: vp });
  };

  const dirtyHint = t("shot_detail_save_first");

  const loadExternalGenerationSection = async (kind: "storyboard" | "video") => {
    const pkg = await API.getExternalGenerationPackage(projectName, segmentId, scriptFile || "");
    return kind === "storyboard" ? pkg.storyboard : pkg.video;
  };

  const handleCopyExternalPrompt = async (kind: "storyboard" | "video") => {
    if (dirty || saving) {
      useAppStore.getState().pushToast(dirtyHint, "warning");
      return;
    }
    if (!scriptFile) {
      useAppStore.getState().pushToast("缺少剧本文件，无法复制外部生成提示词", "error");
      return;
    }
    setCopyingPrompt(kind);
    try {
      const section = await loadExternalGenerationSection(kind);
      await copyText(section.external_prompt);
      const refText = section.references.length
        ? `，参考图 ${section.references.length} 张已写入提示词清单，图片内容优先`
        : "";
      useAppStore
        .getState()
        .pushToast(`${kind === "storyboard" ? "分镜图" : "视频"}提示词已复制${refText}`, "success");
    } catch (err) {
      useAppStore.getState().pushToast(errMsg(err), "error");
    } finally {
      setCopyingPrompt(null);
    }
  };

  const handleExportExternalReferences = async (kind: "storyboard" | "video") => {
    if (dirty || saving) {
      useAppStore.getState().pushToast(dirtyHint, "warning");
      return;
    }
    if (!scriptFile) {
      useAppStore.getState().pushToast("缺少剧本文件，无法导出外部生成参考图", "error");
      return;
    }

    const label = kind === "storyboard" ? "分镜图" : "视频";
    setExportingRefs(kind);
    try {
      const section = await loadExternalGenerationSection(kind);
      let promptCopied = true;
      try {
        await copyText(section.external_prompt);
      } catch {
        promptCopied = false;
      }

      const targetDirectory = await pickDesktopDirectory({
        title: `选择${label}参考图导出目录`,
      });
      if (!targetDirectory) {
        useAppStore
          .getState()
          .pushToast(
            promptCopied
              ? `${label}提示词已复制，已取消导出参考图`
              : `已取消导出参考图，${label}提示词未能自动复制`,
            promptCopied ? "success" : "warning",
          );
        return;
      }

      const result = await exportExternalGenerationPackage(
        projectName,
        section.references,
        section.external_prompt,
        targetDirectory,
      );

      const copiedText = result.copiedCount > 0
        ? `参考图已导出 ${result.copiedCount} 张`
        : "没有可导出的参考图";
      const failedText = result.failed.length > 0
        ? `，${result.failed.length} 张参考图导出失败`
        : "";
      const promptFileText = result.promptPath
        ? "，提示词文件已保存"
        : result.promptWriteError
          ? "，提示词文件保存失败"
          : "";
      const clipboardText = promptCopied ? "，提示词已复制" : "，提示词未能自动复制";
      const type = result.failed.length > 0 || result.promptWriteError || !promptCopied
        ? "warning"
        : "success";

      useAppStore
        .getState()
        .pushToast(`${label}${copiedText}${failedText}${promptFileText}${clipboardText}`, type);
    } catch (err) {
      useAppStore.getState().pushToast(errMsg(err), "error");
    } finally {
      setExportingRefs(null);
    }
  };

  const sbEstimate = segCost?.estimate?.image;
  const vidEstimate = segCost?.estimate?.video;

  const assets = segment.generated_assets;
  const hasStoryboard = !!assets?.storyboard_image;

  const characterNames =
    contentMode === "drama"
      ? (segment as DramaScene).characters_in_scene ?? []
      : (segment as NarrationSegment).characters_in_segment ?? [];
  const sceneNames = segment.scenes ?? [];
  const propNames = segment.props ?? [];
  const refsReadOnly = !onUpdatePrompt;

  const handleRefsSave = async (patch: Record<string, string[]>) => {
    if (!onUpdatePrompt || Object.keys(patch).length === 0) return;
    await onUpdatePrompt(segmentId, patch);
  };

  const leftColumn = (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto px-3.5 pb-5 pt-3.5">
      <ReferencesSection
        projectName={projectName}
        contentMode={contentMode}
        characterNames={characterNames}
        sceneNames={sceneNames}
        propNames={propNames}
        onSave={handleRefsSave}
        disabled={dirty || saving || refsReadOnly}
        disabledHint={dirty ? dirtyHint : undefined}
      />

      {(novelText || contentMode === "narration") && (
        <div>
          <div
            className="mb-2 text-[10.5px] font-bold uppercase"
            style={{
              color: "var(--color-text-4)",
              letterSpacing: "1px",
              fontFamily: "var(--font-mono)",
            }}
          >
            {t("detail_section_novel")}
          </div>
          <div
            className="rounded-md px-3 py-2.5"
            style={{
              background:
                "linear-gradient(180deg, oklch(0.22 0.012 265 / 0.5), oklch(0.20 0.012 265 / 0.35))",
              border: "1px solid var(--color-hairline-soft)",
              borderLeft: "3px solid var(--color-accent-soft)",
            }}
          >
            <p
              className="display-serif m-0 text-[13px]"
              style={{ lineHeight: 1.65, color: "var(--color-text)" }}
            >
              {novelText || t("no_original_text")}
            </p>
          </div>
        </div>
      )}
    </div>
  );

  const midColumn = (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto px-5 pb-7 pt-3.5">
      <div
        className="text-[10.5px] font-bold uppercase"
        style={{
          color: "var(--color-text-4)",
          letterSpacing: "1px",
          fontFamily: "var(--font-mono)",
        }}
      >
        {t("detail_section_prompts")}
      </div>

      <section>
        <div className="mb-2 flex items-center gap-1.5">
          <ImageIcon
            className="h-3.5 w-3.5"
            style={{ color: "var(--color-text-3)" }}
          />
          <span
            className="text-[12.5px] font-semibold"
            style={{ color: "var(--color-text-2)" }}
          >
            {t("detail_image_prompt_title")}
          </span>
          <span className="flex-1" />
          <button
            type="button"
            onClick={() => void handleCopyExternalPrompt("storyboard")}
            disabled={saving || copyingPrompt !== null || exportingRefs !== null}
            title="复制外部生成提示词"
            aria-label="复制分镜图外部生成提示词"
            className="focus-ring inline-flex h-6 w-6 items-center justify-center rounded-md transition-colors hover:bg-[oklch(1_0_0_/_0.05)] disabled:cursor-not-allowed disabled:opacity-50"
            style={{ color: "var(--color-text-3)" }}
          >
            {copyingPrompt === "storyboard" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            type="button"
            onClick={() => void handleExportExternalReferences("storyboard")}
            disabled={saving || copyingPrompt !== null || exportingRefs !== null}
            title="导出参考图并复制提示词"
            aria-label="导出分镜图参考图并复制提示词"
            className="focus-ring inline-flex h-6 w-6 items-center justify-center rounded-md transition-colors hover:bg-[oklch(1_0_0_/_0.05)] disabled:cursor-not-allowed disabled:opacity-50"
            style={{ color: "var(--color-text-3)" }}
          >
            {exportingRefs === "storyboard" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <FolderDown className="h-3.5 w-3.5" />
            )}
          </button>
          {imgDraft && (
            <span
              className="num text-[10px]"
              style={{ color: "var(--color-text-4)" }}
            >
              {t("detail_field_chars_count", { count: imgDraft.scene.length })}
            </span>
          )}
        </div>
        {imgDraft ? (
          <ImagePromptEditor prompt={imgDraft} onUpdate={handleImgUpdate} />
        ) : (
          <textarea
            className="prompt-ta"
            value={
              typeof draft.image_prompt === "string" ? draft.image_prompt : ""
            }
            onChange={(e) => handleImgStringChange(e.target.value)}
            placeholder={t("detail_image_prompt_placeholder")}
            style={{ minHeight: 124 }}
          />
        )}
      </section>

      <section>
        <div className="mb-2 flex items-center gap-1.5">
          <Film
            className="h-3.5 w-3.5"
            style={{ color: "var(--color-text-3)" }}
          />
          <span
            className="text-[12.5px] font-semibold"
            style={{ color: "var(--color-text-2)" }}
          >
            {t("detail_video_prompt_title")}
          </span>
          <span className="flex-1" />
          <button
            type="button"
            onClick={() => void handleCopyExternalPrompt("video")}
            disabled={saving || copyingPrompt !== null || exportingRefs !== null}
            title="复制外部生成提示词"
            aria-label="复制视频外部生成提示词"
            className="focus-ring inline-flex h-6 w-6 items-center justify-center rounded-md transition-colors hover:bg-[oklch(1_0_0_/_0.05)] disabled:cursor-not-allowed disabled:opacity-50"
            style={{ color: "var(--color-text-3)" }}
          >
            {copyingPrompt === "video" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            type="button"
            onClick={() => void handleExportExternalReferences("video")}
            disabled={saving || copyingPrompt !== null || exportingRefs !== null}
            title="导出参考图并复制提示词"
            aria-label="导出视频参考图并复制提示词"
            className="focus-ring inline-flex h-6 w-6 items-center justify-center rounded-md transition-colors hover:bg-[oklch(1_0_0_/_0.05)] disabled:cursor-not-allowed disabled:opacity-50"
            style={{ color: "var(--color-text-3)" }}
          >
            {exportingRefs === "video" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <FolderDown className="h-3.5 w-3.5" />
            )}
          </button>
          {vidDraft && (
            <span
              className="num text-[10px]"
              style={{ color: "var(--color-text-4)" }}
            >
              {t("detail_field_chars_count", { count: vidDraft.action.length })}
            </span>
          )}
        </div>
        {vidDraft ? (
          <VideoPromptEditor prompt={vidDraft} onUpdate={handleVidUpdate} />
        ) : (
          <textarea
            className="prompt-ta"
            value={
              typeof draft.video_prompt === "string" ? draft.video_prompt : ""
            }
            onChange={(e) => handleVidStringChange(e.target.value)}
            placeholder={t("detail_video_prompt_placeholder")}
            style={{ minHeight: 88 }}
          />
        )}
      </section>

      {characterNames.length > 0 && (
        <section>
          <div
            className="mb-2 text-[10.5px] font-bold uppercase"
            style={{
              color: "var(--color-text-4)",
              letterSpacing: "1px",
              fontFamily: "var(--font-mono)",
            }}
          >
            {t("detail_section_dialogue")}
          </div>
          {vidDraft ? (
            <DialogueListEditor
              dialogue={vidDraft.dialogue ?? []}
              speakerOptions={characterNames}
              onChange={handleDialogueChange}
            />
          ) : (
            <div
              className="rounded-md py-3 text-center text-[11.5px] italic"
              style={{
                border: "1px dashed var(--color-hairline)",
                color: "var(--color-text-4)",
              }}
            >
              {t("detail_dialogue_empty")}
            </div>
          )}
        </section>
      )}
    </div>
  );

  const rightColumn = (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto px-[18px] pb-7 pt-3.5">
      <MediaCard
        kind="storyboard"
        projectName={projectName}
        segmentId={segmentId}
        assetPath={assets?.storyboard_image ?? null}
        scriptFile={scriptFile}
        aspectRatio={aspectRatio}
        hideGenerateButton={isGridMode}
        generating={generatingStoryboard}
        estimatedCost={sbEstimate ?? undefined}
        onGenerate={(quality) => onGenerateStoryboard?.(segmentId, quality)}
        onRestore={onRestoreStoryboard}
        onUploaded={onRestoreStoryboard}
        generateDisabled={dirty || saving}
        uploadDisabled={dirty || saving}
        generateDisabledHint={dirty ? dirtyHint : undefined}
      />
      <MediaCard
        kind="video"
        projectName={projectName}
        segmentId={segmentId}
        assetPath={assets?.video_clip ?? null}
        scriptFile={scriptFile}
        posterPath={assets?.video_thumbnail ?? null}
        aspectRatio={aspectRatio}
        generating={generatingVideo}
        generateDisabled={!hasStoryboard || dirty || saving}
        generateDisabledHint={dirty ? dirtyHint : undefined}
        estimatedCost={vidEstimate ?? undefined}
        expectedVideoContinuity={expectedVideoContinuity}
        onGenerate={(quality) => onGenerateVideo?.(segmentId, quality)}
        onRestore={onRestoreVideo}
        onUploaded={onRestoreVideo}
        uploadDisabled={dirty || saving}
      />
    </div>
  );

  const navDisabled = dirty || saving;

  return (
    <div
      className="flex min-h-0 min-w-0 flex-col overflow-hidden"
      style={{
        background:
          "radial-gradient(ellipse at top, oklch(0.20 0.012 270 / 0.35), oklch(0.17 0.010 265 / 0.2))",
      }}
    >
      <div
        className="relative flex items-center gap-2.5 px-5 py-3"
        style={{ borderBottom: "1px solid var(--color-hairline-soft)" }}
      >
        <span
          className="num rounded-md px-2.5 py-1 text-[12px] font-bold"
          style={{
            background:
              "linear-gradient(180deg, var(--color-accent-2), var(--color-accent))",
            color: "oklch(0.14 0 0)",
            letterSpacing: "0.3px",
            boxShadow:
              "inset 0 1px 0 oklch(1 0 0 / 0.3), 0 2px 6px -2px var(--color-accent-glow)",
          }}
        >
          {segmentId}
        </span>
        <DurationPill
          seconds={segment.duration_seconds ?? 0}
          segmentId={segmentId}
          durationOptions={durationOptions}
          onUpdatePrompt={onUpdatePrompt}
        />
        <ShotTierPill
          tier={shotTier}
          explicit={shotTierExplicit}
          segmentId={segmentId}
          onUpdatePrompt={onUpdatePrompt}
        />
        {nextSegment ? (
          <TransitionPill
            value={segment.transition_to_next}
            segmentId={segmentId}
            onUpdatePrompt={onUpdatePrompt}
          />
        ) : null}
        <StatusBadge status={status} />
        <span className="flex-1" />

        <div className="flex items-center gap-1.5">
          <span
            className="num text-[10.5px]"
            style={{ color: "var(--color-text-4)" }}
          >
            {t("shot_detail_count", {
              current: selectedIndex + 1,
              total: totalCount,
            })}
          </span>
          <button
            type="button"
            onClick={onPrev}
            disabled={navDisabled}
            title={navDisabled ? dirtyHint : t("shot_detail_prev")}
            className="sv-navbtn disabled:cursor-not-allowed disabled:opacity-50"
            aria-label={t("shot_detail_prev")}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={onNext}
            disabled={navDisabled}
            title={navDisabled ? dirtyHint : t("shot_detail_next")}
            className="sv-navbtn disabled:cursor-not-allowed disabled:opacity-50"
            aria-label={t("shot_detail_next")}
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
          <NotesDrawer
            shotId={segmentId}
            value={note}
            onCommit={handleNotesCommit}
          />
        </div>
      </div>

      {dirty && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-2 px-5 py-2"
          style={{
            background:
              "linear-gradient(180deg, var(--color-accent-dim), oklch(0.20 0.012 270 / 0.35))",
            borderBottom: "1px solid var(--color-accent-soft)",
          }}
        >
          <span
            aria-hidden="true"
            className="h-1.5 w-1.5 rounded-full"
            style={{
              background: "var(--color-accent)",
              boxShadow: "0 0 6px var(--color-accent-glow)",
            }}
          />
          <span
            className="num text-[10.5px] uppercase"
            style={{
              letterSpacing: "1.0px",
              color: "var(--color-accent-2)",
            }}
          >
            {t("shot_detail_unsaved")}
          </span>
          <span className="flex-1" />
          <button
            type="button"
            onClick={handleCancel}
            disabled={saving}
            className="focus-ring inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[11.5px] text-[var(--color-text-3)] transition-colors [&:not(:disabled)]:hover:bg-[oklch(0.26_0.013_265_/_0.7)] [&:not(:disabled)]:hover:text-[var(--color-text)] disabled:cursor-not-allowed disabled:opacity-50"
            style={{
              border: "1px solid var(--color-hairline)",
              background: "oklch(0.22 0.011 265 / 0.5)",
            }}
          >
            <Undo2 className="h-3.5 w-3.5" />
            <span>{t("shot_detail_cancel")}</span>
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving}
            className="focus-ring inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-[11.5px] font-medium transition-transform [&:not(:disabled)]:hover:-translate-y-px disabled:cursor-not-allowed disabled:opacity-60"
            style={{
              color: "oklch(0.14 0 0)",
              background:
                "linear-gradient(135deg, var(--color-accent-2), var(--color-accent))",
              boxShadow:
                "inset 0 1px 0 oklch(1 0 0 / 0.35), 0 6px 18px -6px var(--color-accent-glow), 0 0 0 1px var(--color-accent-soft)",
            }}
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Check className="h-3.5 w-3.5" />
            )}
            <span>
              {saving ? t("shot_detail_saving") : t("shot_detail_save")}
            </span>
          </button>
        </div>
      )}

      <ResponsiveDetailGrid
        left={leftColumn}
        mid={midColumn}
        right={rightColumn}
      />
    </div>
  );
}

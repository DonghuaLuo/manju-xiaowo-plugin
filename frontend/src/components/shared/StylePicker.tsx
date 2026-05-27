import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { Check, Loader2, Sparkles, Upload, X } from "lucide-react";
import {
  DEFAULT_TEMPLATE_ID,
  type StyleTemplate,
  type StyleCategory,
} from "@/data/style-templates";
import { pickDesktopFile, type UploadFileInput } from "@/utils/desktop-file";
import { resolveStyleThumbnailUrl } from "@/utils/style-thumbnails";

export interface StylePickerValue {
  mode: "template" | "custom";
  templateId: string | null;
  activeCategory: "live" | "anim";
  uploadedFile: UploadFileInput | null;
  /** Either a blob: URL (just-uploaded) or an existing desktop resource URL. */
  uploadedPreview: string | null;
  /** The final style prompt to persist for this project. */
  stylePrompt: string;
}

export interface StylePickerProps {
  value: StylePickerValue;
  onChange: (next: StylePickerValue) => void;
  templates?: StyleTemplate[];
  templatePrompts?: Record<string, string>;
  onAnalyzeCustomStyle?: (file: UploadFileInput) => Promise<string>;
  analyzingCustomStyle?: boolean;
}

const SELECTED_RING_STYLE: CSSProperties = {
  boxShadow:
    "inset 0 0 0 1.5px var(--color-accent), 0 0 0 4px var(--color-bg-grad-a), 0 0 24px -8px var(--color-accent-glow)",
};

const HOVER_RING_STYLE: CSSProperties = {
  boxShadow: "inset 0 0 0 1px var(--color-hairline)",
};

interface TemplateCardProps {
  thumbnail: string | null;
  label: string;
  tagline: string;
  isSelected: boolean;
  isDefault: boolean;
  defaultLabel: string;
  onClick: () => void;
}

function TemplateCard({
  thumbnail,
  label,
  tagline,
  isSelected,
  isDefault,
  defaultLabel,
  onClick,
}: TemplateCardProps) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={isSelected}
      onClick={onClick}
      className="group relative aspect-[3/4] overflow-hidden rounded-[8px] transition-transform duration-150 motion-safe:hover:-translate-y-px focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      style={isSelected ? SELECTED_RING_STYLE : HOVER_RING_STYLE}
    >
      {thumbnail ? (
        <img
          key={thumbnail}
          src={thumbnail}
          alt={label}
          width={240}
          height={320}
          loading="lazy"
          decoding="async"
          className="h-full w-full object-cover"
          onLoad={(e) => {
            e.currentTarget.style.display = "";
          }}
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
      ) : null}
      {/* Fallback gradient if image errors out */}
      <div
        aria-hidden
        className="-z-10 absolute inset-0"
        style={{
          background:
            "linear-gradient(135deg, oklch(0.30 0.04 295), oklch(0.18 0.012 265))",
        }}
      />

      {/* Bottom label gradient */}
      <div
        className="absolute inset-x-0 bottom-0 px-2 py-1.5"
        style={{
          background:
            "linear-gradient(180deg, transparent 0%, oklch(0 0 0 / 0.8) 100%)",
        }}
      >
        <p className="truncate text-[11px] leading-tight text-text">{label}</p>
        {tagline && (
          <p className="mt-0.5 truncate text-[9px] leading-tight text-text-3">
            {tagline}
          </p>
        )}
      </div>

      {/* Selected check */}
      {isSelected && (
        <div
          className="absolute right-1.5 top-1.5 grid h-5 w-5 place-items-center rounded-full"
          style={{
            background:
              "linear-gradient(180deg, var(--color-accent-2), var(--color-accent))",
            color: "oklch(0.14 0 0)",
            boxShadow: "0 0 14px -4px var(--color-accent-glow)",
          }}
        >
          <Check size={11} strokeWidth={3} aria-hidden />
        </div>
      )}

      {/* Default tag */}
      {isDefault && (
        <div
          className="absolute left-1.5 top-1.5 rounded-full px-1.5 py-0.5 font-mono text-[8.5px] font-bold uppercase tracking-[0.12em]"
          style={{
            background: "oklch(0 0 0 / 0.55)",
            color: "var(--color-accent-2)",
            border: "1px solid var(--color-accent-soft)",
            backdropFilter: "blur(6px)",
            WebkitBackdropFilter: "blur(6px)",
          }}
        >
          {defaultLabel}
        </div>
      )}
    </button>
  );
}

function revokeBlobUrl(url: string | null) {
  if (url && url.startsWith("blob:")) URL.revokeObjectURL(url);
}

export function StylePicker({
  value,
  onChange,
  templates: styleTemplates = [],
  templatePrompts = {},
  onAnalyzeCustomStyle,
  analyzingCustomStyle = false,
}: StylePickerProps) {
  const { t } = useTranslation(["common", "templates"]);
  const ownedBlobUrlRef = useRef<string | null>(null);
  const [thumbnailUrls, setThumbnailUrls] = useState<Record<string, string | null>>({});

  useEffect(() => {
    return () => {
      revokeBlobUrl(ownedBlobUrlRef.current);
      ownedBlobUrlRef.current = null;
    };
  }, []);

  const handleCustomTab = () => {
    onChange({
      ...value,
      mode: "custom",
    });
  };

  const handleCategoryTab = (cat: StyleCategory) => {
    onChange({
      ...value,
      mode: "template",
      activeCategory: cat,
    });
  };

  const handlePickFile = async () => {
    const file = await pickDesktopFile({
      title: t("templates:upload_reference"),
      filters: [{ name: "Images", extensions: ["png", "jpg", "jpeg", "webp"] }],
      preview: true,
    });
    if (!file) return;
    revokeBlobUrl(ownedBlobUrlRef.current);
    ownedBlobUrlRef.current = null;
    onChange({
      ...value,
      mode: "custom",
      templateId: null,
      uploadedFile: file,
      uploadedPreview: file.previewUrl ?? null,
      stylePrompt: "",
    });
  };

  const handleClearUpload = () => {
    revokeBlobUrl(ownedBlobUrlRef.current);
    ownedBlobUrlRef.current = null;
    onChange({ ...value, uploadedFile: null, uploadedPreview: null });
  };

  const handleAnalyzeStyle = async () => {
    if (!value.uploadedFile || !onAnalyzeCustomStyle) return;
    const prompt = await onAnalyzeCustomStyle(value.uploadedFile);
    onChange({ ...value, mode: "custom", stylePrompt: prompt });
  };

  const promptEditor = (withAnalyzeButton: boolean) => (
    <div className="flex items-stretch gap-2">
      <textarea
        value={value.stylePrompt}
        onChange={(e) => onChange({ ...value, stylePrompt: e.target.value })}
        placeholder={t(
          value.mode === "custom"
            ? "templates:custom_prompt_placeholder"
            : "templates:template_prompt_placeholder",
        )}
        aria-label={t("templates:style_prompt_label")}
        rows={3}
        className="min-h-[82px] flex-1 resize-y rounded-[9px] border border-hairline-soft bg-bg-grad-a/55 px-3 py-2 font-mono text-[11.5px] leading-[1.55] text-text outline-none transition-colors placeholder:text-text-4 focus:border-accent/55 focus:ring-2 focus:ring-accent/25"
      />
      {withAnalyzeButton ? (
        <button
          type="button"
          onClick={() => void handleAnalyzeStyle()}
          disabled={!value.uploadedFile || !onAnalyzeCustomStyle || analyzingCustomStyle}
          className="inline-flex w-24 shrink-0 items-center justify-center gap-1.5 rounded-[9px] border border-hairline-soft bg-bg-grad-a/65 px-2 text-[12px] font-medium text-text-2 transition-colors hover:border-accent/45 hover:bg-accent-dim hover:text-accent-2 disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          {analyzingCustomStyle ? (
            <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin" aria-hidden />
          ) : (
            <Sparkles className="h-3.5 w-3.5" aria-hidden />
          )}
          <span>{analyzingCustomStyle ? t("templates:analyzing_style") : t("templates:analyze_style")}</span>
        </button>
      ) : null}
    </div>
  );

  const tabCls = (active: boolean) =>
    [
      "rounded-[6px] px-3 py-1 font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
      active
        ? "bg-accent-dim text-accent-2"
        : "text-text-3 hover:text-text",
    ].join(" ");

  const isCustomActive = value.mode === "custom";
  const isLiveActive = value.mode === "template" && value.activeCategory === "live";
  const isAnimActive = value.mode === "template" && value.activeCategory === "anim";
  const templates = useMemo(
    () => (value.mode === "template"
      ? styleTemplates.filter((tpl) => tpl.category === value.activeCategory)
      : []),
    [styleTemplates, value.activeCategory, value.mode],
  );

  useEffect(() => {
    if (value.mode !== "template") return;

    let cancelled = false;
    void Promise.all(
      templates.map(async (tpl) => [
        tpl.id,
        await resolveStyleThumbnailUrl(tpl.thumbnailFile),
      ] as const),
    ).then((entries) => {
      if (cancelled) return;
      setThumbnailUrls((prev) => {
        const next = { ...prev };
        for (const [id, url] of entries) next[id] = url;
        return next;
      });
    });

    return () => {
      cancelled = true;
    };
  }, [templates, value.mode]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {/* Tab pills */}
      <div className="flex w-fit gap-1 rounded-[8px] border border-hairline bg-bg-grad-a/55 p-1">
        <button
          type="button"
          onClick={handleCustomTab}
          className={tabCls(isCustomActive)}
        >
          {t("templates:category.custom")}
        </button>
        <button
          type="button"
          onClick={() => handleCategoryTab("live")}
          className={tabCls(isLiveActive)}
        >
          {t("templates:category.live")}
        </button>
        <button
          type="button"
          onClick={() => handleCategoryTab("anim")}
          className={tabCls(isAnimActive)}
        >
          {t("templates:category.anim")}
        </button>
      </div>

      {value.mode === "custom" ? (
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          <p className="mb-3 text-[12.5px] leading-[1.55] text-text-3">
            {t("templates:tab_custom_desc")}
          </p>

          {value.uploadedPreview ? (
            <div className="relative flex min-h-[260px] flex-1 overflow-hidden rounded-[10px] border border-hairline bg-bg-grad-a/55">
              <img
                src={value.uploadedPreview}
                alt={t("templates:upload_reference")}
                className="h-full w-full object-contain"
              />
              <button
                type="button"
                onClick={handleClearUpload}
                aria-label={t("common:remove")}
                className="absolute right-1.5 top-1.5 rounded-full p-1 text-text-2 transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                style={{
                  background: "oklch(0 0 0 / 0.55)",
                  backdropFilter: "blur(6px)",
                  WebkitBackdropFilter: "blur(6px)",
                }}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => void handlePickFile()}
              className="flex min-h-[260px] w-full flex-1 items-center justify-center gap-2 rounded-[10px] border border-dashed border-hairline-strong bg-bg-grad-a/45 px-3 py-7 text-[12.5px] text-text-3 transition-colors hover:border-accent/45 hover:bg-accent-dim hover:text-accent-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              <Upload className="h-3.5 w-3.5" />
              <span>{t("templates:upload_reference")}</span>
            </button>
          )}

          <p className="mt-2 font-mono text-[10px] uppercase tracking-[0.14em] text-text-4">
            {t("templates:supported_formats")}
          </p>
          {promptEditor(true)}
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-4">
          <div className="grid max-h-[360px] grid-cols-4 gap-3 overflow-y-auto p-1 pr-2">
            {templates.map((tpl) => (
              <TemplateCard
                key={tpl.id}
                thumbnail={thumbnailUrls[tpl.id] ?? null}
                label={t(`templates:name.${tpl.id}`)}
                tagline={t(`templates:tagline.${tpl.id}`, "")}
                isSelected={value.templateId === tpl.id}
                isDefault={tpl.id === DEFAULT_TEMPLATE_ID}
                defaultLabel={t("templates:template_selected_default")}
                onClick={() => onChange({
                  ...value,
                  mode: "template",
                  templateId: tpl.id,
                  stylePrompt: templatePrompts[tpl.id] ?? "",
                })}
              />
            ))}
          </div>
          {promptEditor(false)}
        </div>
      )}
    </div>
  );
}

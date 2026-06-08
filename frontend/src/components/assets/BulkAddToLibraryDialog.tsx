import { useEffect, useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Package } from "lucide-react";
import { API } from "@/api";
import { GlassModal } from "@/components/ui/GlassModal";
import { ModalCloseButton } from "@/components/ui/ModalCloseButton";
import { PrimaryButton } from "@/components/ui/PrimaryButton";
import { SecondaryButton } from "@/components/ui/SecondaryButton";
import { AssetThumb } from "@/components/assets/AssetThumb";
import { useAppStore } from "@/stores/app-store";
import { ASSET_LIBRARY_PAGE_SIZE } from "@/stores/assets-store";
import { useProjectsStore } from "@/stores/projects-store";
import { errMsg } from "@/utils/async";
import type { AssetType } from "@/types/asset";

export interface BulkAddToLibraryItem {
  name: string;
  description: string;
  voiceStyle?: string;
  sheetPath?: string | null;
}

interface Props {
  pageTitle: string;
  projectName: string;
  resourceType: AssetType;
  items: BulkAddToLibraryItem[];
  onClose: () => void;
}

interface ClassificationResult {
  ready: BulkAddToLibraryItem[];
  missingDesign: BulkAddToLibraryItem[];
  alreadyInLibrary: BulkAddToLibraryItem[];
}

interface ClassificationState {
  requestKey: string;
  result: ClassificationResult;
  error: string | null;
}

const EMPTY_CLASSIFICATION: ClassificationResult = {
  ready: [],
  missingDesign: [],
  alreadyInLibrary: [],
};

function createClassificationRequestKey(
  resourceType: AssetType,
  items: BulkAddToLibraryItem[],
): string {
  return JSON.stringify(
    items.map((item) => [resourceType, item.name, item.sheetPath ?? ""]),
  );
}

async function findExistingAssetNames(
  resourceType: AssetType,
  candidateNames: Set<string>,
  signal: AbortSignal,
): Promise<Set<string>> {
  const existingNames = new Set<string>();
  if (candidateNames.size === 0) return existingNames;

  let offset = 0;
  let total = Number.POSITIVE_INFINITY;

  while (offset < total && existingNames.size < candidateNames.size) {
    const res = await API.listAssets(
      { type: resourceType, limit: ASSET_LIBRARY_PAGE_SIZE, offset },
      { signal },
    );
    const pageItems = res.items ?? [];
    for (const asset of pageItems) {
      if (candidateNames.has(asset.name)) {
        existingNames.add(asset.name);
      }
    }
    const pageSize = pageItems.length;
    total = res.total ?? (pageSize === 0 ? offset : offset + pageSize);
    if (pageSize === 0) break;
    offset += pageSize;
  }

  return existingNames;
}

function classifyItems(
  items: BulkAddToLibraryItem[],
  existingNames: Set<string>,
): ClassificationResult {
  const ready: BulkAddToLibraryItem[] = [];
  const missingDesign: BulkAddToLibraryItem[] = [];
  const alreadyInLibrary: BulkAddToLibraryItem[] = [];

  for (const item of items) {
    if (!item.sheetPath) {
      missingDesign.push(item);
      continue;
    }
    if (existingNames.has(item.name)) {
      alreadyInLibrary.push(item);
      continue;
    }
    ready.push(item);
  }

  return { ready, missingDesign, alreadyInLibrary };
}

export function BulkAddToLibraryDialog({
  pageTitle,
  projectName,
  resourceType,
  items,
  onClose,
}: Props) {
  const { t } = useTranslation("assets");
  const titleId = useId();
  const descId = useId();
  const requestKey = useMemo(
    () => createClassificationRequestKey(resourceType, items),
    [items, resourceType],
  );
  const [submitting, setSubmitting] = useState(false);
  const [classificationState, setClassificationState] = useState<ClassificationState>({
    requestKey: "",
    result: EMPTY_CLASSIFICATION,
    error: null,
  });

  useEffect(() => {
    const ctrl = new AbortController();

    void (async () => {
      try {
        const generatedNames = new Set(
          items.filter((item) => item.sheetPath).map((item) => item.name),
        );
        const existingNames = await findExistingAssetNames(resourceType, generatedNames, ctrl.signal);
        if (ctrl.signal.aborted) return;
        setClassificationState({
          requestKey,
          result: classifyItems(items, existingNames),
          error: null,
        });
      } catch (err) {
        if (ctrl.signal.aborted) return;
        setClassificationState({
          requestKey,
          result: EMPTY_CLASSIFICATION,
          error: errMsg(err),
        });
      }
    })();

    return () => {
      ctrl.abort();
    };
  }, [items, requestKey, resourceType]);

  const loading = classificationState.requestKey !== requestKey;
  const result = loading ? EMPTY_CLASSIFICATION : classificationState.result;
  const error = loading ? null : classificationState.error;

  const readyCount = result.ready.length;
  const visibleCount = result.ready.length + result.missingDesign.length;
  const displayCount = loading ? items.length : visibleCount;
  const canConfirm = !loading && !submitting && !error && readyCount > 0;
  const sections = useMemo(
    () => [
      {
        key: "ready",
        title: t("batch_add_to_library_ready"),
        items: result.ready,
        tone: "accent" as const,
      },
      {
        key: "missing",
        title: t("batch_add_to_library_missing_design"),
        items: result.missingDesign,
        tone: "muted" as const,
      },
    ],
    [result.missingDesign, result.ready, t],
  );

  const handleConfirm = async () => {
    if (!canConfirm) return;
    setSubmitting(true);
    const settled = await Promise.allSettled(
      result.ready.map((item) =>
        API.addAssetFromProject({
          project_name: projectName,
          resource_type: resourceType,
          resource_id: item.name,
        }),
      ),
    );
    const succeeded = settled.filter((entry) => entry.status === "fulfilled").length;
    const failed = settled.length - succeeded;

    if (succeeded > 0) {
      useAppStore
        .getState()
        .pushToast(t("batch_add_to_library_success_count", { count: succeeded }), "success");
    }
    if (failed > 0) {
      useAppStore
        .getState()
        .pushToast(t("batch_add_to_library_failed_count", { count: failed }), "error");
    }
    setSubmitting(false);
    onClose();
  };

  return (
    <GlassModal
      open
      onClose={submitting ? () => {} : onClose}
      labelledBy={titleId}
      describedBy={descId}
      widthClassName="w-[920px] max-w-[96vw]"
      panelClassName="flex max-h-[88vh] flex-col"
      closeOnBackdrop={!submitting}
      closeOnEscape={!submitting}
    >
      <div
        className="flex items-start gap-3 px-5 py-4"
        style={{ borderBottom: "1px solid var(--color-hairline-soft)" }}
      >
        <span
          aria-hidden
          className="grid h-10 w-10 shrink-0 place-items-center rounded-xl"
          style={{
            background:
              "linear-gradient(135deg, var(--color-accent-dim), oklch(0.76 0.09 295 / 0.05))",
            border: "1px solid var(--color-accent-soft)",
            color: "var(--color-accent-2)",
            boxShadow: "0 8px 18px -8px var(--color-accent-glow)",
          }}
        >
          <Package className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h2
            id={titleId}
            className="display-serif text-[17px] font-semibold tracking-tight"
            style={{ color: "var(--color-text)" }}
          >
            {t("batch_add_to_library")}
          </h2>
          <p
            id={descId}
            className="mt-1 text-[12.5px] leading-relaxed"
            style={{ color: "var(--color-text-3)" }}
          >
            {t("batch_add_to_library_description", { title: pageTitle })}
          </p>
          <div
            className="num mt-2 text-[10px] uppercase"
            style={{ color: "var(--color-text-4)", letterSpacing: "1px" }}
          >
            {pageTitle} · {String(displayCount).padStart(2, "0")}
          </div>
        </div>
        <ModalCloseButton onClick={onClose} disabled={submitting} />
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {loading ? (
          <div
            className="flex min-h-[260px] flex-col items-center justify-center gap-3 text-center"
            style={{ color: "var(--color-text-3)" }}
          >
            <Loader2 className="h-5 w-5 motion-safe:animate-spin" />
            <p className="text-[13px]">{t("batch_add_to_library_checking")}</p>
          </div>
        ) : error ? (
          <div
            className="rounded-xl px-4 py-4 text-[13px] leading-relaxed"
            style={{
              color: "oklch(0.85 0.13 75)",
              background: "oklch(0.18 0.06 75 / 0.36)",
              border: "1px solid oklch(0.34 0.11 75 / 0.58)",
            }}
          >
            {error}
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {sections.map((section) => (
              <StatusSection
                key={section.key}
                title={section.title}
                items={section.items}
                emptyLabel={t("batch_add_to_library_none")}
                tone={section.tone}
                projectName={projectName}
              />
            ))}
          </div>
        )}
      </div>

      <div
        className="flex items-center gap-2 px-5 py-3"
        style={{ borderTop: "1px solid var(--color-hairline-soft)" }}
      >
        <span className="flex-1 text-[11px]" style={{ color: "var(--color-text-4)" }}>
          {t("batch_add_to_library_summary", { count: readyCount, total: displayCount })}
        </span>
        <SecondaryButton size="sm" onClick={onClose} disabled={submitting}>
          {t("cancel")}
        </SecondaryButton>
        <PrimaryButton
          size="sm"
          onClick={() => void handleConfirm()}
          disabled={!canConfirm}
          leadingIcon={
            submitting ? <Loader2 className="h-3.5 w-3.5 motion-safe:animate-spin" /> : undefined
          }
        >
          {submitting ? t("loading") : t("confirm_batch_add_to_library")}
        </PrimaryButton>
      </div>
    </GlassModal>
  );
}

function StatusSection({
  title,
  items,
  emptyLabel,
  tone,
  projectName,
}: {
  title: string;
  items: BulkAddToLibraryItem[];
  emptyLabel: string;
  tone: "accent" | "muted";
  projectName: string;
}) {
  const assetFingerprints = useProjectsStore((s) => s.assetFingerprints);
  const toneStyles =
    tone === "accent"
      ? {
          countColor: "var(--color-accent-2)",
          countBg: "var(--color-accent-dim)",
          countBorder: "1px solid var(--color-accent-soft)",
        }
      : {
          countColor: "var(--color-text-3)",
          countBg: "oklch(0.20 0.011 265 / 0.55)",
          countBorder: "1px solid var(--color-hairline)",
        };

  return (
    <section
      className="flex min-h-[280px] flex-col rounded-xl p-3"
      style={{
        background:
          "linear-gradient(180deg, oklch(0.22 0.012 265 / 0.52), oklch(0.19 0.010 265 / 0.36))",
        border: "1px solid var(--color-hairline-soft)",
        boxShadow: "inset 0 1px 0 oklch(1 0 0 / 0.03)",
      }}
    >
      <div className="flex items-center gap-2">
        <h3
          className="display-serif min-w-0 flex-1 truncate text-[14px] font-semibold tracking-tight"
          style={{ color: "var(--color-text)" }}
        >
          {title}
        </h3>
        <span
          className="num inline-flex min-w-7 items-center justify-center rounded-md px-1.5 py-[2px] text-[10px]"
          style={{
            color: toneStyles.countColor,
            background: toneStyles.countBg,
            border: toneStyles.countBorder,
          }}
        >
          {items.length}
        </span>
      </div>

      {items.length === 0 ? (
        <div
          className="flex flex-1 items-center justify-center px-3 text-center text-[12px]"
          style={{ color: "var(--color-text-4)" }}
        >
          {emptyLabel}
        </div>
      ) : (
        <ul className="mt-3 flex-1 space-y-2 overflow-y-auto pr-1">
          {items.map((item) => (
            <li
              key={item.name}
              className="flex gap-2 rounded-lg px-3 py-2 text-[12px]"
              style={{
                color: "var(--color-text-2)",
                background: "oklch(0.18 0.010 265 / 0.55)",
                border: "1px solid var(--color-hairline)",
              }}
            >
              {item.sheetPath && (
                <div
                  className="w-[72px] shrink-0 overflow-hidden rounded-md"
                  style={{ border: "1px solid var(--color-hairline-soft)" }}
                >
                  <AssetThumb
                    imageUrl={API.getFileUrl(
                      projectName,
                      item.sheetPath,
                      assetFingerprints[item.sheetPath] ?? null,
                    )}
                    alt={item.name}
                    fallback={<Package className="h-5 w-5" />}
                    variant="picker"
                  />
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium" style={{ color: "var(--color-text)" }}>
                  {item.name}
                </div>
                {item.description && (
                  <div
                    className="mt-1 line-clamp-2 text-[11px]"
                    style={{ color: "var(--color-text-4)" }}
                  >
                    {item.description}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Check,
  ExternalLink,
  ImageIcon,
  Link2,
  MapPin,
  Puzzle,
  Search,
  User,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { AssetThumb } from "@/components/assets/AssetThumb";
import { GlassModal } from "@/components/ui/GlassModal";
import { ImageLightbox } from "@/components/ui/ImageLightbox";
import { ModalCloseButton } from "@/components/ui/ModalCloseButton";
import { PrimaryButton } from "@/components/ui/PrimaryButton";
import { SecondaryButton } from "@/components/ui/SecondaryButton";
import { useProjectsStore } from "@/stores/projects-store";
import type { Character, Prop, Scene } from "@/types";
import { type AssetKind, SHEET_FIELD } from "@/types/reference-video";
import { WARM_TONE } from "@/utils/severity-tone";

type Asset = Character | Scene | Prop;

const REF_PAGE_SIZE = 50;
const LOAD_MORE_DISTANCE_PX = 160;

interface RefRow {
  kind: AssetKind;
  name: string;
  thumbPath?: string;
  description?: string;
  isStale: boolean;
}

export interface SegmentRefsChanges {
  characters?: string[];
  scenes?: string[];
  props?: string[];
}

interface SegmentRefsEditModalProps {
  open: boolean;
  onClose: () => void;
  onSave: (changes: SegmentRefsChanges) => void | Promise<void>;
  /** 保存中：禁用 Save 按钮防止重复提交；由调用方维护 */
  saving?: boolean;
  initialCharacters: string[];
  initialScenes: string[];
  initialProps: string[];
  characters: Record<string, Character>;
  scenes: Record<string, Scene>;
  props: Record<string, Prop>;
  projectName: string;
  onManageClick?: (kind: AssetKind) => void;
}

function arraysEqualUnordered(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const sa = [...a].sort();
  const sb = [...b].sort();
  return sa.every((v, i) => v === sb[i]);
}

function getSheetPath(kind: AssetKind, asset: Asset): string | undefined {
  const value = (asset as unknown as Record<string, unknown>)[SHEET_FIELD[kind]];
  return typeof value === "string" ? value : undefined;
}

function buildRows<A extends Asset>(
  kind: AssetKind,
  dict: Record<string, A>,
  selected: string[],
): RefRow[] {
  const rows: RefRow[] = Object.entries(dict)
    .map(([name, asset]) => ({
      kind,
      name,
      thumbPath: getSheetPath(kind, asset),
      description: asset.description,
      isStale: false,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
  const stale = selected.filter((n) => !(n in dict)).sort();
  for (const name of stale) rows.push({ kind, name, isStale: true });
  return rows;
}

export function SegmentRefsEditModal({
  open,
  onClose,
  onSave,
  saving = false,
  initialCharacters,
  initialScenes,
  initialProps,
  characters,
  scenes,
  props,
  projectName,
  onManageClick,
}: SegmentRefsEditModalProps) {
  const { t } = useTranslation("dashboard");
  const titleId = useId();
  const gridRef = useRef<HTMLDivElement>(null);
  const [activeKind, setActiveKind] = useState<AssetKind>("character");
  const [queries, setQueries] = useState<Record<AssetKind, string>>({
    character: "",
    scene: "",
    prop: "",
  });
  const [visibleCounts, setVisibleCounts] = useState<Record<AssetKind, number>>({
    character: REF_PAGE_SIZE,
    scene: REF_PAGE_SIZE,
    prop: REF_PAGE_SIZE,
  });
  const [tempChars, setTempChars] = useState<string[]>(initialCharacters);
  const [tempScenes, setTempScenes] = useState<string[]>(initialScenes);
  const [tempProps, setTempProps] = useState<string[]>(initialProps);
  const [previewAsset, setPreviewAsset] = useState<{
    src: string;
    alt: string;
    path?: string;
  } | null>(null);

  const tempCharsSet = useMemo(() => new Set(tempChars), [tempChars]);
  const tempScenesSet = useMemo(() => new Set(tempScenes), [tempScenes]);
  const tempPropsSet = useMemo(() => new Set(tempProps), [tempProps]);

  const charRows = useMemo(
    () => buildRows("character", characters, tempChars),
    [characters, tempChars],
  );
  const sceneRows = useMemo(
    () => buildRows("scene", scenes, tempScenes),
    [scenes, tempScenes],
  );
  const propRows = useMemo(
    () => buildRows("prop", props, tempProps),
    [props, tempProps],
  );

  const rowsByKind = useMemo(
    () => ({
      character: charRows,
      scene: sceneRows,
      prop: propRows,
    }),
    [charRows, sceneRows, propRows],
  );
  const selectedSetByKind = useMemo(
    () => ({
      character: tempCharsSet,
      scene: tempScenesSet,
      prop: tempPropsSet,
    }),
    [tempCharsSet, tempScenesSet, tempPropsSet],
  );
  const activeQuery = queries[activeKind];
  const activeRows = useMemo(() => {
    const q = activeQuery.trim().toLowerCase();
    const rows = rowsByKind[activeKind];
    return q
      ? rows.filter((r) => r.name.toLowerCase().includes(q))
      : rows;
  }, [activeKind, activeQuery, rowsByKind]);
  const visibleRows = activeRows.slice(0, visibleCounts[activeKind]);
  const hasMore = visibleRows.length < activeRows.length;

  // stale 计数基于未过滤的完整 rows，避免搜索词把 stale 项过滤后徽标消失
  const countSelectedStale = (rows: RefRow[], set: Set<string>) =>
    rows.reduce((n, r) => (r.isStale && set.has(r.name) ? n + 1 : n), 0);
  const staleCounts = {
    character: countSelectedStale(charRows, tempCharsSet),
    scene: countSelectedStale(sceneRows, tempScenesSet),
    prop: countSelectedStale(propRows, tempPropsSet),
  };

  const setterByKind: Record<AssetKind, typeof setTempChars> = {
    character: setTempChars,
    scene: setTempScenes,
    prop: setTempProps,
  };
  const toggle = (kind: AssetKind, name: string) => {
    setterByKind[kind]((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  };

  const charChanged = !arraysEqualUnordered(tempChars, initialCharacters);
  const scenesChanged = !arraysEqualUnordered(tempScenes, initialScenes);
  const propsChanged = !arraysEqualUnordered(tempProps, initialProps);
  const hasChanges = charChanged || scenesChanged || propsChanged;
  const groups: Array<{
    kind: AssetKind;
    label: string;
    icon: ReactNode;
    selectedSet: Set<string>;
    staleCount: number;
  }> = [
    {
      kind: "character",
      label: t("segment_refs_group_character", { defaultValue: "角色集" }),
      icon: <User className="h-3.5 w-3.5" aria-hidden="true" />,
      selectedSet: tempCharsSet,
      staleCount: staleCounts.character,
    },
    {
      kind: "scene",
      label: t("segment_refs_group_scene", { defaultValue: "场景集" }),
      icon: <MapPin className="h-3.5 w-3.5" aria-hidden="true" />,
      selectedSet: tempScenesSet,
      staleCount: staleCounts.scene,
    },
    {
      kind: "prop",
      label: t("segment_refs_group_prop", { defaultValue: "道具集" }),
      icon: <Puzzle className="h-3.5 w-3.5" aria-hidden="true" />,
      selectedSet: tempPropsSet,
      staleCount: staleCounts.prop,
    },
  ];
  const activeGroup = groups.find((g) => g.kind === activeKind) ?? groups[0];

  useEffect(() => {
    if (gridRef.current) gridRef.current.scrollTop = 0;
  }, [activeKind, activeQuery]);

  const loadMore = useCallback(() => {
    setVisibleCounts((prev) => ({
      ...prev,
      [activeKind]: Math.min(
        activeRows.length,
        prev[activeKind] + REF_PAGE_SIZE,
      ),
    }));
  }, [activeKind, activeRows.length]);

  const handleGridScroll = useCallback(() => {
    const el = gridRef.current;
    if (!el || !hasMore) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceToBottom <= LOAD_MORE_DISTANCE_PX) loadMore();
  }, [hasMore, loadMore]);

  const handleSave = async () => {
    const changes: SegmentRefsChanges = {};
    if (charChanged) changes.characters = tempChars;
    if (scenesChanged) changes.scenes = tempScenes;
    if (propsChanged) changes.props = tempProps;
    await onSave(changes);
  };

  return (
    <GlassModal
      open={open}
      onClose={onClose}
      labelledBy={titleId}
      widthClassName="w-[860px] max-w-[96vw]"
      panelClassName="flex max-h-[90vh] flex-col"
    >
        {/* Header */}
        <div
          className="flex items-center gap-3 px-5 py-4"
          style={{ borderBottom: "1px solid var(--color-hairline-soft)" }}
        >
          <span
            aria-hidden
            className="grid h-9 w-9 shrink-0 place-items-center rounded-lg"
            style={{
              background:
                "linear-gradient(135deg, var(--color-accent-dim), oklch(0.76 0.09 295 / 0.05))",
              border: "1px solid var(--color-accent-soft)",
              color: "var(--color-accent-2)",
              boxShadow: "0 8px 18px -8px var(--color-accent-glow)",
            }}
          >
            <Link2 className="h-4 w-4" />
          </span>
          <div className="min-w-0 flex-1">
            <h3
              id={titleId}
              className="display-serif truncate text-[15px] font-semibold tracking-tight"
              style={{ color: "var(--color-text)" }}
            >
              {t("segment_refs_edit_title")}
            </h3>
            <div
              className="num text-[10px] uppercase"
              style={{
                color: "var(--color-text-4)",
                letterSpacing: "1.0px",
              }}
            >
              {t("eyebrow_segment_refs")}
            </div>
          </div>

          <ModalCloseButton onClick={onClose} ariaLabel={t("segment_refs_close")} />
        </div>

        {/* Body */}
        <div className="flex min-h-0 flex-1 flex-col">
          <div
            className="flex items-center gap-2 px-5 py-3"
            style={{ borderBottom: "1px solid var(--color-hairline-soft)" }}
          >
            {groups.map((group) => {
              const active = group.kind === activeKind;
              const rows = rowsByKind[group.kind];
              const selectedCount = rows.reduce(
                (n, r) => (group.selectedSet.has(r.name) ? n + 1 : n),
                0,
              );
              return (
                <button
                  key={group.kind}
                  type="button"
                  onClick={() => {
                    setActiveKind(group.kind);
                    setVisibleCounts((prev) => ({
                      ...prev,
                      [group.kind]: REF_PAGE_SIZE,
                    }));
                  }}
                  className="focus-ring inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[12px] font-medium transition-colors"
                  style={{
                    color: active ? "var(--color-text)" : "var(--color-text-4)",
                    background: active
                      ? "oklch(0.23 0.012 265 / 0.78)"
                      : "oklch(0.17 0.010 265 / 0.45)",
                    border: active
                      ? "1px solid var(--color-accent-soft)"
                      : "1px solid var(--color-hairline)",
                  }}
                >
                  <span style={{ color: active ? "var(--color-accent-2)" : "var(--color-text-4)" }}>
                    {group.icon}
                  </span>
                  <span>{group.label}</span>
                  <span
                    className="num rounded px-1.5 py-px text-[10px]"
                    style={{
                      color: active ? "var(--color-accent-2)" : "var(--color-text-4)",
                      background: "oklch(0.10 0.008 265 / 0.42)",
                    }}
                  >
                    {selectedCount}/{rows.length}
                  </span>
                  {group.staleCount > 0 && (
                    <span
                      className="num rounded px-1 py-px text-[10px]"
                      style={{
                        color: WARM_TONE.color,
                        background: WARM_TONE.soft,
                      }}
                    >
                      {group.staleCount}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          <div
            className="flex items-center gap-3 px-5 py-3"
            style={{ borderBottom: "1px solid var(--color-hairline-soft)" }}
          >
            <div
              className="flex flex-1 items-center gap-2 rounded-md px-2.5 py-1.5"
              style={{
                background: "oklch(0.16 0.010 265 / 0.6)",
                border: "1px solid var(--color-hairline)",
              }}
            >
              <Search
                className="h-3.5 w-3.5 shrink-0"
                style={{ color: "var(--color-text-4)" }}
                aria-hidden="true"
              />
              <input
                type="search"
                value={activeQuery}
                onChange={(e) => {
                  const value = e.target.value;
                  setQueries((prev) => ({ ...prev, [activeKind]: value }));
                  setVisibleCounts((prev) => ({
                    ...prev,
                    [activeKind]: REF_PAGE_SIZE,
                  }));
                }}
                placeholder={t("segment_refs_search_group_placeholder", {
                  group: activeGroup.label,
                  defaultValue: "搜索{{group}}…",
                })}
                aria-label={t("segment_refs_search_group_aria", {
                  group: activeGroup.label,
                  defaultValue: "搜索{{group}}",
                })}
                autoComplete="off"
                spellCheck={false}
                className="min-w-0 flex-1 bg-transparent text-[13px] outline-none"
                style={{ color: "var(--color-text)" }}
              />
            </div>
            <span
              className="num text-[11px]"
              style={{ color: "var(--color-text-4)" }}
            >
              {visibleRows.length}/{activeRows.length}
            </span>
          </div>

          <div
            ref={gridRef}
            data-testid={`segment-refs-grid-${activeKind}`}
            onScroll={handleGridScroll}
            className="grid flex-1 grid-cols-4 gap-2 overflow-y-auto p-3"
          >
            {activeRows.length === 0 && activeQuery.trim() && (
              <p
                className="col-span-4 px-4 py-12 text-center text-[12px]"
                style={{ color: "var(--color-text-4)" }}
              >
                {t("segment_refs_search_empty")}
              </p>
            )}
            {activeRows.length === 0 && !activeQuery.trim() && (
              <div
                className="col-span-4 flex items-center gap-2 rounded-md px-3 py-2 text-[12px]"
                style={{
                  border: "1px dashed var(--color-hairline)",
                  color: "var(--color-text-4)",
                }}
              >
                <span className="flex-1">
                  {activeKind === "character"
                    ? t("segment_refs_empty_characters")
                    : t("segment_refs_empty_clues")}
                </span>
                {onManageClick && (
                  <button
                    type="button"
                    onClick={() => onManageClick(activeKind)}
                    className="focus-ring inline-flex items-center gap-1 rounded transition-colors"
                    style={{ color: "var(--color-accent-2)" }}
                  >
                    <span>{t("segment_refs_manage_link")}</span>
                    <ExternalLink className="h-3 w-3" aria-hidden="true" />
                  </button>
                )}
              </div>
            )}
            {visibleRows.map((row) => (
              <RefAssetCard
                key={`${row.kind}-${row.name}`}
                row={row}
                selected={selectedSetByKind[row.kind].has(row.name)}
                onToggle={() => toggle(row.kind, row.name)}
                projectName={projectName}
                staleHint={t("segment_refs_stale_hint")}
                onPreview={setPreviewAsset}
              />
            ))}
            {hasMore && (
              <div className="col-span-4 flex justify-center py-2">
                <SecondaryButton size="sm" onClick={loadMore}>
                  {t("load_more", { defaultValue: "加载更多" })}
                </SecondaryButton>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div
          className="flex items-center gap-2 px-5 py-3"
          style={{
            borderTop: "1px solid var(--color-hairline-soft)",
            background: "oklch(0.17 0.010 250 / 0.5)",
          }}
        >
          <span
            className="num flex-1 text-[11px] uppercase"
            style={{
              letterSpacing: "0.8px",
              color: hasChanges ? WARM_TONE.color : "var(--color-text-4)",
            }}
          >
            {hasChanges
              ? t("segment_refs_changes_pending")
              : t("segment_refs_no_changes")}
          </span>
          <SecondaryButton size="sm" onClick={onClose} disabled={saving}>
            {t("segment_refs_cancel")}
          </SecondaryButton>
          <PrimaryButton
            size="sm"
            disabled={!hasChanges || saving}
            onClick={() => void handleSave()}
          >
            {saving ? t("shot_detail_saving") : t("segment_refs_save")}
          </PrimaryButton>
        </div>
        {previewAsset && (
          <ImageLightbox
            src={previewAsset.src}
            alt={previewAsset.alt}
            downloadSource={
              previewAsset.path
                ? { kind: "project", projectName, path: previewAsset.path }
                : undefined
            }
            onClose={() => setPreviewAsset(null)}
          />
        )}
    </GlassModal>
  );
}

interface RowProps {
  row: RefRow;
  selected: boolean;
  onToggle: () => void;
  projectName: string;
  staleHint: string;
  onPreview: (asset: { src: string; alt: string; path?: string } | null) => void;
}

function RefAssetCard({
  row,
  selected,
  onToggle,
  projectName,
  staleHint,
  onPreview,
}: RowProps) {
  const sheetFp = useProjectsStore((s) =>
    row.thumbPath ? s.getAssetFingerprint(row.thumbPath) : null,
  );
  const showImage = !!row.thumbPath && !row.isStale;
  const thumbSrc = showImage && row.thumbPath
    ? API.getFileUrl(projectName, row.thumbPath, sheetFp)
    : null;
  const description = row.description?.split("\n")[0] ?? "";

  const baseStyle = row.isStale
    ? {
        background: WARM_TONE.soft,
        border: `1px solid ${WARM_TONE.ring}`,
      }
    : selected
      ? {
          background:
            "linear-gradient(135deg, var(--color-accent-dim) 0%, oklch(0.20 0.011 265 / 0.5) 60%)",
          border: "1px solid var(--color-accent-soft)",
          boxShadow:
            "inset 0 1px 0 oklch(1 0 0 / 0.04), 0 4px 14px -6px var(--color-accent-glow)",
        }
      : {
          background: "oklch(0.20 0.011 265 / 0.4)",
          border: "1px solid var(--color-hairline)",
        };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={(e) => {
        if (
          e.target instanceof Element &&
          e.target.closest("[data-ref-preview-trigger='true']")
        ) {
          return;
        }
        onToggle();
      }}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return;
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        onToggle();
      }}
      aria-pressed={selected}
      title={row.isStale ? staleHint : row.name}
      className="focus-ring relative rounded-lg p-2 text-left transition-colors"
      style={baseStyle}
      onMouseEnter={(e) => {
        if (row.isStale || selected) return;
        e.currentTarget.style.borderColor = "var(--color-hairline-strong)";
        e.currentTarget.style.background = "oklch(0.22 0.011 265 / 0.7)";
      }}
      onMouseLeave={(e) => {
        if (row.isStale || selected) return;
        e.currentTarget.style.borderColor = "var(--color-hairline)";
        e.currentTarget.style.background = "oklch(0.20 0.011 265 / 0.5)";
      }}
    >
      {thumbSrc && row.thumbPath ? (
        <button
          type="button"
          data-ref-preview-trigger="true"
          onClick={(event) => {
            event.stopPropagation();
            onPreview({
              src: thumbSrc,
              alt: row.name,
              path: row.thumbPath,
            });
          }}
          onKeyDown={(event) => event.stopPropagation()}
          aria-label={`${row.name} 全屏预览`}
          className="block w-full cursor-zoom-in rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <AssetThumb
            imageUrl={thumbSrc}
            alt={row.name}
            fallback="—"
            variant="picker"
          />
        </button>
      ) : (
        <AssetThumb
          imageUrl={null}
          alt={row.name}
          fallback={
            row.isStale ? (
              <span className="text-[10px]">{staleHint}</span>
            ) : (
              <ImageIcon className="h-5 w-5" aria-hidden="true" />
            )
          }
          variant="picker"
        />
      )}
      <div
        className="mt-1.5 truncate text-[12px] font-semibold"
        style={{ color: row.isStale ? WARM_TONE.color : "var(--color-text)" }}
      >
        {row.name}
      </div>
      {row.isStale ? (
        <div
          className="truncate text-[10px]"
          style={{ color: WARM_TONE.color }}
        >
          {staleHint}
        </div>
      ) : (
        description && (
          <div
            className="truncate text-[10px]"
            style={{ color: "var(--color-text-4)" }}
          >
            {description}
          </div>
        )
      )}
      {selected && (
        <span
          aria-hidden
          className="absolute right-1.5 top-1.5 grid h-5 w-5 place-items-center rounded-full"
          style={{
            color: "oklch(0.14 0 0)",
            background:
              "linear-gradient(135deg, var(--color-accent-2), var(--color-accent))",
            boxShadow:
              "inset 0 1px 0 oklch(1 0 0 / 0.35), 0 0 0 1px var(--color-accent-soft)",
          }}
        >
          <Check className="h-3 w-3" strokeWidth={3} />
        </span>
      )}
      {row.isStale && (
        <span
          className="num absolute left-1.5 top-1.5 rounded px-1.5 py-0.5 text-[9.5px]"
          style={{
            letterSpacing: "0.4px",
            color: WARM_TONE.color,
            background: WARM_TONE.soft,
            border: `1px solid ${WARM_TONE.ring}`,
          }}
        >
          {row.name}
        </span>
      )}
    </div>
  );
}

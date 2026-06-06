import { useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import { Edit3, MapPin, Plus, Puzzle, User } from "lucide-react";
import { API } from "@/api";
import { Popover } from "@/components/ui/Popover";
import { PreviewableImageFrame } from "@/components/ui/PreviewableImageFrame";
import {
  SegmentRefsEditModal,
  type SegmentRefsChanges,
} from "@/components/ui/SegmentRefsEditModal";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import type { Character, Prop, Scene } from "@/types";
import { type AssetKind, SHEET_FIELD } from "@/types/reference-video";
import { errMsg } from "@/utils/async";
import { colorForName } from "@/utils/color";
import { WARM_TONE } from "@/utils/severity-tone";

type CharField = "characters_in_segment" | "characters_in_scene";

interface ReferencesSectionProps {
  projectName: string;
  segmentId: string;
  scriptFile?: string;
  contentMode: "narration" | "drama";
  characterNames: string[];
  sceneNames: string[];
  propNames: string[];
  onSave: (patch: Record<string, string[]>) => void | Promise<void>;
  disabled?: boolean;
  disabledHint?: string;
}

const EMPTY_DICT = Object.freeze({});

type RefAsset = Character | Scene | Prop;

const KIND_BADGE_CLASS: Record<AssetKind, string> = {
  character: "bg-indigo-800/60 text-indigo-300",
  scene: "bg-amber-800/60 text-amber-300",
  prop: "bg-emerald-800/60 text-emerald-300",
};

const KIND_BADGE_KEY: Record<
  AssetKind,
  | "segment_refs_badge_character"
  | "segment_refs_badge_scene"
  | "segment_refs_badge_prop"
> = {
  character: "segment_refs_badge_character",
  scene: "segment_refs_badge_scene",
  prop: "segment_refs_badge_prop",
};

function countMissing(names: string[], dict: Record<string, unknown>): number {
  let n = 0;
  for (const name of names) if (!Object.hasOwn(dict, name)) n += 1;
  return n;
}

function sheetPathFor(kind: AssetKind, asset: RefAsset | undefined): string | undefined {
  if (!asset) return undefined;
  const value = (asset as unknown as Record<string, unknown>)[SHEET_FIELD[kind]];
  return typeof value === "string" && value ? value : undefined;
}

function assetImageShape(kind: AssetKind): string {
  return kind === "character" ? "rounded-full" : "rounded-md";
}

function popoverImageSize(kind: AssetKind): string {
  return kind === "character" ? "h-[108px] w-[108px]" : "h-[120px] w-[90px]";
}

export function ReferencesSection({
  projectName,
  segmentId,
  scriptFile,
  contentMode,
  characterNames,
  sceneNames,
  propNames,
  onSave,
  disabled,
  disabledHint,
}: ReferencesSectionProps) {
  const { t } = useTranslation("dashboard");
  const project = useProjectsStore((s) => s.currentProjectData);
  // 用 useMemo 把 `?? {}` fallback 物化成稳定引用，避免 hook deps 每次重算
  const characters = useMemo(() => project?.characters ?? EMPTY_DICT, [project]);
  const scenes = useMemo(() => project?.scenes ?? EMPTY_DICT, [project]);
  const props = useMemo(() => project?.props ?? EMPTY_DICT, [project]);
  const [open, setOpen] = useState(false);
  const pushToast = useAppStore((s) => s.pushToast);

  const charField: CharField =
    contentMode === "drama" ? "characters_in_scene" : "characters_in_segment";

  const totalCount = characterNames.length + sceneNames.length + propNames.length;
  const isEmpty = totalCount === 0;

  const totalStale = useMemo(() => {
    // project 未加载完时字典为空，会把所有已引用名都误判为 stale；此时跳过计算
    if (!project) return 0;
    return (
      countMissing(characterNames, characters) +
      countMissing(sceneNames, scenes) +
      countMissing(propNames, props)
    );
  }, [project, characterNames, sceneNames, propNames, characters, scenes, props]);

  const [saving, setSaving] = useState(false);

  const handleSave = async (changes: SegmentRefsChanges) => {
    const patch: Record<string, string[]> = {};
    if (changes.characters !== undefined) patch[charField] = changes.characters;
    if (changes.scenes !== undefined) patch.scenes = changes.scenes;
    if (changes.props !== undefined) patch.props = changes.props;
    if (Object.keys(patch).length === 0) {
      setOpen(false);
      return;
    }
    setSaving(true);
    try {
      if (!scriptFile) {
        const message = t("segment_refs_missing_script_file", {
          defaultValue: "缺少剧本文件，无法检查参考图上限，请刷新项目后重试。",
        });
        pushToast(message, "warning");
        throw new Error(message);
      }
      try {
        await API.previewStoryboardReferenceUsage(projectName, segmentId, {
          script_file: scriptFile,
          characters: changes.characters ?? characterNames,
          scenes: changes.scenes ?? sceneNames,
          props: changes.props ?? propNames,
        });
      } catch (err) {
        const message = errMsg(err);
        pushToast(message, "warning");
        throw new Error(message);
      }
      await onSave(patch);
      setOpen(false);
    } finally {
      setSaving(false);
    }
  };

  const openModal = () => {
    if (disabled) return;
    setOpen(true);
  };

  const eyebrow = (
    <div
      className="text-[10.5px] font-bold uppercase"
      style={{
        color: "var(--color-text-4)",
        letterSpacing: "1px",
        fontFamily: "var(--font-mono)",
      }}
    >
      {t("eyebrow_segment_refs")}
    </div>
  );

  const modal = open ? (
    <SegmentRefsEditModal
      open={open}
      onClose={() => setOpen(false)}
      onSave={handleSave}
      saving={saving}
      initialCharacters={characterNames}
      initialScenes={sceneNames}
      initialProps={propNames}
      characters={characters}
      scenes={scenes}
      props={props}
      projectName={projectName}
    />
  ) : null;

  if (isEmpty) {
    return (
      <div>
        <div className="mb-2 flex items-center justify-between">{eyebrow}</div>
        <button
          type="button"
          onClick={openModal}
          disabled={disabled}
          title={disabled ? disabledHint : t("references_add_cta")}
          className="focus-ring group flex w-full items-center gap-2.5 rounded-md px-3 py-2.5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50"
          style={{
            border: "1px dashed var(--color-hairline)",
            color: "var(--color-text-4)",
            background: "transparent",
          }}
          onMouseEnter={(e) => {
            if (disabled) return;
            e.currentTarget.style.borderColor = "var(--color-hairline-strong)";
            e.currentTarget.style.borderStyle = "solid";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = "var(--color-hairline)";
            e.currentTarget.style.borderStyle = "dashed";
          }}
        >
          <span className="flex-1 truncate text-[12px]">
            {t("references_empty_full")}
          </span>
          <span
            className="num inline-flex shrink-0 items-center gap-1 text-[11px]"
            style={{ color: "var(--color-accent-2)" }}
          >
            <Plus className="h-3 w-3" aria-hidden="true" />
            <span>{t("references_add_cta")}</span>
          </span>
        </button>
        {modal}
      </div>
    );
  }

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        {eyebrow}
        {totalStale > 0 && (
          <span
            className="num inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px]"
            style={{
              background: WARM_TONE.soft,
              border: `1px solid ${WARM_TONE.ring}`,
              color: WARM_TONE.color,
            }}
            title={t("segment_refs_stale_hint")}
          >
            <span aria-hidden="true">⚠</span>
            <span>{t("segment_refs_stale_badge", { count: totalStale })}</span>
          </span>
        )}
        <span className="flex-1" />
        <button
          type="button"
          onClick={openModal}
          disabled={disabled}
          title={disabled ? disabledHint : t("segment_refs_edit_button")}
          aria-label={t("segment_refs_edit_button")}
          className="focus-ring inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] transition-colors disabled:cursor-not-allowed disabled:opacity-50"
          style={{
            color: "var(--color-text-3)",
            background: "transparent",
          }}
          onMouseEnter={(e) => {
            if (disabled) return;
            e.currentTarget.style.color = "var(--color-accent-2)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = "var(--color-text-3)";
          }}
        >
          <Edit3 className="h-3 w-3" aria-hidden="true" />
        </button>
      </div>

      <div className="flex w-full flex-col gap-3 px-1 py-0.5">
        {characterNames.length > 0 && (
          <ReferenceGroup
            icon={<User className="h-3 w-3" aria-hidden="true" />}
            label={t("references_badge_character")}
            kind="character"
            names={characterNames}
            assets={characters}
            projectName={projectName}
          />
        )}
        {sceneNames.length > 0 && (
          <ReferenceGroup
            icon={<MapPin className="h-3 w-3" aria-hidden="true" />}
            label={t("references_badge_scene")}
            kind="scene"
            names={sceneNames}
            assets={scenes}
            projectName={projectName}
          />
        )}
        {propNames.length > 0 && (
          <ReferenceGroup
            icon={<Puzzle className="h-3 w-3" aria-hidden="true" />}
            label={t("references_badge_prop")}
            kind="prop"
            names={propNames}
            assets={props}
            projectName={projectName}
          />
        )}
      </div>

      {modal}
    </div>
  );
}

function ReferenceGroup({
  icon,
  label,
  kind,
  names,
  assets,
  projectName,
}: {
  icon: ReactNode;
  label: string;
  kind: AssetKind;
  names: string[];
  assets: Record<string, RefAsset>;
  projectName: string;
}) {
  return (
    <div className="flex w-full min-w-0 flex-col gap-1.5">
      <div
        className="inline-flex h-4 items-center gap-1 text-[11px] font-medium leading-none"
        style={{ color: "var(--color-text-3)" }}
      >
        <span className="inline-flex h-4 items-center" style={{ color: "var(--color-text-4)" }}>
          {icon}
        </span>
        <span className="inline-flex h-4 items-center">{label}</span>
        <span
          className="num inline-flex h-4 items-center"
          style={{ color: "var(--color-text-2)" }}
        >
          {names.length}
        </span>
      </div>
      <div className="flex flex-col gap-1">
        {names.map((name) => (
          <ReferenceRow
            key={`${kind}-${name}`}
            kind={kind}
            name={name}
            asset={assets[name]}
            projectName={projectName}
          />
        ))}
      </div>
    </div>
  );
}

function ReferenceRow({
  kind,
  name,
  asset,
  projectName,
}: {
  kind: AssetKind;
  name: string;
  asset: RefAsset | undefined;
  projectName: string;
}) {
  const sheetPath = sheetPathFor(kind, asset);
  const sheetFp = useProjectsStore((s) =>
    sheetPath ? s.getAssetFingerprint(sheetPath) : null,
  );
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const rowRef = useRef<HTMLButtonElement>(null);
  const currentKey = sheetPath ? `${sheetPath}#${sheetFp ?? ""}` : null;
  const showImage = !!sheetPath && errorKey !== currentKey;
  const iconClass = "h-4 w-4";
  const Icon = kind === "character" ? User : kind === "scene" ? MapPin : Puzzle;
  const imageShape = assetImageShape(kind);

  return (
    <>
      <button
        ref={rowRef}
        type="button"
        onClick={() => {
          if (asset) setPopoverOpen(true);
        }}
        disabled={!asset}
        title={name}
        className="focus-ring flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors disabled:cursor-default"
        style={{ background: "oklch(0.16 0.010 265 / 0.38)" }}
        onMouseEnter={(e) => {
          if (!asset) return;
          e.currentTarget.style.background = "oklch(0.21 0.014 265 / 0.52)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "oklch(0.16 0.010 265 / 0.38)";
        }}
      >
        {showImage ? (
          <img
            src={API.getFileUrl(projectName, sheetPath, sheetFp)}
            alt={name}
            className={`h-9 w-9 shrink-0 object-cover ${imageShape}`}
            onError={() => setErrorKey(currentKey)}
          />
        ) : (
          <span
            className={`flex h-9 w-9 shrink-0 items-center justify-center text-[12px] font-semibold text-white ${
              asset ? colorForName(name) : "bg-gray-800"
            } ${imageShape}`}
          >
            {asset ? name.charAt(0) : <Icon className={iconClass} aria-hidden="true" />}
          </span>
        )}
        <span
          className="min-w-0 flex-1 truncate text-[12px]"
          style={{ color: asset ? "var(--color-text-2)" : "var(--color-text-4)" }}
        >
          {name}
        </span>
        {!asset && (
          <span
            className="num shrink-0 text-[10px]"
            style={{ color: WARM_TONE.color }}
            aria-label="missing"
          >
            ⚠
          </span>
        )}
      </button>
      {asset && (
        <ReferenceAssetPopover
          open={popoverOpen}
          onClose={() => setPopoverOpen(false)}
          kind={kind}
          name={name}
          asset={asset}
          projectName={projectName}
          anchorRef={rowRef}
          sheetPath={sheetPath}
          sheetFp={sheetFp}
        />
      )}
    </>
  );
}

function ReferenceAssetPopover({
  open,
  onClose,
  kind,
  name,
  asset,
  projectName,
  anchorRef,
  sheetPath,
  sheetFp,
}: {
  open: boolean;
  onClose: () => void;
  kind: AssetKind;
  name: string;
  asset: RefAsset;
  projectName: string;
  anchorRef: RefObject<HTMLButtonElement | null>;
  sheetPath: string | undefined;
  sheetFp: number | null;
}) {
  const { t } = useTranslation("dashboard");
  const firstLine = asset.description?.split("\n")[0] ?? "";
  const imageSrc = sheetPath ? API.getFileUrl(projectName, sheetPath, sheetFp) : null;
  const Icon = kind === "character" ? User : kind === "scene" ? MapPin : Puzzle;
  const imageClassName = `${popoverImageSize(kind)} shrink-0 object-cover ${assetImageShape(kind)}`;

  return (
    <Popover
      open={open}
      onClose={onClose}
      anchorRef={anchorRef}
      align="center"
      sideOffset={6}
      width="w-[26rem]"
      layer="modal"
      className="max-w-[calc(100vw-1.5rem)] rounded-lg border border-gray-700 p-2 shadow-xl"
    >
      <div className="flex items-start gap-2.5">
        {sheetPath && imageSrc ? (
          <PreviewableImageFrame
            src={imageSrc}
            alt={name}
            downloadSource={{
              kind: "project",
              projectName,
              path: sheetPath,
            }}
          >
            <img
              src={imageSrc}
              alt={name}
              className={imageClassName}
            />
          </PreviewableImageFrame>
        ) : (
          <div
            className={`flex ${popoverImageSize(kind)} shrink-0 items-center justify-center bg-gray-800 ${assetImageShape(kind)}`}
          >
            <Icon className="h-8 w-8 text-gray-600" aria-hidden />
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <p className="truncate text-sm font-medium text-white">{name}</p>
            <span
              className={`shrink-0 rounded px-1 py-0.5 text-[10px] font-semibold ${KIND_BADGE_CLASS[kind]}`}
            >
              {t(KIND_BADGE_KEY[kind])}
            </span>
          </div>
          {firstLine && (
            <p className="mt-0.5 line-clamp-4 whitespace-normal break-words text-xs leading-relaxed text-gray-400">
              {firstLine}
            </p>
          )}
        </div>
      </div>
    </Popover>
  );
}

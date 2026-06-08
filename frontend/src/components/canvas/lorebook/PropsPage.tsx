import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Package } from "lucide-react";
import { GalleryToolbar } from "./GalleryToolbar";
import { PropCard } from "./PropCard";
import { BulkAddToLibraryDialog } from "@/components/assets/BulkAddToLibraryDialog";
import { AssetFormModal } from "@/components/assets/AssetFormModal";
import { AssetPickerModal } from "@/components/assets/AssetPickerModal";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useScrollTarget } from "@/hooks/useScrollTarget";
import { errMsg } from "@/utils/async";
import type { Prop } from "@/types";
import { GalleryEmptyState } from "./GalleryEmptyState";

interface Props {
  projectName: string;
  props: Record<string, Prop>;
  onUpdateProp: (name: string, updates: Partial<Prop>) => void;
  onGenerateProp: (name: string) => void;
  onAddProp: (name: string, description: string) => Promise<void>;
  onRestorePropVersion?: () => Promise<void> | void;
  onRefreshProject?: () => Promise<void> | void;
  generatingPropNames?: Set<string>;
}

export function PropsPage({ projectName, props, onUpdateProp, onGenerateProp, onAddProp, onRestorePropVersion, onRefreshProject, generatingPropNames }: Props) {
  const { t } = useTranslation(["dashboard", "assets"]);
  const [adding, setAdding] = useState(false);
  const [picking, setPicking] = useState(false);
  const [bulkAdding, setBulkAdding] = useState(false);
  const [search, setSearch] = useState("");

  useScrollTarget("prop");

  const entries = useMemo(() => Object.entries(props), [props]);
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filteredEntries = useMemo(() => {
    if (!normalizedSearch) return entries;
    return entries.filter(([name]) => name.toLocaleLowerCase().includes(normalizedSearch));
  }, [entries, normalizedSearch]);
  const bulkItems = useMemo(
    () =>
      filteredEntries.map(([name, prop]) => ({
        name,
        description: prop.description,
        sheetPath: prop.prop_sheet ?? null,
      })),
    [filteredEntries],
  );

  const handleImport = async (ids: string[]) => {
    try {
      await API.applyAssetsToProject({
        asset_ids: ids,
        target_project: projectName,
        conflict_policy: "skip",
      });
      useAppStore.getState().pushToast(t("assets:import_count", { count: ids.length }), "success");
      await onRefreshProject?.();
    } catch (err) {
      useAppStore.getState().pushToast(errMsg(err), "error");
    } finally {
      setPicking(false);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <GalleryToolbar
        title={t("dashboard:props")}
        count={filteredEntries.length}
        onAdd={() => setAdding(true)}
        onBulkAddToLibrary={() => setBulkAdding(true)}
        bulkAddDisabled={filteredEntries.length === 0}
        onPickFromLibrary={() => setPicking(true)}
        searchValue={search}
        searchPlaceholder={t("dashboard:lorebook_search_placeholder")}
        onSearchChange={setSearch}
      />
      <div className="px-5 py-5">
        {entries.length === 0 ? (
          <GalleryEmptyState
            icon={<Package className="h-6 w-6" />}
            label={t("dashboard:props")}
            hint={t("dashboard:no_props_hint_clickable")}
            onClick={() => setAdding(true)}
          />
        ) : filteredEntries.length === 0 ? (
          <div
            className="rounded-xl px-6 py-14 text-center text-[13px]"
            style={{
              color: "var(--color-text-4)",
              background: "oklch(0.18 0.010 265 / 0.35)",
              border: "1px solid var(--color-hairline-soft)",
            }}
          >
            {t("dashboard:lorebook_no_search_results")}
          </div>
        ) : (
          <div className="grid justify-evenly gap-4 [grid-template-columns:repeat(auto-fill,320px)]">
            {filteredEntries.map(([name, prop]) => (
              <PropCard key={name} name={name} prop={prop} projectName={projectName}
                onUpdate={onUpdateProp}
                onGenerate={onGenerateProp}
                onRestoreVersion={onRestorePropVersion}
                onReload={onRefreshProject}
                generating={generatingPropNames?.has(name)}
              />
            ))}
          </div>
        )}
      </div>

      {adding && (
        <AssetFormModal
          type="prop"
          mode="create"
          onClose={() => setAdding(false)}
          onSubmit={async ({ name, description }) => {
            await onAddProp(name, description);
            setAdding(false);
          }}
        />
      )}

      {picking && (
        <AssetPickerModal
          type="prop"
          existingNames={new Set(Object.keys(props))}
          onClose={() => setPicking(false)}
          onImport={(ids) => { void handleImport(ids); }}
        />
      )}

      {bulkAdding && (
        <BulkAddToLibraryDialog
          pageTitle={t("dashboard:props")}
          projectName={projectName}
          resourceType="prop"
          items={bulkItems}
          onClose={() => setBulkAdding(false)}
        />
      )}
    </div>
  );
}

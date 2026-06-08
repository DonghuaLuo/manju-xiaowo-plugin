import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { User } from "lucide-react";
import { GalleryToolbar } from "./GalleryToolbar";
import { CharacterCard } from "./CharacterCard";
import { BulkAddToLibraryDialog } from "@/components/assets/BulkAddToLibraryDialog";
import { AssetFormModal } from "@/components/assets/AssetFormModal";
import { AssetPickerModal } from "@/components/assets/AssetPickerModal";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useScrollTarget } from "@/hooks/useScrollTarget";
import { errMsg } from "@/utils/async";
import type { Character } from "@/types";
import { GalleryEmptyState } from "./GalleryEmptyState";
import type { UploadFileInput } from "@/utils/desktop-file";

interface Props {
  projectName: string;
  characters: Record<string, Character>;
  onSaveCharacter: (name: string, payload: { description: string; voiceStyle: string; referenceFile?: UploadFileInput | null }) => Promise<void>;
  onGenerateCharacter: (name: string) => void;
  onAddCharacter: (name: string, description: string, voiceStyle: string, referenceFile?: UploadFileInput | null) => Promise<void>;
  onRestoreCharacterVersion?: () => Promise<void> | void;
  onRefreshProject?: () => Promise<void> | void;
  generatingCharacterNames?: Set<string>;
}

export function CharactersPage({ projectName, characters, onSaveCharacter, onGenerateCharacter, onAddCharacter, onRestoreCharacterVersion, onRefreshProject, generatingCharacterNames }: Props) {
  const { t } = useTranslation(["dashboard", "assets"]);
  const [adding, setAdding] = useState(false);
  const [picking, setPicking] = useState(false);
  const [bulkAdding, setBulkAdding] = useState(false);
  const [search, setSearch] = useState("");

  useScrollTarget("character");

  const entries = useMemo(() => Object.entries(characters), [characters]);
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filteredEntries = useMemo(() => {
    if (!normalizedSearch) return entries;
    return entries.filter(([name]) => name.toLocaleLowerCase().includes(normalizedSearch));
  }, [entries, normalizedSearch]);
  const bulkItems = useMemo(
    () =>
      filteredEntries.map(([name, character]) => ({
        name,
        description: character.description,
        voiceStyle: character.voice_style ?? "",
        sheetPath: character.character_sheet ?? null,
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
        title={t("dashboard:characters")}
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
            icon={<User className="h-6 w-6" />}
            label={t("dashboard:characters")}
            hint={t("dashboard:no_characters_hint_clickable")}
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
            {filteredEntries.map(([name, char]) => (
              <CharacterCard key={name} name={name} character={char} projectName={projectName}
                onSave={onSaveCharacter}
                onGenerate={onGenerateCharacter}
                onRestoreVersion={onRestoreCharacterVersion}
                onReload={onRefreshProject}
                generating={generatingCharacterNames?.has(name)}
              />
            ))}
          </div>
        )}
      </div>

      {adding && (
        <AssetFormModal
          type="character"
          mode="create"
          onClose={() => setAdding(false)}
          onSubmit={async ({ name, description, voice_style, image }) => {
            await onAddCharacter(name, description, voice_style, image ?? null);
            setAdding(false);
          }}
        />
      )}

      {picking && (
        <AssetPickerModal
          type="character"
          existingNames={new Set(Object.keys(characters))}
          onClose={() => setPicking(false)}
          onImport={(ids) => { void handleImport(ids); }}
        />
      )}

      {bulkAdding && (
        <BulkAddToLibraryDialog
          pageTitle={t("dashboard:characters")}
          projectName={projectName}
          resourceType="character"
          items={bulkItems}
          onClose={() => setBulkAdding(false)}
        />
      )}
    </div>
  );
}

import { describe, it, expect, beforeEach, vi } from "vitest";
import { ASSET_LIBRARY_PAGE_SIZE, useAssetsStore } from "./assets-store";
import { API } from "@/api";
import type { AssetType } from "@/types/asset";

describe("useAssetsStore", () => {
  beforeEach(() => {
    useAssetsStore.setState(useAssetsStore.getInitialState(), true);
    vi.restoreAllMocks();
  });

  it("loads list by type", async () => {
    vi.spyOn(API, "listAssets" as any).mockResolvedValue({ items: [{ id: "1", type: "scene", name: "A", description: "", voice_style: "", image_path: null, source_project: null, updated_at: null }] });
    await useAssetsStore.getState().loadList("scene");
    expect(useAssetsStore.getState().byType.scene).toHaveLength(1);
    expect(useAssetsStore.getState().totalByType.scene).toBe(1);
  });

  it("loads all asset types for library tab counts", async () => {
    vi.spyOn(API, "listAssets").mockImplementation((async (params = {}) => {
      const type = params.type as AssetType;
      return Promise.resolve({
        total: 1,
        items: [
          {
            id: `${type}-1`,
            type,
            name: `${type} asset`,
            description: "",
            voice_style: "",
            image_path: null,
            source_project: null,
            updated_at: null,
          },
        ],
      });
    }) satisfies typeof API.listAssets);

    await useAssetsStore.getState().loadAllLists();

    expect(useAssetsStore.getState().byType.character).toHaveLength(1);
    expect(useAssetsStore.getState().byType.scene).toHaveLength(1);
    expect(useAssetsStore.getState().byType.prop).toHaveLength(1);
    expect(useAssetsStore.getState().totalByType.character).toBe(1);
    expect(useAssetsStore.getState().totalByType.scene).toBe(1);
    expect(useAssetsStore.getState().totalByType.prop).toBe(1);
    expect(API.listAssets).toHaveBeenCalledWith({ type: "character", q: undefined, limit: ASSET_LIBRARY_PAGE_SIZE, offset: 0 });
    expect(API.listAssets).toHaveBeenCalledWith({ type: "scene", q: undefined, limit: ASSET_LIBRARY_PAGE_SIZE, offset: 0 });
    expect(API.listAssets).toHaveBeenCalledWith({ type: "prop", q: undefined, limit: ASSET_LIBRARY_PAGE_SIZE, offset: 0 });
  });

  it("loads all asset types with the current search query", async () => {
    vi.spyOn(API, "listAssets").mockImplementation((async (params = {}) => {
      return Promise.resolve({
        items: [
          {
            id: `${params.type}-1`,
            type: params.type as AssetType,
            name: `${params.type} asset`,
            description: "",
            voice_style: "",
            image_path: null,
            source_project: null,
            updated_at: null,
          },
        ],
      });
    }) satisfies typeof API.listAssets);

    await useAssetsStore.getState().loadAllLists("castle");

    expect(API.listAssets).toHaveBeenCalledWith({ type: "character", q: "castle", limit: ASSET_LIBRARY_PAGE_SIZE, offset: 0 });
    expect(API.listAssets).toHaveBeenCalledWith({ type: "scene", q: "castle", limit: ASSET_LIBRARY_PAGE_SIZE, offset: 0 });
    expect(API.listAssets).toHaveBeenCalledWith({ type: "prop", q: "castle", limit: ASSET_LIBRARY_PAGE_SIZE, offset: 0 });
  });

  it("appends the next page when loading more", async () => {
    useAssetsStore.setState({
      ...useAssetsStore.getInitialState(),
      byType: {
        character: Array.from({ length: ASSET_LIBRARY_PAGE_SIZE }, (_, index) => ({
          id: `character-${index}`,
          type: "character",
          name: `character-${index}`,
          description: "",
          voice_style: "",
          image_path: null,
          source_project: null,
          updated_at: null,
        })),
        scene: [],
        prop: [],
      },
      totalByType: { character: ASSET_LIBRARY_PAGE_SIZE + 1, scene: 0, prop: 0 },
    }, true);
    vi.spyOn(API, "listAssets").mockResolvedValue({
      total: ASSET_LIBRARY_PAGE_SIZE + 1,
      items: [{
        id: "character-next",
        type: "character",
        name: "next",
        description: "",
        voice_style: "",
        image_path: null,
        source_project: null,
        updated_at: null,
      }],
    });

    await useAssetsStore.getState().loadMore("character");

    expect(API.listAssets).toHaveBeenCalledWith({
      type: "character",
      q: undefined,
      limit: ASSET_LIBRARY_PAGE_SIZE,
      offset: ASSET_LIBRARY_PAGE_SIZE,
    });
    expect(useAssetsStore.getState().byType.character).toHaveLength(ASSET_LIBRARY_PAGE_SIZE + 1);
  });

  it("removes asset locally after delete", async () => {
    useAssetsStore.setState({
      ...useAssetsStore.getInitialState(),
      byType: { character: [], scene: [{ id: "1", type: "scene", name: "A", description: "", voice_style: "", image_path: null, source_project: null, updated_at: null }], prop: [] },
      totalByType: { character: 0, scene: 1, prop: 0 },
    }, true);
    vi.spyOn(API, "deleteAsset" as any).mockResolvedValue(undefined);
    await useAssetsStore.getState().deleteAsset("1", "scene");
    expect(useAssetsStore.getState().byType.scene).toHaveLength(0);
    expect(useAssetsStore.getState().totalByType.scene).toBe(0);
  });
});

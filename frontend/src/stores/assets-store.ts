import { create } from "zustand";
import { API } from "@/api";
import type { Asset, AssetType } from "@/types/asset";

interface AssetsStore {
  byType: Record<AssetType, Asset[]>;
  totalByType: Record<AssetType, number>;
  loadingByType: Record<AssetType, boolean>;
  queryByType: Record<AssetType, string>;
  loadList: (type: AssetType, q?: string) => Promise<void>;
  loadAllLists: (q?: string) => Promise<void>;
  loadMore: (type: AssetType, q?: string) => Promise<void>;
  addAsset: (asset: Asset) => void;
  updateAsset: (asset: Asset) => void;
  deleteAsset: (id: string, type: AssetType) => Promise<void>;
}

const ASSET_TYPES: AssetType[] = ["character", "scene", "prop"];
export const ASSET_LIBRARY_PAGE_SIZE = 60;

const emptyAssetsByType = (): Record<AssetType, Asset[]> => ({ character: [], scene: [], prop: [] });
const emptyNumberByType = (): Record<AssetType, number> => ({ character: 0, scene: 0, prop: 0 });
const emptyLoadingByType = (): Record<AssetType, boolean> => ({ character: false, scene: false, prop: false });
const emptyQueryByType = (): Record<AssetType, string> => ({ character: "", scene: "", prop: "" });

let loadAllSequence = 0;

function queryKey(q?: string) {
  return q ?? "";
}

export const useAssetsStore = create<AssetsStore>((set, get) => ({
  byType: emptyAssetsByType(),
  totalByType: emptyNumberByType(),
  loadingByType: emptyLoadingByType(),
  queryByType: emptyQueryByType(),
  loadList: async (type, q) => {
    const expectedQueryKey = queryKey(q);
    set((s) => ({
      loadingByType: { ...s.loadingByType, [type]: true },
      queryByType: { ...s.queryByType, [type]: expectedQueryKey },
    }));
    try {
      const res = await API.listAssets({ type, q, limit: ASSET_LIBRARY_PAGE_SIZE, offset: 0 });
      if (get().queryByType[type] !== expectedQueryKey) return;
      set((s) => ({
        byType: { ...s.byType, [type]: res.items },
        totalByType: { ...s.totalByType, [type]: res.total ?? res.items.length },
      }));
    } finally {
      if (get().queryByType[type] === expectedQueryKey) {
        set((s) => ({ loadingByType: { ...s.loadingByType, [type]: false } }));
      }
    }
  },
  loadAllLists: async (q) => {
    const seq = ++loadAllSequence;
    const nextQueryKey = queryKey(q);
    set({
      loadingByType: { character: true, scene: true, prop: true },
      queryByType: { character: nextQueryKey, scene: nextQueryKey, prop: nextQueryKey },
    });
    try {
      const entries = await Promise.all(
        ASSET_TYPES.map(async (type) => {
          const res = await API.listAssets({ type, q, limit: ASSET_LIBRARY_PAGE_SIZE, offset: 0 });
          return [type, res.items, res.total ?? res.items.length] as const;
        }),
      );
      if (seq !== loadAllSequence) return;
      set((s) => ({
        byType: {
          ...s.byType,
          ...Object.fromEntries(entries.map(([type, items]) => [type, items])),
        },
        totalByType: {
          ...s.totalByType,
          ...Object.fromEntries(entries.map(([type, _items, total]) => [type, total])),
        },
        loadingByType: { character: false, scene: false, prop: false },
      }));
    } catch (err) {
      if (seq === loadAllSequence) {
        set({ loadingByType: { character: false, scene: false, prop: false } });
      }
      throw err;
    }
  },
  loadMore: async (type, q) => {
    const state = get();
    if (state.loadingByType[type]) return;
    const offset = state.byType[type].length;
    const total = state.totalByType[type];
    if (total > 0 && offset >= total) return;
    const expectedQueryKey = queryKey(q);
    if (state.queryByType[type] !== expectedQueryKey) return;
    set((s) => ({ loadingByType: { ...s.loadingByType, [type]: true } }));
    try {
      const res = await API.listAssets({ type, q, limit: ASSET_LIBRARY_PAGE_SIZE, offset });
      if (get().queryByType[type] !== expectedQueryKey) return;
      set((s) => {
        const seen = new Set(s.byType[type].map((asset) => asset.id));
        const nextItems = [...s.byType[type], ...res.items.filter((asset) => !seen.has(asset.id))];
        return {
          byType: { ...s.byType, [type]: nextItems },
          totalByType: { ...s.totalByType, [type]: res.total ?? Math.max(nextItems.length, total) },
        };
      });
    } finally {
      if (get().queryByType[type] === expectedQueryKey) {
        set((s) => ({ loadingByType: { ...s.loadingByType, [type]: false } }));
      }
    }
  },
  addAsset: (asset) =>
    set((s) => {
      const exists = s.byType[asset.type].some((item) => item.id === asset.id);
      return {
        byType: {
          ...s.byType,
          [asset.type]: exists ? s.byType[asset.type] : [asset, ...s.byType[asset.type]],
        },
        totalByType: {
          ...s.totalByType,
          [asset.type]: exists ? s.totalByType[asset.type] : s.totalByType[asset.type] + 1,
        },
      };
    }),
  updateAsset: (asset) =>
    set((s) => ({
      byType: {
        ...s.byType,
        [asset.type]: s.byType[asset.type].map((a) => (a.id === asset.id ? asset : a)),
      },
    })),
  deleteAsset: async (id, type) => {
    await API.deleteAsset(id);
    set((s) => ({
      byType: { ...s.byType, [type]: s.byType[type].filter((a) => a.id !== id) },
      totalByType: { ...s.totalByType, [type]: Math.max(0, s.totalByType[type] - 1) },
    }));
  },
}));

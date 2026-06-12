export interface GridLayout {
  gridSize: "grid_4" | null;
  rows: number;
  cols: number;
  cellCount: number;
  batchCount: number;
  chunkSizes: number[];
}

interface GridMatchRecord {
  id: string;
  episode: number;
  scene_ids: string[];
  created_at: string;
  status?: string;
  grid_image_path?: string | null;
  frame_chain?: Array<{ image_path?: string | null }>;
}

function hasRenderableGridImage(grid: GridMatchRecord): boolean {
  if (grid.grid_image_path) return true;
  return grid.frame_chain?.some((cell) => Boolean(cell.image_path)) ?? false;
}

function getGridDisplayPriority(grid: GridMatchRecord): number {
  const hasImage = hasRenderableGridImage(grid);
  if (grid.status === "completed" && hasImage) return 4;
  if (grid.status === "completed") return 3;
  if (hasImage) return 2;
  if (grid.status === "pending" || grid.status === "generating" || grid.status === "splitting") {
    return 1;
  }
  return 0;
}

/**
 * 后端会把连续组拆成最多 4 个镜头的多个 chunk。
 * 每条 grid 记录的 scene_ids 是 group 的子集；匹配时按子集判断，
 * 再按 created_at 降序贪心覆盖，过滤掉被新生成覆盖的旧 chunk。
 */
export function matchGridsForGroup<G extends GridMatchRecord>(
  grids: G[],
  groupSceneIds: Iterable<string>,
  episode: number,
): G[] {
  const idSet = new Set(groupSceneIds);
  const matched = grids.filter(
    (g) =>
      g.episode === episode &&
      g.scene_ids.length > 0 &&
      g.scene_ids.every((id) => idSet.has(id)),
  );

  const sorted = [...matched].sort((a, b) => {
    const priorityDelta = getGridDisplayPriority(b) - getGridDisplayPriority(a);
    if (priorityDelta !== 0) return priorityDelta;
    return b.created_at.localeCompare(a.created_at);
  });

  const selected: G[] = [];
  const covered = new Set<string>();
  for (const g of sorted) {
    const hasUncovered = g.scene_ids.some((id) => !covered.has(id));
    if (hasUncovered) {
      selected.push(g);
      for (const id of g.scene_ids) covered.add(id);
    }
  }

  return selected.sort((a, b) => a.created_at.localeCompare(b.created_at));
}

export function groupBySegmentBreak<S extends { segment_break?: boolean }>(
  segments: S[],
): S[][] {
  const groups: S[][] = [];
  let current: S[] = [];
  for (const seg of segments) {
    if (seg.segment_break && current.length > 0) {
      groups.push(current);
      current = [];
    }
    current.push(seg);
  }
  if (current.length > 0) groups.push(current);
  return groups;
}

export function planGridChunkSizes(count: number): number[] {
  if (count <= 0) return [];
  const chunks: number[] = [];
  let remaining = count;
  while (remaining > 0) {
    const size = Math.min(4, remaining);
    chunks.push(size);
    remaining -= size;
  }
  return chunks;
}

export function computeGridSize(count: number, _aspectRatio: string = "9:16"): GridLayout {
  const empty: GridLayout = {
    gridSize: null,
    rows: 0,
    cols: 0,
    cellCount: count,
    batchCount: 0,
    chunkSizes: [],
  };
  if (count < 1) return empty;
  const chunkSizes = planGridChunkSizes(count);
  if (chunkSizes.length === 0) return empty;

  return {
    gridSize: "grid_4",
    rows: 2,
    cols: 2,
    cellCount: 4,
    batchCount: chunkSizes.length,
    chunkSizes,
  };
}

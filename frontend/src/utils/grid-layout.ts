export interface GridLayout {
  gridSize: "grid_2" | "grid_3" | "grid_4" | null;
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

  const sorted = [...matched].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  );

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
  if (count <= 1) return [];
  const terminal: Record<number, number[]> = {
    2: [2],
    3: [3],
    4: [4],
    5: [3, 2],
    6: [3, 3],
    7: [4, 3],
    8: [4, 4],
  };
  if (terminal[count]) return terminal[count];

  const chunks: number[] = [];
  let remaining = count;
  while (remaining > 8) {
    chunks.push(4);
    remaining -= 4;
  }
  chunks.push(...terminal[remaining]);
  return chunks;
}

export function computeGridSize(count: number, aspectRatio: string = "9:16"): GridLayout {
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
  const [w, h] = aspectRatio.split(":").map(Number);
  const isHorizontal = w > h;
  const firstChunk = chunkSizes[0];

  let gridSize: "grid_2" | "grid_3" | "grid_4";
  let rows: number;
  let cols: number;

  if (firstChunk === 4) {
    gridSize = "grid_4";
    rows = 2;
    cols = 2;
  } else {
    gridSize = firstChunk === 2 ? "grid_2" : "grid_3";
    rows = isHorizontal ? firstChunk : 1;
    cols = isHorizontal ? 1 : firstChunk;
  }

  return { gridSize, rows, cols, cellCount: count, batchCount: chunkSizes.length, chunkSizes };
}

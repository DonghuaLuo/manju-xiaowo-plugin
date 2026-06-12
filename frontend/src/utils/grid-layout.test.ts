import { describe, expect, it } from "vitest";
import { computeGridSize, groupBySegmentBreak, matchGridsForGroup, planGridChunkSizes } from "./grid-layout";

interface FakeGrid {
  id: string;
  episode: number;
  scene_ids: string[];
  created_at: string;
  status?: "pending" | "generating" | "splitting" | "completed" | "failed";
  grid_image_path?: string | null;
  frame_chain?: Array<{ image_path?: string | null }>;
}

function grid(
  id: string,
  scene_ids: string[],
  created_at: string,
  episode = 1,
  patch: Partial<FakeGrid> = {},
): FakeGrid {
  return { id, episode, scene_ids, created_at, ...patch };
}

describe("matchGridsForGroup", () => {
  it("matches a single grid covering the whole group exactly", () => {
    const grids = [grid("g1", ["s1", "s2", "s3"], "2026-05-01T00:00:00Z")];
    const result = matchGridsForGroup(grids, ["s1", "s2", "s3"], 1);
    expect(result.map((g) => g.id)).toEqual(["g1"]);
  });

  it("matches multiple chunk grids when a group exceeds cell_count", () => {
    const big = Array.from({ length: 14 }, (_, i) => `s${i + 1}`);
    const grids = [
      grid("g9", big.slice(0, 9), "2026-05-01T00:00:00Z"),
      grid("g4", big.slice(9), "2026-05-01T00:00:01Z"),
    ];
    const result = matchGridsForGroup(grids, big, 1);
    expect(result.map((g) => g.id)).toEqual(["g9", "g4"]);
  });

  it("ignores grids belonging to a different episode", () => {
    const grids = [
      grid("g1", ["s1", "s2"], "2026-05-01T00:00:00Z", 1),
      grid("g2", ["s1", "s2"], "2026-05-01T00:00:00Z", 2),
    ];
    const result = matchGridsForGroup(grids, ["s1", "s2"], 1);
    expect(result.map((g) => g.id)).toEqual(["g1"]);
  });

  it("ignores grids whose scene_ids contain ids outside the group", () => {
    const grids = [
      grid("g1", ["s1", "s2"], "2026-05-01T00:00:00Z"),
      grid("g_other", ["s1", "s99"], "2026-05-01T00:00:01Z"),
    ];
    const result = matchGridsForGroup(grids, ["s1", "s2"], 1);
    expect(result.map((g) => g.id)).toEqual(["g1"]);
  });

  it("dedupes regenerations by keeping grids that contribute uncovered scenes", () => {
    const grids = [
      grid("old", ["s1", "s2"], "2026-05-01T00:00:00Z"),
      grid("new", ["s1", "s2"], "2026-05-02T00:00:00Z"),
    ];
    const result = matchGridsForGroup(grids, ["s1", "s2"], 1);
    expect(result.map((g) => g.id)).toEqual(["new"]);
  });

  it("returns chunks ordered by created_at ascending", () => {
    const big = Array.from({ length: 14 }, (_, i) => `s${i + 1}`);
    const grids = [
      grid("late", big.slice(9), "2026-05-01T00:00:05Z"),
      grid("early", big.slice(0, 9), "2026-05-01T00:00:00Z"),
    ];
    const result = matchGridsForGroup(grids, big, 1);
    expect(result.map((g) => g.id)).toEqual(["early", "late"]);
  });

  it("filters obsolete overlapping grids covered by newer generations", () => {
    const grids = [
      grid("obsolete_subset", ["s1", "s2"], "2026-05-01T00:00:00Z"),
      grid("obsolete_superset", ["s1", "s2", "s3", "s4", "s5"], "2026-05-01T00:00:01Z"),
      grid("new_chunk_1", ["s1", "s2", "s3"], "2026-05-02T00:00:00Z"),
      grid("new_chunk_2", ["s4", "s5"], "2026-05-02T00:00:01Z"),
    ];
    const result = matchGridsForGroup(grids, ["s1", "s2", "s3", "s4", "s5"], 1);
    expect(result.map((g) => g.id)).toEqual(["new_chunk_1", "new_chunk_2"]);
  });

  it("keeps an older completed image visible while a newer duplicate is still empty", () => {
    const grids = [
      grid("completed_with_image", ["s1", "s2"], "2026-05-01T00:00:00Z", 1, {
        status: "completed",
        grid_image_path: "grids/completed.png",
        frame_chain: [{ image_path: "storyboards/s1.png" }],
      }),
      grid("new_empty_generating", ["s1", "s2"], "2026-05-02T00:00:00Z", 1, {
        status: "generating",
        grid_image_path: null,
        frame_chain: [],
      }),
    ];

    const result = matchGridsForGroup(grids, ["s1", "s2"], 1);
    expect(result.map((g) => g.id)).toEqual(["completed_with_image"]);
  });
});

describe("planGridChunkSizes", () => {
  it("keeps grid batches within 1-4 shots and packs fours first", () => {
    expect(planGridChunkSizes(1)).toEqual([1]);
    expect(planGridChunkSizes(5)).toEqual([4, 1]);
    expect(planGridChunkSizes(9)).toEqual([4, 4, 1]);
    expect(planGridChunkSizes(12)).toEqual([4, 4, 4]);
  });
});

describe("computeGridSize", () => {
  it("treats a single scene as a 2x2 grid with placeholders", () => {
    expect(computeGridSize(1, "9:16")).toMatchObject({
      gridSize: "grid_4",
      rows: 2,
      cols: 2,
      cellCount: 4,
      batchCount: 1,
    });
  });

  it("uses a 2x2 grid for horizontal 3-shot batches", () => {
    expect(computeGridSize(3, "16:9")).toMatchObject({
      gridSize: "grid_4",
      rows: 2,
      cols: 2,
      batchCount: 1,
    });
  });

  it("uses a 2x2 grid for vertical 3-shot batches", () => {
    expect(computeGridSize(3, "9:16")).toMatchObject({
      gridSize: "grid_4",
      rows: 2,
      cols: 2,
      batchCount: 1,
    });
  });
});

describe("groupBySegmentBreak", () => {
  it("starts a new group at the current segment_break item", () => {
    const groups = groupBySegmentBreak([
      { id: "s1", segment_break: false },
      { id: "s2", segment_break: false },
      { id: "s3", segment_break: true },
      { id: "s4", segment_break: false },
    ]);

    expect(groups.map((group) => group.map((item) => item.id))).toEqual([
      ["s1", "s2"],
      ["s3", "s4"],
    ]);
  });
});

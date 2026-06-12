import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import type { GridGeneration } from "@/types/grid";
import { GridPreviewPanel } from "./GridPreviewPanel";

const gridFixture: GridGeneration = {
  id: "grid-1",
  episode: 1,
  script_file: "episode-1.txt",
  scene_ids: ["S1"],
  grid_image_path: "grids/grid-1.png",
  rows: 2,
  cols: 2,
  cell_count: 4,
  frame_chain: [
    {
      index: 0,
      row: 0,
      col: 0,
      frame_type: "first",
      prev_scene_id: null,
      next_scene_id: "S1",
      image_path: "storyboards/scene_S1.png",
    },
    {
      index: 1,
      row: 0,
      col: 1,
      frame_type: "placeholder",
      prev_scene_id: null,
      next_scene_id: null,
      image_path: null,
    },
    {
      index: 2,
      row: 1,
      col: 0,
      frame_type: "placeholder",
      prev_scene_id: null,
      next_scene_id: null,
      image_path: null,
    },
    {
      index: 3,
      row: 1,
      col: 1,
      frame_type: "placeholder",
      prev_scene_id: null,
      next_scene_id: null,
      image_path: null,
    },
  ],
  status: "completed",
  prompt: null,
  provider: "demo",
  model: "demo-model",
  grid_size: "2x2",
  created_at: "2026-01-01T00:00:00Z",
  error_message: null,
  reference_images: [],
};

describe("GridPreviewPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("opens a sliced storyboard cell in the shared image lightbox", async () => {
    vi.spyOn(API, "getGrid").mockResolvedValue(gridFixture);

    render(
      <GridPreviewPanel
        projectName="demo"
        gridId="grid-1"
        defaultExpanded
      />,
    );

    const previewButton = await screen.findByRole("button", {
      name: "第 1 格 · S1 全屏预览",
    });

    fireEvent.click(previewButton);

    expect(
      screen.getByRole("dialog", { name: "第 1 格 · S1 全屏预览" }),
    ).toBeInTheDocument();
  });

  it("opens a reference image in the shared image lightbox", async () => {
    vi.spyOn(API, "getGrid").mockResolvedValue({
      ...gridFixture,
      reference_images: [
        {
          ref_type: "character",
          name: "Hero",
          path: "characters/hero.png",
        },
      ],
    });

    render(
      <GridPreviewPanel
        projectName="demo"
        gridId="grid-1"
        defaultExpanded
      />,
    );

    const previewButton = await screen.findByRole("button", {
      name: "Hero 全屏预览",
    });

    fireEvent.click(previewButton);

    expect(
      screen.getByRole("dialog", { name: "Hero 全屏预览" }),
    ).toBeInTheDocument();
  });

  it("renders legacy 3x1 grid records as a 2x2 storyboard mosaic", async () => {
    vi.spyOn(API, "getGrid").mockResolvedValue({
      ...gridFixture,
      id: "grid-legacy",
      scene_ids: ["S1", "S2", "S3"],
      rows: 3,
      cols: 1,
      cell_count: 3,
      frame_chain: [
        {
          index: 0,
          row: 0,
          col: 0,
          frame_type: "first",
          prev_scene_id: null,
          next_scene_id: "S1",
          image_path: "storyboards/scene_S1.png",
        },
        {
          index: 1,
          row: 1,
          col: 0,
          frame_type: "transition",
          prev_scene_id: "S1",
          next_scene_id: "S2",
          image_path: "storyboards/scene_S2.png",
        },
        {
          index: 2,
          row: 2,
          col: 0,
          frame_type: "transition",
          prev_scene_id: "S2",
          next_scene_id: "S3",
          image_path: "storyboards/scene_S3.png",
        },
      ],
    });

    render(
      <GridPreviewPanel
        projectName="demo"
        gridId="grid-legacy"
        defaultExpanded
      />,
    );

    const mosaic = await screen.findByRole("group", { name: "宫格切片分镜预览" });
    expect(mosaic).toHaveStyle("grid-template-columns: repeat(2, minmax(0, 1fr))");
    expect(screen.getByTitle("第 4 格 · 占位")).toBeInTheDocument();
    expect(screen.getByText(/4 格 · grid_4/)).toBeInTheDocument();
  });
});

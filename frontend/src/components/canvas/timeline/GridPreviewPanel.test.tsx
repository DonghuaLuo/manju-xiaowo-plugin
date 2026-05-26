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
  frame_chain: [],
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

  it("opens the composite grid image in the shared image lightbox", async () => {
    vi.spyOn(API, "getGrid").mockResolvedValue(gridFixture);

    render(
      <GridPreviewPanel
        projectName="demo"
        gridIds={["grid-1"]}
        defaultExpanded
      />,
    );

    const previewButton = await screen.findByRole("button", {
      name: "宫格合成图 全屏预览",
    });

    fireEvent.click(previewButton);

    expect(
      screen.getByRole("dialog", { name: "宫格合成图 全屏预览" }),
    ).toBeInTheDocument();
  });
});

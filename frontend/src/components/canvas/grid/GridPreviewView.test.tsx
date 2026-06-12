import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { GridPreviewView } from "./GridPreviewView";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import type { GridGeneration } from "@/types/grid";
import type { NarrationSegment } from "@/types";

vi.mock("@/components/canvas/timeline/GridPreviewPanel", () => ({
  GridPreviewPanel: ({ gridId }: { gridId?: string | null }) => (
    <div data-testid="grid-preview-panel">{gridId || "empty"}</div>
  ),
}));

function makeSegment(id = "SEG-1", patch: Partial<NarrationSegment> = {}): NarrationSegment {
  return {
    segment_id: id,
    episode: 1,
    duration_seconds: 4,
    segment_break: false,
    novel_text: "A",
    characters_in_segment: [],
    scenes: [],
    props: [],
    image_prompt: "image-1",
    video_prompt: "video-1",
    transition_to_next: "cut",
    ...patch,
  } as NarrationSegment;
}

function makeGridGeneration(
  id: string,
  sceneIds: string[],
  createdAt = "2026-01-01T00:00:00Z",
): GridGeneration {
  return {
    id,
    episode: 1,
    script_file: "episode_1.json",
    scene_ids: sceneIds,
    grid_image_path: `grids/${id}.png`,
    rows: 2,
    cols: 2,
    cell_count: 4,
    frame_chain: [],
    status: "completed",
    prompt: null,
    provider: "demo",
    model: "demo",
    grid_size: "grid_4",
    created_at: createdAt,
    error_message: null,
    reference_images: [],
  };
}

describe("GridPreviewView", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.spyOn(API, "listGrids").mockResolvedValue([]);
  });

  it("asks for confirmation before generating a single scene through the grid flow", async () => {
    const onGenerateGrid = vi.fn().mockResolvedValue(undefined);
    const onGenerateStoryboard = vi.fn().mockResolvedValue(undefined);

    render(
      <GridPreviewView
        projectName="demo"
        episode={1}
        scriptFile="episode_1.json"
        segments={[makeSegment()]}
        contentMode="narration"
        aspectRatio="9:16"
        onGenerateGrid={onGenerateGrid}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", {
        name: /生成宫格镜头板|Generate grid board/i,
      }),
    );

    const dialog = await screen.findByRole("dialog", { name: /生成宫格镜头板|Generate grid board/i });
    fireEvent.click(within(dialog).getByRole("button", { name: /确认|Confirm/i }));

    await waitFor(() => {
      expect(onGenerateGrid).toHaveBeenCalledWith(1, "episode_1.json", ["SEG-1"]);
    });
    expect(onGenerateStoryboard).not.toHaveBeenCalled();
  });

  it("matches a refreshed single-scene grid instead of hiding it as a storyboard-only item", async () => {
    const grid: GridGeneration = {
      id: "grid-single",
      episode: 1,
      script_file: "episode_1.json",
      scene_ids: ["SEG-1"],
      grid_image_path: "grids/grid-single.png",
      rows: 2,
      cols: 2,
      cell_count: 4,
      frame_chain: [],
      status: "completed",
      prompt: null,
      provider: "demo",
      model: "demo",
      grid_size: "grid_4",
      created_at: "2026-01-01T00:00:00Z",
      error_message: null,
      reference_images: [],
    };
    vi.mocked(API.listGrids).mockResolvedValue([grid]);

    render(
      <GridPreviewView
        projectName="demo"
        episode={1}
        scriptFile="episode_1.json"
        segments={[makeSegment()]}
        contentMode="narration"
        aspectRatio="16:9"
        onGenerateGrid={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("grid-preview-panel")).toHaveTextContent("grid-single");
    });
  });

  it("renders planned split chunks as separate empty panels", async () => {
    render(
      <GridPreviewView
        projectName="demo"
        episode={1}
        scriptFile="episode_1.json"
        segments={Array.from({ length: 5 }, (_, index) => makeSegment(`SEG-${index + 1}`))}
        contentMode="narration"
        aspectRatio="9:16"
        onGenerateGrid={vi.fn()}
      />,
    );

    const panels = await screen.findAllByTestId("grid-preview-panel");
    expect(panels).toHaveLength(2);
    expect(panels[0]).toHaveTextContent("empty");
    expect(panels[1]).toHaveTextContent("empty");
    expect(
      screen.getAllByRole("button", {
        name: /生成宫格镜头板|Generate grid board/i,
      }),
    ).toHaveLength(2);
    expect(screen.queryByText(/4\+1/)).not.toBeInTheDocument();
  });

  it("keeps a missing split chunk visible when only part of the group has a grid", async () => {
    vi.mocked(API.listGrids).mockResolvedValue([
      makeGridGeneration("grid-4", ["SEG-1", "SEG-2", "SEG-3", "SEG-4"]),
    ]);
    const onGenerateGrid = vi.fn().mockResolvedValue(undefined);

    render(
      <GridPreviewView
        projectName="demo"
        episode={1}
        scriptFile="episode_1.json"
        segments={Array.from({ length: 5 }, (_, index) => makeSegment(`SEG-${index + 1}`))}
        contentMode="narration"
        aspectRatio="9:16"
        onGenerateGrid={onGenerateGrid}
      />,
    );

    await waitFor(() => {
      const panels = screen.getAllByTestId("grid-preview-panel");
      expect(panels).toHaveLength(2);
      expect(panels[0]).toHaveTextContent("grid-4");
      expect(panels[1]).toHaveTextContent("empty");
    });

    fireEvent.click(
      screen.getByRole("button", {
        name: /生成宫格镜头板|Generate grid board/i,
      }),
    );

    const dialog = await screen.findByRole("dialog", { name: /生成宫格镜头板|Generate grid board/i });
    fireEvent.click(within(dialog).getByRole("button", { name: /确认|Confirm/i }));

    await waitFor(() => {
      expect(onGenerateGrid).toHaveBeenCalledWith(1, "episode_1.json", ["SEG-5"]);
    });
  });

  it("renders split grid records as separate expanded panels instead of one switcher", async () => {
    const grids: GridGeneration[] = [
      {
        id: "grid-4",
        episode: 1,
        script_file: "episode_1.json",
        scene_ids: ["SEG-1", "SEG-2", "SEG-3", "SEG-4"],
        grid_image_path: "grids/grid-4.png",
        rows: 2,
        cols: 2,
        cell_count: 4,
        frame_chain: [],
        status: "completed",
        prompt: null,
        provider: "demo",
        model: "demo",
        grid_size: "grid_4",
        created_at: "2026-01-01T00:00:00Z",
        error_message: null,
        reference_images: [],
      },
      {
        id: "grid-1",
        episode: 1,
        script_file: "episode_1.json",
        scene_ids: ["SEG-5"],
        grid_image_path: "grids/grid-1.png",
        rows: 2,
        cols: 2,
        cell_count: 4,
        frame_chain: [],
        status: "completed",
        prompt: null,
        provider: "demo",
        model: "demo",
        grid_size: "grid_4",
        created_at: "2026-01-01T00:00:01Z",
        error_message: null,
        reference_images: [],
      },
    ];
    vi.mocked(API.listGrids).mockResolvedValue(grids);

    render(
      <GridPreviewView
        projectName="demo"
        episode={1}
        scriptFile="episode_1.json"
        segments={Array.from({ length: 5 }, (_, index) => makeSegment(`SEG-${index + 1}`))}
        contentMode="narration"
        aspectRatio="9:16"
        onGenerateGrid={vi.fn()}
      />,
    );

    await waitFor(() => {
      const panels = screen.getAllByTestId("grid-preview-panel");
      expect(panels).toHaveLength(2);
      expect(panels[0]).toHaveTextContent("grid-4");
      expect(panels[1]).toHaveTextContent("grid-1");
    });
    expect(screen.queryByText("grid-4,grid-1")).not.toBeInTheDocument();
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { GridPreviewView } from "./GridPreviewView";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import type { NarrationSegment } from "@/types";

vi.mock("@/components/canvas/timeline/GridPreviewPanel", () => ({
  GridPreviewPanel: () => <div data-testid="grid-preview-panel" />,
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

describe("GridPreviewView", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.spyOn(API, "listGrids").mockResolvedValue([]);
  });

  it("asks for confirmation before generating a single scene through the storyboard flow", async () => {
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
        onGenerateStoryboard={onGenerateStoryboard}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", {
        name: /生成分镜|Generate storyboard/i,
      }),
    );

    const dialog = await screen.findByRole("dialog", { name: /生成分镜|Generate storyboard/i });
    fireEvent.click(within(dialog).getByRole("button", { name: /确认|Confirm/i }));

    await waitFor(() => {
      expect(onGenerateStoryboard).toHaveBeenCalledWith("SEG-1");
    });
    expect(onGenerateGrid).not.toHaveBeenCalled();
  });

  it("shows real chunk sizes when a continuous group is split into multiple grids", async () => {
    render(
      <GridPreviewView
        projectName="demo"
        episode={1}
        scriptFile="episode_1.json"
        segments={Array.from({ length: 5 }, (_, index) => makeSegment(`SEG-${index + 1}`))}
        contentMode="narration"
        aspectRatio="9:16"
        onGenerateGrid={vi.fn()}
        onGenerateStoryboard={vi.fn()}
      />,
    );

    expect(await screen.findByText(/3\+2/)).toBeInTheDocument();
    expect(screen.getAllByText(/2 批|2 batches/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/5 格 .*0×0/)).not.toBeInTheDocument();
  });
});

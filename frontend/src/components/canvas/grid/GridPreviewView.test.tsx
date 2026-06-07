import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { GridPreviewView } from "./GridPreviewView";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import type { NarrationSegment } from "@/types";

vi.mock("@/components/canvas/timeline/GridPreviewPanel", () => ({
  GridPreviewPanel: () => <div data-testid="grid-preview-panel" />,
}));

function makeSegment(): NarrationSegment {
  return {
    segment_id: "SEG-1",
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
  } as NarrationSegment;
}

describe("GridPreviewView", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.spyOn(API, "listGrids").mockResolvedValue([]);
  });

  it("asks for confirmation before generating a grid group", async () => {
    const onGenerateGrid = vi.fn().mockResolvedValue(undefined);

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

    const dialog = await screen.findByRole("dialog", {
      name: /生成宫格镜头板|Generate grid board/i,
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /确认|Confirm/i }));

    await waitFor(() => {
      expect(onGenerateGrid).toHaveBeenCalledWith(1, "episode_1.json", ["SEG-1"]);
    });
  });
});

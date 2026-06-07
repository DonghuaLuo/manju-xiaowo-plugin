import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { GridImageToVideoCanvas } from "./GridImageToVideoCanvas";
import { useCostStore } from "@/stores/cost-store";
import { useTasksStore } from "@/stores/tasks-store";
import type { EpisodeScript, ProjectData } from "@/types";

vi.mock("./GridPreviewView", () => ({
  GridPreviewView: () => <div data-testid="grid-preview-view" />,
}));

vi.mock("../timeline/EpisodeHeader", () => ({
  EpisodeHeader: () => <div data-testid="episode-header" />,
}));

vi.mock("../timeline/PreprocessingView", () => ({
  PreprocessingView: () => <div data-testid="preprocessing-view" />,
}));

vi.mock("../timeline/ShotSplitView", () => ({
  ShotSplitView: () => <div data-testid="shot-split-view" />,
}));

vi.mock("@/hooks/useScrollTarget", () => ({
  useScrollTarget: () => {},
}));

function makeEpisodeScript(): EpisodeScript {
  return {
    episode: 1,
    title: "EP1",
    content_mode: "narration",
    duration_seconds: 4,
    novel: { title: "Novel", chapter: "1" },
    segments: [
      {
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
        generated_assets: {
          storyboard_image: "storyboard-1.png",
        },
      },
    ],
  } as unknown as EpisodeScript;
}

function makeProjectData(): ProjectData {
  return {
    title: "Demo",
    content_mode: "narration",
    style: "",
    episodes: [],
    characters: {},
    scenes: {},
    props: {},
    aspect_ratio: "9:16",
  } as unknown as ProjectData;
}

describe("GridImageToVideoCanvas", () => {
  beforeEach(() => {
    useTasksStore.setState(useTasksStore.getInitialState(), true);
    useCostStore.setState(useCostStore.getInitialState(), true);
    useCostStore.setState({
      debouncedFetch: vi.fn(),
      getEpisodeCost: () => undefined,
    });
  });

  it("asks for confirmation before generating all grids", async () => {
    const onGenerateGrid = vi.fn().mockResolvedValue(undefined);

    render(
      <GridImageToVideoCanvas
        projectName="demo"
        episode={1}
        hasDraft
        episodeScript={makeEpisodeScript()}
        scriptFile="episode_1.json"
        projectData={makeProjectData()}
        onGenerateGrid={onGenerateGrid}
      />,
    );

    fireEvent.click(screen.getByRole("tab", { name: /宫格图|Grids/i }));
    fireEvent.click(screen.getByRole("button", { name: /一键生成宫格镜头板|Generate grid boards/i }));

    const dialog = await screen.findByRole("dialog", {
      name: /一键生成宫格镜头板|Generate grid boards/i,
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /确认|Confirm/i }));

    await waitFor(() => {
      expect(onGenerateGrid).toHaveBeenCalledWith(1, "episode_1.json");
    });
  });
});

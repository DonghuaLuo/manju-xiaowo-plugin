import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { TimelineCanvas } from "./TimelineCanvas";
import { useCostStore } from "@/stores/cost-store";
import { useTasksStore } from "@/stores/tasks-store";
import type { EpisodeScript, ProjectData } from "@/types";

vi.mock("./PreprocessingView", () => ({
  PreprocessingView: () => <div data-testid="preprocessing-view" />,
}));

vi.mock("./ShotSplitView", () => ({
  ShotSplitView: () => <div data-testid="shot-split-view" />,
}));

vi.mock("./EpisodeHeader", () => ({
  EpisodeHeader: () => <div data-testid="episode-header" />,
}));

function makeEpisodeScript(): EpisodeScript {
  return {
    episode: 1,
    title: "EP1",
    content_mode: "narration",
    duration_seconds: 8,
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
      {
        segment_id: "SEG-2",
        episode: 1,
        duration_seconds: 4,
        segment_break: false,
        novel_text: "B",
        characters_in_segment: [],
        scenes: [],
        props: [],
        image_prompt: "image-2",
        video_prompt: "video-2",
        transition_to_next: "cut",
        generated_assets: {
          storyboard_image: null,
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

describe("TimelineCanvas", () => {
  beforeEach(() => {
    useTasksStore.setState(useTasksStore.getInitialState(), true);
    useCostStore.setState(useCostStore.getInitialState(), true);
    useCostStore.setState({
      debouncedFetch: vi.fn(),
      getEpisodeCost: () => undefined,
    });
  });

  it("asks for confirmation before batch generating storyboards", async () => {
    const onGenerateStoryboard = vi.fn();

    render(
      <TimelineCanvas
        projectName="demo"
        episode={1}
        hasDraft
        episodeScript={makeEpisodeScript()}
        scriptFile="episode_1.json"
        projectData={makeProjectData()}
        onGenerateStoryboard={onGenerateStoryboard}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: /批量生成分镜图|Batch generate storyboards/i }),
    );

    const dialog = await screen.findByRole("dialog", {
      name: /批量生成分镜图|Batch generate storyboards/i,
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /确认|Confirm/i }));

    await waitFor(() => expect(onGenerateStoryboard).toHaveBeenCalledTimes(2));
    expect(onGenerateStoryboard).toHaveBeenNthCalledWith(
      1,
      "SEG-1",
      "episode_1.json",
      undefined,
      undefined,
    );
    expect(onGenerateStoryboard).toHaveBeenNthCalledWith(
      2,
      "SEG-2",
      "episode_1.json",
      undefined,
      undefined,
    );
  });

  it("asks for confirmation before batch generating videos and skips shots without storyboard", async () => {
    const onGenerateVideo = vi.fn();

    render(
      <TimelineCanvas
        projectName="demo"
        episode={1}
        hasDraft
        episodeScript={makeEpisodeScript()}
        scriptFile="episode_1.json"
        projectData={makeProjectData()}
        onGenerateVideo={onGenerateVideo}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /批量生成视频|Batch generate videos/i }));

    const dialog = await screen.findByRole("dialog", {
      name: /批量生成视频|Batch generate videos/i,
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /确认|Confirm/i }));

    await waitFor(() => expect(onGenerateVideo).toHaveBeenCalledTimes(1));
    expect(onGenerateVideo).toHaveBeenCalledWith(
      "SEG-1",
      "episode_1.json",
      undefined,
      undefined,
    );
  });
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PluginSDK } from "xiaowo-sdk";
import { API } from "@/api";
import { MediaCard } from "./MediaCard";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MediaCard", () => {
  beforeEach(() => {
    vi.spyOn(API, "getVersions").mockResolvedValue({
      resource_type: "videos",
      resource_id: "SEG-1",
      current_version: 0,
      versions: [],
    });
    vi.spyOn(API, "getQualityRatings").mockResolvedValue({ ratings: [] });
  });

  it("uses a plugin lightbox for generated video fullscreen", async () => {
    render(
      <MediaCard
        kind="video"
        projectName="demo"
        segmentId="SEG-1"
        assetPath="videos/scene_SEG-1.mp4"
        aspectRatio="16:9"
        hideGenerateButton
      />,
    );

    const video = document.querySelector("video");
    expect(video).toHaveAttribute(
      "controlsList",
      "nofullscreen nodownload noremoteplayback",
    );

    fireEvent.click(screen.getByRole("button", { name: /最大化|Maximize/ }));

    await waitFor(() => expect(PluginSDK.maximize).toHaveBeenCalledTimes(1));
    expect(
      screen.getByRole("dialog", { name: /SEG-1 .*全屏预览/ }),
    ).toBeInTheDocument();
  });

  it("downloads generated video by copying the project file", async () => {
    vi.spyOn(API, "getProjectFileLocalPath").mockResolvedValueOnce(
      "D:/manju-projects/demo/videos/scene_SEG-1.mp4",
    );
    vi.mocked(PluginSDK.dialog.save).mockResolvedValueOnce("D:/exports/scene_SEG-1.mp4");

    render(
      <MediaCard
        kind="video"
        projectName="demo"
        segmentId="SEG-1"
        assetPath="videos/scene_SEG-1.mp4"
        aspectRatio="16:9"
        hideGenerateButton
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "下载视频" }));

    await waitFor(() =>
      expect(PluginSDK.fs.copyFile).toHaveBeenCalledWith(
        "D:/manju-projects/demo/videos/scene_SEG-1.mp4",
        "D:/exports/scene_SEG-1.mp4",
      ),
    );
    expect(PluginSDK.dialog.save).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "保存视频",
        defaultPath: "scene_SEG-1.mp4",
      }),
    );
  });

  it("shows current version quality and input status badges", async () => {
    vi.spyOn(API, "getVersions").mockResolvedValueOnce({
      resource_type: "videos",
      resource_id: "SEG-1",
      current_version: 1,
      versions: [
        {
          version: 1,
          filename: "scene_SEG-1.mp4",
          created_at: "2026-01-01T00:00:00Z",
          file_size: 1024,
          is_current: true,
          generation_quality: "final",
          generation_route: {
            provider: "doubao",
            model: "seedance",
            resolution: "1080p",
            duration_seconds: 6,
          },
          provider_input_images: {
            start_image: {
              resized: true,
              transcoded: false,
              source_bytes: 4_000_000,
              input_bytes: 800_000,
            },
          },
          source_storyboard_generation_quality: "final",
        },
      ],
    });

    render(
      <MediaCard
        kind="video"
        projectName="demo"
        segmentId="SEG-1"
        assetPath="videos/scene_SEG-1.mp4"
        aspectRatio="16:9"
        hideGenerateButton
      />,
    );

    expect(await screen.findByText("视频精修版")).toBeInTheDocument();
    expect(screen.getByText("1080p")).toBeInTheDocument();
    expect(screen.getByText("6s")).toBeInTheDocument();
    expect(screen.getByText("doubao/seedance")).toBeInTheDocument();
    expect(screen.getByText("已优化输入图")).toBeInTheDocument();
    expect(screen.getByText("基于当前精修分镜")).toBeInTheDocument();
  });

  it("shows grid storyboard as a valid video source badge", async () => {
    vi.spyOn(API, "getVersions").mockResolvedValueOnce({
      resource_type: "videos",
      resource_id: "SEG-1",
      current_version: 1,
      versions: [
        {
          version: 1,
          filename: "scene_SEG-1.mp4",
          created_at: "2026-01-01T00:00:00Z",
          file_size: 1024,
          is_current: true,
          generation_quality: "final",
          source_storyboard_generation_quality: "grid",
        },
      ],
    });

    render(
      <MediaCard
        kind="video"
        projectName="demo"
        segmentId="SEG-1"
        assetPath="videos/scene_SEG-1.mp4"
        aspectRatio="16:9"
        hideGenerateButton
      />,
    );

    expect(await screen.findByText("基于当前宫格分镜")).toBeInTheDocument();
  });

  it("requires an overall rating before saving dimension ratings", async () => {
    vi.spyOn(API, "getVersions").mockResolvedValueOnce({
      resource_type: "storyboards",
      resource_id: "SEG-1",
      current_version: 2,
      versions: [
        {
          version: 2,
          filename: "storyboard_SEG-1.png",
          created_at: "2026-01-01T00:00:00Z",
          file_size: 1024,
          is_current: true,
        },
      ],
    });
    const upsertRating = vi
      .spyOn(API, "upsertQualityRating")
      .mockResolvedValue({ rating: {} });

    render(
      <MediaCard
        kind="storyboard"
        projectName="demo"
        segmentId="SEG-1"
        assetPath="storyboards/storyboard_SEG-1.png"
        aspectRatio="16:9"
        hideGenerateButton
      />,
    );

    const dimensionSelect = await screen.findByRole("combobox", { name: "角色一致" });
    expect(dimensionSelect).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "设置质量评分 4 星" }));
    await waitFor(() =>
      expect(upsertRating).toHaveBeenCalledWith(
        "demo",
        expect.objectContaining({ rating: 4, dimensions: {} }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "角色一致" })).not.toBeDisabled(),
    );

    fireEvent.click(screen.getByRole("combobox", { name: "角色一致" }));
    fireEvent.click(await screen.findByRole("option", { name: "5" }));

    await waitFor(() =>
      expect(upsertRating).toHaveBeenLastCalledWith(
        "demo",
        expect.objectContaining({
          rating: 4,
          dimensions: { character_consistency: 5 },
        }),
      ),
    );
  });

  it("opens storyboard final generation modes before triggering generation", async () => {
    const onGenerate = vi.fn();

    render(
      <MediaCard
        kind="storyboard"
        projectName="demo"
        segmentId="SEG-1"
        assetPath={null}
        aspectRatio="16:9"
        onGenerate={onGenerate}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "精修版" }));
    expect(onGenerate).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /精修版 ·/ })).not.toBeInTheDocument();

    const draftLockedOption = await screen.findByRole("button", { name: /沿当前分镜精修/ });
    expect(draftLockedOption.querySelector("svg")).not.toBeInTheDocument();
    fireEvent.click(draftLockedOption);
    expect(onGenerate).toHaveBeenLastCalledWith("final", {
      finalGenerationMode: "draft_locked",
    });

    fireEvent.click(screen.getByRole("button", { name: "精修版" }));
    fireEvent.click(await screen.findByRole("button", { name: /重新出图/ }));
    expect(onGenerate).toHaveBeenLastCalledWith("final", {
      finalGenerationMode: "fresh_sample",
    });
  });

  it("renders the video final button with the same action icon", () => {
    render(
      <MediaCard
        kind="video"
        projectName="demo"
        segmentId="SEG-1"
        assetPath={null}
        aspectRatio="16:9"
        estimatedCost={{ CNY: 1.23 }}
        onGenerate={vi.fn()}
      />,
    );

    const finalButton = screen.getByRole("button", { name: "精修版" });
    expect(finalButton.querySelector("svg")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成快速版" })).toBeInTheDocument();
  });
});

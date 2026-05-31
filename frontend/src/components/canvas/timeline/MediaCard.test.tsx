import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PluginSDK } from "xiaowo-sdk";
import { API } from "@/api";
import { MediaCard } from "./MediaCard";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MediaCard", () => {
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
});

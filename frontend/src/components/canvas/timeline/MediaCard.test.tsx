import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PluginSDK } from "xiaowo-sdk";
import { MediaCard } from "./MediaCard";

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
});

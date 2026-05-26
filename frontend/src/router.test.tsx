import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { PluginSDK } from "xiaowo-sdk";
import { API } from "@/api";
import { AppRoutes } from "./router";

vi.mock("@/components/layout", () => ({
  StudioLayout: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="studio-layout">{children}</div>
  ),
}));

vi.mock("@/components/canvas/StudioCanvasRouter", () => ({
  StudioCanvasRouter: () => <div data-testid="studio-canvas" />,
}));

vi.mock("@/components/pages/ProjectsPage", () => ({
  ProjectsPage: () => <div data-testid="projects-page" />,
}));

vi.mock("@/components/pages/SystemConfigPage", () => ({
  SystemConfigPage: () => <div data-testid="system-config-page" />,
}));

vi.mock("@/components/pages/ProjectSettingsPage", () => ({
  ProjectSettingsPage: () => <div data-testid="project-settings-page" />,
}));

vi.mock("@/components/pages/AssetLibraryPage", () => ({
  AssetLibraryPage: () => <div data-testid="asset-library-page" />,
}));

vi.mock("@/pages/NotFoundPage", () => ({
  NotFoundPage: () => <div data-testid="not-found-page" />,
}));

vi.mock("@/components/layout/ToastOverlay", () => ({
  ToastOverlay: () => null,
}));

function renderRoutes(path: string) {
  const location = memoryLocation({ path, record: true });
  return render(
    <Router hook={location.hook}>
      <AppRoutes />
    </Router>,
  );
}

describe("AppRoutes", () => {
  it("retries window maximize after a failed first request and stops after success", async () => {
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        content_mode: "narration",
        style: "Anime",
        episodes: [],
        characters: {},
        scenes: {},
        props: {},
      },
      scripts: {},
      asset_fingerprints: {},
    });

    const maximize = vi.mocked(PluginSDK.maximize);
    maximize.mockRejectedValueOnce(new Error("maximize failed"));
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    const first = renderRoutes("/app/projects/demo");
    await waitFor(() => {
      expect(maximize).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(consoleError).toHaveBeenCalledWith(
        "Failed to maximize plugin window on first project entry",
        expect.any(Error),
      );
    });
    first.unmount();

    const second = renderRoutes("/app/projects/second-demo");
    await waitFor(() => {
      expect(maximize).toHaveBeenCalledTimes(2);
    });
    second.unmount();

    renderRoutes("/app/projects/third-demo");
    await waitFor(() => {
      expect(API.getProject).toHaveBeenCalledWith("third-demo");
    });
    expect(maximize).toHaveBeenCalledTimes(2);
    consoleError.mockRestore();
  });
});

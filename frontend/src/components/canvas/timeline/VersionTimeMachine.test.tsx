import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { VersionTimeMachine } from "./VersionTimeMachine";
import { useAppStore } from "@/stores/app-store";

describe("VersionTimeMachine", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.restoreAllMocks();
  });

  it("loads versions on demand and restores a previous version", async () => {
    vi.spyOn(API, "getVersions")
      .mockResolvedValueOnce({
        resource_type: "storyboards",
        resource_id: "SEG-1",
        current_version: 2,
        versions: [
          {
            version: 1,
            filename: "v1.png",
            created_at: "2026-02-01T00:00:00Z",
            file_size: 10,
            is_current: false,
            prompt: "old prompt",
            file_url: "/api/v1/files/demo/versions/storyboards/v1.png",
          },
          {
            version: 2,
            filename: "v2.png",
            created_at: "2026-02-01T01:00:00Z",
            file_size: 12,
            is_current: true,
            file_url: "/api/v1/files/demo/versions/storyboards/v2.png",
          },
        ],
      })
      .mockResolvedValueOnce({
        resource_type: "storyboards",
        resource_id: "SEG-1",
        current_version: 1,
        versions: [
          {
            version: 1,
            filename: "v1.png",
            created_at: "2026-02-01T00:00:00Z",
            file_size: 10,
            is_current: true,
            prompt: "old prompt",
            file_url: "/api/v1/files/demo/versions/storyboards/v1.png",
          },
          {
            version: 2,
            filename: "v2.png",
            created_at: "2026-02-01T01:00:00Z",
            file_size: 12,
            is_current: false,
          },
        ],
      });
    vi.spyOn(API, "restoreVersion").mockResolvedValue({ success: true });
    const onRestore = vi.fn().mockResolvedValue(undefined);

    render(
      <VersionTimeMachine
        projectName="demo"
        resourceType="storyboards"
        resourceId="SEG-1"
        onRestore={onRestore}
      />,
    );

    expect(API.getVersions).not.toHaveBeenCalled();

    // Open the panel
    fireEvent.click(screen.getByRole("button", { name: /版本/ }));

    // Click v1 pill to preview
    expect(await screen.findByRole("button", { name: "v1" })).toBeInTheDocument();
    expect(API.getVersions).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    expect(await screen.findByAltText("版本 v1 预览")).toBeInTheDocument();
    expect(screen.getByText("old prompt")).toBeInTheDocument();

    // Click restore button in header
    fireEvent.click(screen.getByRole("button", { name: /切换到此版本/ }));

    await waitFor(() => {
      expect(API.restoreVersion).toHaveBeenCalledWith(
        "demo",
        "storyboards",
        "SEG-1",
        1,
      );
      expect(onRestore).toHaveBeenCalledWith(1);
      expect(API.getVersions).toHaveBeenCalledTimes(2);
      expect(useAppStore.getState().toast?.text).toBe("已切换到 v1");
    });
  });

  it("shows character preview with contain layout so tall images are not cropped", async () => {
    vi.spyOn(API, "getVersions").mockResolvedValue({
      resource_type: "characters",
      resource_id: "Hero",
      current_version: 2,
      versions: [
        {
          version: 1,
          filename: "v1.png",
          created_at: "2026-02-01T00:00:00Z",
          file_size: 10,
          is_current: false,
          prompt: "hero prompt",
          file_url: "/api/v1/files/demo/versions/characters/Hero_v1.png",
        },
        {
          version: 2,
          filename: "v2.png",
          created_at: "2026-02-01T01:00:00Z",
          file_size: 12,
          is_current: true,
          file_url: "/api/v1/files/demo/versions/characters/Hero_v2.png",
        },
      ],
    });

    render(
      <VersionTimeMachine
        projectName="demo"
        resourceType="characters"
        resourceId="Hero"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /版本/ }));
    expect(await screen.findByRole("button", { name: "v1" })).toBeInTheDocument();

    // Click v1 pill to preview
    fireEvent.click(screen.getByRole("button", { name: "v1" }));

    const previewImage = await screen.findByAltText("版本 v1 预览");
    expect(previewImage).toHaveClass("object-contain");
    expect(previewImage.parentElement).toHaveClass("h-80");

    fireEvent.click(previewImage);
    expect(
      screen.getByRole("dialog", { name: "版本 v1 预览 全屏预览" }),
    ).toBeInTheDocument();
  });

  it("deletes a non-current design version after confirmation", async () => {
    vi.spyOn(API, "getVersions")
      .mockResolvedValueOnce({
        resource_type: "characters",
        resource_id: "Hero",
        current_version: 2,
        versions: [
          {
            version: 1,
            filename: "v1.png",
            created_at: "2026-02-01T00:00:00Z",
            file_size: 10,
            is_current: false,
            prompt: "old prompt",
            file_url: "/api/v1/files/demo/versions/characters/Hero_v1.png",
          },
          {
            version: 2,
            filename: "v2.png",
            created_at: "2026-02-01T01:00:00Z",
            file_size: 12,
            is_current: true,
            file_url: "/api/v1/files/demo/versions/characters/Hero_v2.png",
          },
        ],
      })
      .mockResolvedValueOnce({
        resource_type: "characters",
        resource_id: "Hero",
        current_version: 2,
        versions: [
          {
            version: 2,
            filename: "v2.png",
            created_at: "2026-02-01T01:00:00Z",
            file_size: 12,
            is_current: true,
            file_url: "/api/v1/files/demo/versions/characters/Hero_v2.png",
          },
        ],
      });
    vi.spyOn(API, "deleteVersion").mockResolvedValue({ success: true });

    render(
      <VersionTimeMachine
        projectName="demo"
        resourceType="characters"
        resourceId="Hero"
        allowDelete
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /版本/ }));
    expect(await screen.findByRole("button", { name: "v1" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    fireEvent.click(await screen.findByRole("button", { name: "删除版本" }));

    expect(await screen.findByRole("dialog", { name: "删除版本" })).toBeInTheDocument();
    const deleteButtons = screen.getAllByRole("button", { name: "删除版本" });
    fireEvent.mouseDown(deleteButtons[deleteButtons.length - 1]);
    expect(screen.getByRole("dialog", { name: "删除版本" })).toBeInTheDocument();
    fireEvent.click(deleteButtons[deleteButtons.length - 1]);

    await waitFor(() => {
      expect(API.deleteVersion).toHaveBeenCalledWith("demo", "characters", "Hero", 1);
      expect(API.getVersions).toHaveBeenCalledTimes(2);
      expect(useAppStore.getState().toast?.text).toBe("已删除 v1");
    });
  });

  it("warns when version file cleanup partly fails", async () => {
    vi.spyOn(API, "getVersions")
      .mockResolvedValueOnce({
        resource_type: "characters",
        resource_id: "Hero",
        current_version: 2,
        versions: [
          {
            version: 1,
            filename: "v1.png",
            created_at: "2026-02-01T00:00:00Z",
            file_size: 10,
            is_current: false,
          },
          {
            version: 2,
            filename: "v2.png",
            created_at: "2026-02-01T01:00:00Z",
            file_size: 12,
            is_current: true,
          },
        ],
      })
      .mockResolvedValueOnce({
        resource_type: "characters",
        resource_id: "Hero",
        current_version: 2,
        versions: [
          {
            version: 2,
            filename: "v2.png",
            created_at: "2026-02-01T01:00:00Z",
            file_size: 12,
            is_current: true,
          },
        ],
      });
    vi.spyOn(API, "deleteVersion").mockResolvedValue({
      success: true,
      failed_files: ["versions/characters/Hero_v1.png"],
      file_delete_errors: [{ file: "versions/characters/Hero_v1.png", message: "busy" }],
    });

    render(
      <VersionTimeMachine
        projectName="demo"
        resourceType="characters"
        resourceId="Hero"
        allowDelete
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /版本/ }));
    expect(await screen.findByRole("button", { name: "v1" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    fireEvent.click(await screen.findByRole("button", { name: "删除版本" }));
    const deleteButtons = screen.getAllByRole("button", { name: "删除版本" });
    fireEvent.click(deleteButtons[deleteButtons.length - 1]);

    await waitFor(() => {
      expect(API.deleteVersion).toHaveBeenCalledWith("demo", "characters", "Hero", 1);
      expect(API.getVersions).toHaveBeenCalledTimes(2);
      expect(useAppStore.getState().toast?.text).toBe(
        "已删除记录，但有 1 个文件未成功删除。",
      );
      expect(useAppStore.getState().toast?.tone).toBe("warning");
    });
  });

  it("keeps delete success when version reload fails after deletion", async () => {
    vi.spyOn(API, "getVersions")
      .mockResolvedValueOnce({
        resource_type: "characters",
        resource_id: "Hero",
        current_version: 2,
        versions: [
          {
            version: 1,
            filename: "v1.png",
            created_at: "2026-02-01T00:00:00Z",
            file_size: 10,
            is_current: false,
            prompt: "old prompt",
            file_url: "/api/v1/files/demo/versions/characters/Hero_v1.png",
          },
          {
            version: 2,
            filename: "v2.png",
            created_at: "2026-02-01T01:00:00Z",
            file_size: 12,
            is_current: true,
            file_url: "/api/v1/files/demo/versions/characters/Hero_v2.png",
          },
        ],
      })
      .mockRejectedValueOnce(new Error("reload failed"));
    vi.spyOn(API, "deleteVersion").mockResolvedValue({ success: true });

    render(
      <VersionTimeMachine
        projectName="demo"
        resourceType="characters"
        resourceId="Hero"
        allowDelete
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /版本/ }));
    expect(await screen.findByRole("button", { name: "v1" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "v1" }));
    fireEvent.click(await screen.findByRole("button", { name: "删除版本" }));
    const deleteButtons = screen.getAllByRole("button", { name: "删除版本" });
    fireEvent.click(deleteButtons[deleteButtons.length - 1]);

    await waitFor(() => {
      expect(API.deleteVersion).toHaveBeenCalledWith("demo", "characters", "Hero", 1);
      expect(screen.queryByRole("dialog", { name: "删除版本" })).not.toBeInTheDocument();
      expect(useAppStore.getState().toast?.text).toBe("加载失败: reload failed");
    });
  });

  it("does not show delete button for the current design version", async () => {
    vi.spyOn(API, "getVersions").mockResolvedValue({
      resource_type: "characters",
      resource_id: "Hero",
      current_version: 2,
      versions: [
        {
          version: 1,
          filename: "v1.png",
          created_at: "2026-02-01T00:00:00Z",
          file_size: 10,
          is_current: false,
          file_url: "/api/v1/files/demo/versions/characters/Hero_v1.png",
        },
        {
          version: 2,
          filename: "v2.png",
          created_at: "2026-02-01T01:00:00Z",
          file_size: 12,
          is_current: true,
          file_url: "/api/v1/files/demo/versions/characters/Hero_v2.png",
        },
      ],
    });

    render(
      <VersionTimeMachine
        projectName="demo"
        resourceType="characters"
        resourceId="Hero"
        allowDelete
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /版本/ }));
    expect(await screen.findByRole("button", { name: "v2" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "v2" }));

    expect(await screen.findByText("当前")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "删除版本" })).not.toBeInTheDocument();
  });
});

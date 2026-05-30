import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { DeleteDesignButton } from "./DeleteDesignButton";

describe("DeleteDesignButton", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    useProjectsStore.setState({ assetFingerprints: {} });
    vi.restoreAllMocks();
  });

  it("shows a warning when the design is already used", async () => {
    vi.spyOn(API, "getDesignResourceUsage").mockResolvedValue({
      resource_type: "characters",
      resource_id: "Hero",
      in_use: true,
      usages: [{ script_file: "episode_1.json", kind: "segment", item_id: "E1S01" }],
    });

    render(
      <DeleteDesignButton
        projectName="demo"
        resourceType="characters"
        resourceId="Hero"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "删除设计图" }));

    await waitFor(() => {
      expect(useAppStore.getState().toast?.text).toBe("已应用，无法删除");
      expect(API.getDesignResourceUsage).toHaveBeenCalledWith("demo", "characters", "Hero");
    });
  });

  it("confirms and deletes an unused design", async () => {
    const onDeleted = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(API, "getDesignResourceUsage").mockResolvedValue({
      resource_type: "characters",
      resource_id: "Hero",
      in_use: false,
      usages: [],
    });
    vi.spyOn(API, "deleteDesignResource").mockResolvedValue({
      success: true,
      asset_fingerprints: { "characters/Hero.png": 0 },
    });

    render(
      <DeleteDesignButton
        projectName="demo"
        resourceType="characters"
        resourceId="Hero"
        onDeleted={onDeleted}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "删除设计图" }));

    expect(await screen.findByRole("dialog", { name: "删除设计图" })).toBeInTheDocument();
    const deleteButtons = screen.getAllByRole("button", { name: "删除设计图" });
    fireEvent.click(deleteButtons[deleteButtons.length - 1]);

    await waitFor(() => {
      expect(API.deleteDesignResource).toHaveBeenCalledWith("demo", "characters", "Hero");
      expect(onDeleted).toHaveBeenCalled();
      expect(useProjectsStore.getState().assetFingerprints["characters/Hero.png"]).toBe(0);
      expect(useAppStore.getState().toast?.text).toBe("已删除 Hero");
    });
  });

  it("warns when design file cleanup partly fails", async () => {
    const onDeleted = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(API, "getDesignResourceUsage").mockResolvedValue({
      resource_type: "characters",
      resource_id: "Hero",
      in_use: false,
      usages: [],
    });
    vi.spyOn(API, "deleteDesignResource").mockResolvedValue({
      success: true,
      failed_files: ["characters/Hero.png"],
      file_delete_errors: [{ file: "characters/Hero.png", message: "busy" }],
    });

    render(
      <DeleteDesignButton
        projectName="demo"
        resourceType="characters"
        resourceId="Hero"
        onDeleted={onDeleted}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "删除设计图" }));
    expect(await screen.findByRole("dialog", { name: "删除设计图" })).toBeInTheDocument();
    const deleteButtons = screen.getAllByRole("button", { name: "删除设计图" });
    fireEvent.click(deleteButtons[deleteButtons.length - 1]);

    await waitFor(() => {
      expect(API.deleteDesignResource).toHaveBeenCalledWith("demo", "characters", "Hero");
      expect(onDeleted).toHaveBeenCalled();
      expect(useAppStore.getState().toast?.text).toBe(
        "已删除记录，但有 1 个文件未成功删除。",
      );
      expect(useAppStore.getState().toast?.tone).toBe("warning");
    });
  });

  it("keeps delete success when reload fails after deletion", async () => {
    const onDeleted = vi.fn().mockRejectedValue(new Error("reload failed"));
    vi.spyOn(API, "getDesignResourceUsage").mockResolvedValue({
      resource_type: "characters",
      resource_id: "Hero",
      in_use: false,
      usages: [],
    });
    vi.spyOn(API, "deleteDesignResource").mockResolvedValue({
      success: true,
      asset_fingerprints: { "characters/Hero.png": 0 },
    });

    render(
      <DeleteDesignButton
        projectName="demo"
        resourceType="characters"
        resourceId="Hero"
        onDeleted={onDeleted}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "删除设计图" }));
    expect(await screen.findByRole("dialog", { name: "删除设计图" })).toBeInTheDocument();
    const deleteButtons = screen.getAllByRole("button", { name: "删除设计图" });
    fireEvent.click(deleteButtons[deleteButtons.length - 1]);

    await waitFor(() => {
      expect(API.deleteDesignResource).toHaveBeenCalledWith("demo", "characters", "Hero");
      expect(onDeleted).toHaveBeenCalled();
      expect(screen.queryByRole("dialog", { name: "删除设计图" })).not.toBeInTheDocument();
      expect(useAppStore.getState().toast?.text).toBe("加载失败: reload failed");
    });
  });
});

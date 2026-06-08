import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { BulkAddToLibraryDialog } from "./BulkAddToLibraryDialog";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts) {
        return `${key}:${Object.entries(opts)
          .map(([name, value]) => `${name}=${String(value)}`)
          .join(",")}`;
      }
      return key;
    },
  }),
}));

describe("BulkAddToLibraryDialog", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useAppStore.setState({ toast: null });
  });

  it("classifies current page items and only imports generated items not already in library", async () => {
    vi.spyOn(API, "listAssets").mockResolvedValue({
      total: 1,
      items: [
        {
          id: "asset-1",
          type: "character",
          name: "Hero",
          description: "",
          voice_style: "",
          image_path: null,
          source_project: null,
          updated_at: null,
        },
      ],
    });
    const addSpy = vi.spyOn(API, "addAssetFromProject").mockResolvedValue({
      asset: {
        id: "asset-2",
        type: "character",
        name: "Villain",
        description: "",
        voice_style: "",
        image_path: null,
        source_project: "demo",
        updated_at: null,
      },
    });
    const onClose = vi.fn();

    render(
      <BulkAddToLibraryDialog
        pageTitle="角色集"
        projectName="demo"
        resourceType="character"
        items={[
          { name: "Hero", description: "已在资产库", sheetPath: "characters/hero.png" },
          { name: "Villain", description: "可加入", sheetPath: "characters/villain.png" },
          { name: "Sidekick", description: "还没出图", sheetPath: null },
        ]}
        onClose={onClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("batch_add_to_library_ready")).toBeInTheDocument();
      expect(screen.getByText("Villain")).toBeInTheDocument();
      expect(screen.getByText("Sidekick")).toBeInTheDocument();
    });
    expect(screen.queryByText("Hero")).not.toBeInTheDocument();
    expect(screen.getByAltText("Villain")).toHaveAttribute(
      "src",
      expect.stringContaining("characters/villain.png"),
    );
    expect(screen.queryByAltText("Hero")).not.toBeInTheDocument();
    expect(screen.queryByAltText("Sidekick")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "confirm_batch_add_to_library" }));

    await waitFor(() => {
      expect(addSpy).toHaveBeenCalledTimes(1);
      expect(addSpy).toHaveBeenCalledWith({
        project_name: "demo",
        resource_type: "character",
        resource_id: "Villain",
      });
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(useAppStore.getState().toast?.tone).toBe("success");
    });
  });

  it("scans paged asset library results while hiding existing items from the dialog", async () => {
    vi.spyOn(API, "listAssets").mockImplementation((async (params = {}) => {
      if ((params.offset ?? 0) === 0) {
        return {
          total: 61,
          items: Array.from({ length: 60 }, (_, index) => ({
            id: `asset-${index + 1}`,
            type: "scene" as const,
            name: `Scene ${index + 1}`,
            description: "",
            voice_style: "",
            image_path: null,
            source_project: null,
            updated_at: null,
          })),
        };
      }
      return {
        total: 61,
        items: [
          {
            id: "asset-61",
            type: "scene" as const,
            name: "Final Scene",
            description: "",
            voice_style: "",
            image_path: null,
            source_project: null,
            updated_at: null,
          },
        ],
      };
    }) satisfies typeof API.listAssets);

    render(
      <BulkAddToLibraryDialog
        pageTitle="场景库"
        projectName="demo"
        resourceType="scene"
        items={[
          { name: "Final Scene", description: "已经入库", sheetPath: "scenes/final.png" },
          { name: "New Scene", description: "待加入", sheetPath: "scenes/new.png" },
        ]}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(API.listAssets).toHaveBeenCalledTimes(2);
      expect(screen.getByText("New Scene")).toBeInTheDocument();
    });
    expect(screen.queryByText("Final Scene")).not.toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: "confirm_batch_add_to_library" }),
    ).not.toBeDisabled();
  });
});

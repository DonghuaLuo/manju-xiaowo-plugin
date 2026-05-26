import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AssetPickerModal } from "./AssetPickerModal";
import { API } from "@/api";

// Mock i18next
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts) {
        let result = key;
        for (const [k, v] of Object.entries(opts)) {
          result = result.replace(`{{${k}}}`, String(v));
        }
        return result;
      }
      return key;
    },
  }),
}));

const fixtures = [
  { id: "1", type: "character" as const, name: "王小明", description: "", voice_style: "", image_path: null, source_project: null, updated_at: null },
  { id: "2", type: "character" as const, name: "小师妹", description: "", voice_style: "", image_path: null, source_project: null, updated_at: null },
];

describe("AssetPickerModal", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("multi-selects and calls onImport", async () => {
    vi.spyOn(API, "listAssets").mockResolvedValue({ items: fixtures });
    const onImport = vi.fn();
    render(
      <AssetPickerModal
        type="character"
        existingNames={new Set()}
        onClose={() => {}}
        onImport={onImport}
      />
    );
    await waitFor(() => screen.getByText("王小明"));
    fireEvent.click(screen.getByText("王小明"));
    fireEvent.click(screen.getByText("小师妹"));
    const buttons = screen.getAllByRole("button");
    const importButton = buttons.find(b => b.textContent?.includes("confirm_import") && !(b as HTMLButtonElement).disabled);
    fireEvent.click(importButton!);
    await waitFor(() => expect(onImport).toHaveBeenCalledWith(["1", "2"]));
  });

  it("disables already-in-project assets", async () => {
    vi.spyOn(API, "listAssets").mockResolvedValue({ items: fixtures });
    render(
      <AssetPickerModal type="character" existingNames={new Set(["王小明"])}
        onClose={() => {}} onImport={vi.fn()} />
    );
    await waitFor(() => screen.getByText("王小明"));
    const card = screen.getByRole("button", { name: /王小明/ });
    expect(card).toHaveAttribute("aria-disabled", "true");
  });

  it("previews only assets that are not already in the project", async () => {
    vi.spyOn(API, "listAssets").mockResolvedValue({
      items: [
        {
          ...fixtures[0],
          image_path: "_global_assets/characters/wang.png",
          updated_at: "2026-01-01T00:00:00Z",
        },
        {
          ...fixtures[1],
          image_path: "_global_assets/characters/shimei.png",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
    });

    render(
      <AssetPickerModal type="character" existingNames={new Set(["王小明"])}
        onClose={() => {}} onImport={vi.fn()} />
    );

    await waitFor(() => screen.getByText("小师妹"));

    expect(
      screen.queryByRole("button", { name: "王小明 全屏预览" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "小师妹 全屏预览" }));

    expect(
      screen.getByRole("dialog", { name: "小师妹 全屏预览" }),
    ).toBeInTheDocument();
  });
});

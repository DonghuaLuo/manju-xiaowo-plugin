import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AddCharacterForm } from "./AddCharacterForm";

const desktopFileMock = vi.hoisted(() => ({
  pickDesktopFile: vi.fn(),
}));

vi.mock("@/utils/desktop-file", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/utils/desktop-file")>();
  return {
    ...actual,
    pickDesktopFile: desktopFileMock.pickDesktopFile,
  };
});

function desktopImageRef(name = "hero.png") {
  return {
    kind: "desktop-file" as const,
    path: `C:\\fixtures\\${name}`,
    name,
    previewUrl: `asset://fixtures/${name}`,
    contentType: "image/png",
  };
}

describe("AddCharacterForm", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    desktopFileMock.pickDesktopFile.mockReset();
    Object.defineProperty(globalThis.URL, "createObjectURL", {
      writable: true,
      value: vi.fn(() => "blob:add-character-ref"),
    });
    Object.defineProperty(globalThis.URL, "revokeObjectURL", {
      writable: true,
      value: vi.fn(),
    });
  });

  it("submits an optional reference file together with the new character", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <AddCharacterForm onSubmit={onSubmit} onCancel={vi.fn()} />,
    );

    fireEvent.change(screen.getByPlaceholderText("角色名称"), {
      target: { value: "Hero" },
    });
    fireEvent.change(
      screen.getByPlaceholderText("角色外貌、性格、背景等描述..."),
      {
        target: { value: "hero desc" },
      },
    );
    fireEvent.change(screen.getByPlaceholderText("例如：温柔但有威严"), {
      target: { value: "warm" },
    });

    const file = desktopImageRef();
    desktopFileMock.pickDesktopFile.mockResolvedValueOnce(file);
    fireEvent.click(screen.getByRole("button", { name: /上传参考图/ }));
    await waitFor(() => {
      expect(screen.getByText("已选择参考图")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "添加" }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith("Hero", "hero desc", "warm", file);
    });
  });
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CharacterCard } from "./CharacterCard";
import { useAppStore } from "@/stores/app-store";

vi.mock("@/components/canvas/timeline/VersionTimeMachine", () => ({
  VersionTimeMachine: () => <div data-testid="version-time-machine">versions</div>,
}));

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

describe("CharacterCard", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.restoreAllMocks();
    desktopFileMock.pickDesktopFile.mockReset();
    Object.defineProperty(globalThis.URL, "createObjectURL", {
      writable: true,
      value: vi.fn(() => "blob:character-ref"),
    });
    Object.defineProperty(globalThis.URL, "revokeObjectURL", {
      writable: true,
      value: vi.fn(),
    });
  });

  it("renders existing saved reference image", () => {
    render(
      <CharacterCard
        name="Hero"
        character={{
          description: "hero desc",
          voice_style: "warm",
          reference_image: "characters/refs/Hero.png",
        }}
        projectName="demo"
        onSave={vi.fn()}
        onGenerate={vi.fn()}
      />,
    );

    expect(screen.getByAltText(/Hero.*参考图/)).toHaveAttribute(
      "src",
      "/api/v1/files/demo/characters/refs/Hero.png",
    );
  });

  it("keeps selected reference file until save and submits it in the payload", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <CharacterCard
        name="Hero"
        character={{ description: "hero desc", voice_style: "warm" }}
        projectName="demo"
        onSave={onSave}
        onGenerate={vi.fn()}
      />,
    );

    const file = desktopImageRef();
    desktopFileMock.pickDesktopFile.mockResolvedValueOnce(file);
    fireEvent.click(screen.getByRole("button", { name: "上传参考图" }));

    await waitFor(() => {
      expect(screen.getByText(/待保存参考图/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /保存/ }));

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith("Hero", {
        description: "hero desc",
        voiceStyle: "warm",
        referenceFile: file,
      });
    });
  });

  it("auto-resizes the description textarea as content grows", async () => {
    render(
      <CharacterCard
        name="Hero"
        character={{ description: "hero desc", voice_style: "warm" }}
        projectName="demo"
        onSave={vi.fn().mockResolvedValue(undefined)}
        onGenerate={vi.fn()}
      />,
    );

    const textarea = screen.getByPlaceholderText(/角色描述/);
    Object.defineProperty(textarea, "scrollHeight", {
      configurable: true,
      value: 128,
    });

    fireEvent.change(textarea, { target: { value: "hero desc with more lines" } });

    await waitFor(() => {
      expect(textarea).toHaveStyle({ height: "128px" });
    });
  });

  it("renders voice style as a multiline textarea and saves edited lines", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <CharacterCard
        name="Hero"
        character={{ description: "hero desc", voice_style: "warm" }}
        projectName="demo"
        onSave={onSave}
        onGenerate={vi.fn()}
      />,
    );

    const voiceStyle = screen.getByLabelText("声音风格") as HTMLTextAreaElement;
    expect(voiceStyle.tagName).toBe("TEXTAREA");
    expect(voiceStyle.rows).toBe(3);

    fireEvent.change(voiceStyle, {
      target: { value: "温柔但有威严\n语速偏慢，尾音稳定" },
    });
    fireEvent.click(screen.getByRole("button", { name: /保存/ }));

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith("Hero", {
        description: "hero desc",
        voiceStyle: "温柔但有威严\n语速偏慢，尾音稳定",
        referenceFile: null,
      });
    });
  });
});

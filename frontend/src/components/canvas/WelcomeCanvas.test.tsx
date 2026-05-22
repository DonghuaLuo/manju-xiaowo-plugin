import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nextProvider } from "react-i18next";
import { WelcomeCanvas } from "@/components/canvas/WelcomeCanvas";
import { API } from "@/api";
import i18n from "@/i18n";
import { useAppStore } from "@/stores/app-store";

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

function desktopSourceRef(name = "novel.txt") {
  return {
    kind: "desktop-file" as const,
    path: `C:\\fixtures\\${name}`,
    name,
    contentType: "text/plain",
  };
}

describe("WelcomeCanvas", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.restoreAllMocks();
    desktopFileMock.pickDesktopFile.mockReset();
  });

  it("shows the project title instead of the internal project name", async () => {
    vi.spyOn(API, "listFiles").mockResolvedValue({ files: { source: [] } });

    render(
      <WelcomeCanvas
        projectName="halou-92d19a04"
        projectTitle="哈喽项目"
      />,
    );

    expect(await screen.findByText("欢迎来到 哈喽项目！")).toBeInTheDocument();
    expect(screen.queryByText("欢迎来到 halou-92d19a04！")).not.toBeInTheDocument();
  });
});

function renderWelcome(props: Partial<Parameters<typeof WelcomeCanvas>[0]>) {
  return render(
    <I18nextProvider i18n={i18n}>
      <WelcomeCanvas
        projectName="p"
        onUpload={props.onUpload ?? vi.fn().mockResolvedValue(undefined)}
        onAnalyze={props.onAnalyze ?? vi.fn().mockResolvedValue(undefined)}
        {...props}
      />
    </I18nextProvider>,
  );
}

describe("WelcomeCanvas auto-analyze on first upload", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.restoreAllMocks();
    desktopFileMock.pickDesktopFile.mockReset();
    vi.spyOn(API, "listFiles").mockResolvedValue({ files: { source: [] } });
  });

  it("triggers onAnalyze automatically after first upload from idle", async () => {
    const onUpload = vi.fn().mockResolvedValue(undefined);
    const onAnalyze = vi.fn().mockResolvedValue(undefined);
    renderWelcome({ onUpload, onAnalyze });

    const file = desktopSourceRef("novel.txt");
    desktopFileMock.pickDesktopFile.mockResolvedValueOnce(file);
    const dropZoneLabel = await screen.findByText("拖拽文件到此处");
    fireEvent.click(dropZoneLabel.closest("button")!);

    await waitFor(() => expect(onUpload).toHaveBeenCalledWith(file));
    await waitFor(() => expect(onAnalyze).toHaveBeenCalledTimes(1));
  });

  it("does NOT auto-trigger analyze when uploading from has_sources", async () => {
    vi.spyOn(API, "listFiles").mockResolvedValue({
      files: { source: [{ name: "existing.txt", size: 10, url: "/x" }] },
    });
    const onUpload = vi.fn().mockResolvedValue(undefined);
    const onAnalyze = vi.fn();
    renderWelcome({ onUpload, onAnalyze });

    const file = desktopSourceRef("second.docx");
    desktopFileMock.pickDesktopFile.mockResolvedValueOnce(file);
    fireEvent.click(await screen.findByRole("button", { name: /添加更多文件/ }));

    await waitFor(() => expect(onUpload).toHaveBeenCalled());
    expect(onAnalyze).not.toHaveBeenCalled();
  });
});

describe("WelcomeCanvas accept extension", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.restoreAllMocks();
    desktopFileMock.pickDesktopFile.mockReset();
    vi.spyOn(API, "listFiles").mockResolvedValue({ files: { source: [] } });
  });

  it("offers .docx, .epub, .pdf in the desktop file dialog filter", async () => {
    renderWelcome({});
    desktopFileMock.pickDesktopFile.mockResolvedValueOnce(null);
    const dropZoneLabel = await screen.findByText("拖拽文件到此处");
    fireEvent.click(dropZoneLabel.closest("button")!);

    await waitFor(() => {
      expect(desktopFileMock.pickDesktopFile).toHaveBeenCalledWith(
        expect.objectContaining({
          filters: [
            expect.objectContaining({
              extensions: expect.arrayContaining(["docx", "epub", "pdf"]),
            }),
          ],
        }),
      );
    });
  });
});

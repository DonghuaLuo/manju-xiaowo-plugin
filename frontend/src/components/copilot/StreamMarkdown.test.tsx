import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StreamMarkdown } from "./StreamMarkdown";

const desktopDownloadMock = vi.hoisted(() => ({
  saveBlobWithDialog: vi.fn(),
}));

vi.mock("@/utils/desktop-download", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/utils/desktop-download")>();
  return {
    ...actual,
    saveBlobWithDialog: desktopDownloadMock.saveBlobWithDialog,
  };
});

describe("StreamMarkdown table controls", () => {
  beforeEach(() => {
    desktopDownloadMock.saveBlobWithDialog.mockReset();
  });

  it("saves markdown tables through the desktop save dialog", async () => {
    const user = userEvent.setup();
    desktopDownloadMock.saveBlobWithDialog.mockResolvedValue("C:\\exports\\table.csv");

    render(
      <StreamMarkdown
        content={[
          "| 镜头 | 内容 |",
          "| --- | --- |",
          "| 1 | 开场旁白 |",
        ].join("\n")}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "下载" }));
    await user.click(await screen.findByRole("menuitem", { name: "CSV" }));

    await waitFor(() => {
      expect(desktopDownloadMock.saveBlobWithDialog).toHaveBeenCalledTimes(1);
    });

    const [blob, options] = desktopDownloadMock.saveBlobWithDialog.mock.calls[0] as [
      Blob,
      {
        title: string;
        defaultFileName: string;
        filters: Array<{ name: string; extensions: string[] }>;
      },
    ];
    expect(options.title).toBe("保存表格");
    expect(options.defaultFileName).toBe("table.csv");
    expect(options.filters).toEqual([{ name: "CSV", extensions: ["csv"] }]);
    await expect(blob.text()).resolves.toContain("开场旁白");
  });

  it("renders table fullscreen on an opaque plugin surface", async () => {
    const user = userEvent.setup();

    render(
      <StreamMarkdown
        content={[
          "| 集数 | 剧本 |",
          "| --- | --- |",
          "| E01 | 第一集 |",
        ].join("\n")}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "最大化" }));

    expect(screen.getByRole("dialog", { name: "最大化" })).toHaveClass(
      "markdown-table-fullscreen",
    );
  });
});

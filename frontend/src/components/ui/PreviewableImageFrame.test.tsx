import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PreviewableImageFrame } from "./PreviewableImageFrame";

describe("PreviewableImageFrame", () => {
  it("opens a fullscreen preview and closes from both the close button and backdrop", () => {
    render(
      <PreviewableImageFrame src="/demo.png" alt="示例图">
        <img src="/demo.png" alt="示例图" />
      </PreviewableImageFrame>,
    );

    const image = screen.getByRole("img", { name: "示例图" });

    fireEvent.click(image);
    expect(
      screen.getByRole("dialog", { name: "示例图 全屏预览" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "关闭图片预览" }));
    expect(
      screen.queryByRole("dialog", { name: "示例图 全屏预览" }),
    ).not.toBeInTheDocument();

    fireEvent.click(image);
    // backdrop button (click-to-close) is the sibling of the close button
    const backdropBtn = screen.getByRole("button", { name: "关闭全屏预览" });
    fireEvent.click(backdropBtn);

    expect(
      screen.queryByRole("dialog", { name: "示例图 全屏预览" }),
    ).not.toBeInTheDocument();
  }, 10_000);

  it("keeps the hover icon visual-only and ignores nested action buttons", () => {
    const nestedAction = vi.fn();

    render(
      <PreviewableImageFrame src="/demo.png" alt="示例图">
        <div>
          <img src="/demo.png" alt="示例图" />
          <button type="button" onClick={nestedAction}>
            change
          </button>
        </div>
      </PreviewableImageFrame>,
    );

    expect(
      screen.queryByRole("button", { name: "示例图 全屏预览" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "change" }));

    expect(nestedAction).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByRole("dialog", { name: "示例图 全屏预览" }),
    ).not.toBeInTheDocument();
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ImageLightbox } from "./ImageLightbox";

describe("ImageLightbox", () => {
  it("zooms the image with the mouse wheel", () => {
    render(<ImageLightbox src="/demo.png" alt="示例图" onClose={() => {}} />);

    const dialog = screen.getByRole("dialog", { name: "示例图 全屏预览" });
    const image = screen.getByRole("img", { name: "示例图" });

    fireEvent.wheel(dialog, { deltaY: -100 });
    expect(image).toHaveStyle({
      transform: "translate3d(0px, 0px, 0) scale(1.12)",
    });

    fireEvent.wheel(dialog, { deltaY: 100 });
    expect(image).toHaveStyle({
      transform: "translate3d(0px, 0px, 0) scale(1)",
    });
  });

  it("drags the image while the left mouse button is held", () => {
    render(<ImageLightbox src="/demo.png" alt="示例图" onClose={() => {}} />);

    const dialog = screen.getByRole("dialog", { name: "示例图 全屏预览" });
    const image = screen.getByRole("img", { name: "示例图" });

    fireEvent.pointerDown(dialog, {
      button: 0,
      clientX: 10,
      clientY: 20,
      pointerId: 1,
    });
    fireEvent.pointerMove(dialog, {
      clientX: 35,
      clientY: 15,
      pointerId: 1,
    });
    fireEvent.pointerUp(dialog, {
      clientX: 35,
      clientY: 15,
      pointerId: 1,
    });

    expect(image).toHaveStyle({
      transform: "translate3d(25px, -5px, 0) scale(1)",
    });
  });

  it("keeps backdrop click-to-close behavior", () => {
    const onClose = vi.fn();
    render(<ImageLightbox src="/demo.png" alt="示例图" onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "关闭全屏预览" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

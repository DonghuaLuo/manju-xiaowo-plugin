import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ResolutionPicker } from "./ResolutionPicker";

describe("ResolutionPicker", () => {
  it("select mode renders options + default and maps empty to null", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <ResolutionPicker
        mode="select"
        options={["720p", "1080p"]}
        value={null}
        onChange={onChange}
        placeholder="默认（不传）"
      />
    );
    const select = screen.getByRole("combobox");
    expect(select).toBeInTheDocument();
    expect(screen.getByText("默认（不传）")).toBeInTheDocument();
    fireEvent.click(select);
    fireEvent.click(screen.getByRole("option", { name: "720p" }));
    expect(onChange).toHaveBeenCalledWith("720p");
    rerender(
      <ResolutionPicker
        mode="select"
        options={["720p", "1080p"]}
        value="720p"
        onChange={onChange}
        placeholder="默认（不传）"
      />
    );
    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "默认（不传）" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("select mode renders its dropdown above modal settings overlays", () => {
    render(
      <div className="fixed inset-0 z-50">
        <ResolutionPicker
          mode="select"
          options={["720p", "1080p"]}
          value={null}
          onChange={() => {}}
          placeholder="默认（不传）"
          aria-label="分辨率"
        />
      </div>,
    );

    fireEvent.click(screen.getByRole("combobox", { name: "分辨率" }));

    expect(screen.getByRole("listbox", { name: "分辨率" }).parentElement).toHaveClass("z-50");
    expect(screen.getByRole("option", { name: "720p" })).toBeInTheDocument();
  });

  it("empty options not rendered", () => {
    const { container } = render(
      <ResolutionPicker
        mode="select"
        options={[]}
        value={null}
        onChange={() => {}}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it("combobox mode allows custom input", () => {
    const onChange = vi.fn();
    render(
      <ResolutionPicker
        mode="combobox"
        options={["720p", "1080p", "4K"]}
        value={null}
        onChange={onChange}
        placeholder="默认（不传）"
      />
    );
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "1024x1024" } });
    expect(onChange).toHaveBeenCalledWith("1024x1024");
    fireEvent.change(input, { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("combobox mode closes after choosing a listed option", async () => {
    const onChange = vi.fn();
    render(
      <ResolutionPicker
        mode="combobox"
        options={["720p", "1080p", "4K"]}
        value={null}
        onChange={onChange}
        placeholder="默认（不传）"
        aria-label="分辨率"
      />
    );

    const input = screen.getByRole("combobox", { name: "分辨率" });
    fireEvent.focus(input);
    fireEvent.click(screen.getByRole("option", { name: "720p" }));

    expect(onChange).toHaveBeenCalledWith("720p");
    await waitFor(() => {
      expect(screen.queryByRole("listbox", { name: "分辨率" })).not.toBeInTheDocument();
    });
  });

  it("combobox mode renders its dropdown above modal overlays", () => {
    render(
      <div className="fixed inset-0 z-50">
        <ResolutionPicker
          mode="combobox"
          options={["512px", "1K", "2K"]}
          value={null}
          onChange={() => {}}
          placeholder="默认（不传）"
          aria-label="图片分辨率"
        />
      </div>,
    );

    fireEvent.focus(screen.getByRole("combobox", { name: "图片分辨率" }));

    expect(screen.getByRole("listbox", { name: "图片分辨率" }).parentElement).toHaveClass("z-50");
    expect(screen.getByRole("option", { name: "1K" })).toBeInTheDocument();
  });

  it("combobox mode opens the full option list from the dropdown button after a selection", async () => {
    render(
      <ResolutionPicker
        mode="combobox"
        options={["512px", "1K", "2K"]}
        value={null}
        onChange={() => {}}
        placeholder="默认（不传）"
        aria-label="图片分辨率"
      />,
    );

    fireEvent.focus(screen.getByRole("combobox", { name: "图片分辨率" }));
    fireEvent.click(screen.getByRole("option", { name: "1K" }));
    await waitFor(() => {
      expect(screen.queryByRole("listbox", { name: "图片分辨率" })).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "图片分辨率" }));

    expect(screen.getByRole("option", { name: "默认（不传）" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "512px" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "1K" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "2K" })).toBeInTheDocument();
  });
});

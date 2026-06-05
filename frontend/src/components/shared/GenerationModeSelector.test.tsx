import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { GenerationModeSelector } from "./GenerationModeSelector";

function setup(overrides: Partial<React.ComponentProps<typeof GenerationModeSelector>> = {}) {
  const onChange = vi.fn();
  const utils = render(
    <GenerationModeSelector value="storyboard" onChange={onChange} {...overrides} />,
  );
  return { ...utils, onChange };
}

describe("GenerationModeSelector", () => {
  it("renders three mode options by default", () => {
    setup();
    expect(screen.getByRole("radio", { name: /Image-to-Video|图生视频/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Grid Fast Storyboards|宫格分镜/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Reference Video Preview|参考视频/ })).toBeInTheDocument();
  });

  it("marks the current value as checked", () => {
    setup({ value: "reference_video" });
    const refRadio = screen.getByRole("radio", { name: /Reference Video Preview|参考视频/ }) as HTMLInputElement;
    expect(refRadio.checked).toBe(true);
  });

  it("emits onChange with canonical value when clicked", () => {
    const { onChange } = setup();
    fireEvent.click(screen.getByRole("radio", { name: /Grid Fast Storyboards|宫格分镜/ }));
    expect(onChange).toHaveBeenCalledWith("grid");
  });

  it("shows the description text for the selected mode", () => {
    setup({ value: "reference_video" });
    expect(
      screen.getByText(/Skip storyboards|跳过分镜/),
    ).toBeInTheDocument();
  });

  it("disables modes passed in disabledModes", () => {
    setup({ disabledModes: ["reference_video"] });
    const ref = screen.getByRole("radio", { name: /Reference Video Preview|参考视频/ }) as HTMLInputElement;
    expect(ref.disabled).toBe(true);
  });

  it("locks every mode in read-only mode", () => {
    const { onChange } = setup({ readOnly: true });
    const grid = screen.getByRole("radio", { name: /Grid Fast Storyboards|宫格分镜/ }) as HTMLInputElement;
    const storyboard = screen.getByRole("radio", { name: /Image-to-Video|图生视频/ }) as HTMLInputElement;

    expect(storyboard.disabled).toBe(true);
    expect(grid.disabled).toBe(true);
    fireEvent.click(grid);
    expect(onChange).not.toHaveBeenCalled();
  });
});

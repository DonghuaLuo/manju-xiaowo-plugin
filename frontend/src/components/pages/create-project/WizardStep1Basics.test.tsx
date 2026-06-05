import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import "@/i18n"; // ensure i18n resources loaded
import { WizardStep1Basics } from "./WizardStep1Basics";
import type { ScriptSplittingTemplateInfo } from "@/api";

const baseValue = {
  title: "",
  contentMode: "narration" as const,
  aspectRatio: "9:16" as const,
  generationMode: "storyboard" as const,
};

const scriptSplittingTemplates: ScriptSplittingTemplateInfo[] = [
  {
    id: "narration_storyboard",
    content_mode: "narration",
    name: "图生视频方案",
    description: "先生成分镜图，再生成视频。",
    supported_generation_modes: ["storyboard"],
    recommended_generation_modes: ["storyboard"],
  },
  {
    id: "narration_grid",
    content_mode: "narration",
    name: "宫格方案",
    description: "快速批量生成宫格分镜。",
    supported_generation_modes: ["grid", "storyboard"],
    recommended_generation_modes: ["grid", "storyboard"],
    default_generation_mode: "grid",
  },
  {
    id: "drama_legacy_scene_default",
    content_mode: "drama",
    name: "通用拆分方案",
    description: "把剧情拆成清晰可生成的视觉场景。",
    supported_generation_modes: ["storyboard", "reference_video", "grid"],
    recommended_generation_modes: ["storyboard", "reference_video", "grid"],
    default_generation_mode: "storyboard",
  },
  {
    id: "drama_reference",
    content_mode: "drama",
    name: "剧情参考视频方案",
    description: "剧情模式下优先使用参考视频。",
    supported_generation_modes: ["reference_video", "storyboard"],
    recommended_generation_modes: ["reference_video", "storyboard"],
    default_generation_mode: "reference_video",
  },
];

describe("WizardStep1Basics", () => {
  it("disables Next button when title is empty", () => {
    render(
      <WizardStep1Basics
        value={baseValue}
        onChange={() => {}}
        onNext={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /下一步/ })).toBeDisabled();
  });

  it("enables Next button when title has content", () => {
    render(
      <WizardStep1Basics
        value={{ ...baseValue, title: "demo" }}
        onChange={() => {}}
        onNext={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: /下一步/ })).toBeEnabled();
  });

  it("calls onNext when Next is clicked with valid title", () => {
    const onNext = vi.fn();
    render(
      <WizardStep1Basics
        value={{ ...baseValue, title: "demo" }}
        onChange={() => {}}
        onNext={onNext}
        onCancel={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    expect(onNext).toHaveBeenCalledOnce();
  });

  it("emits onChange when content mode changes", () => {
    const onChange = vi.fn();
    render(
      <WizardStep1Basics
        value={baseValue}
        onChange={onChange}
        onNext={() => {}}
        onCancel={() => {}}
        scriptSplittingTemplates={scriptSplittingTemplates}
      />,
    );
    // click drama option (剧情模式)
    fireEvent.click(screen.getByText(/剧情模式|Drama Mode/));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        contentMode: "drama",
        generationMode: "storyboard",
        scriptSplittingTemplateId: "drama_legacy_scene_default",
      }),
    );
  });

  it("selecting a script splitting template selects its first recommended generation mode", () => {
    const onChange = vi.fn();
    render(
      <WizardStep1Basics
        value={{
          ...baseValue,
          title: "demo",
          scriptSplittingTemplateId: "narration_storyboard",
        }}
        onChange={onChange}
        onNext={() => {}}
        onCancel={() => {}}
        scriptSplittingTemplates={scriptSplittingTemplates}
      />,
    );

    fireEvent.click(screen.getByRole("combobox", { name: /选择拆分方案/ }));
    fireEvent.click(screen.getByRole("option", { name: /宫格方案/ }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        generationMode: "grid",
        scriptSplittingTemplateId: "narration_grid",
      }),
    );
  });

  it("emits onChange when aspect ratio changes", () => {
    const onChange = vi.fn();
    render(
      <WizardStep1Basics
        value={baseValue}
        onChange={onChange}
        onNext={() => {}}
        onCancel={() => {}}
      />,
    );
    // click 横屏 16:9
    fireEvent.click(screen.getByText(/横屏/));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ aspectRatio: "16:9" }),
    );
  });

  it("emits onChange when generation mode changes", () => {
    const onChange = vi.fn();
    render(
      <WizardStep1Basics
        value={baseValue}
        onChange={onChange}
        onNext={() => {}}
        onCancel={() => {}}
      />,
    );
    // click 宫格分镜 / Grid Fast Storyboards
    fireEvent.click(screen.getByRole("radio", { name: /Grid Fast Storyboards|宫格分镜/ }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ generationMode: "grid" }),
    );
  });

  it("disables generation modes unsupported by the selected script splitting template", () => {
    const onChange = vi.fn();
    render(
      <WizardStep1Basics
        value={{
          ...baseValue,
          title: "demo",
          scriptSplittingTemplateId: "narration_storyboard",
        }}
        onChange={onChange}
        onNext={() => {}}
        onCancel={() => {}}
        scriptSplittingTemplates={scriptSplittingTemplates}
      />,
    );

    const referenceVideoRadio = screen.getByRole("radio", { name: /Reference Video Preview|参考视频/ });
    const gridRadio = screen.getByRole("radio", { name: /Grid Fast Storyboards|宫格分镜/ });
    expect(referenceVideoRadio).toBeDisabled();
    expect(gridRadio).toBeDisabled();

    fireEvent.click(referenceVideoRadio);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("emits onChange when title input changes", () => {
    const onChange = vi.fn();
    render(
      <WizardStep1Basics
        value={baseValue}
        onChange={onChange}
        onNext={() => {}}
        onCancel={() => {}}
      />,
    );
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "hello" },
    });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ title: "hello" }),
    );
  });

  it("calls onCancel when Cancel is clicked", () => {
    const onCancel = vi.fn();
    render(
      <WizardStep1Basics
        value={baseValue}
        onChange={() => {}}
        onNext={() => {}}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /取消|Cancel/i }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("marks title input as aria-required", () => {
    render(
      <WizardStep1Basics
        value={baseValue}
        onChange={() => {}}
        onNext={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByRole("textbox")).toHaveAttribute("aria-required", "true");
  });

  it("renders project_id_auto_gen_hint below the title input", () => {
    render(
      <WizardStep1Basics
        value={baseValue}
        onChange={() => {}}
        onNext={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(
      screen.getByText(/系统会自动生成内部项目标识/),
    ).toBeInTheDocument();
  });

  it("switches generation mode to reference_video", () => {
    const onChange = vi.fn();
    render(
      <WizardStep1Basics
        value={{ title: "t", contentMode: "narration", aspectRatio: "9:16", generationMode: "storyboard" }}
        onChange={onChange}
        onNext={() => {}}
        onCancel={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("radio", { name: /Reference Video Preview|参考视频/ }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ generationMode: "reference_video" }));
  });
});

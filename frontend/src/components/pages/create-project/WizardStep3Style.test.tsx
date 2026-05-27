import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import "@/i18n";
import { WizardStep3Style } from "./WizardStep3Style";

const baseValue = {
  mode: "template" as const,
  templateId: "live_premium_drama",
  activeCategory: "live" as const,
  uploadedFile: null,
  uploadedPreview: null,
  stylePrompt: "画风：真人电视剧风格，精品短剧画风，大师级构图",
};

const templatePrompts = {
  live_premium_drama: "画风：真人电视剧风格，精品短剧画风，大师级构图",
  live_zhang_yimou: "画风：参考张艺谋电影风格，极致用色，强烈构图，仪式感叙事",
  anim_ghibli: "画风：参考吉卜力动画电影风格，宫崎骏动画风格",
};

const templates = [
  { id: "live_premium_drama", category: "live" as const, thumbnailFile: "live_premium_drama.png" },
  { id: "live_zhang_yimou", category: "live" as const, thumbnailFile: "live_zhang_yimou.png" },
  { id: "anim_ghibli", category: "anim" as const, thumbnailFile: "anim_ghibli.png" },
];

const noop = () => {};
const commonProps = { onBack: noop, onCreate: noop, onCancel: noop, creating: false, templates, templatePrompts };

describe("WizardStep3Style", () => {
  it("renders live templates in default live tab with default one selected", () => {
    render(<WizardStep3Style value={baseValue} onChange={noop} {...commonProps} />);
    // The default template gets a "default" badge
    expect(screen.getAllByText(/（默认）|\(default\)/i).length).toBeGreaterThanOrEqual(1);
  });

  it("emits onChange with new templateId when a template card is clicked", () => {
    const onChange = vi.fn();
    render(<WizardStep3Style value={baseValue} onChange={onChange} {...commonProps} />);
    // Click a different live template by its i18n name (e.g. 张艺谋风格)
    const card = screen.getByRole("button", { name: /张艺谋/ });
    fireEvent.click(card);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      mode: "template",
      templateId: "live_zhang_yimou",
      stylePrompt: expect.stringContaining("张艺谋"),
    }));
  });

  it("shows and edits the final style prompt under preset cards", () => {
    const onChange = vi.fn();
    render(<WizardStep3Style value={baseValue} onChange={onChange} {...commonProps} />);
    const promptBox = screen.getByLabelText(/风格提示词|Style prompt/);
    expect(promptBox).toHaveValue(baseValue.stylePrompt);
    fireEvent.change(promptBox, { target: { value: "项目专用风格提示词" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      stylePrompt: "项目专用风格提示词",
    }));
  });

  it("switches to custom mode while preserving templateId (切换无损失)", () => {
    const onChange = vi.fn();
    render(<WizardStep3Style value={baseValue} onChange={onChange} {...commonProps} />);
    fireEvent.click(screen.getByRole("button", { name: /自定义|Custom/ }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      mode: "custom",
      templateId: baseValue.templateId,   // 原 template 保留，回切时恢复
      stylePrompt: baseValue.stylePrompt,
    }));
  });

  it("keeps an edited final prompt when switching tabs", () => {
    const onChange = vi.fn();
    const editedValue = { ...baseValue, stylePrompt: "项目最终采用的提示词" };
    const { rerender } = render(<WizardStep3Style value={editedValue} onChange={onChange} {...commonProps} />);

    fireEvent.click(screen.getByRole("button", { name: /自定义|Custom/ }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      mode: "custom",
      stylePrompt: "项目最终采用的提示词",
    }));

    const customValue = { ...editedValue, mode: "custom" as const };
    rerender(<WizardStep3Style value={customValue} onChange={onChange} {...commonProps} />);
    fireEvent.click(screen.getByRole("button", { name: /真人剧|Live/ }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      mode: "template",
      stylePrompt: "项目最终采用的提示词",
    }));
  });

  it("switches category tab while preserving uploaded file/preview (切换无损失)", () => {
    const onChange = vi.fn();
    const uploaded = new File([""], "x.png", { type: "image/png" });
    const valueWithUpload = {
      ...baseValue,
      mode: "custom" as const,
      uploadedFile: uploaded,
      uploadedPreview: "blob:test",
    };
    render(<WizardStep3Style value={valueWithUpload} onChange={onChange} {...commonProps} />);
    fireEvent.click(screen.getByRole("button", { name: /漫剧|Animation/ }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      mode: "template",
      activeCategory: "anim",
      uploadedFile: uploaded,
      uploadedPreview: "blob:test",
    }));
  });

  it("switches to anim tab while preserving the live templateId (cross-tab selection is not auto-overridden)", () => {
    const onChange = vi.fn();
    render(<WizardStep3Style value={baseValue} onChange={onChange} {...commonProps} />);
    fireEvent.click(screen.getByRole("button", { name: /漫剧|Animation/ }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      mode: "template",
      activeCategory: "anim",
      templateId: "live_premium_drama",   // preserved from live; anim tab shows no selection
    }));
  });

  it("keeps Create button enabled when custom mode has no uploaded file (style 为可选)", () => {
    const value = { ...baseValue, mode: "custom" as const, templateId: null };
    render(<WizardStep3Style value={value} onChange={noop} {...commonProps} />);
    const createBtn = screen.getByRole("button", { name: /创建项目|Create/i });
    expect(createBtn).not.toBeDisabled();
  });

  it("enables Create button when custom mode has uploaded file", () => {
    const value = {
      ...baseValue,
      mode: "custom" as const,
      templateId: null,
      uploadedFile: new File([""], "x.png", { type: "image/png" }),
      uploadedPreview: "blob:test",
    };
    render(<WizardStep3Style value={value} onChange={noop} {...commonProps} />);
    const createBtn = screen.getByRole("button", { name: /创建项目|Create/i });
    expect(createBtn).toBeEnabled();
  });

  it("disables Create button while creating=true", () => {
    render(<WizardStep3Style value={baseValue} onChange={noop} {...{ ...commonProps, creating: true }} />);
    // While creating, button reads "创建中…" / "Creating…"
    const createBtn = screen.getByRole("button", { name: /创建中|Creating|创建项目|Create/i });
    expect(createBtn).toBeDisabled();
  });

  it("calls onBack when Back is clicked", () => {
    const onBack = vi.fn();
    render(<WizardStep3Style value={baseValue} onChange={noop} {...commonProps} onBack={onBack} />);
    fireEvent.click(screen.getByRole("button", { name: /上一步|Back/ }));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it("calls onCancel when Cancel is clicked", () => {
    const onCancel = vi.fn();
    render(<WizardStep3Style value={baseValue} onChange={noop} {...commonProps} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: /取消|Cancel/ }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("preserves null templateId when switching from custom to live tab (no auto-selection)", () => {
    const onChange = vi.fn();
    const customValue = { ...baseValue, mode: "custom" as const, templateId: null };
    render(<WizardStep3Style value={customValue} onChange={onChange} {...commonProps} />);
    fireEvent.click(screen.getByRole("button", { name: /真人剧|Live/ }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      mode: "template",
      activeCategory: "live",
      templateId: null,   // unchanged; user must explicitly click a card
    }));
  });

  it("preserves live templateId when re-clicking live tab", () => {
    const onChange = vi.fn();
    const value = { ...baseValue, templateId: "live_zhang_yimou" };
    render(<WizardStep3Style value={value} onChange={onChange} {...commonProps} />);
    fireEvent.click(screen.getByRole("button", { name: /真人剧|Live/ }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      activeCategory: "live",
      templateId: "live_zhang_yimou",
    }));
  });

  it("shows no selected card in anim tab when current templateId belongs to live (bug repro)", () => {
    // Simulate the state AFTER the (fixed) tab switch: live_premium_drama
    // stays as templateId but activeCategory moves to anim.
    const crossTabValue = { ...baseValue, activeCategory: "anim" as const };
    render(<WizardStep3Style value={crossTabValue} onChange={noop} {...commonProps} />);
    // No anim template card should be rendered as pressed/selected.
    const pressedCards = screen.queryAllByRole("button", { pressed: true });
    // The tab buttons themselves don't use aria-pressed, so this queries only template cards.
    expect(pressedCards).toHaveLength(0);
  });

  it("preserves anim templateId when re-clicking anim tab", () => {
    const onChange = vi.fn();
    const animValue = { ...baseValue, activeCategory: "anim" as const, templateId: "anim_ghibli" };
    render(<WizardStep3Style value={animValue} onChange={onChange} {...commonProps} />);
    fireEvent.click(screen.getByRole("button", { name: /漫剧|Animation/ }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      activeCategory: "anim",
      templateId: "anim_ghibli",
    }));
  });
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PluginSDK } from "xiaowo-sdk";
import "@/i18n";
import { API, type ScriptSplittingTemplateInfo } from "@/api";
import { ScriptSplittingTemplatesSection } from "./ScriptSplittingTemplatesSection";

const universalTemplate: ScriptSplittingTemplateInfo = {
  id: "narration_legacy_reading_default",
  source: "builtin",
  content_mode: "narration",
  name: "通用拆分方案",
  description: "按旁白节奏拆成可生成片段。",
  supported_generation_modes: ["storyboard", "reference_video", "grid"],
  recommended_generation_modes: ["storyboard", "reference_video", "grid"],
  default_generation_mode: "storyboard",
  output_fields: ["segment_id", "novel_text", "duration_seconds"],
  split_rules: ["按朗读速度每秒约 5-6 字估算字数上限。"],
  forbidden_patterns: ["不要拆断完整语义。"],
};

const customTemplate: ScriptSplittingTemplateInfo = {
  id: "user_narration_hook",
  source: "user_generated",
  base_template_id: "narration_legacy_reading_default",
  derived_from_template_id: "narration_legacy_reading_default",
  creation_mode: "improve",
  content_mode: "narration",
  name: "自定义说书钩子",
  description: "用户保存过的说书钩子方案。",
  supported_generation_modes: ["storyboard"],
  recommended_generation_modes: ["storyboard"],
  default_generation_mode: "storyboard",
  output_fields: ["segment_id", "novel_text"],
  split_rules: ["每段必须有明确钩子。"],
  forbidden_patterns: ["不要机械按字数拆分。"],
  user_overlay: {
    extra_split_rules: ["每段必须有明确钩子。"],
    extra_forbidden_patterns: ["不要机械按字数拆分。"],
  },
};

const validAiTemplateText = [
  "# 拆分方案",
  "标题：夜读强钩子 · 改进版",
  "描述：适合旁白短视频的强钩子拆分。",
  "内容模式：旁白模式",
  "来源模板：user_narration_hook",
  "支持视频生成方式：图生视频",
  "",
  "## 拆分规则",
  "- 前三段必须连续制造追问。",
  "- 每段只承载一个清晰信息点。",
  "",
  "## 禁止写法",
  "- 不要把心理活动硬改成不存在的动作。",
].join("\n");

function mockTemplates(templates: ScriptSplittingTemplateInfo[] = [customTemplate]) {
  vi.spyOn(API, "getScriptSplittingTemplates").mockResolvedValue({
    success: true,
    templates,
  });
}

describe("ScriptSplittingTemplatesSection", () => {
  it("copies different external AI instructions for improvement and new-style modes", async () => {
    mockTemplates([universalTemplate, customTemplate]);

    render(<ScriptSplittingTemplatesSection />);

    fireEvent.click(await screen.findByRole("combobox", { name: /拆分方案模板|Script splitting template/i }));
    fireEvent.click(screen.getByRole("option", { name: /自定义说书钩子/ }));

    const copyButton = screen.getByRole("button", { name: /复制一段给外部 AI 的说明/ });
    fireEvent.click(copyButton);

    await waitFor(() => expect(PluginSDK.clipboard.writeText).toHaveBeenCalledTimes(1));
    const improvePrompt = vi.mocked(PluginSDK.clipboard.writeText).mock.calls.at(-1)?.[0] as string;
    expect(improvePrompt).toContain("创建方式：基于选中模板改进");
    expect(improvePrompt).toContain("来源模板：user_narration_hook");
    expect(improvePrompt).toContain("继承它的系统字段和可落地规则骨架");
    expect(improvePrompt).toContain("每段必须有明确钩子。");

    fireEvent.click(screen.getByRole("radio", { name: /创建全新风格模板/ }));
    fireEvent.click(copyButton);

    await waitFor(() => expect(PluginSDK.clipboard.writeText).toHaveBeenCalledTimes(2));
    const newStylePrompt = vi.mocked(PluginSDK.clipboard.writeText).mock.calls.at(-1)?.[0] as string;
    expect(newStylePrompt).toContain("创建方式：创建全新风格模板");
    expect(newStylePrompt).toContain("来源模板：narration_legacy_reading_default");
    expect(newStylePrompt).toContain("不要继承某个预设模板的题材风格");
    expect(newStylePrompt).not.toContain("来源模板：user_narration_hook");
  });

  it("uses the selected custom template as the copy source when saving an improved template", async () => {
    mockTemplates();
    const saveSpy = vi.spyOn(API, "saveScriptSplittingTemplate").mockResolvedValue({
      success: true,
      template: {
        ...customTemplate,
        id: "user_narration_hook_v2",
        name: "夜读强钩子 · 改进版",
      },
    });

    render(<ScriptSplittingTemplatesSection />);

    const pasteBox = await screen.findByPlaceholderText(/把外部 AI 生成的最终文案粘贴到这里/);
    fireEvent.change(pasteBox, { target: { value: validAiTemplateText } });

    const saveButton = screen.getByRole("button", { name: /保存为拆分方案/ });
    await waitFor(() => expect(saveButton).toBeEnabled());
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(saveSpy).toHaveBeenCalledWith(expect.objectContaining({
        base_template_id: "user_narration_hook",
        derived_from_template_id: "user_narration_hook",
        creation_mode: "improve",
      }));
    });
  });

  it("requires pasted AI text to explicitly declare content and generation modes", async () => {
    mockTemplates();
    const saveSpy = vi.spyOn(API, "saveScriptSplittingTemplate").mockResolvedValue({
      success: true,
      template: customTemplate,
    });

    render(<ScriptSplittingTemplatesSection />);

    const pasteBox = await screen.findByPlaceholderText(/把外部 AI 生成的最终文案粘贴到这里/);
    fireEvent.change(pasteBox, {
      target: {
        value: [
          "# 拆分方案",
          "标题：缺字段方案",
          "描述：缺少内容模式和支持视频生成方式。",
          "",
          "## 拆分规则",
          "- 每段必须有明确钩子。",
        ].join("\n"),
      },
    });

    expect(await screen.findByText(/没有识别到“内容模式”/)).toBeInTheDocument();
    expect(screen.getByText(/没有识别到“支持视频生成方式”/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /保存为拆分方案/ })).toBeDisabled();
    expect(saveSpy).not.toHaveBeenCalled();
  });
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Router, Route } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import "@/i18n";
import { API } from "@/api";
import * as providerModels from "@/utils/provider-models";
import { useAppStore } from "@/stores/app-store";
import { ProjectSettingsPage } from "@/components/pages/ProjectSettingsPage";

const FAKE_CONFIG = {
  options: { video_backends: [], image_backends: [], text_backends: [], provider_names: {} },
  settings: {
    default_video_backend: "",
    default_image_backend: "",
    text_backend_script: "",
    text_backend_overview: "",
    text_backend_style: "",
  },
};

const FAKE_CONFIG_WITH_DEFAULTS = {
  options: {
    video_backends: ["gemini/veo-3"],
    image_backends: ["gemini/nano-banana"],
    text_backends: ["gemini/g25"],
    provider_names: { gemini: "Gemini" },
  },
  settings: {
    default_video_backend: "gemini/veo-3",
    default_image_backend: "gemini/nano-banana",
    default_image_backend_t2i: "gemini/nano-banana",
    default_image_backend_i2i: "gemini/nano-banana",
    text_backend_script: "gemini/g25",
    text_backend_overview: "gemini/g25",
    text_backend_style: "gemini/g25",
  },
};

function renderAt(path: string) {
  const location = memoryLocation({ path, record: true });
  return render(
    <Router hook={location.hook}>
      <Route path="/app/projects/:projectName/settings" component={ProjectSettingsPage} />
    </Router>,
  );
}

describe("ProjectSettingsPage – style picker", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.restoreAllMocks();
    vi.spyOn(API, "getSystemConfig").mockResolvedValue(FAKE_CONFIG as unknown as Awaited<ReturnType<typeof API.getSystemConfig>>);
    vi.spyOn(API, "getStyleTemplates").mockResolvedValue({
      success: true,
      templates: [
        {
          id: "live_premium_drama",
          category: "live",
          prompt: "画风：真人电视剧风格，精品短剧画风，大师级构图",
          thumbnail_file: "live_premium_drama.png",
        },
        {
          id: "live_zhang_yimou",
          category: "live",
          prompt: "画风：参考张艺谋电影风格，极致用色，强烈构图，仪式感叙事",
          thumbnail_file: "live_zhang_yimou.png",
        },
      ],
    });
    vi.spyOn(API, "getScriptSplittingTemplates").mockResolvedValue({
      success: true,
      templates: [],
    });
    vi.spyOn(API, "getVideoCapabilities").mockRejectedValue(new Error("no capabilities"));
    vi.spyOn(providerModels, "getProviderModels").mockResolvedValue([]);
    vi.spyOn(providerModels, "getCustomProviderModels").mockResolvedValue([]);
  });

  it("loads a project with style_template_id and selects the matching template card by default", async () => {
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        style_template_id: "live_zhang_yimou",
        style: "画风：参考张艺谋电影风格",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);

    renderAt("/app/projects/demo/settings");

    await waitFor(() => {
      // Selected card has aria-pressed=true
      const selected = screen.getByRole("button", { name: /张艺谋/, pressed: true });
      expect(selected).toBeInTheDocument();
    });
  });

  it("loads a project with style_image and switches to custom tab with existing preview", async () => {
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        style_image: "style_reference.png",
        style_description: "old desc",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);

    renderAt("/app/projects/demo/settings");

    await waitFor(() => {
      const img = screen.getByAltText(/上传风格参考图|Upload style reference/) as HTMLImageElement;
      expect(img.src).toContain("style_reference.png");
    });
  });

  it("favorites a complete custom style and refreshes templates", async () => {
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        style_image: "style_reference.png",
        style_description: "manual noir lighting",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);
    const updateSpy = vi.spyOn(API, "updateProject").mockResolvedValue({
      success: true,
      project: { title: "Demo" } as unknown as Awaited<ReturnType<typeof API.updateProject>>["project"],
    });
    const favoriteSpy = vi.spyOn(API, "createFavoriteStyleTemplate").mockResolvedValue({
      success: true,
      template: {
        id: "favorite_abc123",
        category: "favorite",
        prompt: "manual noir lighting",
        thumbnail_file: "favorite_abc123.png",
        thumbnail_url: "/api/v1/style-templates/favorites/favorite_abc123.png",
        name: "收藏风格 1",
        tagline: "自定义上传",
      },
    });

    renderAt("/app/projects/demo/settings");

    const favoriteBtn = await screen.findByRole("button", { name: /收藏风格|Favorite style/ });
    expect(favoriteBtn).not.toBeDisabled();
    fireEvent.click(favoriteBtn);

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith("demo", {
        style_template_id: null,
        style_description: "manual noir lighting",
      });
      expect(favoriteSpy).toHaveBeenCalledWith({
        stylePrompt: "manual noir lighting",
        projectName: "demo",
        file: null,
      });
    });
  });

  it("can favorite an existing custom style whose prompt is stored in legacy style", async () => {
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        style_image: "style_reference.png",
        style: "legacy noir lighting",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);
    const updateSpy = vi.spyOn(API, "updateProject").mockResolvedValue({
      success: true,
      project: { title: "Demo" } as unknown as Awaited<ReturnType<typeof API.updateProject>>["project"],
    });
    const favoriteSpy = vi.spyOn(API, "createFavoriteStyleTemplate").mockResolvedValue({
      success: true,
      template: {
        id: "favorite_legacy",
        category: "favorite",
        prompt: "legacy noir lighting",
        thumbnail_file: "favorite_legacy.png",
        name: "收藏风格 1",
        tagline: "自定义上传",
      },
    });

    renderAt("/app/projects/demo/settings");

    const favoriteBtn = await screen.findByRole("button", { name: /收藏风格|Favorite style/ });
    expect(favoriteBtn).not.toBeDisabled();
    fireEvent.click(favoriteBtn);

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith("demo", {
        style_template_id: null,
        style_description: "legacy noir lighting",
      });
      expect(favoriteSpy).toHaveBeenCalledWith({
        stylePrompt: "legacy noir lighting",
        projectName: "demo",
        file: null,
      });
    });
  });

  it("asks for confirmation before deleting a favorite style", async () => {
    vi.mocked(API.getStyleTemplates)
      .mockResolvedValueOnce({
        success: true,
        templates: [
          {
            id: "live_premium_drama",
            category: "live",
            prompt: "画风：真人电视剧风格，精品短剧画风，大师级构图",
            thumbnail_file: "live_premium_drama.png",
          },
          {
            id: "favorite_noir",
            category: "favorite",
            prompt: "manual noir lighting",
            thumbnail_file: "favorite_noir.png",
            name: "收藏风格 1",
            tagline: "自定义上传",
          },
        ],
      })
      .mockResolvedValue({
        success: true,
        templates: [
          {
            id: "live_premium_drama",
            category: "live",
            prompt: "画风：真人电视剧风格，精品短剧画风，大师级构图",
            thumbnail_file: "live_premium_drama.png",
          },
        ],
      });
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        style_template_id: "favorite_noir",
        style: "manual noir lighting",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);
    const deleteSpy = vi.spyOn(API, "deleteFavoriteStyleTemplate").mockResolvedValue({
      success: true,
    });

    renderAt("/app/projects/demo/settings");

    const deleteBtn = await screen.findByRole("button", { name: /删除收藏风格|Delete favorite style/ });
    fireEvent.click(deleteBtn);

    expect(deleteSpy).not.toHaveBeenCalled();
    expect(await screen.findByRole("dialog", { name: /删除收藏风格/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /删除风格/ }));

    await waitFor(() => {
      expect(deleteSpy).toHaveBeenCalledWith("favorite_noir");
    });
  });

  it("clearing the reference image keeps save enabled and triggers clear PATCH", async () => {
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        style_image: "style_reference.png",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);
    const updateSpy = vi.spyOn(API, "updateProject").mockResolvedValue({
      success: true,
      project: { title: "Demo" } as unknown as Awaited<ReturnType<typeof API.updateProject>>["project"],
    });

    renderAt("/app/projects/demo/settings");

    await waitFor(() => screen.getByAltText(/上传风格参考图|Upload style reference/));
    const removeBtn = screen.getByRole("button", { name: /^(remove|移除)$/i });
    fireEvent.click(removeBtn);

    // 移除自定义图后 save 应可点：保存即清除后端残留 style_image / description
    const saveBtn = screen.getByRole("button", { name: /保存风格|Save style/ });
    expect(saveBtn).not.toBeDisabled();
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith("demo", {
        style_template_id: null,
        clear_style_image: true,
      });
    });
  });

  it("clicking 清空风格 when project has a template sends clear PATCH", async () => {
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        style_template_id: "live_premium_drama",
        style: "画风：...",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);
    const updateSpy = vi.spyOn(API, "updateProject").mockResolvedValue({
      success: true,
      project: { title: "Demo" } as unknown as Awaited<ReturnType<typeof API.updateProject>>["project"],
    });

    renderAt("/app/projects/demo/settings");

    // 等到 style picker 已经 mount（能找到保存按钮）
    await screen.findByRole("button", { name: /保存风格|Save style/ });

    const clearBtn = screen.getByRole("button", { name: /清空风格|Clear style/ });
    fireEvent.click(clearBtn);

    const saveBtn = screen.getByRole("button", { name: /保存风格|Save style/ });
    expect(saveBtn).not.toBeDisabled();
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith("demo", {
        style_template_id: null,
        clear_style_image: true,
      });
    });
  });

  it("falls back to 9:16 aspect ratio highlight when project has no aspect_ratio set", async () => {
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);

    renderAt("/app/projects/demo/settings");

    const portrait = await screen.findByRole("radio", { name: /竖屏 9:16/ });
    expect(portrait).toBeChecked();
    const landscape = screen.getByRole("radio", { name: /横屏 16:9/ });
    expect(landscape).not.toBeChecked();
  });

  it("shows 'follow global default · provider · model' in model triggers when project has no model override", async () => {
    vi.spyOn(API, "getSystemConfig").mockResolvedValue(
      FAKE_CONFIG_WITH_DEFAULTS as unknown as Awaited<ReturnType<typeof API.getSystemConfig>>,
    );
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);

    renderAt("/app/projects/demo/settings");

    // 项目无 image override + 全局默认双能力 → 单下拉模式（label = 图片模型 / Image Model）
    const imageTrigger = await screen.findByRole("combobox", { name: /^(图片模型|Image Model)$/ });
    expect(imageTrigger).toHaveTextContent(/跟随全局默认|Use global default/);
    expect(imageTrigger).toHaveTextContent(/nano-banana/);
  });

  it("saves a template change via PATCH style_template_id", async () => {
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        style_template_id: "live_premium_drama",
        style: "...",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);
    const updateSpy = vi.spyOn(API, "updateProject").mockResolvedValue({
      success: true,
      project: { title: "Demo", style_template_id: "live_zhang_yimou" } as unknown as Awaited<ReturnType<typeof API.updateProject>>["project"],
    });

    renderAt("/app/projects/demo/settings");

    const card = await screen.findByRole("button", { name: /张艺谋/ });
    fireEvent.click(card);

    const saveBtn = screen.getByRole("button", { name: /保存风格|Save style/ });
    expect(saveBtn).not.toBeDisabled();
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith("demo", {
        style_template_id: "live_zhang_yimou",
        style: expect.stringContaining("张艺谋"),
      });
    });
  });

  it("locks generation_mode and applies only compatible script-splitting template changes", async () => {
    vi.mocked(API.getScriptSplittingTemplates).mockResolvedValue({
      success: true,
      templates: [
        {
          id: "drama_legacy_scene_default",
          source: "builtin",
          content_mode: "drama",
          name: "通用拆分方案",
          description: "通用剧情拆分方案",
          version: 1,
          hash: "sha256:old",
          supported_generation_modes: ["storyboard", "reference_video", "grid"],
          recommended_generation_modes: ["storyboard", "reference_video", "grid"],
          default_generation_mode: "storyboard",
          required_capabilities: [],
          preferred_capabilities: [],
          output_fields: [],
          split_rules: [],
          forbidden_patterns: [],
        },
        {
          id: "drama_web_short_hook",
          source: "builtin",
          content_mode: "drama",
          name: "短剧爽点节奏",
          description: "高密度冲突、强钩子、强反转。",
          version: 1,
          hash: "sha256:hook",
          supported_generation_modes: ["storyboard", "reference_video"],
          recommended_generation_modes: ["storyboard", "reference_video"],
          default_generation_mode: "storyboard",
          required_capabilities: [],
          preferred_capabilities: [],
          output_fields: [],
          split_rules: [],
          forbidden_patterns: [],
        },
      ],
    });
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        content_mode: "drama",
        generation_mode: "storyboard",
        script_splitting_template_id: "drama_legacy_scene_default",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);
    vi.spyOn(API, "updateProject").mockResolvedValue({
      success: true,
      project: { title: "Demo" } as unknown as Awaited<ReturnType<typeof API.updateProject>>["project"],
    });
    vi.spyOn(API, "previewScriptSplittingTemplateChange").mockResolvedValue({
      success: true,
      preview: {
        preview: true,
        next_template_id: "drama_web_short_hook",
        current_generation_mode: "storyboard",
        next_generation_mode: "storyboard",
        generation_mode_changed: false,
        affected_assets: [],
        suggested_action: "future_episodes_only",
      },
    });
    const changeSpy = vi.spyOn(API, "changeScriptSplittingTemplate").mockResolvedValue({
      success: true,
      project: {
        title: "Demo",
        generation_mode: "storyboard",
        script_splitting_template_id: "drama_web_short_hook",
      } as unknown as Awaited<ReturnType<typeof API.changeScriptSplittingTemplate>>["project"],
    });

    renderAt("/app/projects/demo/settings");

    const referenceVideoRadio = await screen.findByRole("radio", { name: /参考视频|Reference Video Preview/i });
    const storyboardRadio = screen.getByRole("radio", { name: /图生视频|Image-to-Video/i });
    expect(referenceVideoRadio).not.toBeChecked();
    expect(storyboardRadio).toBeChecked();
    expect(referenceVideoRadio).toBeDisabled();

    fireEvent.click(referenceVideoRadio);
    expect(referenceVideoRadio).not.toBeChecked();
    expect(storyboardRadio).toBeChecked();

    fireEvent.click(screen.getByRole("combobox", { name: /拆分方案模板|Script splitting template/i }));
    fireEvent.click(screen.getByRole("option", { name: /短剧爽点节奏/ }));

    await waitFor(() => {
      expect(API.previewScriptSplittingTemplateChange).toHaveBeenCalledWith("demo", "drama_web_short_hook");
    });

    const applyBtn = screen.getByRole("button", { name: /应用拆分方案|Apply script splitting/i });
    expect(applyBtn).not.toBeDisabled();
    fireEvent.click(applyBtn);

    await waitFor(() => {
      expect(changeSpy.mock.calls.at(-1)).toEqual([
        "demo",
        "drama_web_short_hook",
        false,
        "apply_keep_drafts",
      ]);
    });
    expect(API.updateProject).not.toHaveBeenCalledWith("demo", expect.objectContaining({ generation_mode: expect.anything() }));
  });
});
describe("ProjectSettingsPage – model_settings resolution", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.restoreAllMocks();
    vi.spyOn(API, "getStyleTemplates").mockResolvedValue({ success: true, templates: [] });
    vi.spyOn(API, "getScriptSplittingTemplates").mockResolvedValue({ success: true, templates: [] });
    vi.spyOn(providerModels, "getProviderModels").mockResolvedValue([]);
    vi.spyOn(providerModels, "getCustomProviderModels").mockResolvedValue([]);
  });

  it("disables unsupported Flex service tier for the selected video model", async () => {
    vi.spyOn(API, "getSystemConfig").mockResolvedValue({
      options: {
        ...FAKE_CONFIG_WITH_DEFAULTS.options,
        video_backends: ["ark/doubao-seedance-2-0"],
        provider_names: { ark: "火山方舟" },
      },
      settings: {
        ...FAKE_CONFIG_WITH_DEFAULTS.settings,
        default_video_backend: "ark/doubao-seedance-2-0",
      },
    } as unknown as Awaited<ReturnType<typeof API.getSystemConfig>>);
    vi.spyOn(API, "getVideoCapabilities").mockResolvedValue({
      provider_id: "ark",
      model: "doubao-seedance-2-0",
      supported_durations: [5],
      max_duration: 5,
      max_reference_images: 9,
      resolutions: ["720p"],
      capabilities: ["text_to_video", "image_to_video"],
      supports_service_tier: false,
      service_tiers: ["default"],
      source: "registry",
    } as unknown as Awaited<ReturnType<typeof API.getVideoCapabilities>>);
    vi.spyOn(providerModels, "getProviderModels").mockResolvedValue([
      {
        id: "ark",
        display_name: "火山方舟",
        description: "",
        status: "ready",
        media_types: ["video"],
        capabilities: [],
        configured_keys: [],
        missing_keys: [],
        models: {
          "doubao-seedance-2-0": {
            display_name: "Seedance 2.0",
            media_type: "video",
            capabilities: ["text_to_video", "image_to_video"],
            default: true,
            supported_durations: [5],
            duration_resolution_constraints: {},
            resolutions: ["720p"],
          },
        },
      },
    ] as Awaited<ReturnType<typeof providerModels.getProviderModels>>);
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        video_backend: "ark/doubao-seedance-2-0",
        shot_tier_profiles: {
          S: {
            profiles: {
              video_final: {
                service_tier: "flex",
              },
            },
          },
        },
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);
    vi.spyOn(API, "previewGenerationRoutes").mockResolvedValue({ routes: [] });
    vi.spyOn(API, "getProviderRecommendations").mockResolvedValue({
      recommendations: [],
      min_calls: 1,
    });
    vi.spyOn(API, "getQualityStats").mockResolvedValue({
      count: 0,
      average_rating: null,
      groups: {},
      ratings: [],
    });

    renderAt("/app/projects/demo/settings");

    const serviceTierTriggers = await screen.findAllByRole("combobox", { name: /服务档位|Service tier/ });
    expect(serviceTierTriggers[0]).toHaveValue("default");
    fireEvent.click(serviceTierTriggers[0]);

    const flexOption = await screen.findByRole("option", { name: /Flex/ });
    expect(flexOption).toBeDisabled();
    expect(flexOption).toHaveTextContent(/不支持此档位|does not support/i);
  });

  it("previews grid generation without validating inactive reference-video routes", async () => {
    vi.spyOn(API, "getSystemConfig").mockResolvedValue({
      ...FAKE_CONFIG_WITH_DEFAULTS,
    } as unknown as Awaited<ReturnType<typeof API.getSystemConfig>>);
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        video_backend: "gemini/veo-3",
        image_provider_t2i: "gemini/nano-banana",
        image_provider_i2i: "gemini/nano-banana",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);
    const previewSpy = vi.spyOn(API, "previewGenerationRoutes").mockResolvedValue({ routes: [] });
    vi.spyOn(API, "getProviderRecommendations").mockResolvedValue({
      recommendations: [],
      min_calls: 1,
    });
    vi.spyOn(API, "getQualityStats").mockResolvedValue({
      count: 0,
      average_rating: null,
      groups: {},
      ratings: [],
    });

    renderAt("/app/projects/demo/settings");

    await waitFor(() => expect(previewSpy).toHaveBeenCalled());
    const payload = previewSpy.mock.calls.at(-1)?.[1];
    const gridRoutes = payload?.routes.filter((route) => route.task_kind === "grid") ?? [];
    const referenceVideoRoutes = payload?.routes.filter((route) => route.task_kind === "reference_video") ?? [];

    expect(gridRoutes).toEqual([
      expect.objectContaining({ quality: "final", capability: "t2i" }),
      expect.objectContaining({ quality: "final", capability: "i2i" }),
    ]);
    expect(referenceVideoRoutes).toEqual([]);
  });

  it("previews reference-video routes only for reference-video projects", async () => {
    vi.spyOn(API, "getSystemConfig").mockResolvedValue({
      ...FAKE_CONFIG_WITH_DEFAULTS,
    } as unknown as Awaited<ReturnType<typeof API.getSystemConfig>>);
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        generation_mode: "reference_video",
        video_backend: "gemini/veo-3",
        image_provider_t2i: "gemini/nano-banana",
        image_provider_i2i: "gemini/nano-banana",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);
    const previewSpy = vi.spyOn(API, "previewGenerationRoutes").mockResolvedValue({ routes: [] });
    vi.spyOn(API, "getProviderRecommendations").mockResolvedValue({
      recommendations: [],
      min_calls: 1,
    });
    vi.spyOn(API, "getQualityStats").mockResolvedValue({
      count: 0,
      average_rating: null,
      groups: {},
      ratings: [],
    });

    renderAt("/app/projects/demo/settings");

    await waitFor(() => expect(previewSpy).toHaveBeenCalled());
    const payload = previewSpy.mock.calls.at(-1)?.[1];
    const referenceVideoRoutes = payload?.routes.filter((route) => route.task_kind === "reference_video") ?? [];

    expect(referenceVideoRoutes).toEqual([
      expect.objectContaining({ quality: "draft" }),
      expect.objectContaining({ quality: "final" }),
    ]);
  });

  it("hides reference-video quality profiles for non-reference-video projects", async () => {
    vi.spyOn(API, "getSystemConfig").mockResolvedValue({
      ...FAKE_CONFIG_WITH_DEFAULTS,
    } as unknown as Awaited<ReturnType<typeof API.getSystemConfig>>);
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        generation_mode: "storyboard",
        video_backend: "gemini/veo-3",
        image_provider_t2i: "gemini/nano-banana",
        image_provider_i2i: "gemini/nano-banana",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);
    vi.spyOn(API, "previewGenerationRoutes").mockResolvedValue({ routes: [] });
    vi.spyOn(API, "getProviderRecommendations").mockResolvedValue({
      recommendations: [],
      min_calls: 1,
    });
    vi.spyOn(API, "getQualityStats").mockResolvedValue({
      count: 0,
      average_rating: null,
      groups: {},
      ratings: [],
    });

    renderAt("/app/projects/demo/settings");

    await waitFor(() => expect(screen.getByText("视频快速版")).toBeInTheDocument());
    expect(screen.queryByText("参考视频快速版")).not.toBeInTheDocument();
    expect(screen.queryByText("参考视频精修版")).not.toBeInTheDocument();
  });

  it("shows reference-video quality profiles for reference-video projects", async () => {
    vi.spyOn(API, "getSystemConfig").mockResolvedValue({
      ...FAKE_CONFIG_WITH_DEFAULTS,
    } as unknown as Awaited<ReturnType<typeof API.getSystemConfig>>);
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        generation_mode: "reference_video",
        video_backend: "gemini/veo-3",
        image_provider_t2i: "gemini/nano-banana",
        image_provider_i2i: "gemini/nano-banana",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);
    vi.spyOn(API, "previewGenerationRoutes").mockResolvedValue({ routes: [] });
    vi.spyOn(API, "getProviderRecommendations").mockResolvedValue({
      recommendations: [],
      min_calls: 1,
    });
    vi.spyOn(API, "getQualityStats").mockResolvedValue({
      count: 0,
      average_rating: null,
      groups: {},
      ratings: [],
    });

    renderAt("/app/projects/demo/settings");

    await waitFor(() => expect(screen.getByText("参考视频快速版")).toBeInTheDocument());
    expect(screen.getByText("参考视频精修版")).toBeInTheDocument();
  });

  it("groups repeated route preview errors by message", async () => {
    vi.spyOn(API, "getSystemConfig").mockResolvedValue({
      ...FAKE_CONFIG_WITH_DEFAULTS,
    } as unknown as Awaited<ReturnType<typeof API.getSystemConfig>>);
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        video_backend: "ark/doubao-seedance-1-5-pro-251215",
        image_provider_t2i: "gemini/nano-banana",
        image_provider_i2i: "gemini/nano-banana",
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);
    vi.spyOn(API, "previewGenerationRoutes").mockResolvedValue({
      routes: [
        {
          ok: false,
          label: "参考视频快速版",
          task_kind: "reference_video",
          quality: "draft",
          error: "当前模型不支持参考图，请切换到 Seedance 2.0。",
        },
        {
          ok: false,
          label: "参考视频精修版",
          task_kind: "reference_video",
          quality: "final",
          error: "当前模型不支持参考图，请切换到 Seedance 2.0。",
        },
      ],
    });
    vi.spyOn(API, "getProviderRecommendations").mockResolvedValue({
      recommendations: [],
      min_calls: 1,
    });
    vi.spyOn(API, "getQualityStats").mockResolvedValue({
      count: 0,
      average_rating: null,
      groups: {},
      ratings: [],
    });

    renderAt("/app/projects/demo/settings");

    await screen.findByText("参考视频快速版、参考视频精修版: 当前模型不支持参考图，请切换到 Seedance 2.0。");
    expect(screen.queryByText(/^参考视频快速版: 当前模型不支持参考图/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^参考视频精修版: 当前模型不支持参考图/)).not.toBeInTheDocument();
  });

  it("loads existing model_settings resolution into video/image pickers", async () => {
    vi.spyOn(API, "getSystemConfig").mockResolvedValue({
      ...FAKE_CONFIG_WITH_DEFAULTS,
    } as unknown as Awaited<ReturnType<typeof API.getSystemConfig>>);
    // 提供含 resolutions 的 provider，使 ResolutionPicker 能够渲染
    vi.spyOn(providerModels, "getProviderModels").mockResolvedValue([
      {
        id: "gemini",
        display_name: "Gemini",
        description: "",
        status: "ready",
        media_types: ["video", "image"],
        capabilities: [],
        configured_keys: [],
        missing_keys: [],
        models: {
          "veo-3": {
            display_name: "Veo 3",
            media_type: "video",
            capabilities: [],
            default: true,
            supported_durations: [5, 8],
            duration_resolution_constraints: {},
            resolutions: ["720p", "1080p"],
          },
          "nano-banana": {
            display_name: "Nano Banana",
            media_type: "image",
            capabilities: [],
            default: true,
            supported_durations: [],
            duration_resolution_constraints: {},
            resolutions: ["720p", "1080p"],
          },
        },
      },
    ] as Awaited<ReturnType<typeof providerModels.getProviderModels>>);
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        video_backend: "gemini/veo-3",
        image_provider_t2i: "gemini/nano-banana",
        image_provider_i2i: "gemini/nano-banana",
        model_settings: {
          "gemini/veo-3": { resolution: "1080p" },
          "gemini/nano-banana": { resolution: "720p" },
        },
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);

    renderAt("/app/projects/demo/settings");

    // 等待 ResolutionPicker 出现并验证已加载的初始值
    // select 模式的 ResolutionPicker 渲染为自定义 combobox，当前值会写在 trigger value 上
    await waitFor(() => {
      const selects = screen.getAllByRole("combobox");
      // 找到视频分辨率 select（aria-label 为 "分辨率"）
      const resSelects = selects.filter((el) =>
        el.getAttribute("aria-label")?.includes("分辨率") || el.getAttribute("aria-label")?.includes("Resolution"),
      );
      expect(resSelects.length).toBeGreaterThan(0);
      // 验证已加载的值
      const values = resSelects.map((el) => (el as HTMLButtonElement).value);
      expect(values).toContain("1080p");
      expect(values).toContain("720p");
    });
  });

  it("saves resolution changes via updateProject with model_settings", async () => {
    vi.spyOn(API, "getSystemConfig").mockResolvedValue({
      ...FAKE_CONFIG_WITH_DEFAULTS,
    } as unknown as Awaited<ReturnType<typeof API.getSystemConfig>>);
    // getProject 会被 handleSave 内调用一次（获取 existingModelSettings），mock 始终返回相同 project
    vi.spyOn(API, "getProject").mockResolvedValue({
      project: {
        title: "Demo",
        video_backend: "gemini/veo-3",
        image_provider_t2i: "gemini/nano-banana",
        image_provider_i2i: "gemini/nano-banana",
        model_settings: {
          "gemini/veo-3": { resolution: "1080p" },
          "gemini/nano-banana": { resolution: "720p" },
        },
        episodes: [],
        characters: {},
        clues: {},
      },
      scripts: {},
    } as unknown as Awaited<ReturnType<typeof API.getProject>>);
    const updateSpy = vi.spyOn(API, "updateProject").mockResolvedValue({
      success: true,
      project: { title: "Demo" } as unknown as Awaited<ReturnType<typeof API.updateProject>>["project"],
    });

    renderAt("/app/projects/demo/settings");

    // 等配置加载完
    await screen.findByRole("radio", { name: /竖屏 9:16/ });

    const saveBtn = screen.getByRole("button", { name: /^(保存|Save)$/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith(
        "demo",
        expect.objectContaining({
          model_settings: expect.objectContaining({
            "gemini/veo-3": expect.objectContaining({ resolution: "1080p" }),
            "gemini/nano-banana": expect.objectContaining({ resolution: "720p" }),
          }),
        }),
      );
    });
  });
});

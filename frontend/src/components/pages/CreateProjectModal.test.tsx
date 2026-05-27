import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// Stub URL object APIs not available in jsdom
globalThis.URL.createObjectURL ??= vi.fn(() => "blob:mock");
globalThis.URL.revokeObjectURL ??= vi.fn();
import "@/i18n";
import { CreateProjectModal } from "./CreateProjectModal";
import { API } from "@/api";
import { useProjectsStore } from "@/stores/projects-store";
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

// Mock wouter navigation
const navigateMock = vi.fn();
vi.mock("wouter", () => ({
  useLocation: () => ["/app/projects", navigateMock],
}));

function desktopImageRef(name = "style.png") {
  return {
    kind: "desktop-file" as const,
    path: `C:\\fixtures\\${name}`,
    name,
    previewUrl: `asset://fixtures/${name}`,
    contentType: "image/png",
  };
}

const mockSysConfig = {
  settings: {
    default_video_backend: "",
    default_image_backend: "",
    default_text_backend: "",
    text_backend_script: "",
    text_backend_overview: "",
    text_backend_style: "",
    video_generate_audio: false,
    anthropic_api_key: { is_set: false, masked: null },
    anthropic_base_url: "",
    anthropic_model: "",
    anthropic_default_haiku_model: "",
    anthropic_default_opus_model: "",
    anthropic_default_sonnet_model: "",
    claude_code_subagent_model: "",
    agent_session_cleanup_delay_seconds: 0,
    agent_max_concurrent_sessions: 0,
  },
  options: {
    video_backends: ["gemini-aistudio/veo-3"],
    image_backends: ["gemini-aistudio/nano-banana"],
    text_backends: ["gemini-aistudio/g25"],
    provider_names: { "gemini-aistudio": "Gemini AI Studio" },
  },
};

const mockProviders = {
  providers: [
    {
      id: "gemini-aistudio",
      display_name: "Gemini AI Studio",
      description: "",
      status: "ready" as const,
      media_types: ["video", "image", "text"],
      capabilities: [],
      configured_keys: [],
      missing_keys: [],
      models: {
        "veo-3": {
          display_name: "veo-3",
          media_type: "video",
          capabilities: [],
          default: false,
          supported_durations: [4, 6, 8],
          duration_resolution_constraints: {},
        },
      },
    },
  ],
};

describe("CreateProjectModal", () => {
  beforeEach(() => {
    navigateMock.mockClear();
    desktopFileMock.pickDesktopFile.mockReset();
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
    useProjectsStore.setState({ showCreateModal: true });
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.spyOn(API, "getSystemConfig").mockResolvedValue(mockSysConfig as never);
    vi.spyOn(API, "getProviders").mockResolvedValue(mockProviders as never);
    vi.spyOn(API, "listCustomProviders").mockResolvedValue({ providers: [] });
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
    vi.spyOn(API, "createProject").mockResolvedValue({
      success: true,
      name: "demo-proj",
      project: {} as never,
    });
    vi.spyOn(API, "uploadStyleImage").mockResolvedValue({
      success: true,
      style_image: "",
      style_description: "",
      url: "",
    });
    vi.spyOn(API, "analyzeStyleImage").mockResolvedValue({
      success: true,
      style_description: "cinematic custom prompt",
    });
  });

  it("starts at step 1 and shows title input", () => {
    render(<CreateProjectModal />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    // Next button disabled until title typed
    expect(screen.getByRole("button", { name: /下一步/ })).toBeDisabled();
  });

  it("advances from step 1 to step 2 after title entered and Next clicked", async () => {
    render(<CreateProjectModal />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "demo" } });
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    // Step 2 shows loading or Back button
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /上一步/ })).toBeInTheDocument()
    );
  });

  it("advances from step 2 to step 3 without validation", async () => {
    render(<CreateProjectModal />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "demo" } });
    fireEvent.click(screen.getByRole("button", { name: /下一步/ })); // to step 2
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /下一步/ })).toBeEnabled()
    );
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    // Step 3: Create button appears
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /创建项目/ })).toBeInTheDocument()
    );
  });

  it("submits createProject with default template when Create clicked on step 3", async () => {
    render(<CreateProjectModal />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "demo" } });
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /下一步/ })).toBeEnabled()
    );
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /创建项目/ })).toBeInTheDocument()
    );
    await waitFor(() =>
      expect(screen.getByLabelText(/风格提示词|Style prompt/)).toHaveValue("画风：真人电视剧风格，精品短剧画风，大师级构图")
    );
    fireEvent.click(screen.getByRole("button", { name: /创建项目/ }));
    await waitFor(() => expect(API.createProject).toHaveBeenCalled());
    expect(API.createProject).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "demo",
        content_mode: "narration",
        aspect_ratio: "9:16",
        generation_mode: "storyboard",
        style_template_id: "live_premium_drama",
        style: "画风：真人电视剧风格，精品短剧画风，大师级构图",
        video_backend: null,
        image_provider_t2i: null,
        image_provider_i2i: null,
        default_duration: null,
      })
    );
    expect(navigateMock).toHaveBeenCalledWith("/app/projects/demo-proj");
  });

  it("goes back from step 2 to step 1 preserving title", async () => {
    render(<CreateProjectModal />);
    const titleInput = screen.getByRole("textbox");
    fireEvent.change(titleInput, { target: { value: "demo" } });
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /上一步/ })).toBeInTheDocument()
    );
    fireEvent.click(screen.getByRole("button", { name: /上一步/ }));
    // Back on step 1, title preserved
    expect(screen.getByRole("textbox")).toHaveValue("demo");
  });

  it("shows error toast and stays on step 3 when createProject fails", async () => {
    vi.spyOn(API, "createProject").mockRejectedValueOnce(new Error("boom"));
    render(<CreateProjectModal />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "demo" } });
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /下一步/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /创建项目/ })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /创建项目/ }));
    await waitFor(() => expect(API.createProject).toHaveBeenCalled());
    // Not navigated away
    expect(navigateMock).not.toHaveBeenCalled();
    // Create button re-enabled after failure (creating=false)
    await waitFor(() => expect(screen.getByRole("button", { name: /创建项目/ })).toBeEnabled());
  });

  it("calls uploadStyleImage after createProject when in custom mode with uploaded file", async () => {
    render(<CreateProjectModal />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "demo" } });
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /下一步/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /创建项目/ })).toBeInTheDocument());

    // Switch to custom tab
    fireEvent.click(screen.getByRole("button", { name: /自定义|Custom/ }));
    const file = desktopImageRef();
    desktopFileMock.pickDesktopFile.mockResolvedValueOnce(file);
    fireEvent.click(screen.getByRole("button", { name: /上传风格参考图|Upload reference/ }));
    await waitFor(() => expect(screen.getByAltText(/上传风格参考图|Upload reference/)).toBeInTheDocument());

    await waitFor(() => expect(screen.getByRole("button", { name: /创建项目/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /创建项目/ }));

    await waitFor(() => expect(API.createProject).toHaveBeenCalled());
    expect(API.createProject).toHaveBeenCalledWith(expect.objectContaining({
      style_template_id: null,
    }));
    await waitFor(() => expect(API.uploadStyleImage).toHaveBeenCalledWith("demo-proj", file, {
      styleDescription: undefined,
    }));
  });

  it("uses the edited template prompt when creating from a preset", async () => {
    render(<CreateProjectModal />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "demo" } });
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /下一步/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /创建项目/ })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /张艺谋/ }));
    const promptBox = screen.getByLabelText(/风格提示词|Style prompt/);
    await waitFor(() => expect((promptBox as HTMLTextAreaElement).value).toContain("张艺谋"));
    fireEvent.change(promptBox, { target: { value: "自定义张艺谋电影质感" } });
    fireEvent.click(screen.getByRole("button", { name: /创建项目/ }));

    await waitFor(() => expect(API.createProject).toHaveBeenCalled());
    expect(API.createProject).toHaveBeenCalledWith(expect.objectContaining({
      style_template_id: "live_zhang_yimou",
      style: "自定义张艺谋电影质感",
    }));
  });

  it("can analyze a custom reference before create and pass the editable prompt to upload", async () => {
    render(<CreateProjectModal />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "demo" } });
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /下一步/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /创建项目/ })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /自定义|Custom/ }));
    const file = desktopImageRef("style-analyze.png");
    desktopFileMock.pickDesktopFile.mockResolvedValueOnce(file);
    fireEvent.click(screen.getByRole("button", { name: /上传风格参考图|Upload reference/ }));
    await waitFor(() => expect(screen.getByAltText(/上传风格参考图|Upload reference/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /分析风格|Analyze/ }));
    const promptBox = screen.getByLabelText(/风格提示词|Style prompt/);
    await waitFor(() => expect(promptBox).toHaveValue("cinematic custom prompt"));
    fireEvent.change(promptBox, { target: { value: "edited analyzed prompt" } });
    fireEvent.click(screen.getByRole("button", { name: /创建项目/ }));

    await waitFor(() => expect(API.uploadStyleImage).toHaveBeenCalledWith("demo-proj", file, {
      styleDescription: "edited analyzed prompt",
    }));
  });

  it("允许在 custom tab 未上传文件时创建项目（风格为可选）", async () => {
    render(<CreateProjectModal />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "demo" } });
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /下一步/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /下一步/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /创建项目/ })).toBeInTheDocument());

    // Switch to custom tab WITHOUT uploading anything
    fireEvent.click(screen.getByRole("button", { name: /自定义|Custom/ }));

    // Create button should still be enabled — style is optional
    await waitFor(() => expect(screen.getByRole("button", { name: /创建项目/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /创建项目/ }));

    await waitFor(() => expect(API.createProject).toHaveBeenCalled());
    expect(API.createProject).toHaveBeenCalledWith(expect.objectContaining({
      style_template_id: null,
    }));
    // No upload since no file
    expect(API.uploadStyleImage).not.toHaveBeenCalled();
  });
});

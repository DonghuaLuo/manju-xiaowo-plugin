import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { PluginSDK } from "xiaowo-sdk";
import { API } from "@/api";
import zhDashboard from "@/i18n/zh/dashboard";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { getGreetingKey, ProjectsPage } from "@/components/pages/ProjectsPage";

const desktopFileMock = vi.hoisted(() => ({
  pickDesktopFile: vi.fn(),
}));

vi.mock("@/components/pages/CreateProjectModal", () => ({
  CreateProjectModal: () => <div data-testid="create-project-modal">Create Project Modal</div>,
}));

vi.mock("@/utils/desktop-file", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/utils/desktop-file")>();
  return {
    ...actual,
    pickDesktopFile: desktopFileMock.pickDesktopFile,
  };
});

function renderPage() {
  const location = memoryLocation({ path: "/app/projects", record: true });
  return {
    ...render(
      <Router hook={location.hook}>
        <ProjectsPage />
      </Router>,
    ),
    location,
  };
}

function projectArchiveRef(name = "project.zip") {
  return {
    kind: "desktop-file" as const,
    path: `C:\\fixtures\\${name}`,
    name,
    contentType: "application/zip",
  };
}

function clickImportZip() {
  fireEvent.click(screen.getAllByRole("button", { name: "导入 ZIP" })[0]);
}

describe("ProjectsPage", () => {
  beforeEach(() => {
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.restoreAllMocks();
    desktopFileMock.pickDesktopFile.mockReset();
  });

  it("shows loading state while projects are being fetched", () => {
    vi.spyOn(API, "listProjects").mockImplementation(
      () => new Promise(() => {}),
    );

    renderPage();
    expect(screen.getByText("加载项目列表...")).toBeInTheDocument();
  });

  it("shows empty state when no projects exist", async () => {
    vi.spyOn(API, "listProjects").mockResolvedValue({ projects: [] });

    renderPage();

    // 0 项目时仅渲染 NewProjectTile 占位卡（lobby_new_project_title）
    expect(await screen.findByText("新建项目")).toBeInTheDocument();
    expect(API.listProjects).toHaveBeenCalledWith({ check_extmodel: true });
  });

  it("uses the correct greeting bucket for the local time", () => {
    expect(getGreetingKey(new Date(2026, 0, 1, 4, 59))).toBe("lobby_hero_greeting_late");
    expect(getGreetingKey(new Date(2026, 0, 1, 5, 0))).toBe("lobby_hero_greeting_morning");
    expect(getGreetingKey(new Date(2026, 0, 1, 10, 59))).toBe("lobby_hero_greeting_morning");
    expect(getGreetingKey(new Date(2026, 0, 1, 11, 0))).toBe("lobby_hero_greeting_afternoon");
    expect(getGreetingKey(new Date(2026, 0, 1, 17, 59))).toBe("lobby_hero_greeting_afternoon");
    expect(getGreetingKey(new Date(2026, 0, 1, 18, 0))).toBe("lobby_hero_greeting_evening");
    expect(getGreetingKey(new Date(2026, 0, 1, 21, 59))).toBe("lobby_hero_greeting_evening");
    expect(getGreetingKey(new Date(2026, 0, 1, 22, 0))).toBe("lobby_hero_greeting_late");
  });

  it("uses neutral Chinese lobby copy instead of clock-sensitive wording", () => {
    expect(zhDashboard.lobby_hero_greeting_morning).toBe("欢迎回来，导演。");
    expect(zhDashboard.lobby_hero_greeting_afternoon).toBe("欢迎回来，导演。");
    expect(zhDashboard.lobby_hero_greeting_evening).toBe("欢迎回来，导演。");
    expect(zhDashboard.lobby_hero_greeting_late).toBe("欢迎回来，导演。");
    expect(zhDashboard.lobby_hero_subtitle_quiet).toBe("当前没有作品在制作中。");
  });

  it("renders project cards when data exists", async () => {
    vi.spyOn(API, "listProjects").mockResolvedValue({
      projects: [
        {
          name: "demo",
          title: "Demo Project",
          style: "Anime",
          style_template_id: "anim_kyoto",
          thumbnail: null,
          status: {
            current_phase: "production",
            phase_progress: 0.5,
            characters: { total: 2, completed: 2 },
            scenes: { total: 1, completed: 1 },
            props: { total: 1, completed: 0 },
            episodes_summary: { total: 1, scripted: 1, in_production: 1, completed: 0 },
          },
        },
      ],
    });

    renderPage();

    // Title may render twice (cinemascope poster overlay + heading) in the
    // featured "Now Editing" card — see ProjectsPage.tsx Darkroom design.
    expect((await screen.findAllByText("Demo Project")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("商业动画 京都").length).toBeGreaterThan(0);
    expect(screen.getAllByText("制作中").length).toBeGreaterThan(0);
    expect(screen.getByText("50%")).toBeInTheDocument();
  });

  it("retries the initial projects fetch when plugin backend is still warming up", async () => {
    vi.spyOn(API, "listProjects")
      .mockRejectedValueOnce(new Error("backend is not ready"))
      .mockResolvedValueOnce({
        projects: [
          {
            name: "recovered-demo",
            title: "Recovered Demo",
            style: "Anime",
            style_template_id: "anim_kyoto",
            thumbnail: null,
            status: {
              current_phase: "production",
              phase_progress: 0.5,
              characters: { total: 2, completed: 2 },
              scenes: { total: 1, completed: 1 },
              props: { total: 1, completed: 0 },
              episodes_summary: { total: 1, scripted: 1, in_production: 1, completed: 0 },
            },
          },
        ],
      });

    renderPage();

    expect(screen.getByText("加载项目列表...")).toBeInTheDocument();
    expect((await screen.findAllByText("Recovered Demo", {}, { timeout: 2000 })).length).toBeGreaterThan(0);
    expect(API.listProjects).toHaveBeenCalledTimes(2);
  });

  it("shows 自定义风格 label when project has style_image but no template_id", async () => {
    vi.spyOn(API, "listProjects").mockResolvedValue({
      projects: [
        {
          name: "demo",
          title: "Custom Demo",
          style: "",
          style_template_id: null,
          style_image: "style_reference.png",
          thumbnail: null,
          status: {
            current_phase: "production",
            phase_progress: 0.1,
            characters: { total: 1, completed: 0 },
            scenes: { total: 0, completed: 0 },
            props: { total: 0, completed: 0 },
            episodes_summary: { total: 1, scripted: 0, in_production: 1, completed: 0 },
          },
        },
      ],
    });

    renderPage();

    expect((await screen.findAllByText("Custom Demo")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/自定义风格/).length).toBeGreaterThan(0);
  });

  it("shows 未设置风格 label when project has neither template_id nor style_image", async () => {
    vi.spyOn(API, "listProjects").mockResolvedValue({
      projects: [
        {
          name: "demo",
          title: "Empty Style Demo",
          style: "",
          style_template_id: null,
          style_image: null,
          thumbnail: null,
          status: {
            current_phase: "production",
            phase_progress: 0,
            characters: { total: 0, completed: 0 },
            scenes: { total: 0, completed: 0 },
            props: { total: 0, completed: 0 },
            episodes_summary: { total: 0, scripted: 0, in_production: 0, completed: 0 },
          },
        },
      ],
    });

    renderPage();

    expect((await screen.findAllByText("Empty Style Demo")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/未设置风格/).length).toBeGreaterThan(0);
  });

  it("opens create project modal after clicking new project button", async () => {
    vi.spyOn(API, "listProjects").mockResolvedValue({ projects: [] });

    renderPage();
    await screen.findByText("新建项目");
    expect(screen.queryByTestId("create-project-modal")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "创建项目" }));

    await waitFor(() => {
      expect(screen.getByTestId("create-project-modal")).toBeInTheDocument();
    });
  });

  it("opens the asset export dialog with asset libraries selected by default", async () => {
    vi.spyOn(API, "listProjects").mockResolvedValue({ projects: [] });
    vi.spyOn(API, "getAssetArchiveExportInfo").mockResolvedValue({
      projectsRoot: "D:\\ArcReel\\projects",
      globalAssetsRoot: "D:\\ArcReel\\projects\\_global_assets",
      styleFavoritesRoot: "D:\\ArcReel\\projects\\_style_favorites",
      scriptSplittingTemplatesRoot: "D:\\ArcReel\\projects\\_script_splitting_templates",
    });

    renderPage();
    await screen.findByText("新建项目");

    fireEvent.click(screen.getByRole("button", { name: "导出资产" }));

    expect(await screen.findByRole("heading", { name: "导出资产" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /角色库/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /场景库/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /道具库/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /自定义风格收藏/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /导出拆分模板/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /同时导出全局配置/ })).not.toBeChecked();
    expect(await screen.findByText("D:\\ArcReel\\projects")).toBeInTheDocument();
  });

  it("starts asset export with the selected options", async () => {
    vi.spyOn(API, "listProjects").mockResolvedValue({ projects: [] });
    vi.spyOn(API, "getAssetArchiveExportInfo").mockResolvedValue({
      projectsRoot: "D:\\ArcReel\\projects",
    });
    vi.spyOn(API, "startAssetArchiveExport").mockResolvedValue({
      taskId: "asset-task-1",
      status: "queued",
      exportPath: "C:\\exports\\assets.zip",
    });
    vi.spyOn(API, "getExportTaskStatus").mockResolvedValue(null);
    vi.mocked(PluginSDK.dialog.save).mockResolvedValueOnce("C:\\exports\\assets.zip");

    renderPage();
    await screen.findByText("新建项目");

    fireEvent.click(screen.getByRole("button", { name: "导出资产" }));
    await screen.findByRole("heading", { name: "导出资产" });
    fireEvent.click(screen.getByRole("checkbox", { name: /同时导出全局配置/ }));
    const exportButtons = screen.getAllByRole("button", { name: "导出资产" });
    fireEvent.click(exportButtons[exportButtons.length - 1]);

    await waitFor(() => {
      expect(API.startAssetArchiveExport).toHaveBeenCalledWith("C:\\exports\\assets.zip", {
        includeAssets: {
          character: true,
          scene: true,
          prop: true,
          styleFavorites: true,
        },
        includeGlobalConfig: true,
        includeScriptSplittingTemplates: true,
      });
    });
  });

  it("retries loading asset export info after a failed attempt", async () => {
    vi.spyOn(API, "listProjects").mockResolvedValue({ projects: [] });
    const infoSpy = vi.spyOn(API, "getAssetArchiveExportInfo")
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({
        projectsRoot: "D:\\ArcReel\\projects",
      });

    renderPage();
    await screen.findByText("新建项目");

    fireEvent.click(screen.getByRole("button", { name: "导出资产" }));
    await screen.findByRole("heading", { name: "导出资产" });
    await waitFor(() => {
      expect(infoSpy).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "导出资产" })).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "导出资产" }));
    await waitFor(() => {
      expect(infoSpy).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("D:\\ArcReel\\projects")).toBeInTheDocument();
  });

  it("imports a zip project, refreshes the list, and navigates to the workspace", async () => {
    vi.spyOn(API, "listProjects")
      .mockResolvedValueOnce({ projects: [] })
      .mockResolvedValueOnce({
        projects: [
          {
            name: "imported-demo",
            title: "Imported Demo",
            style: "Anime",
            thumbnail: null,
            status: {
              current_phase: "completed",
              phase_progress: 1,
              characters: { total: 1, completed: 1 },
              scenes: { total: 1, completed: 1 },
              props: { total: 0, completed: 0 },
              episodes_summary: { total: 1, scripted: 1, in_production: 0, completed: 1 },
            },
          },
        ],
      });
    vi.spyOn(API, "importProject").mockResolvedValue({
      success: true,
      project_name: "imported-demo",
      project: {
        title: "Imported Demo",
        content_mode: "narration",
        style: "Anime",
        episodes: [],
        characters: {},
        scenes: {},
        props: {},
      },
      warnings: ["发现未识别的附加文件/目录: extras"],
      conflict_resolution: "none",
      diagnostics: {
        auto_fixed: [{ code: "missing_clues_field", message: "segments[0]: 补全缺失字段 clues_in_segment" }],
        warnings: [{ code: "validation_warning", message: "发现未识别的附加文件/目录: extras" }],
      },
    });

    const { location } = renderPage();
    await screen.findByText("新建项目");

    const file = projectArchiveRef();
    desktopFileMock.pickDesktopFile.mockResolvedValueOnce(file);
    clickImportZip();

    await waitFor(() => {
      expect(API.importProject).toHaveBeenCalledWith(file, "prompt");
    });
    // 当存在 warnings/auto_fixed 时先弹诊断对话框，关闭后才跳转
    expect(await screen.findByText("导入诊断")).toBeInTheDocument();
    expect(useAppStore.getState().toast?.text).toContain("自动修复");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => {
      expect(location.history?.at(-1)).toBe("/app/projects/imported-demo");
    });
  });

  it("imports an asset archive, refreshes the lobby, and stays on the projects page", async () => {
    vi.spyOn(API, "listProjects")
      .mockResolvedValueOnce({ projects: [] })
      .mockResolvedValueOnce({ projects: [] });
    vi.spyOn(API, "importProject").mockResolvedValue({
      success: true,
      import_type: "asset_archive",
      summary: {
        assets: 2,
        asset_files: 3,
        style_favorites_files: 1,
        global_config: true,
        global_config_rows: { system_settings: 1 },
        global_config_files: 0,
      },
      warnings: [],
      diagnostics: {
        auto_fixed: [],
        warnings: [],
      },
    });

    const { location } = renderPage();
    await screen.findByText("新建项目");

    const file = projectArchiveRef("assets.zip");
    desktopFileMock.pickDesktopFile.mockResolvedValueOnce(file);
    clickImportZip();

    await waitFor(() => {
      expect(API.importProject).toHaveBeenCalledWith(file, "prompt");
    });
    await waitFor(() => {
      expect(useAppStore.getState().toast?.text).toContain("资产导入完成");
    });
    expect(location.history?.at(-1)).toBe("/app/projects");
  });

  it("shows a structured toast when import fails", async () => {
    vi.spyOn(API, "listProjects").mockResolvedValue({ projects: [] });
    const error = new Error("导入包校验失败") as Error & {
      detail?: string;
      errors?: string[];
      warnings?: string[];
      diagnostics?: {
        blocking: { code: string; message: string }[];
        auto_fixable: { code: string; message: string }[];
        warnings: { code: string; message: string }[];
      };
    };
    error.detail = "导入包校验失败";
    error.errors = ["缺少 project.json", "缺少 scripts/episode_1.json", "缺少角色图"];
    error.warnings = ["发现未识别的附加文件/目录: extras"];
    error.diagnostics = {
      blocking: [
        { code: "validation_error", message: "缺少 project.json" },
        { code: "validation_error", message: "缺少 scripts/episode_1.json" },
      ],
      auto_fixable: [
        { code: "missing_clues_field", message: "segments[0]: 补全缺失字段 clues_in_segment" },
      ],
      warnings: [
        { code: "validation_warning", message: "发现未识别的附加文件/目录: extras" },
      ],
    };
    vi.spyOn(API, "importProject").mockRejectedValue(error);

    renderPage();
    await screen.findByText("新建项目");

    desktopFileMock.pickDesktopFile.mockResolvedValueOnce(projectArchiveRef("broken.zip"));
    clickImportZip();

    await waitFor(() => {
      expect(screen.getByText("导入失败诊断")).toBeInTheDocument();
    });
    expect(screen.getByText("缺少 project.json")).toBeInTheDocument();
    expect(screen.getByText("缺少 scripts/episode_1.json")).toBeInTheDocument();
    expect(screen.getByText("segments[0]: 补全缺失字段 clues_in_segment")).toBeInTheDocument();
  });

  it("opens a secondary confirmation when import hits a duplicate project id", async () => {
    vi.spyOn(API, "listProjects")
      .mockResolvedValueOnce({ projects: [] })
      .mockResolvedValueOnce({
        projects: [
          {
            name: "demo",
            title: "Demo",
            style: "Anime",
            thumbnail: null,
            status: {
              current_phase: "completed",
              phase_progress: 1,
              characters: { total: 1, completed: 1 },
              scenes: { total: 1, completed: 1 },
              props: { total: 0, completed: 0 },
              episodes_summary: { total: 1, scripted: 1, in_production: 0, completed: 1 },
            },
          },
        ],
      });
    const conflictError = new Error("检测到项目编号冲突") as Error & {
      status?: number;
      detail?: string;
      errors?: string[];
      conflict_project_name?: string;
    };
    conflictError.status = 409;
    conflictError.detail = "检测到项目编号冲突";
    conflictError.errors = ["项目编号 'demo' 已存在"];
    conflictError.conflict_project_name = "demo";

    vi.spyOn(API, "importProject")
      .mockRejectedValueOnce(conflictError)
      .mockResolvedValueOnce({
        success: true,
        project_name: "demo-renamed",
        project: {
          title: "Renamed Demo",
          content_mode: "narration",
          style: "Anime",
          episodes: [],
          characters: {},
          scenes: {},
          props: {},
        },
        warnings: [],
        conflict_resolution: "renamed",
        diagnostics: {
          auto_fixed: [],
          warnings: [],
        },
      });

    const { location } = renderPage();
    await screen.findByText("新建项目");

    const file = projectArchiveRef();
    desktopFileMock.pickDesktopFile.mockResolvedValueOnce(file);
    clickImportZip();

    expect(await screen.findByText("检测到项目编号重复")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "自动重命名导入" }));

    await waitFor(() => {
      expect(API.importProject).toHaveBeenNthCalledWith(1, file, "prompt");
    });
    await waitFor(() => {
      expect(API.importProject).toHaveBeenNthCalledWith(2, file, "rename");
    });
    await waitFor(() => {
      expect(location.history?.at(-1)).toBe("/app/projects/demo-renamed");
    });
  });
});

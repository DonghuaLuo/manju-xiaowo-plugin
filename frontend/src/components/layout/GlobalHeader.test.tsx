import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Router } from "wouter";
import { memoryLocation } from "wouter/memory-location";
import { PluginSDK } from "xiaowo-sdk";
import { GlobalHeader } from "@/components/layout/GlobalHeader";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useAssistantStore } from "@/stores/assistant-store";
import { useProjectsStore } from "@/stores/projects-store";
import { useTasksStore } from "@/stores/tasks-store";
import { useUsageStore } from "@/stores/usage-store";

vi.mock("@/components/task-hud/TaskHud", () => ({
  TaskHud: () => <div data-testid="task-hud" />,
}));

vi.mock("./UsageDrawer", () => ({
  UsageDrawer: () => <div data-testid="usage-drawer" />,
}));

vi.mock("./WorkspaceNotificationsDrawer", () => ({
  WorkspaceNotificationsDrawer: ({ open }: { open: boolean }) =>
    open ? <div data-testid="notifications-drawer" /> : null,
}));

const desktopDownloadMock = vi.hoisted(() => ({
  offerOpenSavedFile: vi.fn(),
  saveBlobWithDialog: vi.fn(),
}));

vi.mock("@/utils/desktop-download", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/utils/desktop-download")>();
  return {
    ...actual,
    offerOpenSavedFile: desktopDownloadMock.offerOpenSavedFile,
    saveBlobWithDialog: desktopDownloadMock.saveBlobWithDialog,
  };
});

vi.mock("./ExportScopeDialog", () => ({
  ExportScopeDialog: ({
    open,
    onSelect,
    onJianyingExport,
  }: {
    open: boolean;
    onClose: () => void;
    onSelect: (scope: "current" | "full") => void;
    anchorRef: React.RefObject<HTMLElement | null>;
    episodes?: unknown[];
    onJianyingExport?: (episode: number, draftPath: string, jianyingVersion: string) => void;
    jianyingExporting?: boolean;
  }) =>
    open ? (
      <div data-testid="export-scope-dialog">
        <button data-testid="scope-current" onClick={() => onSelect("current")}>
          仅当前版本
        </button>
        <button data-testid="scope-full" onClick={() => onSelect("full")}>
          全部数据
        </button>
        <button
          data-testid="scope-jianying"
          onClick={() => onJianyingExport?.(1, "C:\\Jianying\\Drafts", "6")}
        >
          剪映草稿
        </button>
      </div>
    ) : null,
}));

function renderHeader(path = "/characters") {
  const location = memoryLocation({ path, record: true });
  return render(
    <Router hook={location.hook}>
      <GlobalHeader />
    </Router>
  );
}

describe("GlobalHeader", () => {
  beforeEach(() => {
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
    useAppStore.setState(useAppStore.getInitialState(), true);
    useAssistantStore.setState(useAssistantStore.getInitialState(), true);
    useTasksStore.setState(useTasksStore.getInitialState(), true);
    useUsageStore.setState(useUsageStore.getInitialState(), true);
    vi.restoreAllMocks();
    desktopDownloadMock.offerOpenSavedFile.mockReset();
    desktopDownloadMock.saveBlobWithDialog.mockReset();
    vi.mocked(PluginSDK.dialog.save).mockReset();
    vi.mocked(PluginSDK.dialog.save).mockResolvedValue(null);
    vi.mocked(PluginSDK.dialog.ask).mockReset();
    vi.mocked(PluginSDK.dialog.ask).mockResolvedValue(false);
    vi.mocked(PluginSDK.shell.open).mockReset();
    vi.mocked(PluginSDK.shell.open).mockResolvedValue(undefined);
  });

  it("prefers the project title over the internal project name", async () => {
    vi.spyOn(API, "getUsageStats").mockResolvedValue({
      total_cost: 0,
      image_count: 0,
      video_count: 0,
      failed_count: 0,
      total_count: 0,
    });

    useProjectsStore.setState({
      currentProjectName: "halou-92d19a04",
      currentProjectData: {
        title: "哈喽项目",
        content_mode: "narration",
        style: "Anime",
        episodes: [],
        characters: {},
        scenes: {},
        props: {},
      },
    });

    renderHeader();

    expect(screen.getByText("哈喽项目")).toBeInTheDocument();
    expect(screen.queryByText("halou-92d19a04")).not.toBeInTheDocument();

    await waitFor(() => {
      expect(API.getUsageStats).toHaveBeenCalledWith({
        projectName: "halou-92d19a04",
      });
    });
  });

  it("shows unread notification count and opens the drawer", async () => {
    vi.spyOn(API, "getUsageStats").mockResolvedValue({
      total_cost: 0,
      image_count: 0,
      video_count: 0,
      failed_count: 0,
      total_count: 0,
    });

    useAppStore.getState().pushWorkspaceNotification({
      text: "AI 刚更新了道具「玉佩」，点击查看",
      target: {
        type: "prop",
        id: "玉佩",
        route: "/props",
      },
    });

    renderHeader();

    expect(screen.getByTitle("会话通知: 1 条")).toBeInTheDocument();
    screen.getByRole("button", { name: "打开通知中心" }).click();
    expect(await screen.findByTestId("notifications-drawer")).toBeInTheDocument();
  });

  it("exports the current project zip via desktop save dialog", async () => {
    vi.spyOn(API, "getUsageStats").mockResolvedValue({
      total_cost: 0,
      image_count: 0,
      video_count: 0,
      failed_count: 0,
      total_count: 0,
    });
    vi.spyOn(API, "startProjectArchiveExport").mockResolvedValue({
      taskId: "export-task-1",
      status: "queued",
      exportPath: "C:\\exports\\demo-current.zip",
    });
    vi.mocked(PluginSDK.dialog.save).mockResolvedValueOnce("C:\\exports\\demo-current.zip");

    useProjectsStore.setState({
      currentProjectName: "demo",
      currentProjectData: {
        title: "导出项目",
        content_mode: "narration",
        style: "Anime",
        episodes: [],
        characters: {},
        scenes: {},
        props: {},
      },
    });

    renderHeader();
    // Click export button to open dialog
    screen.getByRole("button", { name: "导出当前项目 ZIP" }).click();

    // Wait for dialog to appear then click "仅当前版本"
    const scopeBtn = await screen.findByTestId("scope-current");
    scopeBtn.click();

    await waitFor(() => {
      expect(API.startProjectArchiveExport).toHaveBeenCalledWith(
        "demo",
        "current",
        "C:\\exports\\demo-current.zip",
      );
    });
    expect(PluginSDK.dialog.save).toHaveBeenCalledWith(
      expect.objectContaining({
        defaultPath: "demo-current.zip",
        filters: [{ name: "ZIP", extensions: ["zip"] }],
      }),
    );
    expect(useAppStore.getState().toast?.text).toContain("项目 ZIP 导出任务已开始");
  });

  it("uses an in-app dialog and backend call to open an exported location", async () => {
    vi.spyOn(API, "getUsageStats").mockResolvedValue({
      total_cost: 0,
      image_count: 0,
      video_count: 0,
      failed_count: 0,
      total_count: 0,
    });
    vi.spyOn(API, "getExportTaskStatus").mockResolvedValue({
      taskId: "export-task-1",
      kind: "project_archive",
      status: "completed",
      projectName: "demo",
      scope: "current",
      exportPath: "C:\\exports\\demo-current.zip",
      diagnostics: { blocking: [], auto_fixed: [], warnings: [] },
    });
    vi.spyOn(API, "startProjectArchiveExport").mockResolvedValue({
      taskId: "export-task-1",
      status: "queued",
      exportPath: "C:\\exports\\demo-current.zip",
    });
    vi.spyOn(API, "openDesktopPath").mockResolvedValue(undefined);
    vi.mocked(PluginSDK.dialog.save).mockResolvedValueOnce("C:\\exports\\demo-current.zip");

    useProjectsStore.setState({
      currentProjectName: "demo",
      currentProjectData: {
        title: "导出项目",
        content_mode: "narration",
        style: "Anime",
        episodes: [],
        characters: {},
        scenes: {},
        props: {},
      },
    });

    renderHeader();
    screen.getByRole("button", { name: "导出当前项目 ZIP" }).click();
    const scopeBtn = await screen.findByTestId("scope-current");
    scopeBtn.click();

    await waitFor(() => {
      expect(API.startProjectArchiveExport).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(API.getExportTaskStatus).toHaveBeenCalledWith("export-task-1");
    });

    expect(await screen.findByText("打开保存位置？")).toBeInTheDocument();
    expect(screen.getByText(/C:\\exports\\demo-current\.zip/)).toBeInTheDocument();

    screen.getByRole("button", { name: "打开" }).click();

    await waitFor(() => {
      expect(API.openDesktopPath).toHaveBeenCalledWith("C:\\exports\\demo-current.zip");
    });
    expect(PluginSDK.shell.open).not.toHaveBeenCalled();
    expect(PluginSDK.dialog.ask).not.toHaveBeenCalled();
  });

  it("warns when a Jianying draft export skips ungenerated shots", async () => {
    vi.spyOn(API, "getUsageStats").mockResolvedValue({
      total_cost: 0,
      image_count: 0,
      video_count: 0,
      failed_count: 0,
      total_count: 0,
    });
    vi.spyOn(API, "startJianyingDraftExport").mockResolvedValue({
      taskId: "jianying-task-1",
      status: "queued",
      draftPath: "C:\\Jianying\\Drafts",
    });
    vi.spyOn(API, "getExportTaskStatus").mockResolvedValue({
      taskId: "jianying-task-1",
      kind: "jianying_draft",
      status: "completed",
      projectName: "demo",
      episode: 1,
      draftPath: "C:\\Jianying\\Drafts",
      draftDir: "C:\\Jianying\\Drafts\\demo_第1集",
      summary: {
        episode: 1,
        total_count: 5,
        exported_count: 3,
        missing_count: 2,
        exported_ids: ["S1", "S2", "S4"],
        missing_ids: ["S3", "S5"],
      },
    });

    useProjectsStore.setState({
      currentProjectName: "demo",
      currentProjectData: {
        title: "导出项目",
        content_mode: "narration",
        style: "Anime",
        episodes: [{ episode: 1, title: "第一集", script_file: "episode_1.json" }],
        characters: {},
        scenes: {},
        props: {},
      },
    });

    renderHeader();
    screen.getByRole("button", { name: "导出当前项目 ZIP" }).click();
    const jianyingBtn = await screen.findByTestId("scope-jianying");
    jianyingBtn.click();

    await waitFor(() => {
      expect(API.startJianyingDraftExport).toHaveBeenCalledWith(
        "demo",
        1,
        "C:\\Jianying\\Drafts",
        "6",
      );
    });
    await waitFor(() => {
      expect(API.getExportTaskStatus).toHaveBeenCalledWith("jianying-task-1");
    });
    await waitFor(() => {
      const notification = useAppStore.getState().workspaceNotifications[0];
      expect(notification?.tone).toBe("warning");
      expect(notification?.text).toContain("已导出 3 个视频，跳过 2 个未生成镜头");
      expect(notification?.text).toContain("未生成镜头：S3、S5");
    });
  });

  it("renders asset library button", async () => {
    vi.spyOn(API, "getUsageStats").mockResolvedValue({
      total_cost: 0,
      image_count: 0,
      video_count: 0,
      failed_count: 0,
      total_count: 0,
    });

    renderHeader();

    expect(screen.getByRole("button", { name: "资产库" })).toBeInTheDocument();
  });

  it("records the absolute workspace route before opening the asset library", async () => {
    vi.spyOn(API, "getUsageStats").mockResolvedValue({
      total_cost: 0,
      image_count: 0,
      video_count: 0,
      failed_count: 0,
      total_count: 0,
    });
    useProjectsStore.setState({
      currentProjectName: "demo",
      currentProjectData: {
        title: "导出项目",
        content_mode: "narration",
        style: "Anime",
        episodes: [],
        characters: {},
        scenes: {},
        props: {},
      },
    });

    renderHeader("/characters");
    screen.getByRole("button", { name: "资产库" }).click();

    expect(sessionStorage.getItem("assetLibrary:returnTo")).toBe("/app/projects/demo/characters");
  });

  it("shows an error toast when exporting fails", async () => {
    vi.spyOn(API, "getUsageStats").mockResolvedValue({
      total_cost: 0,
      image_count: 0,
      video_count: 0,
      failed_count: 0,
      total_count: 0,
    });
    vi.spyOn(API, "startProjectArchiveExport").mockRejectedValue(new Error("network"));
    vi.mocked(PluginSDK.dialog.save).mockResolvedValueOnce("C:\\exports\\demo-full.zip");

    useProjectsStore.setState({
      currentProjectName: "demo",
      currentProjectData: {
        title: "导出项目",
        content_mode: "narration",
        style: "Anime",
        episodes: [],
        characters: {},
        scenes: {},
        props: {},
      },
    });

    renderHeader();
    screen.getByRole("button", { name: "导出当前项目 ZIP" }).click();

    const scopeBtn = await screen.findByTestId("scope-full");
    scopeBtn.click();

    await waitFor(() => {
      expect(useAppStore.getState().toast?.text).toContain("导出失败");
    });
  });
});

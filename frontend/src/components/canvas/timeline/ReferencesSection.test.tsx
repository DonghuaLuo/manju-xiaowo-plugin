import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import type { ProjectData } from "@/types";
import { ReferencesSection } from "./ReferencesSection";

describe("ReferencesSection", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
    vi.restoreAllMocks();
  });

  it("preflights candidate references before saving and blocks over-limit selections", async () => {
    useProjectsStore.getState().setCurrentProject("demo", {
      title: "Demo",
      content_mode: "narration",
      style: "Anime",
      characters: {
        Hero: { description: "hero", character_sheet: "characters/hero.png" },
        Villain: { description: "villain", character_sheet: "characters/villain.png" },
      },
      scenes: {},
      props: {},
    } as unknown as ProjectData);
    const preflight = vi
      .spyOn(API, "previewStoryboardReferenceUsage")
      .mockRejectedValue(new Error("当前图片模型最多支持 3 张参考图"));
    const onSave = vi.fn();

    render(
      <ReferencesSection
        projectName="demo"
        segmentId="E1S02"
        scriptFile="episode_1.json"
        contentMode="narration"
        characterNames={["Hero"]}
        sceneNames={[]}
        propNames={[]}
        onSave={onSave}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "编辑引用" }));
    const villainRow = screen
      .getAllByRole("button", { name: /Villain/ })
      .find((el) => el.getAttribute("aria-pressed") !== null);
    expect(villainRow).toBeTruthy();
    fireEvent.click(villainRow!);
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(preflight).toHaveBeenCalledWith("demo", "E1S02", {
        script_file: "episode_1.json",
        characters: ["Hero", "Villain"],
        scenes: [],
        props: [],
      });
    });
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByText("当前图片模型最多支持 3 张参考图")).toBeInTheDocument();
  });

  it("blocks saving when the script file is unavailable", async () => {
    useProjectsStore.getState().setCurrentProject("demo", {
      title: "Demo",
      content_mode: "narration",
      style: "Anime",
      characters: {
        Hero: { description: "hero", character_sheet: "characters/hero.png" },
        Villain: { description: "villain", character_sheet: "characters/villain.png" },
      },
      scenes: {},
      props: {},
    } as unknown as ProjectData);
    const preflight = vi
      .spyOn(API, "previewStoryboardReferenceUsage")
      .mockResolvedValue({ ok: true, message: null, scenarios: [] });
    const onSave = vi.fn();

    render(
      <ReferencesSection
        projectName="demo"
        segmentId="E1S02"
        contentMode="narration"
        characterNames={["Hero"]}
        sceneNames={[]}
        propNames={[]}
        onSave={onSave}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "编辑引用" }));
    const villainRow = screen
      .getAllByRole("button", { name: /Villain/ })
      .find((el) => el.getAttribute("aria-pressed") !== null);
    expect(villainRow).toBeTruthy();
    fireEvent.click(villainRow!);
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(screen.getByText("缺少剧本文件，无法检查参考图上限，请刷新项目后重试。")).toBeInTheDocument();
    });
    expect(preflight).not.toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("removes a reference directly from the current shot after confirmation", async () => {
    useProjectsStore.getState().setCurrentProject("demo", {
      title: "Demo",
      content_mode: "narration",
      style: "Anime",
      characters: {
        Hero: { description: "hero", character_sheet: "characters/hero.png" },
      },
      scenes: {
        Forest: { description: "forest", scene_sheet: "scenes/forest.png" },
      },
      props: {},
    } as unknown as ProjectData);
    const preflight = vi
      .spyOn(API, "previewStoryboardReferenceUsage")
      .mockResolvedValue({ ok: true, message: null, scenarios: [] });
    const onSave = vi.fn().mockResolvedValue(undefined);

    render(
      <ReferencesSection
        projectName="demo"
        segmentId="E1S02"
        scriptFile="episode_1.json"
        contentMode="narration"
        characterNames={["Hero"]}
        sceneNames={["Forest"]}
        propNames={[]}
        onSave={onSave}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "从当前分镜移除 Hero 引用" }));

    const dialog = screen.getByRole("dialog", { name: "移除引用" });
    expect(
      within(dialog).getByText("确定只从当前分镜移除角色「Hero」的引用吗？素材图片本身不会被删除。"),
    ).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "移除" }));

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith({ characters_in_segment: [] });
    });
    expect(preflight).not.toHaveBeenCalled();
  });

  it("does not remove a reference directly when the script file is unavailable", async () => {
    useProjectsStore.getState().setCurrentProject("demo", {
      title: "Demo",
      content_mode: "narration",
      style: "Anime",
      characters: {
        Hero: { description: "hero", character_sheet: "characters/hero.png" },
      },
      scenes: {},
      props: {},
    } as unknown as ProjectData);
    const onSave = vi.fn().mockResolvedValue(undefined);

    render(
      <ReferencesSection
        projectName="demo"
        segmentId="E1S02"
        contentMode="narration"
        characterNames={["Hero"]}
        sceneNames={[]}
        propNames={[]}
        onSave={onSave}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "从当前分镜移除 Hero 引用" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "移除引用" })).getByRole("button", { name: "移除" }));

    await waitFor(() => {
      expect(useAppStore.getState().toast?.text).toBe("缺少剧本文件，无法更新引用，请刷新项目后重试。");
    });
    expect(onSave).not.toHaveBeenCalled();
  });
});

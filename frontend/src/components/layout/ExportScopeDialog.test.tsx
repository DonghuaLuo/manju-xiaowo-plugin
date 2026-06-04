import { useRef } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PluginSDK } from "xiaowo-sdk";
import { API } from "@/api";
import { ExportScopeDialog } from "./ExportScopeDialog";
import type { EpisodeMeta } from "@/types/project";

const DRAFT_PATH_STORAGE_KEY = "arcreel_jianying_draft_path";

const episodes: EpisodeMeta[] = [
  {
    episode: 1,
    title: "第一集",
    script_file: "episode_1.json",
  },
];

function Harness() {
  const anchorRef = useRef<HTMLButtonElement | null>(null);
  return (
    <div>
      <button ref={anchorRef} type="button">
        anchor
      </button>
      <ExportScopeDialog
        open
        onClose={() => {}}
        onSelect={() => {}}
        anchorRef={anchorRef}
        episodes={episodes}
        onJianyingExport={() => {}}
      />
    </div>
  );
}

describe("ExportScopeDialog", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(PluginSDK.dialog.open).mockResolvedValue(null);
  });

  async function openJianyingForm() {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /导出为剪映草稿/ }));
    return {
      user,
      input: screen.getByLabelText("草稿目录路径") as HTMLInputElement,
    };
  }

  it("refreshes and persists the draft path when the backend detects Jianying", async () => {
    localStorage.setItem(DRAFT_PATH_STORAGE_KEY, "D:\\old-draft-root");
    vi.spyOn(API, "detectJianyingDraftRoot").mockResolvedValue("D:\\Jianying\\Drafts");

    const { input } = await openJianyingForm();

    await waitFor(() => {
      expect(input).toHaveValue("D:\\Jianying\\Drafts");
    });
    expect(localStorage.getItem(DRAFT_PATH_STORAGE_KEY)).toBe("D:\\Jianying\\Drafts");
  });

  it("keeps the stored draft path when auto detection returns empty", async () => {
    localStorage.setItem(DRAFT_PATH_STORAGE_KEY, "D:\\manual-draft-root");
    vi.spyOn(API, "detectJianyingDraftRoot").mockResolvedValue("");

    const { input } = await openJianyingForm();

    await waitFor(() => {
      expect(API.detectJianyingDraftRoot).toHaveBeenCalledTimes(1);
    });
    expect(input).toHaveValue("D:\\manual-draft-root");
    expect(localStorage.getItem(DRAFT_PATH_STORAGE_KEY)).toBe("D:\\manual-draft-root");
  });

  it("persists the manually selected draft path immediately", async () => {
    vi.spyOn(API, "detectJianyingDraftRoot").mockResolvedValue("");
    vi.mocked(PluginSDK.dialog.open).mockResolvedValueOnce("D:\\picked-draft-root");

    const { input, user } = await openJianyingForm();
    await user.click(screen.getByRole("button", { name: "选择草稿目录" }));

    await waitFor(() => {
      expect(input).toHaveValue("D:\\picked-draft-root");
    });
    expect(localStorage.getItem(DRAFT_PATH_STORAGE_KEY)).toBe("D:\\picked-draft-root");
  });

  it("does not expose episode readiness checks from the Jianying form", async () => {
    vi.spyOn(API, "detectJianyingDraftRoot").mockResolvedValue("");
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: /导出为剪映草稿/ }));

    expect(screen.queryByRole("button", { name: "检查本集视频完整性" })).not.toBeInTheDocument();
  });
});

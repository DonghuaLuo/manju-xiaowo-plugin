import { describe, expect, it, vi } from "vitest";
import { PluginSDK } from "xiaowo-sdk";
import { API } from "@/api";
import { exportExternalGenerationPackage } from "./external-generation-export";

describe("exportExternalGenerationPackage", () => {
  it("creates the target directory before exporting references when it does not exist", async () => {
    vi.mocked(PluginSDK.fs.exists).mockResolvedValueOnce(false);
    vi.spyOn(API, "getProjectFileLocalPath").mockResolvedValue("D:/project/characters/xiaoyue.png");

    const result = await exportExternalGenerationPackage(
      "demo",
      [{
        index: 1,
        filename: "01_角色_小月.png",
        label: "角色：小月",
        path: "characters/xiaoyue.png",
        url: "/api/v1/files/demo/characters/xiaoyue.png",
      }],
      "分镜图生成提示词",
      "D:/exports/new-folder",
    );

    expect(PluginSDK.fs.createDir).toHaveBeenCalledWith("D:/exports/new-folder", true);
    expect(PluginSDK.fs.copyFile).toHaveBeenCalledWith(
      "D:/project/characters/xiaoyue.png",
      "D:/exports/new-folder/01_角色_小月.png",
    );
    expect(PluginSDK.fs.writeTextFile).toHaveBeenCalledWith(
      "D:/exports/new-folder/00_外部生成提示词.txt",
      "分镜图生成提示词",
      false,
    );
    expect(result.failed).toHaveLength(0);
    expect(result.copiedCount).toBe(1);
  });
});

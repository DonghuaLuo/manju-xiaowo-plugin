import { beforeEach, describe, expect, it, vi } from "vitest";
import { PluginSDK } from "xiaowo-sdk";
import {
  __resetStyleThumbnailResourceCacheForTests,
  getStyleThumbnailDevUrl,
  resolveStyleThumbnailUrl,
} from "./style-thumbnails";

type TestWindow = Window & typeof globalThis & {
  __TAURI__?: {
    core?: {
      invoke?: unknown;
      convertFileSrc?: unknown;
    };
  };
};

describe("style thumbnail resource urls", () => {
  beforeEach(() => {
    __resetStyleThumbnailResourceCacheForTests();
    delete (window as TestWindow).__TAURI__;
    vi.clearAllMocks();
  });

  it("uses the Vite-only dev URL when no Tauri bridge is available", async () => {
    await expect(resolveStyleThumbnailUrl("live_cinematic_ancient.png")).resolves.toBe(
      "/style-thumbnails/live_cinematic_ancient.png",
    );
    expect(PluginSDK.getInfo).not.toHaveBeenCalled();
  });

  it("converts backend public resources through PluginSDK.convertFileSrc", async () => {
    (window as TestWindow).__TAURI__ = {
      core: {
        invoke: vi.fn(),
        convertFileSrc: vi.fn(),
      },
    };
    vi.mocked(PluginSDK.getInfo).mockResolvedValue({
      manifest: { id: "manju", title: "Manju", version: "1.00" },
      window_scale: "100",
      language: "zh",
      plugin_dir: "D:\\rust_app\\xiaowo\\plugins\\manju",
    });
    vi.mocked(PluginSDK.convertFileSrc).mockImplementation((filePath: string) => `asset://localhost/${filePath}`);

    await expect(resolveStyleThumbnailUrl("live_cinematic_ancient.png")).resolves.toBe(
      "asset://localhost/D:/rust_app/xiaowo/plugins/manju/backend/public/style-thumbnails/live_cinematic_ancient.png",
    );
    expect(PluginSDK.convertFileSrc).toHaveBeenCalledWith(
      "D:/rust_app/xiaowo/plugins/manju/backend/public/style-thumbnails/live_cinematic_ancient.png",
    );
  });

  it("rejects unsafe thumbnail names", () => {
    expect(getStyleThumbnailDevUrl("../secret.png")).toBeNull();
  });
});

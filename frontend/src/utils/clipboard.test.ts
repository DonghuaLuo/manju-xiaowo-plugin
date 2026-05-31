import { describe, expect, it, vi } from "vitest";
import { PluginSDK } from "xiaowo-sdk";
import { copyText } from "./clipboard";

describe("copyText", () => {
  it("uses the desktop clipboard before browser clipboard APIs", async () => {
    const browserWriteText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: browserWriteText },
    });

    await copyText("外部生成提示词");

    expect(PluginSDK.clipboard.writeText).toHaveBeenCalledWith("外部生成提示词");
    expect(browserWriteText).not.toHaveBeenCalled();
  });

  it("falls back to browser clipboard when the desktop clipboard is unavailable", async () => {
    vi.mocked(PluginSDK.clipboard.writeText).mockRejectedValueOnce(new Error("bridge unavailable"));
    const browserWriteText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: browserWriteText },
    });

    await copyText("外部生成提示词");

    expect(PluginSDK.clipboard.writeText).toHaveBeenCalledWith("外部生成提示词");
    expect(browserWriteText).toHaveBeenCalledWith("外部生成提示词");
  });
});

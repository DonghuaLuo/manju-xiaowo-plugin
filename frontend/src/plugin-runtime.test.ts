import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const callBackendMock = vi.hoisted(() => vi.fn());

vi.mock("xiaowo-sdk", () => ({
  PluginSDK: {
    callBackend: callBackendMock,
    onBackendEvent: vi.fn(),
    offBackendEvent: vi.fn(),
  },
}));

const flushPromises = async () => {
  await new Promise((resolve) => setTimeout(resolve, 0));
};

describe("plugin runtime media adapter", () => {
  let originalFetch: typeof globalThis.fetch;
  let originalEventSource: typeof globalThis.EventSource;
  let originalSetAttribute: typeof Element.prototype.setAttribute;
  let originalImageSrc: PropertyDescriptor | undefined;
  let originalMediaSrc: PropertyDescriptor | undefined;
  let originalSourceSrc: PropertyDescriptor | undefined;

  beforeEach(async () => {
    originalFetch = globalThis.fetch;
    originalEventSource = globalThis.EventSource;
    originalSetAttribute = Element.prototype.setAttribute;
    originalImageSrc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src");
    originalMediaSrc = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, "src");
    originalSourceSrc = Object.getOwnPropertyDescriptor(HTMLSourceElement.prototype, "src");
    vi.resetModules();
    callBackendMock.mockReset();
    callBackendMock.mockResolvedValue({
      success: true,
      content: {
        kind: "binary",
        base64: btoa("image"),
        mimeType: "image/png",
      },
    });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:http://localhost/ipc-media");
    await import("./plugin-runtime");
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    globalThis.EventSource = originalEventSource;
    Element.prototype.setAttribute = originalSetAttribute;
    if (originalImageSrc) Object.defineProperty(HTMLImageElement.prototype, "src", originalImageSrc);
    if (originalMediaSrc) Object.defineProperty(HTMLMediaElement.prototype, "src", originalMediaSrc);
    if (originalSourceSrc) Object.defineProperty(HTMLSourceElement.prototype, "src", originalSourceSrc);
    vi.restoreAllMocks();
  });

  it("uses a transparent placeholder while converting an API image to a blob URL", async () => {
    const { installPluginRuntimeAdapters } = await import("./plugin-runtime");
    installPluginRuntimeAdapters();

    const image = document.createElement("img");
    image.src = "/api/v1/files/蛇瞳/characters/苏婉.png?v=1";

    expect(image.getAttribute("src")).toMatch(/^data:image\/gif;base64,/);
  });

  it("keeps the current blob visible while replacing it with another API image", async () => {
    const { installPluginRuntimeAdapters } = await import("./plugin-runtime");
    installPluginRuntimeAdapters();

    const image = document.createElement("img");
    image.src = "blob:old-media";
    image.src = "/api/v1/files/蛇瞳/characters/奶奶.png?v=2";

    expect(image.getAttribute("src")).toBe("blob:old-media");
  });

  it("reuses cached API image blobs across remounted image elements", async () => {
    const { installPluginRuntimeAdapters } = await import("./plugin-runtime");
    installPluginRuntimeAdapters();

    const first = document.createElement("img");
    first.src = "/api/v1/files/蛇瞳/characters/苏婉.png?v=1";
    await flushPromises();

    const second = document.createElement("img");
    second.src = "/api/v1/files/蛇瞳/characters/苏婉.png?v=1";

    expect(first.getAttribute("src")).toBe("blob:http://localhost/ipc-media");
    expect(second.getAttribute("src")).toBe("blob:http://localhost/ipc-media");
    expect(callBackendMock).toHaveBeenCalledTimes(1);
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("shares one in-flight backend request for simultaneous API image loads", async () => {
    let resolveBackend: (value: unknown) => void = () => {};
    callBackendMock.mockReturnValue(
      new Promise((resolve) => {
        resolveBackend = resolve;
      }),
    );
    const { installPluginRuntimeAdapters } = await import("./plugin-runtime");
    installPluginRuntimeAdapters();

    const first = document.createElement("img");
    const second = document.createElement("img");
    first.src = "/api/v1/files/蛇瞳/characters/奶奶.png?v=2";
    second.src = "/api/v1/files/蛇瞳/characters/奶奶.png?v=2";

    await flushPromises();

    expect(callBackendMock).toHaveBeenCalledTimes(1);

    resolveBackend({
      success: true,
      content: {
        kind: "binary",
        base64: btoa("image"),
        mimeType: "image/png",
      },
    });
    await flushPromises();

    expect(first.getAttribute("src")).toBe("blob:http://localhost/ipc-media");
    expect(second.getAttribute("src")).toBe("blob:http://localhost/ipc-media");
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("ignores a stale blob conversion after the media src changes", async () => {
    let resolveBackend: (value: unknown) => void = () => {};
    callBackendMock.mockReturnValue(
      new Promise((resolve) => {
        resolveBackend = resolve;
      }),
    );
    const { installPluginRuntimeAdapters } = await import("./plugin-runtime");
    installPluginRuntimeAdapters();

    const image = document.createElement("img");
    image.src = "/api/v1/files/蛇瞳/characters/苏婉.png?v=1";
    image.src = "";
    resolveBackend({
      success: true,
      content: {
        kind: "binary",
        base64: btoa("image"),
        mimeType: "image/png",
      },
    });
    await flushPromises();

    expect(image.getAttribute("src")).toBe("");
  });
});

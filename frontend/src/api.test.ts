import { beforeEach, describe, expect, it, vi } from "vitest";
import { PluginSDK } from "xiaowo-sdk";
import { API, __resetLocalAssetRootsForTests } from "@/api";

type TestWindow = Window & typeof globalThis & {
  __TAURI__?: {
    core?: {
      invoke?: unknown;
      convertFileSrc?: unknown;
    };
  };
};

describe("API style template media URLs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    __resetLocalAssetRootsForTests();
    (window as TestWindow).__TAURI__ = {
      core: {
        invoke: vi.fn(),
        convertFileSrc: vi.fn(),
      },
    };
  });

  it("maps favorite style thumbnail HTTP compatibility URLs to local desktop files", async () => {
    vi.mocked(PluginSDK.callBackend).mockImplementation(async (method: string) => {
      if (method === "manju_api_get_asset_roots") {
        return { projects_root: "D:\\manju-data\\projects" };
      }
      if (method === "manju_api_get_style_templates") {
        return {
          success: true,
          content: {
            kind: "json",
            value: {
              success: true,
              templates: [
                {
                  id: "favorite_noir",
                  category: "favorite",
                  prompt: "manual noir lighting",
                  thumbnail_file: "favorite_noir.png",
                  thumbnail_url: "/api/v1/style-templates/favorites/favorite_noir.png",
                },
              ],
            },
          },
        };
      }
      throw new Error(`unexpected backend method: ${method}`);
    });

    const result = await API.getStyleTemplates();

    expect(result.templates[0]?.thumbnail_url).toBe(
      "asset://localhost/D:/manju-data/projects/_style_favorites/images/favorite_noir.png",
    );
  });
});

describe("API desktop IPC payloads", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    __resetLocalAssetRootsForTests();
    (window as TestWindow).__TAURI__ = {
      core: {
        invoke: vi.fn(),
        convertFileSrc: vi.fn(),
      },
    };
  });

  it("sends direct query payloads without WebUI resource fields", async () => {
    vi.mocked(PluginSDK.callBackend).mockImplementation(async (method: string) => {
      if (method === "manju_api_get_asset_roots") {
        return { projects_root: "D:\\manju-data\\projects" };
      }
      if (method === "manju_api_list_projects") {
        return {
          success: true,
          content: {
            kind: "json",
            value: { projects: [] },
          },
        };
      }
      throw new Error(`unexpected backend method: ${method}`);
    });

    await API.listProjects({ check_extmodel: true });

    const payload = vi.mocked(PluginSDK.callBackend).mock.calls.find(
      ([method]) => method === "manju_api_list_projects",
    )?.[1] as Record<string, unknown>;
    expect(payload).toMatchObject({
      pathParams: {},
      query: { check_extmodel: ["true"] },
    });
    expect(payload).not.toHaveProperty("operation");
    expect(payload).not.toHaveProperty("resource");
  });

  it("sends decoded path params without WebUI resource fields", async () => {
    vi.mocked(PluginSDK.callBackend).mockImplementation(async (method: string) => {
      if (method === "manju_api_get_video_capabilities") {
        return {
          success: true,
          content: {
            kind: "json",
            value: {},
          },
        };
      }
      throw new Error(`unexpected backend method: ${method}`);
    });

    await API.getVideoCapabilities("demo project");

    const payload = vi.mocked(PluginSDK.callBackend).mock.calls.find(
      ([method]) => method === "manju_api_get_video_capabilities",
    )?.[1] as Record<string, unknown>;
    expect(payload).toMatchObject({
      pathParams: { name: "demo project" },
      query: {},
    });
    expect(payload).not.toHaveProperty("operation");
    expect(payload).not.toHaveProperty("resource");
  });
});

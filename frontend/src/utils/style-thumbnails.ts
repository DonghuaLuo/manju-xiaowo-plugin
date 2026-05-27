import { PluginSDK } from "xiaowo-sdk";

const STYLE_THUMBNAIL_RESOURCE_DIR = "backend/public/style-thumbnails";
const STYLE_THUMBNAIL_DEV_PREFIX = "/style-thumbnails";

type TauriBridgeWindow = Window & typeof globalThis & {
  __TAURI__?: {
    core?: {
      invoke?: unknown;
      convertFileSrc?: unknown;
    };
  };
};

let pluginResourceRoot: string | null | undefined;
let pluginResourceRootPromise: Promise<string | null> | null = null;

function hasTauriBridge(): boolean {
  if (typeof window === "undefined") return false;
  const tauriWindow = window as TauriBridgeWindow;
  return (
    typeof tauriWindow.__TAURI__?.core?.invoke === "function"
    && typeof tauriWindow.__TAURI__?.core?.convertFileSrc === "function"
  );
}

function normalizeLocalPath(path: string): string {
  return path.replace(/\\/g, "/").replace(/\/+$/, "");
}

function cleanRelativePath(path: string): string | null {
  const normalized = path.replace(/\\/g, "/").replace(/^\/+/, "");
  const parts = normalized.split("/").filter(Boolean);
  if (parts.some((part) => part === "." || part === "..")) return null;
  return parts.join("/");
}

function joinLocalPath(root: string, ...segments: string[]): string | null {
  const cleaned = segments.map(cleanRelativePath);
  if (cleaned.some((segment) => segment == null)) return null;
  return [normalizeLocalPath(root), ...(cleaned as string[])].filter(Boolean).join("/");
}

export function getStyleThumbnailDevUrl(fileName: string): string | null {
  const cleanFileName = cleanRelativePath(fileName);
  if (!cleanFileName) return null;
  return `${STYLE_THUMBNAIL_DEV_PREFIX}/${cleanFileName}`;
}

async function ensurePluginResourceRoot(): Promise<string | null> {
  if (pluginResourceRoot !== undefined) return pluginResourceRoot;
  if (pluginResourceRootPromise) return pluginResourceRootPromise;
  if (!hasTauriBridge()) return null;

  pluginResourceRootPromise = PluginSDK.getInfo()
    .then((info) => {
      const pluginDir = info.plugin_dir?.trim();
      pluginResourceRoot = pluginDir
        ? joinLocalPath(pluginDir, STYLE_THUMBNAIL_RESOURCE_DIR)
        : null;
      return pluginResourceRoot;
    })
    .catch(() => {
      pluginResourceRoot = null;
      return pluginResourceRoot;
    })
    .finally(() => {
      pluginResourceRootPromise = null;
    });

  return pluginResourceRootPromise;
}

export async function resolveStyleThumbnailUrl(fileName: string): Promise<string | null> {
  const cleanFileName = cleanRelativePath(fileName);
  if (!cleanFileName) return null;
  if (!hasTauriBridge()) return getStyleThumbnailDevUrl(cleanFileName);

  const root = await ensurePluginResourceRoot();
  if (!root) return null;

  const localPath = joinLocalPath(root, cleanFileName);
  return localPath ? PluginSDK.convertFileSrc(localPath) : null;
}

export function __resetStyleThumbnailResourceCacheForTests(): void {
  pluginResourceRoot = undefined;
  pluginResourceRootPromise = null;
}

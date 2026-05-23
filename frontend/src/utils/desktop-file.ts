import { PluginSDK } from "xiaowo-sdk";

export interface DesktopFileRef {
  kind: "desktop-file";
  path: string;
  name: string;
  previewUrl?: string;
  contentType?: string;
}

export interface PickDesktopFileOptions {
  title?: string;
  filters?: { name: string; extensions: string[] }[];
  preview?: boolean;
}

const MIME_BY_EXTENSION: Record<string, string> = {
  ".gif": "image/gif",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".json": "application/json",
  ".md": "text/markdown",
  ".pdf": "application/pdf",
  ".png": "image/png",
  ".txt": "text/plain",
  ".webp": "image/webp",
  ".zip": "application/zip",
};

export type UploadFileInput = File | DesktopFileRef;

interface ReadLocalFileResponse {
  ok: boolean;
  code?: string;
  detail?: string;
  name?: string;
  mimeType?: string;
  size?: number;
  base64?: string;
}

export function isDesktopFileRef(value: unknown): value is DesktopFileRef {
  return Boolean(value)
    && typeof value === "object"
    && (value as { kind?: unknown }).kind === "desktop-file"
    && typeof (value as { path?: unknown }).path === "string";
}

export function getUploadFileName(file: UploadFileInput): string {
  return isDesktopFileRef(file) ? file.name : file.name;
}

function basename(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() || path;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

export function inferContentType(name: string): string | undefined {
  return MIME_BY_EXTENSION[extensionOf(name)];
}

export function desktopFileRefFromPath(
  path: string,
  options: { preview?: boolean } = {},
): DesktopFileRef {
  const name = basename(path);
  return {
    kind: "desktop-file",
    path,
    name,
    previewUrl: options.preview ? PluginSDK.convertFileSrc(path) : undefined,
    contentType: inferContentType(name),
  };
}

export async function pickDesktopFile(
  options: PickDesktopFileOptions = {},
): Promise<DesktopFileRef | null> {
  const selected = await PluginSDK.dialog.open({
    title: options.title,
    multiple: false,
    directory: false,
    filters: options.filters,
  });
  if (!selected || Array.isArray(selected)) return null;

  return desktopFileRefFromPath(selected, { preview: options.preview });
}

export async function readDesktopFileAsDataUrl(
  file: DesktopFileRef,
  maxBytes?: number,
): Promise<{ dataUrl: string; mimeType: string; size: number }> {
  const result = await PluginSDK.callBackend<ReadLocalFileResponse>(
    "arcreel_read_local_file",
    {
      path: file.path,
      filename: file.name,
      contentType: file.contentType,
      maxBytes,
    },
  );
  if (!result.ok || !result.base64) {
    throw new Error(result.detail || `Failed to read local file: ${file.name}`);
  }

  const mimeType = result.mimeType || file.contentType || "application/octet-stream";
  return {
    dataUrl: `data:${mimeType};base64,${result.base64}`,
    mimeType,
    size: result.size ?? 0,
  };
}

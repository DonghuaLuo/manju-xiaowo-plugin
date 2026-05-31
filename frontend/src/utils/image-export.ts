import { PluginSDK } from "xiaowo-sdk";
import { API } from "@/api";

export type ImageDownloadSource =
  | { kind: "project"; projectName: string; path: string }
  | { kind: "global"; path: string }
  | { kind: "local"; path: string };

const INVALID_FILENAME_CHARS = new Set(["<", ">", ":", "\"", "/", "\\", "|", "?", "*"]);

function extensionFromName(name: string): string | null {
  const clean = name.split(/[?#]/)[0] ?? "";
  const match = clean.match(/\.([a-z0-9]+)$/i);
  return match ? match[1].toLowerCase() : null;
}

function filenameFromPath(path: string): string | null {
  const clean = path.split(/[?#]/)[0] ?? "";
  const last = clean.split(/[\\/]/).filter(Boolean).pop();
  if (!last) return null;
  try {
    return decodeURIComponent(last);
  } catch {
    return last;
  }
}

function sanitizeBaseName(value: string): string {
  const trimmed = value.trim().replace(/\.[a-z0-9]+$/i, "");
  const safe = Array.from(trimmed, (char) =>
    char.charCodeAt(0) < 32 || INVALID_FILENAME_CHARS.has(char) ? "_" : char,
  ).join("").replace(/\s+/g, " ");
  return safe || `manju-image-${Date.now()}`;
}

async function resolveDownloadSourcePath(source: ImageDownloadSource): Promise<string | null> {
  if (source.kind === "project") {
    return API.getProjectFileLocalPath(source.projectName, source.path);
  }
  if (source.kind === "global") {
    return API.getGlobalAssetLocalPath(source.path);
  }
  return source.path;
}

async function fetchBlob(src: string): Promise<Blob> {
  const response = await fetch(src);
  if (!response.ok) {
    throw new Error(`图片读取失败：${response.status}`);
  }
  return response.blob();
}

async function blobToPng(blob: Blob): Promise<Blob> {
  if (blob.type === "image/png") return blob;
  const bitmap = await createImageBitmap(blob);
  try {
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("无法创建图片画布");
    ctx.drawImage(bitmap, 0, 0);
    const png = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/png"),
    );
    if (!png) throw new Error("图片转换失败");
    return png;
  } finally {
    bitmap.close();
  }
}

export async function copyImageToClipboard(src: string): Promise<void> {
  if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
    throw new Error("当前环境不支持复制图片到剪贴板");
  }
  const blob = await fetchBlob(src);
  const png = await blobToPng(blob);
  await navigator.clipboard.write([
    new ClipboardItem({
      "image/png": png,
    }),
  ]);
}

export async function downloadImageWithDialog(
  source: ImageDownloadSource,
  fallbackName: string,
): Promise<string | null> {
  const sourcePath = await resolveDownloadSourcePath(source);
  if (!sourcePath) {
    throw new Error("缺少可下载的本地图片文件路径");
  }
  const sourceName = filenameFromPath(source.path) ?? fallbackName;
  const ext =
    extensionFromName(sourceName) ??
    "png";
  const savePath = await PluginSDK.dialog.save({
    title: "保存图片",
    defaultPath: `${sanitizeBaseName(sourceName)}.${ext}`,
    filters: [
      {
        name: "Images",
        extensions: ["png", "jpg", "jpeg", "webp", "gif"],
      },
    ],
  });
  if (!savePath) return null;

  await PluginSDK.fs.copyFile(sourcePath, savePath);
  return savePath;
}

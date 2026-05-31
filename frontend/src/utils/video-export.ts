import { PluginSDK } from "xiaowo-sdk";
import { API } from "@/api";

const INVALID_FILENAME_CHARS = new Set(["<", ">", ":", "\"", "/", "\\", "|", "?", "*"]);

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
  return safe || `manju-video-${Date.now()}`;
}

function defaultVideoFileName(assetPath: string, fallbackName: string): string {
  const sourceName = filenameFromPath(assetPath) ?? fallbackName;
  const ext = sourceName.match(/\.([a-z0-9]+)$/i)?.[1]?.toLowerCase() ?? "mp4";
  return `${sanitizeBaseName(sourceName)}.${ext}`;
}

export async function downloadProjectVideoWithDialog(
  projectName: string,
  assetPath: string,
  fallbackName: string,
): Promise<string | null> {
  const savePath = await PluginSDK.dialog.save({
    title: "保存视频",
    defaultPath: defaultVideoFileName(assetPath, fallbackName),
    filters: [{ name: "MP4 Video", extensions: ["mp4"] }],
  });
  if (!savePath) return null;

  const sourcePath = await API.getProjectFileLocalPath(projectName, assetPath);
  if (!sourcePath) {
    throw new Error("缺少可下载的本地视频文件路径");
  }

  await PluginSDK.fs.copyFile(sourcePath, savePath);
  return savePath;
}

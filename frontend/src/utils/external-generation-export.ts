import { PluginSDK } from "xiaowo-sdk";
import { API, type ExternalGenerationReference } from "@/api";

export interface ExternalReferenceExportFailure {
  filename: string;
  reason: string;
}

export interface ExternalGenerationExportResult {
  copiedCount: number;
  failed: ExternalReferenceExportFailure[];
  promptPath?: string;
  promptWriteError?: string;
}

const INVALID_FILENAME_CHARS = new Set(["<", ">", ":", "：", "\"", "/", "\\", "|", "?", "*"]);

function messageFromError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function safeFilename(value: string | undefined, fallback: string): string {
  const raw = (value || fallback).trim();
  const normalized = Array.from(raw, (char) => (
    char.charCodeAt(0) < 32 || INVALID_FILENAME_CHARS.has(char) ? "_" : char
  )).join("");
  const safe = normalized
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^[ ._]+|[ ._]+$/g, "");
  return safe || fallback;
}

function extensionOf(path: string | undefined): string {
  const match = path?.match(/(\.[a-z0-9]+)(?:[?#].*)?$/i);
  const ext = match?.[1]?.toLowerCase();
  if (ext === ".jpg" || ext === ".jpeg" || ext === ".png" || ext === ".webp") return ext;
  return ".png";
}

function fallbackReferenceFilename(reference: ExternalGenerationReference, index: number): string {
  const refIndex = reference.index || index;
  const stem = safeFilename(reference.label, "参考图");
  return `${String(refIndex).padStart(2, "0")}_${stem}${extensionOf(reference.path)}`;
}

function referenceFilename(reference: ExternalGenerationReference, index: number): string {
  return safeFilename(reference.filename, fallbackReferenceFilename(reference, index));
}

async function ensureTargetDirectory(targetDirectory: string): Promise<void> {
  const exists = await PluginSDK.fs.exists(targetDirectory).catch(() => false);
  if (!exists) {
    await PluginSDK.fs.createDir(targetDirectory, true);
    return;
  }

  const isDirectory = await PluginSDK.fs.isDir(targetDirectory).catch(() => true);
  if (!isDirectory) {
    throw new Error("目标路径不是目录");
  }
}

export async function exportExternalGenerationPackage(
  projectName: string,
  references: ExternalGenerationReference[],
  prompt: string,
  targetDirectory: string,
): Promise<ExternalGenerationExportResult> {
  await ensureTargetDirectory(targetDirectory);

  const failed: ExternalReferenceExportFailure[] = [];
  let copiedCount = 0;

  for (const [index, reference] of references.entries()) {
    const filename = referenceFilename(reference, index + 1);
    try {
      const sourcePath = await API.getProjectFileLocalPath(projectName, reference.path);
      if (!sourcePath) {
        failed.push({ filename, reason: "无法定位源文件" });
        continue;
      }
      const targetPath = await PluginSDK.path.join(targetDirectory, filename);
      await PluginSDK.fs.copyFile(sourcePath, targetPath);
      copiedCount += 1;
    } catch (error) {
      failed.push({ filename, reason: messageFromError(error) });
    }
  }

  let promptPath: string | undefined;
  let promptWriteError: string | undefined;
  try {
    promptPath = await PluginSDK.path.join(targetDirectory, "00_外部生成提示词.txt");
    await PluginSDK.fs.writeTextFile(promptPath, prompt, false);
  } catch (error) {
    promptWriteError = messageFromError(error);
    promptPath = undefined;
  }

  return { copiedCount, failed, promptPath, promptWriteError };
}

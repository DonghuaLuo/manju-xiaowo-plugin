export const SOURCE_FILE_EXTENSIONS = [".txt", ".md", ".docx", ".epub", ".pdf"] as const;

export const SOURCE_FILE_DIALOG_EXTENSIONS = SOURCE_FILE_EXTENSIONS.map((ext) => ext.replace(/^\./, ""));

export const SOURCE_FILE_ACCEPT = SOURCE_FILE_EXTENSIONS.join(",");

export const SOURCE_FILE_FORMAT_LABEL = SOURCE_FILE_DIALOG_EXTENSIONS.map((ext) => ext.toUpperCase()).join(" · ");

export function isSupportedSourceFileName(filename: string): boolean {
  const normalized = filename.trim().toLowerCase();
  return SOURCE_FILE_EXTENSIONS.some((ext) => normalized.endsWith(ext));
}

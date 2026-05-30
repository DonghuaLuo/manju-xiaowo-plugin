import { describe, expect, it } from "vitest";

import {
  SOURCE_FILE_ACCEPT,
  SOURCE_FILE_DIALOG_EXTENSIONS,
  SOURCE_FILE_FORMAT_LABEL,
  isSupportedSourceFileName,
} from "./source-files";

describe("source file helpers", () => {
  it("keeps picker, label, and accept formats on the same extension set", () => {
    expect(SOURCE_FILE_DIALOG_EXTENSIONS).toEqual(["txt", "md", "docx", "epub", "pdf"]);
    expect(SOURCE_FILE_ACCEPT).toBe(".txt,.md,.docx,.epub,.pdf");
    expect(SOURCE_FILE_FORMAT_LABEL).toBe("TXT · MD · DOCX · EPUB · PDF");
  });

  it("accepts supported source file names case-insensitively", () => {
    expect(isSupportedSourceFileName("novel.TXT")).toBe(true);
    expect(isSupportedSourceFileName("outline.md")).toBe(true);
    expect(isSupportedSourceFileName("book.docx")).toBe(true);
    expect(isSupportedSourceFileName("book.epub")).toBe(true);
    expect(isSupportedSourceFileName("scan.pdf")).toBe(true);
  });

  it("rejects unsupported or extensionless names", () => {
    expect(isSupportedSourceFileName("image.png")).toBe(false);
    expect(isSupportedSourceFileName("novel")).toBe(false);
  });
});

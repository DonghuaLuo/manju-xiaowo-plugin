import { describe, expect, it } from "vitest";
import { sanitizeImageSrc } from "./safe-url";

describe("sanitizeImageSrc", () => {
  it("allows Xiaowo/Tauri local asset URLs for desktop previews", () => {
    expect(sanitizeImageSrc("asset://localhost/C:/tmp/cover.png")).toBe(
      "asset://localhost/C:/tmp/cover.png",
    );
  });

  it("keeps data URLs image-only", () => {
    expect(sanitizeImageSrc("data:image/png;base64,abc")).toBe("data:image/png;base64,abc");
    expect(sanitizeImageSrc("data:text/html;base64,abc")).toBeUndefined();
  });
});

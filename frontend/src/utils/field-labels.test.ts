import { describe, expect, it } from "vitest";
import { readableMarkdownTableFieldLabel } from "./field-labels";

describe("readableMarkdownTableFieldLabel", () => {
  it("maps script preprocessing field names to readable labels", () => {
    expect(readableMarkdownTableFieldLabel("scene_id")).toBe("场景编号");
    expect(readableMarkdownTableFieldLabel("duration_seconds")).toBe("预计时长（秒）");
    expect(readableMarkdownTableFieldLabel("first_frame_intent")).toBe("首帧意图");
    expect(readableMarkdownTableFieldLabel("payoff_hook")).toBe("爽点承接");
  });

  it("humanizes unknown snake case fields and preserves already-readable labels", () => {
    expect(readableMarkdownTableFieldLabel("custom_hook_score")).toBe("Custom Hook Score");
    expect(readableMarkdownTableFieldLabel("场景 ID")).toBe("场景 ID");
  });
});

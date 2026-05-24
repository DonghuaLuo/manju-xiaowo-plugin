import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TaskProgressBlock } from "./TaskProgressBlock";

describe("TaskProgressBlock", () => {
  it("hides zero token progress usage", () => {
    render(
      <TaskProgressBlock
        block={{
          type: "task_progress",
          status: "task_progress",
          description: "重试宫格分镜",
          usage: { total_tokens: 0, tool_uses: 1, duration_ms: 100 },
        }}
      />,
    );

    expect(screen.getByText("重试宫格分镜")).toBeInTheDocument();
    expect(screen.queryByText(/tokens:/)).not.toBeInTheDocument();
  });

  it("shows positive token progress usage", () => {
    render(
      <TaskProgressBlock
        block={{
          type: "task_progress",
          status: "task_progress",
          description: "分析素材",
          usage: { total_tokens: 128, tool_uses: 1, duration_ms: 100 },
        }}
      />,
    );

    expect(screen.getByText("分析素材 (tokens: 128)")).toBeInTheDocument();
  });
});

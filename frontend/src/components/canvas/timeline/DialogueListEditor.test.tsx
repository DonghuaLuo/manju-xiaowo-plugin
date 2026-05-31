import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DialogueListEditor } from "./DialogueListEditor";

describe("DialogueListEditor", () => {
  it("adds dialogue with the first referenced character", () => {
    const onChange = vi.fn();

    render(
      <DialogueListEditor
        dialogue={[]}
        speakerOptions={["小月", "阿城"]}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "添加对话" }));

    expect(onChange).toHaveBeenCalledWith([{ speaker: "小月", line: "" }]);
  });

  it("selects speakers from referenced characters", () => {
    const onChange = vi.fn();

    render(
      <DialogueListEditor
        dialogue={[{ speaker: "小月", line: "我们走吧" }]}
        speakerOptions={["小月", "阿城"]}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("combobox", { name: "角色" }));
    fireEvent.click(screen.getByRole("option", { name: "阿城" }));

    expect(onChange).toHaveBeenCalledWith([{ speaker: "阿城", line: "我们走吧" }]);
  });
});

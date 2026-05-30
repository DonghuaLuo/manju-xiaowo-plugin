import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useRef } from "react";
import { TaskHud } from "@/components/task-hud/TaskHud";
import { useAppStore } from "@/stores/app-store";
import { useTasksStore } from "@/stores/tasks-store";
import { makeTask } from "@/test/factories";
import i18n from "@/i18n";

function HostedTaskHud() {
  const anchorRef = useRef<HTMLDivElement>(null);
  return (
    <div>
      <div ref={anchorRef} data-testid="anchor" />
      <TaskHud anchorRef={anchorRef} />
    </div>
  );
}

function resetStores() {
  useAppStore.setState({ taskHudOpen: true });
  useTasksStore.setState({
    tasks: [],
    stats: { queued: 0, running: 0, cancelling: 0, succeeded: 0, failed: 0, cancelled: 0, total: 0 },
  });
}

describe("TaskHud cascade label", () => {
  afterEach(() => {
    useAppStore.setState({ taskHudOpen: false });
    useTasksStore.setState({
      tasks: [],
      stats: { queued: 0, running: 0, cancelling: 0, succeeded: 0, failed: 0, cancelled: 0, total: 0 },
    });
  });

  it("renders cascade label when cancelled_by is cascade", async () => {
    await i18n.changeLanguage("zh");
    resetStores();
    useTasksStore.setState({
      tasks: [
        makeTask({
          task_id: "cascade-1",
          status: "cancelled",
          cancelled_by: "cascade",
          task_type: "video",
          media_type: "video",
        }),
      ],
    });

    render(<HostedTaskHud />);

    expect((await screen.findAllByText("级联")).length).toBeGreaterThan(0);
  });

  it("does not render cascade label for user cancel", async () => {
    await i18n.changeLanguage("zh");
    resetStores();
    useTasksStore.setState({
      tasks: [
        makeTask({
          task_id: "user-1",
          status: "cancelled",
          cancelled_by: "user",
          task_type: "video",
          media_type: "video",
        }),
      ],
    });

    render(<HostedTaskHud />);

    expect(screen.queryByText("级联")).toBeNull();
  });

  it("renders English cascade label after locale switch", async () => {
    await i18n.changeLanguage("en");
    resetStores();
    useTasksStore.setState({
      tasks: [
        makeTask({
          task_id: "cascade-en",
          status: "cancelled",
          cancelled_by: "cascade",
          task_type: "video",
          media_type: "video",
        }),
      ],
    });

    render(<HostedTaskHud />);

    expect((await screen.findAllByText("cascaded")).length).toBeGreaterThan(0);
    await i18n.changeLanguage("zh");
  });
});

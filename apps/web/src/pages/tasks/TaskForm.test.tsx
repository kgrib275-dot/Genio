import { fireEvent, render, screen } from "@testing-library/react";
import type { HumanTask } from "@/lib/api/v5a";
import { TaskForm } from "@/pages/tasks/TaskForm";

const task: HumanTask = {
  id: "t1",
  app_name: "휴가 신청",
  kind: "approval",
  title: "휴가 승인",
  detail: "",
  fields: [],
  assignee_role: null,
  status: "open",
  response: {},
  due_at: null,
  created_at: "2026-11-19T00:00:00Z",
  completed_at: null,
};

describe("TaskForm 승인 링크", () => {
  it("메일의 승인 링크로 오면 안내만 보이고 누르기 전에는 처리하지 않는다", () => {
    const onSubmit = vi.fn();
    render(
      <TaskForm task={task} pending={false} error={null} onSubmit={onSubmit} prefer="approve" />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("승인하려고 오셨네요");
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /승인/ }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ approved: true }));
  });

  it("링크 표시가 없으면 안내가 없다", () => {
    render(<TaskForm task={task} pending={false} error={null} onSubmit={() => undefined} />);
    expect(screen.queryByRole("status")).toBeNull();
  });
});

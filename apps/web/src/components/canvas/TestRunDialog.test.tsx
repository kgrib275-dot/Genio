import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TestRunDialog } from "@/components/canvas/TestRunDialog";
import type { GraphNode } from "@/lib/api/types";
import { useCanvas } from "@/store/canvas";

const inputNode = {
  id: "n1",
  type: "input",
  position: { x: 0, y: 0 },
  data: { fields: [{ key: "message", label: "질문", type: "text" }] },
} as unknown as GraphNode;

function renderDialog(onRun: (i: Record<string, unknown>, o?: { dryRun: boolean }) => void) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <TestRunDialog
        open
        onClose={() => undefined}
        inputNode={inputNode}
        onRun={onRun}
        running={false}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response("[]", { status: 200, headers: { "content-type": "application/json" } }),
    ),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("TestRunDialog 시험 모드", () => {
  it("보내는 단계가 없으면 시험 모드 칸이 없고 dryRun은 false다", () => {
    useCanvas.getState().load("app1", { version: 1, nodes: [inputNode], edges: [], variables: {} });
    const onRun = vi.fn();
    renderDialog(onRun);
    expect(screen.queryByText("시험 모드")).toBeNull();
    fireEvent.submit(document.getElementById("test-run") as HTMLFormElement);
    expect(onRun).toHaveBeenCalledWith({}, { dryRun: false });
  });

  it("서비스 연결 단계가 있으면 기본으로 켜져 있고, 끄면 기억한다", () => {
    const connector = {
      id: "n2",
      type: "connector",
      position: { x: 300, y: 0 },
      data: {},
    } as unknown as GraphNode;
    useCanvas
      .getState()
      .load("app1", { version: 1, nodes: [inputNode, connector], edges: [], variables: {} });
    const onRun = vi.fn();
    renderDialog(onRun);
    const box = screen.getByRole("checkbox");
    expect(box).toBeChecked();
    fireEvent.submit(document.getElementById("test-run") as HTMLFormElement);
    expect(onRun).toHaveBeenLastCalledWith({}, { dryRun: true });
    fireEvent.click(box);
    fireEvent.submit(document.getElementById("test-run") as HTMLFormElement);
    expect(onRun).toHaveBeenLastCalledWith({}, { dryRun: false });
    expect(window.localStorage.getItem("genio.testDryRun")).toBe("0");
  });
});

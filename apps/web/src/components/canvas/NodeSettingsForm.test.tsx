import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NodeSettingsForm } from "@/components/canvas/NodeSettingsPanel";
import { toRjsfUiSchema } from "@/components/canvas/uiSchema";
import type { GraphNode, NodeType } from "@/lib/api/types";

const llmSpec: NodeType = {
  type: "llm",
  label: "AI 응답",
  category: "AI",
  description: "",
  source: "builtin",
  input_schema: {
    type: "object",
    properties: {
      label: { type: "string", title: "이름" },
      temperature: { type: "number", title: "창의성(0~1)", minimum: 0, maximum: 2 },
      system: { type: "string", title: "역할 지시" },
      prompt: { type: "string", title: "프롬프트" },
      output_schema: { type: "object", title: "출력 형식(JSON Schema)" },
    },
    required: ["prompt"],
  },
  output_schema: {},
  ui_schema: {
    system: { "ui:widget": "textarea" },
    prompt: { "ui:widget": "textarea" },
    output_schema: { "ui:widget": "json" },
  },
};

const node: GraphNode = {
  id: "n2",
  type: "llm",
  position: { x: 0, y: 0 },
  data: { label: "분류", prompt: "{{n1.message}}" },
};

describe("NodeSettingsForm", () => {
  it("ui_schema의 json 위젯을 필드로 바꾼다", () => {
    const ui = toRjsfUiSchema(llmSpec);
    expect(ui.output_schema).toEqual({ "ui:field": "json" });
    expect(ui.prompt).toEqual({ "ui:widget": "textarea" });
  });

  it("스키마로 칸을 만들고 고친 값을 넘겨준다", () => {
    const onChange = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <NodeSettingsForm node={node} spec={llmSpec} wsId="ws1" onChange={onChange} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("역할 지시")).toBeInTheDocument();
    expect(screen.getByText("출력 형식(JSON Schema)")).toBeInTheDocument();
    const prompt = screen.getByLabelText(/프롬프트/) as HTMLTextAreaElement;
    expect(prompt.value).toBe("{{n1.message}}");
    fireEvent.change(prompt, { target: { value: "{{n1.message}} 를 분류해" } });
    const last = onChange.mock.calls.at(-1)?.[0] as Record<string, unknown>;
    expect(last.prompt).toBe("{{n1.message}} 를 분류해");
    expect(last.label).toBe("분류");

    const json = screen.getByLabelText("출력 형식(JSON Schema)");
    fireEvent.change(json, { target: { value: '{"type":"object"}' } });
    const after = onChange.mock.calls.at(-1)?.[0] as Record<string, unknown>;
    expect(after.output_schema).toEqual({ type: "object" });
  });
});

// NodeSpec의 ui_schema를 react-jsonschema-form 형식으로 바꾼다.
import type { NodeType } from "@/lib/api/types";

type UiEntry = Record<string, unknown>;

/** 위젯 이름 → rjsf 설정. json은 객체·형식 없는 값도 다뤄야 해서 필드(ui:field)로 쓴다. */
export function toRjsfUiSchema(spec: Pick<NodeType, "ui_schema" | "input_schema">): UiEntry {
  const out: UiEntry = { "ui:submitButtonOptions": { norender: true } };
  const props = (spec.input_schema.properties ?? {}) as Record<string, Record<string, unknown>>;
  for (const [key, raw] of Object.entries(spec.ui_schema ?? {})) {
    const entry = { ...(raw as UiEntry) };
    if (entry["ui:widget"] === "json") {
      delete entry["ui:widget"];
      entry["ui:field"] = "json";
    }
    out[key] = entry;
  }
  // 형식(type)이 없는 속성은 rjsf가 그릴 수 없으므로 JSON 입력으로 받는다.
  for (const [key, prop] of Object.entries(props)) {
    if (prop && prop.type === undefined && !(key in out)) out[key] = { "ui:field": "json" };
    if (prop && prop.type === "object" && !prop.properties && !(key in out)) {
      out[key] = { "ui:field": "json" };
    }
  }
  return out;
}

/** 다른 노드 출력을 참조하는 표현식 목록(설정 패널 도움말). */
export function referenceHints(
  nodes: { id: string; type: string; data: Record<string, unknown> }[],
  exceptId: string,
): string[] {
  const hints: string[] = [];
  for (const n of nodes) {
    if (n.id === exceptId) continue;
    if (n.type === "input") {
      const fields = (n.data.fields as { key?: string }[] | undefined) ?? [];
      for (const f of fields) if (f.key) hints.push(`{{${n.id}.${f.key}}}`);
    } else if (n.type === "llm") {
      hints.push(`{{${n.id}.text}}`);
      const schema = n.data.output_schema as { properties?: Record<string, unknown> } | undefined;
      for (const k of Object.keys(schema?.properties ?? {})) hints.push(`{{${n.id}.${k}}}`);
    } else if (n.type === "knowledge_search") {
      hints.push(`{{${n.id}.context}}`);
    } else if (n.type === "http") {
      hints.push(`{{${n.id}.body}}`);
    } else if (n.type !== "output" && n.type !== "condition") {
      hints.push(`{{${n.id}.…}}`);
    }
  }
  return hints;
}

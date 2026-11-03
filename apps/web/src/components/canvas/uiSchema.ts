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

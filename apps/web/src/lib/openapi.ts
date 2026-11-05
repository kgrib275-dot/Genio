// 공개 API 문서(OpenAPI) 보여 주기용 순수 함수: 묶음별 정리, 스키마 → 표, curl 예시.

export interface OpenApiDoc {
  openapi?: string;
  info?: { title?: string; description?: string; version?: string };
  servers?: { url: string }[];
  tags?: { name: string; description?: string }[];
  paths: Record<string, Record<string, OpenApiOp>>;
  components?: { schemas?: Record<string, Schema> };
}

export interface OpenApiParam {
  name: string;
  in: "path" | "query" | "header" | "cookie";
  required?: boolean;
  description?: string;
  schema?: Schema;
}

export interface OpenApiOp {
  summary?: string;
  description?: string;
  tags?: string[];
  parameters?: OpenApiParam[];
  requestBody?: { required?: boolean; content?: Record<string, { schema?: Schema }> };
  responses?: Record<
    string,
    { description?: string; content?: Record<string, { schema?: Schema }> }
  >;
}

export interface Schema {
  $ref?: string;
  type?: string | string[];
  title?: string;
  description?: string;
  properties?: Record<string, Schema>;
  required?: string[];
  items?: Schema;
  enum?: unknown[];
  anyOf?: Schema[];
  oneOf?: Schema[];
  allOf?: Schema[];
  default?: unknown;
  example?: unknown;
  additionalProperties?: boolean | Schema;
  format?: string;
  maxLength?: number;
  minLength?: number;
}

export interface Endpoint {
  method: string;
  path: string;
  summary: string;
  description: string;
  op: OpenApiOp;
}

export interface TagGroup {
  tag: string;
  description: string;
  endpoints: Endpoint[];
}

const METHOD_ORDER = ["get", "post", "put", "patch", "delete"];

export function resolveRef(doc: OpenApiDoc, schema: Schema | undefined): Schema {
  let cur: Schema = schema ?? {};
  for (let i = 0; i < 8 && cur.$ref; i++) {
    const name = cur.$ref.split("/").pop() ?? "";
    cur = doc.components?.schemas?.[name] ?? {};
  }
  return cur;
}

/** 묶음(태그)마다 경로를 모으고, 검색어에 맞는 것만 남긴다. */
export function groupEndpoints(doc: OpenApiDoc, query = ""): TagGroup[] {
  const q = query.trim().toLowerCase();
  const byTag = new Map<string, Endpoint[]>();
  for (const [path, item] of Object.entries(doc.paths ?? {})) {
    for (const method of METHOD_ORDER) {
      const op = item[method];
      if (!op) continue;
      const summary = op.summary ?? "";
      const description = (op.description ?? "").trim();
      if (q && !`${path} ${method} ${summary} ${description}`.toLowerCase().includes(q)) continue;
      const tag = op.tags?.[0] ?? "기타";
      byTag.set(tag, [...(byTag.get(tag) ?? []), { method, path, summary, description, op }]);
    }
  }
  const order = (doc.tags ?? []).map((t) => t.name);
  return [...byTag.entries()]
    .sort(([a], [b]) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99))
    .map(([tag, endpoints]) => ({
      tag,
      description: doc.tags?.find((t) => t.name === tag)?.description ?? "",
      endpoints,
    }));
}

function typeOf(doc: OpenApiDoc, schema: Schema | undefined): string {
  const s = resolveRef(doc, schema);
  const variants = s.anyOf ?? s.oneOf;
  if (variants) {
    const names = [...new Set(variants.map((v) => typeOf(doc, v)))];
    return names.join(" 또는 ");
  }
  if (s.enum) return s.enum.map((e) => JSON.stringify(e)).join(" | ");
  const t = Array.isArray(s.type) ? s.type.join(" | ") : s.type;
  if (t === "array") return `${typeOf(doc, s.items)}[]`;
  const names: Record<string, string> = {
    string: "글",
    integer: "정수",
    number: "숫자",
    boolean: "참/거짓",
    object: "객체",
    null: "없음",
  };
  return names[t ?? ""] ?? t ?? "값";
}

export interface SchemaRow {
  name: string;
  type: string;
  required: boolean;
  description: string;
}

/** 객체 스키마의 칸들을 표 줄로 펼친다(중첩은 `a.b` 이름, 깊이 3까지). */
export function schemaRows(
  doc: OpenApiDoc,
  schema: Schema | undefined,
  prefix = "",
  depth = 0,
): SchemaRow[] {
  const s = resolveRef(doc, schema);
  const props = s.properties ?? {};
  const req = new Set(s.required ?? []);
  const rows: SchemaRow[] = [];
  for (const [name, raw] of Object.entries(props)) {
    const p = resolveRef(doc, raw);
    const full = prefix ? `${prefix}.${name}` : name;
    const bits = [p.description ?? raw.description ?? ""];
    if (p.maxLength) bits.push(`최대 ${p.maxLength}자`);
    if (p.default !== undefined && p.default !== null && typeof p.default !== "object")
      bits.push(`기본값 ${JSON.stringify(p.default)}`);
    rows.push({
      name: full,
      type: typeOf(doc, raw),
      required: req.has(name),
      description: bits.filter(Boolean).join(" · "),
    });
    const nested = p.type === "object" || p.properties ? p : resolveRef(doc, p.items);
    if (depth < 2 && nested.properties) rows.push(...schemaRows(doc, nested, full, depth + 1));
  }
  return rows;
}

/** 스키마로 예시 값을 만든다(example·default가 있으면 그것을 쓴다). */
export function exampleFromSchema(doc: OpenApiDoc, schema: Schema | undefined, depth = 0): unknown {
  const s = resolveRef(doc, schema);
  if (s.example !== undefined) return s.example;
  if (s.default !== undefined && s.default !== null) return s.default;
  const variants = s.anyOf ?? s.oneOf;
  if (variants) {
    const first = variants.find((v) => resolveRef(doc, v).type !== "null") ?? variants[0];
    return exampleFromSchema(doc, first, depth + 1);
  }
  if (s.enum?.length) return s.enum[0];
  const t = Array.isArray(s.type) ? (s.type.find((x) => x !== "null") ?? "string") : s.type;
  if (t === "object" || s.properties) {
    if (depth > 3) return {};
    const out: Record<string, unknown> = {};
    const req = new Set(s.required ?? []);
    for (const [k, v] of Object.entries(s.properties ?? {})) {
      // 필수 칸과 짧은 칸만 예시에 넣어 읽기 쉽게
      if (req.size === 0 || req.has(k) || Object.keys(out).length < 2)
        out[k] = exampleFromSchema(doc, v, depth + 1);
    }
    return out;
  }
  if (t === "array") return [exampleFromSchema(doc, s.items, depth + 1)];
  if (t === "integer" || t === "number") return 0;
  if (t === "boolean") return false;
  return "글";
}

/** 묶음 이름으로 보는 인증 방법 */
export function authOf(tag: string): { header: string | null; note: string } {
  if (tag.startsWith("서비스 API"))
    return { header: "Authorization: Bearer gk-내_API_키", note: "앱 API 키(gk-…)가 필요해요." };
  if (tag.startsWith("MCP"))
    return {
      header: "Authorization: Bearer gk-내_API_키",
      note: "'MCP 도구' 권한이 있는 키가 필요해요.",
    };
  if (tag.startsWith("외부에서 받기"))
    return { header: null, note: "주소의 비밀 토큰이 인증이에요." };
  return { header: null, note: "공유 주소의 토큰으로 부르고, 앱의 공개 범위·IP 제한을 따라요." };
}

const MCP_BODY = { jsonrpc: "2.0", id: 1, method: "tools/list" };

/** 그대로 복사해 쓸 수 있는 curl 예시 */
export function curlExample(doc: OpenApiDoc, ep: Endpoint, tag: string, origin: string): string {
  const fill = (path: string) => path.replace(/\{([^}]+)\}/g, (_m, n: string) => `<${n}>`);
  let url = origin.replace(/\/$/, "") + fill(ep.path);
  const query = (ep.op.parameters ?? []).filter((p) => p.in === "query" && p.required);
  if (query.length)
    url +=
      "?" + query.map((p) => `${p.name}=${String(exampleFromSchema(doc, p.schema))}`).join("&");
  const lines: string[] = [];
  const sse = ep.path.endsWith("/chat") && ep.method === "post";
  lines.push(`curl ${sse ? "-N " : ""}-X ${ep.method.toUpperCase()} "${url}"`);
  const auth = authOf(tag).header;
  if (auth) lines.push(`  -H "${auth}"`);
  const bodySchema = ep.op.requestBody?.content?.["application/json"]?.schema;
  if (ep.path.endsWith("/service/mcp") && ep.method === "post") {
    lines.push('  -H "Content-Type: application/json"');
    lines.push(`  -d '${JSON.stringify(MCP_BODY)}'`);
  } else if (bodySchema) {
    lines.push('  -H "Content-Type: application/json"');
    lines.push(`  -d '${JSON.stringify(exampleFromSchema(doc, bodySchema), null, 0)}'`);
  } else if (ep.op.requestBody?.content?.["multipart/form-data"]) {
    lines.push('  -F "file=@./문서.pdf"');
  }
  return lines.join(" \\\n");
}

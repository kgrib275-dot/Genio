// v0.8 외부 도구 단계(MCP 도구·API 도구)의 설정 칸: 연결 정보 고르기, 도구 고르기, 도구가 받는 값 칸
import { useState } from "react";
import type { FieldProps, WidgetProps } from "@rjsf/utils";
import { Link } from "react-router-dom";
import { JsonField, type NodeFormContext } from "@/components/canvas/widgets";
import { ValueInput } from "@/components/canvas/ValueInput";
import { useCredentials } from "@/lib/api/resources";
import {
  coerceFieldValue,
  simpleFields,
  useApiToolSet,
  useMcpTools,
  type ApiOperation,
  type ToolField,
} from "@/lib/api/v8tools";

const inputCls =
  "w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500";

function ctxOf(props: WidgetProps | FieldProps): NodeFormContext {
  return (props.formContext ??
    props.registry.formContext ?? { wsId: "", formData: {} }) as NodeFormContext;
}

// ---------------- 연결 정보 고르기 ----------------
function KindSelect({
  props,
  kind,
  placeholder,
  emptyText,
}: {
  props: WidgetProps;
  kind: string;
  placeholder: string;
  emptyText: string;
}) {
  const ctx = ctxOf(props);
  const creds = useCredentials(ctx.wsId);
  const list = (creds.data ?? []).filter((c) => c.connector_key === kind);
  return (
    <div>
      <select
        id={props.id}
        className={inputCls}
        value={(props.value as string | undefined) ?? ""}
        disabled={props.disabled || props.readonly}
        onChange={(e) => props.onChange(e.target.value || undefined)}
      >
        <option value="">{placeholder}</option>
        {list.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      {creds.error ? (
        <p className="mt-1 text-xs text-slate-500">연결 정보 목록을 볼 권한이 없어요.</p>
      ) : (
        list.length === 0 && (
          <p className="mt-1 text-xs text-slate-500">
            {emptyText}{" "}
            <Link to="/connectors" target="_blank" className="font-medium text-indigo-600">
              연결 정보 열기 ↗
            </Link>
          </p>
        )
      )}
    </div>
  );
}

export function McpServerWidget(props: WidgetProps) {
  return (
    <KindSelect
      props={props}
      kind="mcp_server"
      placeholder="MCP 서버 선택"
      emptyText="연결한 MCP 서버가 없어요. 연결 정보 화면에서 'MCP 서버 연결하기'로 추가하세요."
    />
  );
}

export function ApiToolSetWidget(props: WidgetProps) {
  return (
    <KindSelect
      props={props}
      kind="api_tool_set"
      placeholder="API 도구 묶음 선택"
      emptyText="가져온 API 도구가 없어요. 연결 정보 화면에서 'API 도구(OpenAPI) 가져오기'로 추가하세요."
    />
  );
}

// ---------------- MCP 도구 ----------------
export function McpToolWidget(props: WidgetProps) {
  const ctx = ctxOf(props);
  const serverId = ctx.formData.credential_id as string | undefined;
  const tools = useMcpTools(ctx.wsId, serverId);
  const value = (props.value as string | undefined) ?? "";
  const list = tools.data?.tools ?? [];
  const current = list.find((t) => t.name === value);
  return (
    <div className="space-y-1">
      <select
        id={props.id}
        className={inputCls}
        value={value}
        disabled={props.disabled || props.readonly || !serverId}
        onChange={(e) => props.onChange(e.target.value || undefined)}
      >
        <option value="">{serverId ? "도구 선택" : "먼저 MCP 서버를 고르세요"}</option>
        {value && !current && <option value={value}>{value} (서버 목록에 없어요)</option>}
        {list.map((t) => (
          <option key={t.name} value={t.name}>
            {t.name}
          </option>
        ))}
      </select>
      {tools.isLoading && <p className="text-[11px] text-slate-500">도구 목록을 불러오는 중…</p>}
      {tools.data && !tools.data.ok && (
        <p className="text-[11px] text-red-600">{tools.data.message}</p>
      )}
      {tools.error && (
        <p className="text-[11px] text-slate-500">
          도구 목록을 볼 권한이 없거나 불러오지 못했어요.
        </p>
      )}
      {current?.description && (
        <p className="text-[11px] leading-snug text-slate-500">{current.description}</p>
      )}
    </div>
  );
}

// ---------------- 도구가 받는 값 칸 ----------------
type Bag = Record<string, unknown>;

function FieldRow({
  field,
  id,
  value,
  wsId,
  disabled,
  badge,
  onChange,
}: {
  field: ToolField;
  id: string;
  value: unknown;
  wsId: string;
  disabled: boolean;
  badge?: string;
  onChange: (v: unknown) => void;
}) {
  const text = value === undefined || value === null ? "" : String(value);
  return (
    <div className="mb-2.5">
      <label
        htmlFor={id}
        className="mb-1 flex items-center gap-1.5 text-xs font-medium text-slate-600"
      >
        <span>{field.label}</span>
        {field.required && <span className="text-red-500">*</span>}
        {badge && (
          <span className="rounded bg-slate-100 px-1 py-px text-[10px] font-normal text-slate-500">
            {badge}
          </span>
        )}
      </label>
      {field.kind === "choice" || field.kind === "boolean" ? (
        <select
          id={id}
          className={inputCls}
          value={text}
          disabled={disabled}
          onChange={(e) => onChange(coerceFieldValue(field.kind, e.target.value))}
        >
          <option value="">(비움)</option>
          {(field.kind === "boolean" ? ["true", "false"] : field.options).map((o) => (
            <option key={o} value={o}>
              {field.kind === "boolean" ? (o === "true" ? "예" : "아니오") : o}
            </option>
          ))}
        </select>
      ) : (
        <ValueInput
          id={id}
          wsId={wsId}
          value={text || undefined}
          disabled={disabled}
          onChange={(v) => onChange(coerceFieldValue(field.kind, v ?? ""))}
        />
      )}
      {field.description && (
        <p className="mt-0.5 text-[11px] leading-snug text-slate-400">{field.description}</p>
      )}
    </div>
  );
}

function setKey(bag: Bag, key: string, value: unknown): Bag | undefined {
  const rest = Object.fromEntries(Object.entries(bag).filter(([k]) => k !== key));
  const next: Bag = value === undefined ? rest : { ...rest, [key]: value };
  return Object.keys(next).length > 0 ? next : undefined;
}

/** 칸으로 입력할지, JSON 글로 입력할지 고르는 작은 전환 */
function ModeSwitch({ json, onChange }: { json: boolean; onChange: (json: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!json)}
      className="mb-1 text-[11px] font-medium text-indigo-600 hover:underline"
    >
      {json ? "칸으로 입력하기" : "JSON으로 입력하기(고급)"}
    </button>
  );
}

/** mcp_tool의 arguments: 고른 도구의 입력 스키마가 단순하면 칸으로, 아니면 JSON으로 */
export function McpArgsField(props: FieldProps) {
  const ctx = ctxOf(props);
  const tools = useMcpTools(ctx.wsId, ctx.formData.credential_id as string | undefined);
  const tool = tools.data?.tools.find((t) => t.name === ctx.formData.tool);
  const fields = simpleFields(tool?.input_schema);
  const [forceJson, setForceJson] = useState(false);
  const bag = (props.formData ?? {}) as Bag;
  const disabled = Boolean(props.disabled || props.readonly);
  const title = props.schema.title ?? "넘길 값";

  if (!fields || forceJson) {
    return (
      <div>
        {fields && <ModeSwitch json onChange={setForceJson} />}
        <JsonField {...props} />
        {tool && !fields && (
          <p className="-mt-2 mb-2 text-[11px] text-slate-400">
            이 도구의 입력이 복잡해서 JSON으로 적어요. 도구 설명을 참고하세요.
          </p>
        )}
      </div>
    );
  }
  return (
    <div className="mb-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-slate-700">{title}</p>
        <ModeSwitch json={false} onChange={setForceJson} />
      </div>
      {fields.map((f) => (
        <FieldRow
          key={f.name}
          field={f}
          id={`${props.idSchema.$id}_${f.name}`}
          value={bag[f.name]}
          wsId={ctx.wsId}
          disabled={disabled}
          onChange={(v) => props.onChange(setKey(bag, f.name, v))}
        />
      ))}
    </div>
  );
}

// ---------------- API 도구 ----------------
export function ApiOperationWidget(props: WidgetProps) {
  const ctx = ctxOf(props);
  const setId = ctx.formData.tool_set as string | undefined;
  const detail = useApiToolSet(ctx.wsId, setId);
  const value = (props.value as string | undefined) ?? "";
  const ops = detail.data?.operations ?? [];
  const current = ops.find((o) => o.id === value);
  return (
    <div className="space-y-1">
      <select
        id={props.id}
        className={inputCls}
        value={value}
        disabled={props.disabled || props.readonly || !setId}
        onChange={(e) => props.onChange(e.target.value || undefined)}
      >
        <option value="">{setId ? "도구 선택" : "먼저 API 도구 묶음을 고르세요"}</option>
        {value && !current && <option value={value}>{value} (묶음에 없어요)</option>}
        {ops.map((o) => (
          <option key={o.id} value={o.id}>
            {o.method} {o.path}
            {o.summary ? ` — ${o.summary}` : ""}
          </option>
        ))}
      </select>
      {detail.isLoading && <p className="text-[11px] text-slate-500">도구 목록을 불러오는 중…</p>}
      {detail.error && (
        <p className="text-[11px] text-slate-500">
          도구 목록을 볼 권한이 없거나 불러오지 못했어요.
        </p>
      )}
    </div>
  );
}

function paramField(p: ApiOperation["parameters"][number]): ToolField {
  const options = Array.isArray(p.enum) ? p.enum.map(String) : [];
  const t = p.type;
  return {
    name: p.name,
    label: p.name,
    description: p.description,
    required: p.required,
    kind:
      options.length > 0
        ? "choice"
        : t === "integer" || t === "number"
          ? "number"
          : t === "boolean"
            ? "boolean"
            : "text",
    options,
  };
}

const WHERE: Record<string, string> = { path: "주소", query: "검색 조건", header: "헤더" };

/** api_tool의 params: 고른 도구의 주소·검색 조건·헤더 값 칸 */
export function ApiParamsField(props: FieldProps) {
  const ctx = ctxOf(props);
  const detail = useApiToolSet(ctx.wsId, ctx.formData.tool_set as string | undefined);
  const op = detail.data?.operations.find((o) => o.id === ctx.formData.operation);
  const [forceJson, setForceJson] = useState(false);
  const bag = (props.formData ?? {}) as Bag;
  const disabled = Boolean(props.disabled || props.readonly);
  const title = props.schema.title ?? "넘길 값";

  if (!op || forceJson) {
    return (
      <div>
        {op && <ModeSwitch json onChange={setForceJson} />}
        <JsonField {...props} />
      </div>
    );
  }
  if (op.parameters.length === 0) {
    return (
      <p className="mb-3 text-[11px] text-slate-400">
        이 도구는 주소·검색 조건에 넣을 값이 없어요. 필요하면 아래 &apos;보낼 내용&apos;에 적어요.
      </p>
    );
  }
  return (
    <div className="mb-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-slate-700">{title}</p>
        <ModeSwitch json={false} onChange={setForceJson} />
      </div>
      {op.parameters.map((p) => (
        <FieldRow
          key={`${p.in}:${p.name}`}
          field={paramField(p)}
          id={`${props.idSchema.$id}_${p.in}_${p.name}`}
          value={bag[p.name]}
          wsId={ctx.wsId}
          disabled={disabled}
          badge={WHERE[p.in]}
          onChange={(v) => props.onChange(setKey(bag, p.name, v))}
        />
      ))}
    </div>
  );
}

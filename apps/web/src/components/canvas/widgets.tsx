// 단계 설정 폼의 사용자 정의 위젯(설계서 §9: JSON Schema → 폼 자동 생성)
import { useIsDark } from "@/store/theme";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { FieldProps, IconButtonProps, WidgetProps } from "@rjsf/utils";
import { Link } from "react-router-dom";
import { useApps } from "@/lib/api/apps";
import { useConnectorDefinitions, useCredentials, useKnowledgeBases } from "@/lib/api/resources";
import { useDataTables } from "@/lib/api/v4";
import { useCanvas } from "@/store/canvas";
import { RawValueButton, ValueInput } from "@/components/canvas/ValueInput";
import { wantsPicker } from "@/components/canvas/valueRefs";

const MonacoEditor = lazy(() => import("@monaco-editor/react"));

export interface NodeFormContext {
  wsId: string;
  formData: Record<string, unknown>;
}

const inputCls =
  "w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500";

function ctxOf(props: WidgetProps | FieldProps): NodeFormContext {
  return (props.formContext ??
    props.registry.formContext ?? { wsId: "", formData: {} }) as NodeFormContext;
}

export function TextareaWidget(props: WidgetProps) {
  return (
    <ValueInput
      id={props.id}
      multiline
      mono
      wsId={ctxOf(props).wsId}
      value={props.value as string | undefined}
      disabled={props.disabled || props.readonly}
      onChange={(v) => props.onChange(v)}
    />
  );
}

/** 한 줄 글자 칸(rjsf 기본 TextWidget 대신). 값을 넣을 일이 있는 칸에만 '값 끌어오기'를 단다. */
export function ValueTextWidget(props: WidgetProps) {
  const type = (props.schema.type as string | undefined) ?? "string";
  if (type !== "string" || !wantsPicker(props.id) || props.schema.format) {
    return (
      <input
        id={props.id}
        className={inputCls}
        type={type === "number" || type === "integer" ? "number" : "text"}
        value={(props.value as string | number | undefined) ?? ""}
        placeholder={props.placeholder}
        disabled={props.disabled || props.readonly}
        onChange={(e) => {
          const v = e.target.value;
          if (v === "") return props.onChange(undefined);
          props.onChange(type === "number" || type === "integer" ? Number(v) : v);
        }}
      />
    );
  }
  return (
    <ValueInput
      id={props.id}
      wsId={ctxOf(props).wsId}
      value={props.value as string | undefined}
      placeholder={props.placeholder}
      disabled={props.disabled || props.readonly}
      onChange={(v) => props.onChange(v)}
    />
  );
}

export function CodeWidget(props: WidgetProps) {
  const dark = useIsDark();
  return (
    <div className="overflow-hidden rounded-md border border-slate-300">
      <Suspense fallback={<TextareaWidget {...props} />}>
        <MonacoEditor
          height="220px"
          defaultLanguage="python"
          theme={dark ? "vs-dark" : "light"}
          value={(props.value as string | undefined) ?? ""}
          onChange={(v) => props.onChange(v ?? "")}
          options={{ minimap: { enabled: false }, fontSize: 12, scrollBeyondLastLine: false }}
        />
      </Suspense>
    </div>
  );
}

export function KbWidget(props: WidgetProps) {
  const kbs = useKnowledgeBases(ctxOf(props).wsId);
  return (
    <select
      id={props.id}
      className={inputCls}
      value={(props.value as string | undefined) ?? ""}
      onChange={(e) => props.onChange(e.target.value || undefined)}
    >
      <option value="">지식베이스 선택</option>
      {(kbs.data ?? []).map((kb) => (
        <option key={kb.id} value={kb.id}>
          {kb.name} (문서 {kb.document_count}개)
        </option>
      ))}
    </select>
  );
}

/** 다른 앱 실행 단계: 같은 워크스페이스의 다른 앱(지금 앱 제외) */
export function AppWidget(props: WidgetProps) {
  const apps = useApps(ctxOf(props).wsId);
  const current = useCanvas((s) => s.appId);
  const list = (apps.data ?? []).filter((a) => a.id !== current);
  return (
    <div className="space-y-1">
      <select
        id={props.id}
        className={inputCls}
        value={(props.value as string | undefined) ?? ""}
        disabled={props.disabled || props.readonly}
        onChange={(e) => props.onChange(e.target.value || undefined)}
      >
        <option value="">실행할 앱 선택</option>
        {list.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name}
            {a.latest_version ? ` (버전 ${a.latest_version})` : " (저장한 버전 없음)"}
          </option>
        ))}
      </select>
      {apps.data && list.length === 0 && (
        <p className="text-[11px] text-slate-500">
          다른 앱이 없어요. 대시보드에서 앱을 먼저 만드세요.
        </p>
      )}
    </div>
  );
}

/** 데이터 표 단계: 워크스페이스의 데이터 표 */
export function DataTableWidget(props: WidgetProps) {
  const tables = useDataTables(ctxOf(props).wsId);
  return (
    <div className="space-y-1">
      <select
        id={props.id}
        className={inputCls}
        value={(props.value as string | undefined) ?? ""}
        disabled={props.disabled || props.readonly}
        onChange={(e) => props.onChange(e.target.value || undefined)}
      >
        <option value="">데이터 표 선택</option>
        {(tables.data ?? []).map((t) => (
          <option key={t.id} value={t.id}>
            {t.name} ({t.row_count}행)
          </option>
        ))}
      </select>
      <Link
        to="/data"
        target="_blank"
        className="text-[11px] font-medium text-indigo-600 hover:underline"
      >
        데이터 표 만들기·보기 ↗
      </Link>
    </div>
  );
}

export function ConnectorWidget(props: WidgetProps) {
  const defs = useConnectorDefinitions(ctxOf(props).wsId);
  return (
    <select
      id={props.id}
      className={inputCls}
      value={(props.value as string | undefined) ?? ""}
      onChange={(e) => props.onChange(e.target.value || undefined)}
    >
      <option value="">서비스 선택</option>
      {(defs.data ?? []).map((d) => (
        <option key={d.id} value={d.key}>
          {d.name}
        </option>
      ))}
    </select>
  );
}

export function CredentialWidget(props: WidgetProps) {
  const ctx = ctxOf(props);
  const creds = useCredentials(ctx.wsId);
  const connector = ctx.formData.connector as string | undefined;
  const list = (creds.data ?? []).filter((c) => !connector || c.connector_key === connector);
  return (
    <div>
      <select
        id={props.id}
        className={inputCls}
        value={(props.value as string | undefined) ?? ""}
        onChange={(e) => props.onChange(e.target.value || undefined)}
      >
        <option value="">연결 정보 선택</option>
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
            등록된 연결 정보가 없어요. 관리자가 &apos;연결 정보&apos; 메뉴에서 등록할 수 있어요.
          </p>
        )
      )}
    </div>
  );
}

export function ConnectorActionWidget(props: WidgetProps) {
  const ctx = ctxOf(props);
  const defs = useConnectorDefinitions(ctx.wsId);
  const connector = ctx.formData.connector as string | undefined;
  const def = (defs.data ?? []).find((d) => d.key === connector);
  return (
    <select
      id={props.id}
      className={inputCls}
      value={(props.value as string | undefined) ?? ""}
      onChange={(e) => props.onChange(e.target.value || undefined)}
    >
      <option value="">{connector ? "동작 선택" : "먼저 서비스를 고르세요"}</option>
      {(def?.manifest.actions ?? []).map((a) => (
        <option key={a.key} value={a.key}>
          {a.label}
        </option>
      ))}
    </select>
  );
}

/** JSON 값 입력(객체·배열·형식 없는 값). 해석이 안 되면 경고만 보이고 값은 바꾸지 않는다. */
export function JsonField(props: FieldProps) {
  const toText = (v: unknown) => (v === undefined ? "" : JSON.stringify(v, null, 2));
  const [text, setText] = useState(() => toText(props.formData));
  const [bad, setBad] = useState(false);
  const areaRef = useRef<HTMLTextAreaElement | null>(null);

  const apply = (t: string) => {
    setText(t);
    if (!t.trim()) {
      setBad(false);
      props.onChange(undefined);
      return;
    }
    try {
      props.onChange(JSON.parse(t));
      setBad(false);
    } catch {
      setBad(true);
    }
  };

  useEffect(() => {
    setText((prev) => {
      try {
        if (JSON.stringify(JSON.parse(prev || "null")) === JSON.stringify(props.formData ?? null)) {
          return prev;
        }
      } catch {
        return prev;
      }
      return toText(props.formData);
    });
  }, [props.formData]);

  const title = props.schema.title ?? props.name;
  return (
    <div className="mb-3">
      <div className="mb-1 flex items-center justify-between gap-2">
        <label htmlFor={props.idSchema.$id} className="block text-xs font-medium text-slate-600">
          {title}
        </label>
        {!(props.disabled || props.readonly) && (
          <RawValueButton
            wsId={ctxOf(props).wsId}
            onInsert={(token) => {
              const el = areaRef.current;
              const start = el?.selectionStart ?? text.length;
              const end = el?.selectionEnd ?? text.length;
              apply(text.slice(0, start) + token + text.slice(end));
            }}
          />
        )}
      </div>
      <textarea
        id={props.idSchema.$id}
        ref={areaRef}
        className={`${inputCls} min-h-[80px] font-mono text-xs ${bad ? "border-red-400" : ""}`}
        value={text}
        onChange={(e) => apply(e.target.value)}
      />
      {bad && (
        <p className="mt-1 text-xs text-red-600">
          JSON 형식이 맞지 않아요. 따옴표와 괄호를 확인하세요.
        </p>
      )}
    </div>
  );
}

function TextButton({
  label,
  tone,
  props,
}: {
  label: string;
  tone: string;
  props: IconButtonProps;
}) {
  return (
    <button
      type="button"
      onClick={props.onClick}
      disabled={props.disabled}
      className={`${props.className ?? ""} rounded px-2 py-0.5 text-xs font-medium ${tone} hover:bg-slate-100 disabled:opacity-40`}
    >
      {label}
    </button>
  );
}

export function AddButton(props: IconButtonProps) {
  return <TextButton label="+ 추가" tone="text-indigo-600" props={props} />;
}
export function RemoveButton(props: IconButtonProps) {
  return <TextButton label="삭제" tone="text-red-600" props={props} />;
}
export function MoveUpButton(props: IconButtonProps) {
  return <TextButton label="위로" tone="text-slate-500" props={props} />;
}
export function MoveDownButton(props: IconButtonProps) {
  return <TextButton label="아래로" tone="text-slate-500" props={props} />;
}
export function CopyButton(props: IconButtonProps) {
  return <TextButton label="복사" tone="text-slate-500" props={props} />;
}
export function NoSubmitButton() {
  return null;
}

import Form from "@rjsf/core";
import type { RJSFSchema } from "@rjsf/utils";
import validator from "@rjsf/validator-ajv8";
import { useMemo } from "react";
import { CurlImport } from "@/components/canvas/CurlImport";
import { HttpPreview } from "@/components/canvas/HttpPreview";
import { FailureSettings, PinSettings } from "@/components/canvas/FailureSettings";
import { nodeFields, nodeTemplates, nodeWidgets } from "@/components/canvas/formRegistry";
import { withTimingVisibility } from "@/components/canvas/humanTiming";
import { toRjsfUiSchema } from "@/components/canvas/uiSchema";
import type { NodeFormContext } from "@/components/canvas/widgets";
import { NodeTestPanel } from "@/components/canvas/NodeTestPanel";
import { ValueRows } from "@/components/run/ValueInspector";
import { Button } from "@/components/ui/button";
import type { GraphNode, NodeType, RunStep } from "@/lib/api/types";
import { flattenValue } from "@/lib/valueFlatten";

export interface NodeSettingsFormProps {
  node: GraphNode;
  spec: NodeType;
  wsId: string;
  onChange: (data: Record<string, unknown>) => void;
  readOnly?: boolean;
}

/** 처음 쓰는 사람에게는 필요 없는 설정(보통은 그대로 두는 것)은 '고급 설정'으로 접는다. */
const ADVANCED_KEYS: Record<string, string[]> = {
  llm: ["provider", "model", "temperature", "output_schema", "mask_pii", "images"],
  knowledge_search: ["method", "score_threshold", "metadata_filter", "top_k"],
  http: ["headers", "pagination"],
};

/** NodeType.input_schema + ui_schema로 설정 폼을 자동으로 만든다. */
export function NodeSettingsForm({ node, spec, wsId, onChange, readOnly }: NodeSettingsFormProps) {
  const advanced = (ADVANCED_KEYS[spec.type] ?? []).filter(
    (k) => k in ((spec.input_schema as { properties?: object }).properties ?? {}),
  );
  const schema = spec.input_schema as RJSFSchema;
  const props = (schema.properties ?? {}) as NonNullable<RJSFSchema["properties"]>;
  const pick = (keys: string[]): RJSFSchema => ({
    ...schema,
    properties: Object.fromEntries(Object.entries(props).filter(([k]) => keys.includes(k))),
    required: (schema.required ?? []).filter((k) => keys.includes(k)),
  });
  if (advanced.length === 0) {
    return (
      <SettingsPart node={node} spec={spec} wsId={wsId} onChange={onChange} readOnly={readOnly} />
    );
  }
  const basicKeys = Object.keys(props).filter((k) => !advanced.includes(k));
  return (
    <>
      <SettingsPart
        node={node}
        spec={spec}
        wsId={wsId}
        onChange={onChange}
        readOnly={readOnly}
        schema={pick(basicKeys)}
      />
      <details className="mt-3 rounded-lg border border-slate-200">
        <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-slate-700">
          고급 설정 <span className="font-normal text-slate-400">(보통은 그대로 두세요)</span>
        </summary>
        <div className="border-t border-slate-100 px-3 py-2">
          <SettingsPart
            node={node}
            spec={spec}
            wsId={wsId}
            onChange={onChange}
            readOnly={readOnly}
            schema={pick(advanced)}
          />
        </div>
      </details>
    </>
  );
}

function SettingsPart({
  node,
  spec,
  wsId,
  onChange,
  readOnly,
  schema,
}: NodeSettingsFormProps & { schema?: RJSFSchema }) {
  const uiSchema = useMemo(
    () => withTimingVisibility(toRjsfUiSchema(spec), spec.type, node.data),
    [spec, node.data],
  );
  const formContext: NodeFormContext = { wsId, formData: node.data };
  return (
    <Form
      className="genio-form"
      schema={schema ?? (spec.input_schema as RJSFSchema)}
      uiSchema={uiSchema}
      formData={node.data}
      validator={validator}
      widgets={nodeWidgets}
      fields={nodeFields}
      templates={nodeTemplates}
      formContext={formContext}
      disabled={readOnly}
      liveValidate={false}
      showErrorList={false}
      noHtml5Validate
      onChange={(e) =>
        // 이 폼이 맡은 칸만 바꾸고 나머지(다른 폼의 칸, "_"로 시작하는 공통 설정)는 그대로 둔다
        onChange({
          ...node.data,
          ...((e.formData ?? {}) as Record<string, unknown>),
          ...underscoreKeys(node.data),
        })
      }
    />
  );
}

function underscoreKeys(data: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(data).filter(([k]) => k.startsWith("_")));
}

export function NodeSettingsPanel({
  node,
  spec,
  wsId,
  nodes,
  errors,
  onChange,
  onDelete,
  onClose,
  readOnly,
  appId,
  lastStep,
}: {
  node: GraphNode;
  spec: NodeType | undefined;
  wsId: string;
  nodes: GraphNode[];
  errors?: string[];
  onChange: (data: Record<string, unknown>) => void;
  onDelete: () => void;
  onClose: () => void;
  readOnly?: boolean;
  /** 이 단계만 시험할 앱(없으면 시험 영역을 숨긴다) */
  appId?: string;
  /** 방금 한 테스트 실행에서 이 단계가 낸 값 */
  lastStep?: RunStep | null;
}) {
  const hasUpstream = nodes.some((n) => n.id !== node.id);
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between border-b border-slate-200 px-4 py-3">
        <div>
          <p className="text-sm font-semibold">{spec?.label ?? node.type} 설정</p>
          <p className="text-xs text-slate-400">단계 id: {node.id}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 text-slate-400 hover:bg-slate-100"
          aria-label="설정 닫기"
        >
          ✕
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {spec?.description && <p className="mb-3 text-xs text-slate-500">{spec.description}</p>}
        {errors && errors.length > 0 && (
          <div className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
            {errors.map((e, i) => (
              <p key={i}>{e}</p>
            ))}
          </div>
        )}
        {node.disabled && (
          <p className="mb-3 rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
            꺼진 단계예요. 실행할 때 건너뛰고 입력을 그대로 다음 단계로 넘겨요. 캔버스에서 단계를
            고르고 D를 누르면 다시 켜져요.
          </p>
        )}
        {node.type === "http" && !readOnly && (
          <div className="flex flex-wrap gap-2">
            <CurlImport data={node.data} onChange={onChange} />
            <HttpPreview data={node.data} />
          </div>
        )}
        {spec ? (
          <NodeSettingsForm
            node={node}
            spec={spec}
            wsId={wsId}
            onChange={onChange}
            readOnly={readOnly}
          />
        ) : (
          <p className="text-sm text-red-600">
            이 단계 종류({node.type})를 찾을 수 없어요. 마켓에서 해당 아이템을 다시 설치하세요.
          </p>
        )}
        {spec && node.type !== "input" && node.type !== "output" && (
          <FailureSettings key={node.id} data={node.data} onChange={onChange} readOnly={readOnly} />
        )}
        {spec && node.type !== "input" && node.type !== "output" && (
          <PinSettings data={node.data} onChange={onChange} readOnly={readOnly} />
        )}
        {lastStep?.output && Object.keys(lastStep.output).length > 0 && (
          <details className="mt-4 rounded-lg border border-slate-200" open>
            <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-slate-700">
              지난 테스트 실행에서 이 단계가 낸 값
            </summary>
            <div className="border-t border-slate-100">
              <ValueRows nodeId={node.id} rows={flattenValue(lastStep.output)} />
            </div>
          </details>
        )}
        {appId && !readOnly && spec && node.type !== "input" && (
          <NodeTestPanel key={`test-${node.id}`} appId={appId} node={node} />
        )}
        {hasUpstream && !readOnly && (
          <p className="mt-4 rounded bg-slate-50 px-3 py-2 text-xs text-slate-600">
            앞 단계에서 나온 값을 쓰려면 칸 아래 <b>값 끌어오기</b>를 누르세요. 표현식을 직접 쓰고
            싶으면 <b>고급</b>을 켜요.
          </p>
        )}
      </div>
      {!readOnly && (
        <div className="border-t border-slate-200 px-4 py-3">
          <Button variant="outline" size="sm" className="text-red-600" onClick={onDelete}>
            이 단계 삭제
          </Button>
        </div>
      )}
    </div>
  );
}

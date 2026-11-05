// 처리 캔버스에서 칸을 눌렀을 때 아래에 나오는 단계 설정(v0.6 설정 + v0.9 번역·요약·이미지 설명)
import { AlertTriangle, Plus, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/input";
import { useImageEstimate, type Stage } from "@/lib/api/kbcanvas";
import type { ChunkMode } from "@/lib/api/types";
import { MODE_LABEL, usdText } from "@/pages/knowledge/kbCanvasModel";
import { STEP_INFO, formatPairs, parsePairs } from "@/pages/knowledge/pipelineSteps";

const LANGUAGES = [
  "영어",
  "일본어",
  "중국어",
  "한국어",
  "스페인어",
  "프랑스어",
  "독일어",
  "베트남어",
];

function Check({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-slate-700">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function CostNote({ children }: { children: ReactNode }) {
  return (
    <p className="flex gap-1.5 rounded-lg bg-amber-50 px-2.5 py-2 text-xs text-amber-900">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{children}</span>
    </p>
  );
}

function ImageEstimateBox({ kbId, step }: { kbId: string; step: Stage }) {
  const est = useImageEstimate(
    kbId,
    { maxImages: step.max_images ?? 20, minSize: step.min_size ?? 100 },
    step.enabled,
  );
  if (!step.enabled)
    return (
      <p className="text-xs text-slate-500">
        위의 <b>켜기</b>를 눌러야 그림을 설명해요. 켜기 전에는 AI를 부르지 않아요.
      </p>
    );
  if (est.isLoading) return <p className="text-xs text-slate-500">그림 수를 세는 중…</p>;
  const d = est.data;
  if (!d) return null;
  return (
    <div className="space-y-1.5 text-xs">
      <p className="rounded-lg bg-indigo-50 px-2.5 py-2 text-indigo-900">
        문서 {d.scanned}개에서 그림 <b>{d.images}장</b> → 다시 나누면 AI를{" "}
        <b>약 {d.vision_calls}번</b> 불러요. 예상 비용 <b>{usdText(d.estimated_cost_usd)}</b>
        {d.partial && " (앞의 100개 문서만 세었어요)"}
        {d.model && ` · 모델 ${d.model}`}
      </p>
      {!d.model_ok && <CostNote>{d.message.replace("\n", " ")}</CostNote>}
      {d.budget_message && <CostNote>{d.budget_message}</CostNote>}
    </div>
  );
}

export function StepSettings({
  step,
  onChange,
  mode,
  kbId,
}: {
  step: Stage;
  onChange: (s: Stage) => void;
  mode: ChunkMode;
  kbId: string;
}) {
  if (step.type === "clean") {
    const pats = step.remove_patterns ?? [];
    return (
      <div className="space-y-2">
        <div className="grid gap-1.5 sm:grid-cols-2">
          <Check
            label="빈칸·빈 줄 줄이기"
            checked={step.collapse_spaces ?? true}
            onChange={(v) => onChange({ ...step, collapse_spaces: v })}
          />
          <Check
            label="쪽마다 되풀이되는 머리글·바닥글 지우기"
            checked={step.remove_repeated_lines ?? false}
            onChange={(v) => onChange({ ...step, remove_repeated_lines: v })}
          />
          <Check
            label="웹 주소를 [주소]로 가리기"
            checked={step.mask_urls ?? false}
            onChange={(v) => onChange({ ...step, mask_urls: v })}
          />
          <Check
            label="이메일을 [이메일]로 가리기"
            checked={step.mask_emails ?? false}
            onChange={(v) => onChange({ ...step, mask_emails: v })}
          />
        </div>
        <p className="text-xs font-medium text-slate-600">지울 글 패턴(고급, 정규식)</p>
        {pats.map((p, i) => (
          <div key={i} className="flex gap-2">
            <Input
              aria-label={`지울 글 패턴 ${i + 1}`}
              className="font-mono text-xs"
              value={p}
              placeholder="예: 대외비\s*-\s*\d+쪽"
              onChange={(e) =>
                onChange({
                  ...step,
                  remove_patterns: pats.map((x, j) => (j === i ? e.target.value : x)),
                })
              }
            />
            <Button
              size="sm"
              variant="ghost"
              className="h-10 text-slate-400"
              aria-label="패턴 지우기"
              onClick={() => onChange({ ...step, remove_patterns: pats.filter((_, j) => j !== i) })}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
        {pats.length < 10 && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onChange({ ...step, remove_patterns: [...pats, ""] })}
          >
            <Plus className="h-3.5 w-3.5" /> 패턴 추가
          </Button>
        )}
      </div>
    );
  }
  if (step.type === "metadata") {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="모든 문서에 붙일 꼬리표" htmlFor="pl-fixed" hint="예: 출처=사내, 연도=2026">
          <Input
            id="pl-fixed"
            key={formatPairs(step.fixed)}
            defaultValue={formatPairs(step.fixed)}
            onBlur={(e) => onChange({ ...step, fixed: parsePairs(e.target.value) })}
          />
        </Field>
        <Field
          label="파일 이름에서 뽑기(고급)"
          htmlFor="pl-fname"
          hint="예: (?P<부서>[^_]+)_(?P<연도>\d{4}) → 인사_2026.pdf"
        >
          <Input
            id="pl-fname"
            className="font-mono text-xs"
            value={step.filename_pattern ?? ""}
            onChange={(e) => onChange({ ...step, filename_pattern: e.target.value })}
          />
        </Field>
      </div>
    );
  }
  if (step.type === "translate") {
    return (
      <div className="space-y-2">
        <Field label="번역할 언어" htmlFor="pl-lang" hint="목록에 없는 언어는 직접 적어도 돼요.">
          <Input
            id="pl-lang"
            list="pl-lang-options"
            maxLength={30}
            value={step.target_language ?? "영어"}
            onChange={(e) => onChange({ ...step, target_language: e.target.value })}
          />
          <datalist id="pl-lang-options">
            {LANGUAGES.map((l) => (
              <option key={l} value={l} />
            ))}
          </datalist>
        </Field>
        <CostNote>
          조각마다 AI를 불러요(한 번에 최대 200조각까지). 문서가 많으면 비용이 커질 수 있어요.
          질문·답 방식에서는 쓰이지 않아요.
        </CostNote>
      </div>
    );
  }
  if (step.type === "summarize") {
    return (
      <CostNote>
        조각마다 AI가 한 줄 요약을 만들어 검색에 쓰는 글 앞에 붙여요(한 번에 최대 200조각까지).
        검색이 더 정확해질 수 있지만 조각 수만큼 AI를 불러요. 질문·답 방식에서는 쓰이지 않아요.
      </CostNote>
    );
  }
  if (step.type === "image") {
    return (
      <div className="space-y-2">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="문서당 최대 그림 수" htmlFor="pl-maximg" hint="1~20장">
            <Input
              id="pl-maximg"
              type="number"
              min={1}
              max={20}
              value={step.max_images ?? 20}
              onChange={(e) =>
                onChange({
                  ...step,
                  max_images: Math.max(1, Math.min(20, Number(e.target.value) || 1)),
                })
              }
            />
          </Field>
          <Field
            label="이보다 작은 그림은 빼기"
            htmlFor="pl-minimg"
            hint="가로·세로 중 작은 쪽 기준"
          >
            <Select
              id="pl-minimg"
              value={String(step.min_size ?? 100)}
              onChange={(e) => onChange({ ...step, min_size: Number(e.target.value) })}
            >
              {[100, 200, 300, 500].map((v) => (
                <option key={v} value={v}>
                  {v}픽셀
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <p className="text-xs text-slate-500">
          PDF·DOCX·PPTX·XLSX 안의 그림과 올린 그림 파일(PNG·JPG·WEBP)을 AI가 2~3문장으로 설명하고,
          그 설명이 검색에 쓰여요. 같은 그림과 5MB가 넘는 그림은 빼요.
        </p>
        <ImageEstimateBox kbId={kbId} step={step} />
      </div>
    );
  }
  if (step.type === "split") {
    return (
      <p className="text-xs text-slate-500">
        지금 방식: <b>{MODE_LABEL[mode]}</b> (지식베이스 &gt; 설정에서 바꾸거나 위의 '처리 순서
        모음'을 골라요)
      </p>
    );
  }
  return <p className="text-xs text-slate-500">{STEP_INFO[step.type].desc}</p>;
}

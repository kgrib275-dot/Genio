// Dify에서 내보낸 앱 파일(.yml)을 올려 제니오 앱으로 가져오고, 변환 보고서를 보여 준다.
import { AlertTriangle, Ban, CheckCircle2, Download, FileUp, Info } from "lucide-react";
import { useRef, useState, type DragEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import {
  DIFY_MODE_LABEL,
  reportToText,
  useImportDify,
  type DifyImportResult,
  type DifyReport,
} from "@/lib/api/difyImport";
import { cn } from "@/lib/cn";
import { useSession } from "@/store/session";

const GENIO_TYPE_LABEL: Record<string, string> = {
  input: "입력",
  output: "결과",
  llm: "AI 답변",
  condition: "조건 분기",
  http: "웹 요청",
  code: "코드",
  knowledge_search: "지식 검색",
  template: "글 틀",
  question_classifier: "질문 분류",
  parameter_extractor: "값 뽑아내기",
  variable_aggregator: "값 모으기",
  variable_assigner: "대화 값 저장",
  document_extractor: "문서 읽기",
  list_operator: "목록 다루기",
  iteration: "항목마다 반복",
  loop: "되풀이",
  agent: "에이전트",
  approval: "승인",
  ask_person: "사람에게 묻기",
};

function Tile({ n, label, tone }: { n: number; label: string; tone: "ok" | "warn" | "bad" }) {
  const cls = {
    ok: "bg-emerald-50 text-emerald-800",
    warn: "bg-amber-50 text-amber-800",
    bad: "bg-slate-100 text-slate-700",
  }[tone];
  return (
    <div className={cn("rounded-xl px-3 py-2.5 text-center", cls)}>
      <p className="text-xl font-bold leading-none">{n}</p>
      <p className="mt-1 text-[11px] font-medium">{label}</p>
    </div>
  );
}

function Section({
  icon,
  title,
  tone,
  children,
}: {
  icon: ReactNode;
  title: string;
  tone: string;
  children: ReactNode;
}) {
  return (
    <section>
      <h3 className={cn("mb-1.5 flex items-center gap-1.5 text-sm font-semibold", tone)}>
        {icon}
        {title}
      </h3>
      {children}
    </section>
  );
}

/** 변환 보고서: 단계 종류별 목록(JSON 없이 읽는 글) */
export function DifyReportView({ result }: { result: DifyImportResult }) {
  const r: DifyReport = result.report;
  const clean =
    !r.needs_attention.length &&
    !r.unsupported.length &&
    !r.warnings.length &&
    !r.validation_errors.length;
  return (
    <div className="space-y-4" data-testid="dify-report">
      <p className="text-sm text-slate-600">
        <b className="text-slate-900">{result.app.name}</b>을(를) 새 앱(초안)으로 만들었어요. 종류:{" "}
        {DIFY_MODE_LABEL[r.mode] ?? r.mode}
      </p>
      <div className="grid grid-cols-3 gap-2">
        <Tile n={r.stats.converted} label="바뀐 단계" tone="ok" />
        <Tile n={r.stats.needs_attention} label="확인할 곳" tone="warn" />
        <Tile n={r.stats.unsupported} label="옮기지 못한 단계" tone="bad" />
      </div>
      {clean && (
        <p className="flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          <CheckCircle2 className="h-4 w-4 shrink-0" /> 모든 단계가 그대로 옮겨졌어요. 한 번 시험
          실행해 보세요.
        </p>
      )}
      {r.needs_attention.length > 0 && (
        <Section
          icon={<AlertTriangle className="h-4 w-4" />}
          title="확인해 주세요"
          tone="text-amber-700"
        >
          <ul className="space-y-1.5">
            {r.needs_attention.map((i, k) => (
              <li key={k} className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <p className="font-medium">{i.label}</p>
                <p className="text-xs leading-relaxed">{i.message}</p>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {r.unsupported.length > 0 && (
        <Section
          icon={<Ban className="h-4 w-4" />}
          title="옮기지 못한 단계 (꺼 둔 자리로 남겼어요)"
          tone="text-slate-700"
        >
          <ul className="space-y-1.5">
            {r.unsupported.map((i, k) => (
              <li key={k} className="rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-800">
                <p className="font-medium">
                  {i.label}{" "}
                  <span className="rounded bg-white px-1.5 py-0.5 text-[10px] font-normal text-slate-500">
                    Dify {i.dify_type}
                  </span>
                </p>
                <p className="text-xs leading-relaxed text-slate-600">{i.message}</p>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {r.warnings.length > 0 && (
        <Section icon={<Info className="h-4 w-4" />} title="알림" tone="text-slate-700">
          <ul className="list-disc space-y-1 pl-5 text-xs leading-relaxed text-slate-600">
            {r.warnings.map((w, k) => (
              <li key={k}>{w}</li>
            ))}
          </ul>
        </Section>
      )}
      {r.validation_errors.length > 0 && (
        <Section
          icon={<AlertTriangle className="h-4 w-4" />}
          title="빌더에서 고칠 곳"
          tone="text-red-700"
        >
          <ul className="list-disc space-y-1 pl-5 text-xs leading-relaxed text-red-700">
            {r.validation_errors.map((e, k) => (
              <li key={k}>{e.message}</li>
            ))}
          </ul>
        </Section>
      )}
      {r.converted.length > 0 && (
        <details className="rounded-lg border border-slate-200 px-3 py-2 text-sm">
          <summary className="cursor-pointer text-xs font-medium text-slate-600">
            바뀐 단계 {r.converted.length}개 보기
          </summary>
          <ul className="mt-2 space-y-1 text-xs text-slate-600">
            {r.converted.map((i, k) => (
              <li key={k}>
                {i.label} <span className="text-slate-400">(Dify {i.dify_type} →</span>{" "}
                {GENIO_TYPE_LABEL[i.genio_type ?? ""] ?? i.genio_type}
                <span className="text-slate-400">)</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function downloadText(name: string, text: string) {
  const url = URL.createObjectURL(new Blob(["﻿", text], { type: "text/plain;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export function DifyImportDialog({
  open,
  onClose,
  projectId,
}: {
  open: boolean;
  onClose: () => void;
  projectId?: string;
}) {
  const ws = useSession((s) => s.workspaceId);
  const imp = useImportDify(ws);
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [result, setResult] = useState<DifyImportResult | null>(null);

  const upload = (file: File | undefined) => {
    if (!file) return;
    setResult(null);
    imp.mutate({ file, projectId }, { onSuccess: setResult });
  };
  const close = () => {
    setResult(null);
    imp.reset();
    onClose();
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    upload(e.dataTransfer.files?.[0]);
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title={result ? "가져오기 결과" : "Dify에서 가져오기"}
      wide
      footer={
        result ? (
          <>
            <Button
              variant="outline"
              onClick={() =>
                downloadText(
                  `${result.app.name}-가져오기-보고서.txt`,
                  reportToText(result.app.name, result.report),
                )
              }
            >
              <Download className="h-4 w-4" /> 보고서 내려받기
            </Button>
            <Button variant="ghost" onClick={close}>
              닫기
            </Button>
            <Button
              onClick={() => {
                const id = result.app.id;
                close();
                navigate(`/apps/${id}/builder`);
              }}
            >
              빌더에서 열기
            </Button>
          </>
        ) : (
          <Button variant="ghost" onClick={close}>
            닫기
          </Button>
        )
      }
    >
      {result ? (
        <DifyReportView result={result} />
      ) : (
        <div className="space-y-3">
          <p className="text-sm leading-relaxed text-slate-600">
            Dify 앱 화면의 <b>내보내기(DSL)</b>로 받은 <code>.yml</code> 파일을 올리면, 제니오
            흐름으로 바꿔 새 앱(초안)을 만들어요. 옮기지 못하는 부분은 결과 화면에서 알려 드려요.
          </p>
          <input
            ref={fileRef}
            type="file"
            accept=".yml,.yaml,.json,text/yaml"
            className="sr-only"
            aria-label="Dify 앱 파일"
            onChange={(e) => {
              upload(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <div
            role="button"
            tabIndex={0}
            onClick={() => fileRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") fileRef.current?.click();
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={onDrop}
            className={cn(
              "flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-10 text-center transition-colors",
              over
                ? "border-indigo-400 bg-indigo-50"
                : "border-slate-300 bg-slate-50 hover:border-indigo-300 hover:bg-indigo-50/50",
            )}
          >
            <FileUp className="h-8 w-8 text-indigo-500" />
            <p className="text-sm font-medium text-slate-800">
              {imp.isPending ? "바꾸는 중…" : "파일을 끌어다 놓거나 눌러서 고르세요"}
            </p>
            <p className="text-xs text-slate-500">.yml · .yaml · 최대 2MB</p>
          </div>
          <ErrorBox error={imp.error} />
          <p className="text-xs text-slate-500">
            바뀌는 것: 시작·AI 답변·지식 검색·조건·코드·웹 요청·글 틀·질문 분류·값 뽑기·반복·승인
            등. 키와 비밀 값은 옮기지 않아요.
          </p>
        </div>
      )}
    </Dialog>
  );
}

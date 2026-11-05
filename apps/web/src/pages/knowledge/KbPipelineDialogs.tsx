// 질문·답 표 가져오기. 문서 처리 순서 편집은 v0.9부터 처리 캔버스(KbPipelineCanvas.tsx)가 맡는다.
import { useState } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import type { QaColumns } from "@/lib/api/types";
import { useImportQa, useQaColumns } from "@/lib/api/v6kb";

export { PipelineDialog } from "@/pages/knowledge/KbPipelineCanvas";

export function QaImportDialog({ kbId, onClose }: { kbId: string; onClose: () => void }) {
  const columns = useQaColumns(kbId);
  const imp = useImportQa(kbId);
  const [file, setFile] = useState<File | null>(null);
  const [cols, setCols] = useState<QaColumns | null>(null);
  const [q, setQ] = useState("");
  const [a, setA] = useState("");
  return (
    <Dialog
      open
      onClose={onClose}
      title="질문·답 표 가져오기"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button
            disabled={!file || !q || !a || q === a || imp.isPending}
            onClick={() =>
              file &&
              imp.mutate(
                { file, question_column: q, answer_column: a },
                {
                  onSuccess: (d) => {
                    toast.success(
                      d.status === "ready"
                        ? `질문·답 ${d.chunk_count}개를 넣었어요.`
                        : "가져오는 중이에요. 처리가 끝나면 '준비됨'으로 바뀌어요.",
                    );
                    onClose();
                  },
                },
              )
            }
          >
            가져오기
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="text-xs text-slate-500">
          자주 묻는 질문을 엑셀(XLSX)이나 CSV로 올리면 한 줄이 조각 하나가 돼요. 질문으로 찾고, 답을
          그대로 돌려줘요.
        </p>
        <Field label="표 파일" htmlFor="qa-file" hint="첫 줄은 열 이름(예: 질문, 답)">
          <Input
            id="qa-file"
            type="file"
            accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              setCols(null);
              if (!f) return;
              columns.mutate(f, {
                onSuccess: (c) => {
                  setCols(c);
                  setQ(c.question_column ?? c.columns[0] ?? "");
                  setA(c.answer_column ?? c.columns[1] ?? "");
                },
              });
            }}
          />
        </Field>
        {cols && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Field label="질문 열" htmlFor="qa-q">
                <Select id="qa-q" value={q} onChange={(e) => setQ(e.target.value)}>
                  {cols.columns.map((c) => (
                    <option key={c} value={c}>
                      {c || "(이름 없음)"}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="답 열" htmlFor="qa-a">
                <Select id="qa-a" value={a} onChange={(e) => setA(e.target.value)}>
                  {cols.columns.map((c) => (
                    <option key={c} value={c}>
                      {c || "(이름 없음)"}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            {q === a && (
              <p className="text-xs text-red-600">질문 열과 답 열을 다르게 골라 주세요.</p>
            )}
            <p className="text-xs text-slate-500">모두 {cols.row_count}줄 · 앞의 몇 줄:</p>
            <ul className="space-y-1 text-xs">
              {cols.sample.map((row, i) => {
                const qi = cols.columns.indexOf(q);
                const ai = cols.columns.indexOf(a);
                return (
                  <li key={i} className="rounded-lg bg-slate-50 px-2.5 py-1.5">
                    <b>질문</b> {row[qi] ?? ""} · <b>답</b> {row[ai] ?? ""}
                  </li>
                );
              })}
            </ul>
          </>
        )}
        <ErrorBox error={columns.error ?? imp.error} />
      </div>
    </Dialog>
  );
}

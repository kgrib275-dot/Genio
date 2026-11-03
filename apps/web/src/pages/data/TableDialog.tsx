// 데이터 표 만들기·고치기: 이름, 설명, 프로젝트, 칸(키·이름·종류)
import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { useState } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import type { DataColumn, DataColumnType, DataTable } from "@/lib/api/types";
import { useProjects } from "@/lib/api/v3";
import { useCreateDataTable, useUpdateDataTable } from "@/lib/api/v4";
import { COLUMN_TYPES, columnsProblem, suggestKey } from "@/pages/data/values";

export function TableDialog({
  ws,
  editing,
  defaultProject,
  onClose,
  onSaved,
}: {
  ws: string;
  editing: DataTable | null;
  defaultProject?: string | null;
  onClose: () => void;
  onSaved: (t: DataTable) => void;
}) {
  const create = useCreateDataTable(ws);
  const update = useUpdateDataTable(ws);
  const projects = useProjects(ws);
  const [name, setName] = useState(editing?.name ?? "");
  const [description, setDescription] = useState(editing?.description ?? "");
  const [projectId, setProjectId] = useState(editing?.project_id ?? defaultProject ?? "");
  const [cols, setCols] = useState<DataColumn[]>(
    editing?.columns.length
      ? editing.columns
      : [
          { key: "name", label: "이름", type: "text" },
          { key: "note", label: "메모", type: "text" },
        ],
  );
  // 이미 있는 칸의 키는 바꾸지 않는다(저장된 값과 어긋나지 않게)
  const lockedKeys = new Set(editing?.columns.map((c) => c.key) ?? []);
  const problem = !name.trim() ? "표 이름을 적어 주세요." : columnsProblem(cols);
  const pending = create.isPending || update.isPending;

  const setCol = (i: number, patch: Partial<DataColumn>) =>
    setCols(cols.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= cols.length) return;
    const next = [...cols];
    [next[i], next[j]] = [next[j] as DataColumn, next[i] as DataColumn];
    setCols(next);
  };

  const submit = () => {
    if (problem) return;
    const body = {
      name: name.trim(),
      description,
      columns: cols.map((c) => ({ ...c, label: c.label.trim() || c.key })),
      project_id: projectId || null,
    };
    if (editing) update.mutate({ id: editing.id, ...body }, { onSuccess: onSaved });
    else create.mutate(body, { onSuccess: onSaved });
  };

  return (
    <Dialog
      open
      wide
      onClose={onClose}
      title={editing ? "표 고치기" : "새 데이터 표"}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            취소
          </Button>
          <Button onClick={submit} disabled={pending || Boolean(problem)}>
            {pending ? "저장 중…" : editing ? "저장" : "만들기"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="표 이름" htmlFor="dt-name">
            <Input
              id="dt-name"
              value={name}
              placeholder="예: 고객 문의 기록"
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="프로젝트" htmlFor="dt-project">
            <Select
              id="dt-project"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
            >
              <option value="">프로젝트 없음(공용)</option>
              {(projects.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {p.visibility === "private" ? " (비공개)" : ""}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="설명(선택)" htmlFor="dt-desc">
          <Textarea
            id="dt-desc"
            className="min-h-[56px]"
            value={description}
            placeholder="이 표에 무엇을 담는지 적어 두면 함께 쓰는 사람이 알기 쉬워요."
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <div>
          <p className="mb-1 text-xs font-medium text-slate-600">칸</p>
          <div className="hidden grid-cols-[1fr_1fr_8rem_auto] gap-1.5 px-0.5 pb-1 text-[11px] text-slate-400 sm:grid">
            <span>이름(화면에 보임)</span>
            <span>키(흐름에서 쓰는 이름)</span>
            <span>종류</span>
            <span />
          </div>
          <div className="space-y-2 sm:space-y-1.5">
            {cols.map((c, i) => (
              <div
                key={i}
                className="grid grid-cols-2 gap-1.5 rounded-lg border border-slate-200 p-2 sm:grid-cols-[1fr_1fr_8rem_auto] sm:border-0 sm:p-0"
              >
                <Input
                  aria-label={`${i + 1}번째 칸 이름`}
                  value={c.label}
                  placeholder="예: 이메일"
                  onChange={(e) => {
                    const label = e.target.value;
                    const auto =
                      !lockedKeys.has(c.key) &&
                      (c.key === "" ||
                        c.key ===
                          suggestKey(
                            c.label,
                            i,
                            cols.filter((_, j) => j !== i).map((x) => x.key),
                          ));
                    setCol(i, {
                      label,
                      ...(auto
                        ? {
                            key: suggestKey(
                              label,
                              i,
                              cols.filter((_, j) => j !== i).map((x) => x.key),
                            ),
                          }
                        : {}),
                    });
                  }}
                />
                <Input
                  aria-label={`${i + 1}번째 칸 키`}
                  className="font-mono text-xs"
                  value={c.key}
                  disabled={lockedKeys.has(c.key)}
                  title={lockedKeys.has(c.key) ? "이미 값이 있을 수 있어 키는 바꿀 수 없어요." : ""}
                  onChange={(e) => setCol(i, { key: e.target.value.trim() })}
                />
                <Select
                  aria-label={`${i + 1}번째 칸 종류`}
                  value={c.type}
                  onChange={(e) => setCol(i, { type: e.target.value as DataColumnType })}
                >
                  {COLUMN_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </Select>
                <span className="flex items-center justify-end gap-0.5">
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="위로"
                    disabled={i === 0}
                    onClick={() => move(i, -1)}
                  >
                    <ArrowUp className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="아래로"
                    disabled={i === cols.length - 1}
                    onClick={() => move(i, 1)}
                  >
                    <ArrowDown className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label="이 칸 빼기"
                    onClick={() => setCols(cols.filter((_, j) => j !== i))}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </span>
              </div>
            ))}
          </div>
          <Button
            size="sm"
            variant="outline"
            className="mt-2"
            onClick={() =>
              setCols([
                ...cols,
                {
                  key: suggestKey(
                    "",
                    cols.length,
                    cols.map((c) => c.key),
                  ),
                  label: "",
                  type: "text",
                },
              ])
            }
          >
            <Plus className="h-3.5 w-3.5" /> 칸 추가
          </Button>
          {editing && (
            <p className="mt-2 text-[11px] text-slate-400">
              칸을 빼도 이미 넣은 값은 지워지지 않아요. 다시 같은 키로 칸을 만들면 보여요.
            </p>
          )}
        </div>
        {problem && name.trim() !== "" && (
          <div role="alert" className="text-xs text-red-700">
            <p>{problem}</p>
            <p className="text-red-600/80">칸 키를 고친 뒤 다시 저장하세요.</p>
          </div>
        )}
        <ErrorBox error={create.error ?? update.error} />
      </div>
    </Dialog>
  );
}

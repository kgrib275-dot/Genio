import { Save, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import type { GraphNode } from "@/lib/api/types";
import { useSaveTestInputs, useTestInputs } from "@/lib/api/v5c";
import { useCanvas } from "@/store/canvas";

interface InputField {
  key: string;
  label?: string;
  type?: string;
  required?: boolean;
}

type Values = Record<string, string | boolean>;

function toValues(input: Record<string, unknown>): Values {
  const out: Values = {};
  for (const [k, v] of Object.entries(input)) {
    out[k] = typeof v === "boolean" ? v : typeof v === "string" ? v : JSON.stringify(v);
  }
  return out;
}

export function TestRunDialog({
  open,
  onClose,
  inputNode,
  onRun,
  running,
}: {
  open: boolean;
  onClose: () => void;
  inputNode: GraphNode | undefined;
  onRun: (input: Record<string, unknown>) => void;
  running: boolean;
}) {
  const appId = useCanvas((s) => s.appId);
  const saved = useTestInputs(appId, open);
  const save = useSaveTestInputs(appId);
  const fields = ((inputNode?.data.fields as InputField[] | undefined) ?? []).filter((f) => f.key);
  const [values, setValues] = useState<Values>({});
  const [picked, setPicked] = useState("");
  const [name, setName] = useState("");

  useEffect(() => {
    if (!open) return;
    setName("");
    setPicked("");
  }, [open]);

  const collect = (): Record<string, unknown> => {
    const input: Record<string, unknown> = {};
    for (const f of fields) {
      const v = values[f.key];
      if (v === undefined || v === "") continue;
      input[f.key] = f.type === "number" ? Number(v) : v;
    }
    return input;
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onRun(collect());
  };

  const items = saved.data ?? [];
  const pick = (n: string) => {
    setPicked(n);
    const item = items.find((i) => i.name === n);
    if (item) {
      setValues(toValues(item.input));
      setName(item.name);
    }
  };

  const saveCurrent = () => {
    const n = name.trim();
    if (!n) {
      toast.info("저장할 이름을 적어 주세요. 예: 환불 문의");
      return;
    }
    const rest = items.filter((i) => i.name !== n);
    save.mutate([...rest, { name: n, input: collect() }], {
      onSuccess: () => {
        setPicked(n);
        toast.success(`'${n}' 입력을 저장했어요. 다음에 골라서 바로 쓸 수 있어요.`);
      },
    });
  };

  const remove = () => {
    if (!picked) return;
    save.mutate(
      items.filter((i) => i.name !== picked),
      { onSuccess: () => setPicked("") },
    );
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="테스트 실행"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button type="submit" form="test-run" disabled={running || !inputNode}>
            {running ? "실행 중…" : "실행하기"}
          </Button>
        </>
      }
    >
      {!inputNode ? (
        <p className="text-sm text-slate-600">
          입력 단계가 없어요. &apos;단계 추가&apos;에서 &apos;입력&apos; 단계를 하나 넣어 주세요.
        </p>
      ) : (
        <form id="test-run" onSubmit={submit} className="space-y-3">
          {appId && (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-2.5">
              <p className="mb-1.5 text-xs font-medium text-slate-600">저장해 둔 입력</p>
              <div className="flex flex-wrap items-center gap-2">
                <Select
                  aria-label="저장해 둔 입력 고르기"
                  className="min-w-0 flex-1"
                  value={picked}
                  onChange={(e) => pick(e.target.value)}
                >
                  <option value="">
                    {items.length ? "골라서 채우기" : "아직 저장한 입력이 없어요"}
                  </option>
                  {items.map((i) => (
                    <option key={i.name} value={i.name}>
                      {i.name}
                    </option>
                  ))}
                </Select>
                {picked && (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="text-red-600"
                    aria-label={`'${picked}' 지우기`}
                    disabled={save.isPending}
                    onClick={remove}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
            </div>
          )}
          {fields.length === 0 && <p className="text-sm text-slate-500">입력 항목이 없어요.</p>}
          {fields.map((f) => (
            <Field
              key={f.key}
              label={`${f.label || f.key}${f.required ? " *" : ""}`}
              htmlFor={`f-${f.key}`}
            >
              {f.type === "boolean" ? (
                <input
                  id={`f-${f.key}`}
                  type="checkbox"
                  checked={Boolean(values[f.key])}
                  onChange={(e) => setValues({ ...values, [f.key]: e.target.checked })}
                />
              ) : f.type === "number" ? (
                <Input
                  id={`f-${f.key}`}
                  type="number"
                  required={f.required}
                  value={String(values[f.key] ?? "")}
                  onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
                />
              ) : (
                <Textarea
                  id={`f-${f.key}`}
                  required={f.required}
                  value={String(values[f.key] ?? "")}
                  onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
                />
              )}
            </Field>
          ))}
          {appId && fields.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
              <Input
                aria-label="저장할 이름"
                placeholder="이 입력에 이름 붙이기(예: 환불 문의)"
                className="min-w-0 flex-1"
                maxLength={60}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={save.isPending}
                onClick={saveCurrent}
              >
                <Save className="h-3.5 w-3.5" /> 입력 저장
              </Button>
            </div>
          )}
          <ErrorBox error={save.error} />
        </form>
      )}
    </Dialog>
  );
}

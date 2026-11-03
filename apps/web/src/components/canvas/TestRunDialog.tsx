import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import type { GraphNode } from "@/lib/api/types";

interface InputField {
  key: string;
  label?: string;
  type?: string;
  required?: boolean;
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
  const fields = ((inputNode?.data.fields as InputField[] | undefined) ?? []).filter((f) => f.key);
  const [values, setValues] = useState<Record<string, string | boolean>>({});

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const input: Record<string, unknown> = {};
    for (const f of fields) {
      const v = values[f.key];
      if (v === undefined || v === "") continue;
      input[f.key] = f.type === "number" ? Number(v) : v;
    }
    onRun(input);
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
          입력 노드가 없어요. 팔레트에서 &apos;입력&apos; 노드를 하나 추가해 주세요.
        </p>
      ) : (
        <form id="test-run" onSubmit={submit} className="space-y-3">
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
        </form>
      )}
    </Dialog>
  );
}

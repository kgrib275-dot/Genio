// 사람에게 맡긴 일(승인·질문·할 일) 하나를 처리하는 폼. 작업함과 링크 화면이 함께 쓴다.
import { Check, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import type { CompleteTaskBody, HumanTask } from "@/lib/api/v5a";

export function TaskForm({
  task,
  onSubmit,
  pending,
  error,
}: {
  task: HumanTask;
  onSubmit: (body: CompleteTaskBody) => void;
  pending: boolean;
  error: unknown;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [comment, setComment] = useState("");

  const submit = (e: FormEvent, approved?: boolean) => {
    e.preventDefault();
    onSubmit({
      comment,
      ...(task.kind === "approval" ? { approved } : {}),
      ...(task.kind === "question" ? { values } : {}),
    });
  };

  return (
    <form className="space-y-3" onSubmit={(e) => submit(e)}>
      {task.kind === "question" &&
        task.fields.map((f) => (
          <Field
            key={f.key}
            label={`${f.label}${f.required === false ? " (선택)" : ""}`}
            htmlFor={`f-${f.key}`}
          >
            {f.type === "paragraph" ? (
              <Textarea
                id={`f-${f.key}`}
                rows={3}
                required={f.required !== false}
                value={values[f.key] ?? ""}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
              />
            ) : f.type === "choice" && (f.options ?? []).length > 0 ? (
              <Select
                id={`f-${f.key}`}
                required={f.required !== false}
                value={values[f.key] ?? ""}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
              >
                <option value="">고르세요</option>
                {(f.options ?? []).map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </Select>
            ) : (
              <Input
                id={`f-${f.key}`}
                type={f.type === "number" ? "number" : "text"}
                inputMode={f.type === "number" ? "decimal" : undefined}
                required={f.required !== false}
                value={values[f.key] ?? ""}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
              />
            )}
          </Field>
        ))}
      <Field
        label={task.kind === "approval" ? "한마디(선택)" : "남길 말(선택)"}
        htmlFor="task-comment"
      >
        <Textarea
          id="task-comment"
          rows={2}
          maxLength={1000}
          placeholder={
            task.kind === "approval" ? "예: 다음 주 일정 확인 후 승인해요" : "예: 준비 끝났어요"
          }
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
      </Field>
      <ErrorBox error={error} />
      {task.kind === "approval" ? (
        <div className="grid grid-cols-2 gap-2">
          <Button
            type="button"
            variant="outline"
            className="text-red-600"
            disabled={pending}
            onClick={(e) => submit(e as unknown as FormEvent, false)}
          >
            <ThumbsDown className="h-4 w-4" /> 반려
          </Button>
          <Button
            type="button"
            disabled={pending}
            onClick={(e) => submit(e as unknown as FormEvent, true)}
          >
            <ThumbsUp className="h-4 w-4" /> 승인
          </Button>
        </div>
      ) : (
        <Button type="submit" className="w-full" disabled={pending}>
          <Check className="h-4 w-4" /> {task.kind === "question" ? "답 보내기" : "완료로 표시"}
        </Button>
      )}
    </form>
  );
}

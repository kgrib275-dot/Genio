// 일 전달: 지금 담당자가 다른 사람(멤버)이나 역할에게 일을 넘긴다(v0.9)
import { Forward } from "lucide-react";
import { useState } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Select, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { ko } from "@/i18n/ko";
import type { HumanTask } from "@/lib/api/v5a";
import { useForwardTargets, useForwardTask } from "@/lib/api/v9tasks";
import { cn } from "@/lib/cn";

type Mode = "user" | "role";

export function ForwardDialog({
  ws,
  task,
  meId,
  onClose,
  onDone,
}: {
  ws: string;
  task: HumanTask;
  meId: string | undefined;
  onClose: () => void;
  onDone: () => void;
}) {
  const targets = useForwardTargets(ws, true);
  const forward = useForwardTask(ws);
  const [mode, setMode] = useState<Mode>("user");
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState("");
  const [comment, setComment] = useState("");
  // 지금 담당자는 목록에서 뺀다
  const users = (targets.data?.users ?? []).filter(
    (u) => u.id !== task.assignee_user_id && u.id !== meId,
  );
  const roles = (targets.data?.roles ?? []).filter((r) => r.id !== task.assignee_role);
  const ready = mode === "user" ? Boolean(userId) : Boolean(role);

  const submit = () =>
    forward.mutate(
      {
        id: task.id,
        to_user_id: mode === "user" ? userId : undefined,
        to_role: mode === "role" ? role : undefined,
        comment: comment.trim() || undefined,
      },
      {
        onSuccess: () => {
          toast.success("일을 전달했어요. 받은 사람의 작업함에 나타나요.");
          onDone();
        },
      },
    );

  return (
    <Dialog
      open
      onClose={onClose}
      title="일 전달하기"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            닫기
          </Button>
          <Button disabled={!ready || forward.isPending} onClick={submit}>
            <Forward className="h-4 w-4" /> {forward.isPending ? "전달하는 중…" : "전달하기"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-slate-600">
          <b className="text-slate-900">{task.title}</b>을(를) 다른 사람이나 역할에게 넘겨요. 넘긴
          뒤에는 내가 처리할 수 없고, 받은 쪽이 처리해요.
        </p>
        <div
          role="radiogroup"
          aria-label="전달 대상 종류"
          className="inline-flex rounded-lg bg-slate-100 p-1"
        >
          {(["user", "role"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              onClick={() => setMode(m)}
              className={cn(
                "rounded-md px-3 py-1 text-sm",
                mode === m ? "bg-white font-medium shadow-sm" : "text-slate-500",
              )}
            >
              {m === "user" ? "사람에게" : "역할에게"}
            </button>
          ))}
        </div>
        {targets.isLoading && <p className="text-sm text-slate-500">불러오는 중…</p>}
        <ErrorBox error={targets.error} />
        {mode === "user" ? (
          <Field label="받을 사람" htmlFor="fw-user">
            <Select id="fw-user" value={userId} onChange={(e) => setUserId(e.target.value)}>
              <option value="">사람을 고르세요</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} ({ko.roles[u.role as keyof typeof ko.roles] ?? u.role})
                </option>
              ))}
            </Select>
          </Field>
        ) : (
          <Field
            label="받을 역할"
            htmlFor="fw-role"
            hint="그 역할을 가진 사람 누구나 처리할 수 있어요."
          >
            <Select id="fw-role" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="">역할을 고르세요</option>
              {roles.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <Field label="한마디(선택)" htmlFor="fw-comment">
          <Textarea
            id="fw-comment"
            rows={2}
            maxLength={500}
            value={comment}
            placeholder="예: 금액 확인이 필요해서 넘겨요."
            onChange={(e) => setComment(e.target.value)}
          />
        </Field>
        <ErrorBox error={forward.error} />
      </div>
    </Dialog>
  );
}

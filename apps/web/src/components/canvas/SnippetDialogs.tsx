// 스니펫(자주 쓰는 단계 묶음) 저장 창: 고른 단계를 이름 붙여 저장하고 다른 흐름에서 다시 끼워 넣는다.
import { useEffect, useState } from "react";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import type { Clip } from "@/components/canvas/graphOps";
import { useCreateSnippet } from "@/lib/api/snippets";
import { useSession } from "@/store/session";

export function SnippetSaveDialog({
  clip,
  onClose,
}: {
  /** 저장할 단계와 그 사이의 연결(null이면 닫힘) */
  clip: Clip | null;
  onClose: () => void;
}) {
  const ws = useSession((s) => s.workspaceId);
  const create = useCreateSnippet(ws);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  useEffect(() => {
    if (!clip) return;
    const first = clip.nodes[0];
    setName(String(first?.data.label ?? "").slice(0, 60) || "새 스니펫");
    setDescription("");
    create.reset();
    // 열릴 때만 채운다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clip]);

  const hasInput = Boolean(clip?.nodes.some((n) => n.type === "input"));
  const ready = Boolean(clip) && name.trim().length > 0 && !hasInput;

  const save = () => {
    if (!clip || !ready) return;
    create.mutate(
      { name: name.trim(), description: description.trim(), nodes: clip.nodes, edges: clip.edges },
      {
        onSuccess: (s) => {
          toast.success(`'${s.name}' 스니펫을 저장했어요. 단계 추가에서 불러올 수 있어요.`);
          if (s.reselect.length)
            toast.info(`끼워 넣은 뒤 다시 골라야 하는 칸이 ${s.reselect.length}곳 있어요.`);
          onClose();
        },
      },
    );
  };

  return (
    <Dialog
      open={clip !== null}
      onClose={onClose}
      title="스니펫으로 저장"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            닫기
          </Button>
          <Button onClick={save} disabled={!ready || create.isPending}>
            {create.isPending ? "저장하는 중…" : "저장"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-slate-600">
          고른 단계 <b>{clip?.nodes.length ?? 0}개</b>와 그 사이의 연결 {clip?.edges.length ?? 0}
          개를 저장해요. 같은 워크스페이스의 다른 흐름에서 불러다 쓸 수 있어요.
        </p>
        <ul className="list-disc space-y-1 pl-5 text-xs text-slate-500">
          <li>
            연결 정보·지식베이스·데이터 표처럼 고르는 칸은 비워서 저장해요(끼워 넣을 때 다시
            골라요).
          </li>
          <li>
            고르지 않은 바깥 단계의 값을 쓰던 칸은 &apos;없는 단계&apos;로 표시돼 다시 골라야 해요.
          </li>
        </ul>
        {hasInput && (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            시작(입력) 단계는 스니펫에 담을 수 없어요. 시작 단계를 빼고 나머지 단계만 골라 주세요.
          </p>
        )}
        <Field label="이름" htmlFor="snip-name">
          <Input
            id="snip-name"
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field label="설명(선택)" htmlFor="snip-desc">
          <Textarea
            id="snip-desc"
            rows={2}
            maxLength={500}
            placeholder="어떤 일을 하는 묶음인지 적어 두면 찾기 쉬워요."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <ErrorBox error={create.error} />
      </div>
    </Dialog>
  );
}

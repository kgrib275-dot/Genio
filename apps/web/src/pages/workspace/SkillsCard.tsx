// 후속(Y2): 업무 요령(스킬) — 직접 쓰기, 파일로 가져오기, 지우기(제작자 이상)
import { useRef, useState } from "react";
import { Trash2, Upload } from "lucide-react";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import {
  SKILL_MD_EXAMPLE,
  useCreateSkill,
  useDeleteSkill,
  useImportSkill,
  useSkills,
} from "@/lib/api/skills";

const BODY_PLACEHOLDER =
  "따를 내용을 순서대로 적어 주세요.\n1. 주문 번호를 먼저 물어봐요.\n2. 받은 지 7일 안이면 환불할 수 있다고 알려요.";

export function SkillsCard({ ws }: { ws: string }) {
  const q = useSkills(ws);
  const create = useCreateSkill(ws);
  const del = useDeleteSkill(ws);
  const imp = useImportSkill(ws);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [body, setBody] = useState("");
  const [text, setText] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const canSave = Boolean(name.trim() && description.trim() && body.trim());
  return (
    <Card>
      <CardHeader
        title="업무 요령(스킬)"
        description="'환불 문의는 이 순서로 안내해요' 같은 지침을 모아 둬요. 에이전트는 이름과 설명만 보고 있다가 필요할 때만 꺼내 읽어요. 만들어 두면 에이전트 단계에서 골라 쓸 수 있어요."
      />
      <CardBody className="space-y-4">
        {q.isLoading && <Loading />}
        <ErrorBox error={q.error ?? create.error ?? imp.error ?? del.error} />
        {q.data && q.data.skills.length === 0 && (
          <p className="text-sm text-slate-500">아직 업무 요령이 없어요. 아래에서 만들어 보세요.</p>
        )}
        <ul className="divide-y divide-slate-100 text-sm">
          {(q.data?.skills ?? []).map((s) => (
            <li key={s.id} className="flex items-start gap-2 py-2">
              <span className="min-w-0 flex-1">
                <span className="font-medium">{s.name}</span>
                <span className="block text-xs text-slate-500">{s.description}</span>
              </span>
              <button
                type="button"
                aria-label={`${s.name} 지우기`}
                className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                disabled={del.isPending}
                onClick={() => {
                  if (
                    !window.confirm(`'${s.name}' 업무 요령을 지울까요? 쓰던 에이전트에서는 빠져요.`)
                  )
                    return;
                  del.mutate(s.id, { onSuccess: () => toast.success("업무 요령을 지웠어요.") });
                }}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>

        <div className="space-y-2 rounded-lg border border-slate-200 p-3">
          <p className="text-sm font-medium">새로 만들기</p>
          <Input
            aria-label="요령 이름"
            placeholder="이름(예: 환불 안내)"
            maxLength={60}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Input
            aria-label="언제 쓰나요"
            placeholder="언제 쓰나요?(예: 고객이 환불을 물어볼 때)"
            maxLength={500}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <Textarea
            aria-label="따를 내용"
            rows={5}
            placeholder={BODY_PLACEHOLDER}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          <Button
            disabled={create.isPending || !canSave}
            onClick={() =>
              create.mutate(
                { name, description, body },
                {
                  onSuccess: () => {
                    setName("");
                    setDescription("");
                    setBody("");
                    toast.success("업무 요령을 저장했어요.");
                  },
                },
              )
            }
          >
            저장
          </Button>
        </div>

        <details className="rounded-lg border border-slate-200 p-3 text-sm">
          <summary className="cursor-pointer font-medium">
            다른 곳에서 만든 요령 파일(SKILL.md)이 있나요?
          </summary>
          <div className="mt-3 space-y-2">
            <p className="text-xs text-slate-500">
              파일을 올리거나 내용을 붙여 넣으면 이름과 설명을 읽어서 저장해요.
            </p>
            <Textarea
              aria-label="SKILL.md 붙여 넣기"
              rows={6}
              placeholder={SKILL_MD_EXAMPLE}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                disabled={create.isPending || !text.trim()}
                onClick={() =>
                  create.mutate(
                    { skill_md: text },
                    {
                      onSuccess: () => {
                        setText("");
                        toast.success("업무 요령을 저장했어요.");
                      },
                    },
                  )
                }
              >
                붙여 넣은 내용으로 저장
              </Button>
              <input
                ref={fileRef}
                type="file"
                accept=".md,.markdown,.txt,.zip,.skill"
                className="hidden"
                aria-label="요령 파일 고르기"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f)
                    imp.mutate(f, { onSuccess: () => toast.success("업무 요령을 가져왔어요.") });
                }}
              />
              <Button
                variant="secondary"
                disabled={imp.isPending}
                onClick={() => fileRef.current?.click()}
              >
                <Upload className="h-4 w-4" /> 파일로 가져오기
              </Button>
            </div>
          </div>
        </details>
      </CardBody>
    </Card>
  );
}

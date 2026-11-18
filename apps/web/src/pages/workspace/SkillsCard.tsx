// 후속(Y2): 스킬(업무 요령) — SKILL.md 가져오기·붙여 넣기·지우기(제작자 이상)
import { useRef, useState } from "react";
import { Trash2, Upload } from "lucide-react";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import {
  SKILL_MD_EXAMPLE,
  useCreateSkill,
  useDeleteSkill,
  useImportSkill,
  useSkills,
} from "@/lib/api/skills";

export function SkillsCard({ ws }: { ws: string }) {
  const q = useSkills(ws);
  const create = useCreateSkill(ws);
  const del = useDeleteSkill(ws);
  const imp = useImportSkill(ws);
  const [text, setText] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  return (
    <Card>
      <CardHeader
        title="스킬(업무 요령)"
        description="지시문과 참고 내용을 묶어 둔 SKILL.md를 가져오면, 에이전트 단계에서 골라 쓸 수 있어요. 이름과 설명만 늘 보이고 본문은 필요할 때만 읽어서 스킬이 많아도 부담이 적어요."
      />
      <CardBody className="space-y-3">
        {q.isLoading && <Loading />}
        <ErrorBox error={q.error ?? create.error ?? imp.error ?? del.error} />
        {q.data && q.data.skills.length === 0 && (
          <p className="text-sm text-slate-500">아직 스킬이 없어요.</p>
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
                  if (!window.confirm(`'${s.name}' 스킬을 지울까요? 쓰던 에이전트에서는 빠져요.`))
                    return;
                  del.mutate(s.id, { onSuccess: () => toast.success("스킬을 지웠어요.") });
                }}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
        <Textarea
          aria-label="SKILL.md 붙여 넣기"
          rows={6}
          placeholder={SKILL_MD_EXAMPLE}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={create.isPending || !text.trim()}
            onClick={() =>
              create.mutate(
                { skill_md: text },
                {
                  onSuccess: () => {
                    setText("");
                    toast.success("스킬을 저장했어요.");
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
            aria-label="SKILL.md 파일 고르기"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) imp.mutate(f, { onSuccess: () => toast.success("스킬을 가져왔어요.") });
            }}
          />
          <Button
            variant="secondary"
            disabled={imp.isPending}
            onClick={() => fileRef.current?.click()}
          >
            <Upload className="h-4 w-4" /> 파일로 가져오기(.md·.zip)
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

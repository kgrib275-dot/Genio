// 후속(X4): 빌더 상시 규칙 — 빌더가 앱을 만들 때마다 지킬 규칙
import { useEffect, useState } from "react";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import { useBuilderRules, useSaveBuilderRules } from "@/lib/api/builderRules";

export function BuilderRulesCard({ ws }: { ws: string }) {
  const q = useBuilderRules(ws);
  const save = useSaveBuilderRules(ws);
  const [text, setText] = useState("");
  useEffect(() => setText(q.data?.rules ?? ""), [q.data?.rules]);
  const max = q.data?.max_chars ?? 2000;
  return (
    <Card>
      <CardHeader
        title="빌더 상시 규칙"
        description="'알림은 늘 잔디로 보내', '고객에게 보내는 글은 존댓말로'처럼 빌더가 앱을 만들고 고칠 때마다 지킬 규칙이에요. 한 줄에 하나씩 적으세요."
      />
      <CardBody className="space-y-2">
        {q.isLoading && <Loading />}
        <ErrorBox error={q.error ?? save.error} />
        <Textarea
          aria-label="빌더 상시 규칙"
          rows={5}
          maxLength={max}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="flex items-center gap-3">
          <Button
            disabled={save.isPending || text === (q.data?.rules ?? "")}
            onClick={() =>
              save.mutate(text, { onSuccess: () => toast.success("빌더 규칙을 저장했어요.") })
            }
          >
            저장
          </Button>
          <span className="text-xs text-slate-400">
            {text.length}/{max}자
          </span>
        </div>
      </CardBody>
    </Card>
  );
}

import { CheckCircle2, HelpCircle, ThumbsDown } from "lucide-react";
import { useState } from "react";
import { ErrorBox, Loading } from "@/components/ErrorBox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import {
  useAnswerImprovement,
  useDismissImprovement,
  useImprovements,
  type ImprovementItem,
} from "@/lib/api/improvements";
import { timeAgo } from "@/lib/cn";

function Item({ appId, item }: { appId: string; item: ImprovementItem }) {
  const answer = useAnswerImprovement(appId);
  const dismiss = useDismissImprovement(appId);
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  return (
    <Card className="space-y-2 p-4">
      <div className="flex flex-wrap items-center gap-1.5">
        {item.reason === "dislike" ? (
          <Badge tone="red">
            <ThumbsDown className="mr-1 inline h-3 w-3" />
            싫어요
          </Badge>
        ) : (
          <Badge tone="amber">
            <HelpCircle className="mr-1 inline h-3 w-3" />
            답을 못 찾음
          </Badge>
        )}
        {item.count > 1 && <Badge tone="gray">{item.count}번 물었어요</Badge>}
        <span className="text-xs text-slate-400">{timeAgo(item.last_at)}</span>
      </div>
      <p className="text-xs font-semibold text-slate-400">질문</p>
      <p className="whitespace-pre-wrap text-sm text-slate-800">{item.question}</p>
      <p className="text-xs font-semibold text-slate-400">챗봇이 한 답</p>
      <p className="line-clamp-4 whitespace-pre-wrap text-sm text-slate-600">{item.answer}</p>
      {item.comment && (
        <p className="rounded-lg bg-red-50 px-3 py-1.5 text-sm text-red-800">
          받은 의견: {item.comment}
        </p>
      )}
      {open ? (
        <div className="space-y-2">
          <Textarea
            aria-label="바르게 고친 답"
            rows={3}
            value={text}
            placeholder="이 질문에는 이렇게 답하세요"
            onChange={(e) => setText(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => setOpen(false)}>
              취소
            </Button>
            <Button
              size="sm"
              disabled={!text.trim() || answer.isPending}
              onClick={() =>
                answer.mutate(
                  { messageId: item.message_id, answer: text },
                  {
                    onSuccess: () =>
                      toast.success("모범 답변으로 저장했어요. 다음부터 이 답을 써요."),
                    onError: (err) => toast.error(err),
                  },
                )
              }
            >
              모범 답변으로 저장
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex justify-end gap-2">
          <Button
            size="sm"
            variant="ghost"
            disabled={dismiss.isPending}
            onClick={() =>
              dismiss.mutate(item.message_id, {
                onSuccess: () => toast.success("고칠 필요 없는 질문으로 빼 뒀어요."),
                onError: (err) => toast.error(err),
              })
            }
          >
            고칠 필요 없어요
          </Button>
          <Button size="sm" onClick={() => setOpen(true)}>
            바른 답 적기
          </Button>
        </div>
      )}
    </Card>
  );
}

/** 로그 화면의 고칠 질문 탭 */
export function ImprovementsPanel({ appId }: { appId: string }) {
  const q = useImprovements(appId);
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-500">
        챗봇이 답을 못 찾았거나 싫어요를 받은 질문이에요(최근 30일). 바른 답을 적으면 모범 답변으로
        저장돼 다음부터 그 답을 써요.
      </p>
      {q.isLoading && <Loading />}
      <ErrorBox error={q.error} />
      {q.data && q.data.items.length === 0 && (
        <div className="flex items-start gap-2 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-800">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          <p>지금 고칠 질문이 없어요. 사람들이 싫어요를 누르거나 답을 못 찾으면 여기에 모여요.</p>
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {(q.data?.items ?? []).map((it) => (
          <Item key={it.message_id} appId={appId} item={it} />
        ))}
      </div>
    </div>
  );
}

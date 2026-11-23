import { Button } from "@/components/ui/button";

/** 목록에서 바로 승인·반려(모바일에서 두 번 눌러야 하던 걸 한 번으로). 실수 방지로 한 번 더 확인한다. */
export function QuickApprove({
  title,
  pending,
  onDecide,
}: {
  title: string;
  pending: boolean;
  onDecide: (approved: boolean) => void;
}) {
  const ask = (approved: boolean) => {
    if (window.confirm(`"${title}" 요청을 ${approved ? "승인" : "반려"}할까요?`))
      onDecide(approved);
  };
  return (
    <div className="flex gap-2 px-4 pb-3">
      <Button size="sm" disabled={pending} onClick={() => ask(true)}>
        승인
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={pending}
        className="text-red-600"
        onClick={() => ask(false)}
      >
        반려
      </Button>
    </div>
  );
}

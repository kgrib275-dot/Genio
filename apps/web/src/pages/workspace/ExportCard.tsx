import { useMutation } from "@tanstack/react-query";
import { ErrorBox } from "@/components/ErrorBox";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { toast } from "@/components/ui/toast-store";
import { downloadFile } from "@/lib/api/files";

/** 앱과 표 데이터를 한 파일(zip)로 내려받기. 해지·이관·백업 대비. 비밀값은 빠져요. */
export function ExportCard({ ws }: { ws: string }) {
  const m = useMutation({
    mutationFn: () => downloadFile(`/workspaces/${ws}/export`, "genio-내보내기.zip"),
    onSuccess: () => toast.success("내려받았어요."),
  });
  return (
    <Card>
      <CardHeader
        title="내 데이터 내려받기"
        description="이 워크스페이스의 앱(JSON)과 표 데이터(CSV)를 한 파일로 받아요. AI 키·연결 정보는 안전을 위해 빠져요."
      />
      <CardBody className="space-y-3">
        <ErrorBox error={m.error} />
        <Button disabled={m.isPending} onClick={() => m.mutate()}>
          {m.isPending ? "만드는 중…" : "전체 내려받기"}
        </Button>
      </CardBody>
    </Card>
  );
}

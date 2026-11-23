import { useNavigate } from "react-router-dom";
import type { CompanyRow } from "@/lib/api/ops";
import { useSession } from "@/store/session";
import { useSupport } from "@/store/support";

/** 다른 회사에 '지원 접속'으로 들어간다(전체 회사 화면과 왼쪽 워크스페이스 선택에서 같이 쓴다). */
export function useEnterSupport() {
  const navigate = useNavigate();
  const { workspaceId, role, setWorkspace } = useSession();
  const enter = useSupport((s) => s.enter);
  return (c: Pick<CompanyRow, "id" | "name" | "support_access">) => {
    if (c.support_access === "off") return;
    enter({
      id: c.id,
      name: c.name,
      level: c.support_access === "edit" ? "edit" : "read",
      back: { id: workspaceId, role },
    });
    setWorkspace(c.id, "admin");
    navigate("/");
  };
}

// 문서로 챗봇 만들기: 지식베이스 만들기 → 파일 올리기 → 챗봇 만들기를 한 번에 한다.
import { api } from "@/lib/api/client";
import type { AppDetail, KbDocument, KnowledgeBase } from "@/lib/api/types";

export interface DocBotProgress {
  step: "kb" | "upload" | "bot";
  done: number;
  total: number;
}

/** 이미 있는 지식베이스로 챗봇만 만든다 */
export function createChatbotFromKb(
  kbId: string,
  body: { name?: string; project_id?: string },
): Promise<AppDetail> {
  return api.post<AppDetail>(`/knowledge-bases/${kbId}/chatbot`, body);
}

/** 새 지식베이스를 만들고 파일을 올린 뒤 챗봇을 만든다. 올리기에 실패한 파일 이름을 함께 돌려준다. */
export async function createChatbotFromFiles(opts: {
  ws: string;
  name: string;
  files: File[];
  projectId?: string;
  onProgress?: (p: DocBotProgress) => void;
}): Promise<{ app: AppDetail; kb: KnowledgeBase; failed: string[] }> {
  const { ws, name, files, projectId, onProgress } = opts;
  onProgress?.({ step: "kb", done: 0, total: files.length });
  const kb = await api.post<KnowledgeBase>(`/workspaces/${ws}/knowledge-bases`, {
    name,
    project_id: projectId,
  });
  const failed: string[] = [];
  let done = 0;
  for (const file of files) {
    onProgress?.({ step: "upload", done, total: files.length });
    try {
      const form = new FormData();
      form.append("file", file);
      await api.upload<KbDocument>(`/knowledge-bases/${kb.id}/documents`, form);
    } catch {
      failed.push(file.name);
    }
    done += 1;
  }
  if (failed.length === files.length) {
    throw new Error("올린 파일을 하나도 읽지 못했어요. 파일 형식과 크기를 확인해 주세요.");
  }
  onProgress?.({ step: "bot", done, total: files.length });
  const app = await createChatbotFromKb(kb.id, { name: `${name} 챗봇`, project_id: projectId });
  return { app, kb, failed };
}

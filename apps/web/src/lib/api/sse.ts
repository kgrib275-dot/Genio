// fetch 기반 SSE 읽기. EventSource는 헤더를 못 붙이고 POST를 못 해서 직접 파싱한다.
import { rawRequest, toApiError, type RequestOptions } from "@/lib/api/client";

export interface SSEEvent {
  event: string;
  data: unknown;
}

/** 조각난 텍스트를 받아 완성된 이벤트만 넘겨주는 파서. */
export function createSSEParser(onEvent: (ev: SSEEvent) => void) {
  let buffer = "";

  const emitFrame = (frame: string) => {
    let event = "message";
    const dataLines: string[] = [];
    for (const rawLine of frame.split("\n")) {
      const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
      if (!line || line.startsWith(":")) continue;
      const idx = line.indexOf(":");
      const field = idx === -1 ? line : line.slice(0, idx);
      let value = idx === -1 ? "" : line.slice(idx + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") event = value;
      else if (field === "data") dataLines.push(value);
    }
    if (dataLines.length === 0) return;
    const text = dataLines.join("\n");
    let data: unknown = text;
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
    onEvent({ event, data });
  };

  return {
    push(chunk: string) {
      buffer += chunk.replace(/\r\n/g, "\n");
      let idx = buffer.indexOf("\n\n");
      while (idx !== -1) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        emitFrame(frame);
        idx = buffer.indexOf("\n\n");
      }
    },
    flush() {
      if (buffer.trim()) emitFrame(buffer);
      buffer = "";
    },
  };
}

export interface StreamOptions extends Omit<RequestOptions, "form"> {
  onEvent: (ev: SSEEvent) => void;
}

/** SSE 응답을 끝까지 읽는다. 응답이 오류면 ApiError를 던진다. */
export async function streamSSE(path: string, opts: StreamOptions): Promise<void> {
  const res = await rawRequest(path, opts);
  if (!res.ok) throw await toApiError(res);
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const parser = createSSEParser(opts.onEvent);
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parser.push(decoder.decode(value, { stream: true }));
  }
  parser.push(decoder.decode());
  parser.flush();
}

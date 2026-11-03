import { createSSEParser, type SSEEvent } from "@/lib/api/sse";

describe("createSSEParser", () => {
  it("조각난 청크와 여러 이벤트를 순서대로 해석한다", () => {
    const events: SSEEvent[] = [];
    const p = createSSEParser((e) => events.push(e));
    p.push('event: text\ndata: {"del');
    p.push(
      'ta":"안녕"}\n\nevent: ask_user\r\ndata: {"question":"어디로?","options":["#a","#b"]}\r\n\r\n',
    );
    p.push(": keep-alive\n\n");
    p.push('data: plain\n\nevent: done\ndata: {"id":"m1"}');
    expect(events.map((e) => e.event)).toEqual(["text", "ask_user", "message"]);
    p.flush();
    expect(events).toEqual([
      { event: "text", data: { delta: "안녕" } },
      { event: "ask_user", data: { question: "어디로?", options: ["#a", "#b"] } },
      { event: "message", data: "plain" },
      { event: "done", data: { id: "m1" } },
    ]);
  });

  it("여러 줄 data를 줄바꿈으로 잇는다", () => {
    const events: SSEEvent[] = [];
    const p = createSSEParser((e) => events.push(e));
    p.push("event: x\ndata: a\ndata: b\n\n");
    expect(events).toEqual([{ event: "x", data: "a\nb" }]);
  });
});

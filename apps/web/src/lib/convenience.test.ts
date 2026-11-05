// v0.8 편의 기능 순수 함수 시험: 검색창, IP 입력, 공개 API 문서, 단축키 판정.
import { badIpEntries, parseIpText, validIpEntry } from "@/lib/ipRule";
import {
  authOf,
  curlExample,
  exampleFromSchema,
  groupEndpoints,
  schemaRows,
  type OpenApiDoc,
} from "@/lib/openapi";
import { flatten, highlight, moveIndex, pushRecent, readRecents } from "@/lib/palette";
import { isHelpKey, isPaletteKey, isTypingTarget } from "@/lib/shortcuts";

describe("검색어 강조·이동", () => {
  test("대소문자를 무시하고 일치 부분을 나눈다", () => {
    expect(highlight("휴가 신청 봇", "신청")).toEqual([
      { text: "휴가 ", hit: false },
      { text: "신청", hit: true },
      { text: " 봇", hit: false },
    ]);
    expect(highlight("Slack Bot", "bot").map((s) => s.hit)).toEqual([false, true]);
    expect(highlight("abc", "  ")).toEqual([{ text: "abc", hit: false }]);
    expect(highlight("abc", "zzz")).toEqual([{ text: "abc", hit: false }]);
    expect(highlight("aaa", "a").filter((s) => s.hit)).toHaveLength(3);
  });

  test("그룹을 한 줄 목록으로 펼치고 방향키는 끝에서 돈다", () => {
    const rows = flatten([
      { kind: "apps", label: "앱", items: [{ id: "1", title: "A", subtitle: "", to: "/a" }] },
      { kind: "pages", label: "화면", items: [{ id: "2", title: "B", subtitle: "", to: "/b" }] },
    ]);
    expect(rows.map((r) => `${r.kind}:${r.id}`)).toEqual(["apps:1", "pages:2"]);
    expect(rows[1]?.label).toBe("화면");
    expect(moveIndex(0, -1, 2)).toBe(1);
    expect(moveIndex(1, 1, 2)).toBe(0);
    expect(moveIndex(0, 1, 0)).toBe(0);
  });

  test("최근 항목은 워크스페이스마다, 같은 곳은 한 번만, 최대 6개", () => {
    window.localStorage.clear();
    const row = (n: number) => ({
      id: String(n),
      title: `앱${n}`,
      subtitle: "",
      to: `/apps/${n}/builder`,
      kind: "apps",
      label: "앱",
    });
    for (let i = 1; i <= 8; i++) pushRecent("w1", row(i));
    pushRecent("w1", row(5));
    const list = readRecents("w1");
    expect(list).toHaveLength(6);
    expect(list[0]?.id).toBe("5");
    expect(new Set(list.map((r) => r.id)).size).toBe(6);
    expect(readRecents("w2")).toEqual([]);
    window.localStorage.setItem("genio.palette.recent.w3", "깨진 값");
    expect(readRecents("w3")).toEqual([]);
  });
});

describe("단축키 판정", () => {
  const ev = (o: Partial<KeyboardEvent>) =>
    ({
      key: "",
      ctrlKey: false,
      metaKey: false,
      altKey: false,
      shiftKey: false,
      ...o,
    }) as KeyboardEvent;
  test("Ctrl/⌘+K는 검색창, ?는 단축키 보기", () => {
    expect(isPaletteKey(ev({ key: "k", ctrlKey: true }))).toBe(true);
    expect(isPaletteKey(ev({ key: "K", metaKey: true }))).toBe(true);
    expect(isPaletteKey(ev({ key: "k" }))).toBe(false);
    expect(isPaletteKey(ev({ key: "k", ctrlKey: true, shiftKey: true }))).toBe(false);
    expect(isHelpKey(ev({ key: "?" }))).toBe(true);
    expect(isHelpKey(ev({ key: "?", ctrlKey: true }))).toBe(false);
  });
  test("글 치는 중이면 한 글자 단축키를 쓰지 않는다", () => {
    const input = document.createElement("input");
    const div = document.createElement("div");
    const editable = document.createElement("div");
    editable.contentEditable = "true";
    // jsdom은 isContentEditable을 구현하지 않아 직접 정한다
    Object.defineProperty(editable, "isContentEditable", { value: true });
    expect(isTypingTarget(input)).toBe(true);
    expect(isTypingTarget(editable)).toBe(true);
    expect(isTypingTarget(div)).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });
});

describe("IP 입력 점검", () => {
  test("IPv4·IPv6·CIDR", () => {
    for (const ok of [
      "203.0.113.7",
      "203.0.113.0/24",
      "0.0.0.0/0",
      "2001:db8::/32",
      "::1",
      "fe80::1/64",
    ])
      expect(validIpEntry(ok), ok).toBe(true);
    for (const bad of [
      "",
      "abc",
      "256.1.1.1",
      "1.2.3",
      "1.2.3.4/33",
      "2001:db8::/129",
      "1.2.3.4/",
      "1.2.3.4/5/6",
      "::g",
    ])
      expect(validIpEntry(bad), bad).toBe(false);
  });
  test("줄바꿈·쉼표·공백으로 나누고 중복을 뺀다", () => {
    expect(parseIpText("1.1.1.1\n2.2.2.2, 1.1.1.1;  3.3.3.0/24\n\n")).toEqual([
      "1.1.1.1",
      "2.2.2.2",
      "3.3.3.0/24",
    ]);
    expect(badIpEntries(["1.1.1.1", "x", "2.2.2.2/40"])).toEqual(["x", "2.2.2.2/40"]);
  });
});

const DOC: OpenApiDoc = {
  tags: [
    { name: "서비스 API(앱 API 키)", description: "키로 불러요" },
    { name: "공유 링크 앱(챗·입력 폼)", description: "토큰으로 불러요" },
  ],
  paths: {
    "/api/v1/service/chat-messages": {
      post: {
        summary: "대화 보내기",
        tags: ["서비스 API(앱 API 키)"],
        requestBody: {
          required: true,
          content: { "application/json": { schema: { $ref: "#/components/schemas/ChatIn" } } },
        },
        responses: { "200": { description: "답" } },
      },
    },
    "/api/v1/public/apps/{token}/runs/{run_id}": {
      get: {
        summary: "실행 결과 받기",
        tags: ["공유 링크 앱(챗·입력 폼)"],
        parameters: [
          { name: "token", in: "path", required: true, schema: { type: "string" } },
          { name: "page", in: "query", required: true, schema: { type: "integer" } },
        ],
        responses: { "200": { description: "결과" } },
      },
    },
    "/api/v1/service/mcp": {
      post: { summary: "MCP 요청", tags: ["MCP 서버"], responses: {} },
    },
  },
  components: {
    schemas: {
      ChatIn: {
        type: "object",
        required: ["query"],
        properties: {
          query: { type: "string", maxLength: 4000, description: "보낼 말" },
          inputs: { type: "object" },
          conversation_id: { anyOf: [{ type: "string" }, { type: "null" }] },
          opts: { $ref: "#/components/schemas/Opts" },
        },
      },
      Opts: { type: "object", properties: { stream: { type: "boolean", default: true } } },
    },
  },
};

describe("공개 API 문서", () => {
  test("묶음 순서는 문서의 tags 순서, 검색어로 거른다", () => {
    const groups = groupEndpoints(DOC);
    expect(groups.map((g) => g.tag)).toEqual([
      "서비스 API(앱 API 키)",
      "공유 링크 앱(챗·입력 폼)",
      "MCP 서버",
    ]);
    expect(groups[0]?.description).toBe("키로 불러요");
    expect(groupEndpoints(DOC, "runs").flatMap((g) => g.endpoints.map((e) => e.path))).toEqual([
      "/api/v1/public/apps/{token}/runs/{run_id}",
    ]);
    expect(groupEndpoints(DOC, "없는것")).toEqual([]);
  });

  test("스키마를 표 줄로 펼친다(필수·형식·중첩)", () => {
    const rows = schemaRows(DOC, { $ref: "#/components/schemas/ChatIn" });
    const by = Object.fromEntries(rows.map((r) => [r.name, r]));
    expect(by.query).toMatchObject({ type: "글", required: true });
    expect(by.query?.description).toContain("최대 4000자");
    expect(by.conversation_id?.type).toBe("글 또는 없음");
    expect(by["opts.stream"]).toMatchObject({ type: "참/거짓", required: false });
    expect(by["opts.stream"]?.description).toContain("기본값 true");
  });

  test("예시 값과 curl", () => {
    const ex = exampleFromSchema(DOC, { $ref: "#/components/schemas/ChatIn" }) as Record<
      string,
      unknown
    >;
    expect(ex.query).toBe("글");
    const pick = (g: number) => {
      const e = groupEndpoints(DOC)[g]?.endpoints[0];
      if (!e) throw new Error("시험 자료가 없어요");
      return e;
    };
    const curl = curlExample(DOC, pick(0), "서비스 API(앱 API 키)", "https://g.example.com/");
    expect(curl).toContain('curl -X POST "https://g.example.com/api/v1/service/chat-messages"');
    expect(curl).toContain("Authorization: Bearer gk-내_API_키");
    expect(curl).toContain("Content-Type: application/json");
    const c2 = curlExample(DOC, pick(1), "공유 링크 앱(챗·입력 폼)", "https://g.example.com");
    expect(c2).toContain("/api/v1/public/apps/<token>/runs/<run_id>?page=0");
    expect(c2).not.toContain("Authorization");
    expect(curlExample(DOC, pick(2), "MCP 서버", "https://g.example.com")).toContain(
      '"method":"tools/list"',
    );
    expect(authOf("외부에서 받기(웹훅)").header).toBeNull();
    expect(authOf("MCP 서버").header).toContain("Bearer");
  });
});

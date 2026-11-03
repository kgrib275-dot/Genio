import { parseCurl, tokenize } from "@/components/canvas/curl";

describe("cURL 붙여넣기", () => {
  it("따옴표와 줄 이어 쓰기를 풀어 낱말로 나눈다", () => {
    expect(tokenize(`curl -H 'A: b c' \\\n  "https://x.io/?q=\\"1\\""`)).toEqual([
      "curl",
      "-H",
      "A: b c",
      'https://x.io/?q="1"',
    ]);
  });

  it("방식·주소·헤더·JSON 본문을 읽는다", () => {
    const r = parseCurl(
      `curl -X POST https://api.example.com/v1/items -H "Content-Type: application/json" -H 'Authorization: Bearer abc' -d '{"name":"사과","n":2}'`,
    );
    expect(r).toEqual({
      method: "POST",
      url: "https://api.example.com/v1/items",
      headers: { "Content-Type": "application/json", Authorization: "Bearer abc" },
      body: { name: "사과", n: 2 },
    });
  });

  it("본문이 있으면 방식이 없어도 POST, 없으면 GET", () => {
    expect(parseCurl("curl https://a.io --data-raw 'x=1'")?.method).toBe("POST");
    expect(parseCurl("curl https://a.io --data-raw 'x=1'")?.body).toBe("x=1");
    expect(parseCurl("curl 'https://a.io/list'")).toEqual({
      method: "GET",
      url: "https://a.io/list",
      headers: {},
    });
  });

  it("--json, -u, -G를 처리한다", () => {
    const j = parseCurl(`curl --json '{"a":1}' https://a.io`);
    expect(j?.headers["Content-Type"]).toBe("application/json");
    expect(j?.body).toEqual({ a: 1 });
    expect(parseCurl("curl -u user:pw https://a.io")?.headers.Authorization).toBe(
      `Basic ${btoa("user:pw")}`,
    );
    expect(parseCurl("curl -G https://a.io/s -d q=1 -d n=2")?.url).toBe("https://a.io/s?q=1&n=2");
  });

  it("curl이 아니거나 주소가 없으면 null", () => {
    expect(parseCurl("wget https://a.io")).toBeNull();
    expect(parseCurl("curl -X POST")).toBeNull();
  });
});

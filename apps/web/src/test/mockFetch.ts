// 테스트용 가짜 서버. 경로·메서드별로 돌려줄 값을 정하고, 보낸 요청을 기록한다.
export interface Call {
  method: string;
  path: string;
  body: unknown;
}

type Handler = (call: Call) => unknown;

export function mockFetch(routes: Record<string, Handler | unknown>) {
  const calls: Call[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const path = url.replace(/^\/api(\/v1)?/, "");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    const call = { method, path, body };
    calls.push(call);
    const key = Object.keys(routes).find((k) => {
      const [m, p] = k.includes(" ") ? k.split(" ", 2) : ["GET", k];
      return m === method && p === path.split("?")[0];
    });
    const route = key ? routes[key] : undefined;
    const data = typeof route === "function" ? (route as Handler)(call) : route;
    return new Response(JSON.stringify(data ?? (method === "GET" ? [] : {})), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

// cURL 명령을 웹 요청 블록 설정(방식·주소·헤더·본문)으로 바꾼다.

export interface ParsedCurl {
  method: string;
  url: string;
  headers: Record<string, string>;
  body?: unknown;
}

/** 셸처럼 따옴표·역슬래시를 풀어 낱말로 나눈다(줄 끝 \\ 이어 쓰기 포함). */
export function tokenize(cmd: string): string[] {
  const src = cmd.replace(/\\\r?\n/g, " ").replace(/\^\r?\n/g, " ");
  const out: string[] = [];
  let cur = "";
  let has = false;
  let i = 0;
  while (i < src.length) {
    const ch = src[i] as string;
    if (ch === "'") {
      const end = src.indexOf("'", i + 1);
      cur += src.slice(i + 1, end < 0 ? src.length : end);
      has = true;
      i = end < 0 ? src.length : end + 1;
    } else if (ch === '"') {
      i++;
      while (i < src.length && src[i] !== '"') {
        if (src[i] === "\\" && i + 1 < src.length && /["\\$`]/.test(src[i + 1] as string)) i++;
        cur += src[i];
        i++;
      }
      has = true;
      i++;
    } else if (ch === "\\" && i + 1 < src.length) {
      cur += src[i + 1];
      has = true;
      i += 2;
    } else if (/\s/.test(ch)) {
      if (has) out.push(cur);
      cur = "";
      has = false;
      i++;
    } else {
      // $'...' 같은 형식의 $는 버린다
      if (!(ch === "$" && src[i + 1] === "'")) {
        cur += ch;
        has = true;
      }
      i++;
    }
  }
  if (has) out.push(cur);
  return out;
}

function base64(s: string): string {
  try {
    return btoa(unescape(encodeURIComponent(s)));
  } catch {
    return btoa(s);
  }
}

const DATA_FLAGS = new Set([
  "-d",
  "--data",
  "--data-raw",
  "--data-binary",
  "--data-ascii",
  "--data-urlencode",
  "--json",
]);
// 값을 하나 받지만 우리 설정과 상관없는 옵션
const SKIP_WITH_VALUE = new Set([
  "-o",
  "--output",
  "-m",
  "--max-time",
  "--connect-timeout",
  "-A",
  "--user-agent",
  "-e",
  "--referer",
  "-b",
  "--cookie",
  "-x",
  "--proxy",
  "-w",
  "--write-out",
  "--retry",
]);

/** cURL 명령을 읽는다. curl로 시작하지 않거나 주소가 없으면 null. */
export function parseCurl(cmd: string): ParsedCurl | null {
  const t = tokenize(cmd.trim());
  if (t[0]?.toLowerCase() !== "curl") return null;
  let method = "";
  let url = "";
  const headers: Record<string, string> = {};
  const data: string[] = [];
  let isJson = false;
  let forceGet = false;
  for (let i = 1; i < t.length; i++) {
    const a = t[i] as string;
    const next = () => t[++i] ?? "";
    if (a === "-X" || a === "--request") method = next().toUpperCase();
    else if (a.startsWith("-X") && a.length > 2) method = a.slice(2).toUpperCase();
    else if (a === "-H" || a === "--header") {
      const h = next();
      const idx = h.indexOf(":");
      if (idx > 0) headers[h.slice(0, idx).trim()] = h.slice(idx + 1).trim();
    } else if (DATA_FLAGS.has(a)) {
      if (a === "--json") isJson = true;
      data.push(next());
    } else if (a === "-u" || a === "--user") headers["Authorization"] = `Basic ${base64(next())}`;
    else if (a === "-G" || a === "--get") forceGet = true;
    else if (a === "--url") url = next();
    else if (SKIP_WITH_VALUE.has(a)) next();
    else if (!a.startsWith("-") && !url) url = a;
  }
  if (!url) return null;
  if (isJson) {
    headers["Content-Type"] ??= "application/json";
    headers["Accept"] ??= "application/json";
  }
  let body: unknown;
  if (data.length && forceGet) {
    url += (url.includes("?") ? "&" : "?") + data.join("&");
  } else if (data.length) {
    const raw = data.join("&");
    try {
      body = JSON.parse(raw);
    } catch {
      body = raw;
    }
  }
  if (!method) method = body !== undefined ? "POST" : "GET";
  const allowed = ["GET", "POST", "PUT", "PATCH", "DELETE"];
  if (!allowed.includes(method)) method = body !== undefined ? "POST" : "GET";
  return { method, url, headers, ...(body !== undefined ? { body } : {}) };
}

// 모든 API 호출의 단일 진입점. 컴포넌트에서 fetch를 직접 쓰지 않는다.
import type { ApiErrorDetail, GraphError, Tokens } from "@/lib/api/types";

export const API_PREFIX = "/api/v1";

const ACCESS_KEY = "genio.access";
const REFRESH_KEY = "genio.refresh";

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // 저장소를 못 쓰는 환경(사생활 보호 모드 등)에서는 메모리 상태만 유지된다.
  }
}

let memoryAccess: string | null = null;
let memoryRefresh: string | null = null;

export function getAccessToken(): string | null {
  return memoryAccess ?? readStorage(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  return memoryRefresh ?? readStorage(REFRESH_KEY);
}

export function setTokens(tokens: Tokens | null): void {
  memoryAccess = tokens?.access_token ?? null;
  memoryRefresh = tokens?.refresh_token ?? null;
  writeStorage(ACCESS_KEY, memoryAccess);
  writeStorage(REFRESH_KEY, memoryRefresh);
  window.dispatchEvent(new Event("genio:auth"));
}

export function isLoggedIn(): boolean {
  return Boolean(getAccessToken());
}

export class ApiError extends Error {
  readonly status: number;
  readonly hint: string;
  readonly errors: GraphError[];

  constructor(status: number, message: string, hint: string, errors: GraphError[] = []) {
    super(message);
    this.status = status;
    this.hint = hint;
    this.errors = errors;
  }
}

const NETWORK_ERROR = new ApiError(
  0,
  "서버에 연결하지 못했어요.",
  "인터넷 연결을 확인하고 잠시 후 다시 시도하세요.",
);

export async function toApiError(res: Response): Promise<ApiError> {
  let detail: ApiErrorDetail | null = null;
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (body && typeof body.detail === "object" && body.detail !== null) {
      detail = body.detail as ApiErrorDetail;
    }
  } catch {
    detail = null;
  }
  if (detail?.message) {
    return new ApiError(res.status, detail.message, detail.hint ?? "", detail.errors ?? []);
  }
  if (res.status === 401) {
    return new ApiError(401, "로그인이 필요해요.", "다시 로그인한 뒤 시도하세요.");
  }
  return new ApiError(res.status, "요청을 처리하지 못했어요.", "잠시 후 다시 시도하세요.");
}

let refreshing: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  const refresh = getRefreshToken();
  if (!refresh) return false;
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await fetch(`${API_PREFIX}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
        });
        if (!res.ok) return false;
        setTokens((await res.json()) as Tokens);
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => {
          refreshing = null;
        }, 0);
      }
    })();
  }
  return refreshing;
}

function logout(): void {
  setTokens(null);
  window.dispatchEvent(new Event("genio:logout"));
}

export function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  auth?: boolean;
  /** 추가로 붙일 헤더(예: 동시 편집에서 어느 탭인지 알리는 X-Genio-Client) */
  headers?: Record<string, string>;
  /** 탭을 닫는 순간에도 요청이 끝까지 가게 한다(떠남 알림 등 작은 요청용) */
  keepalive?: boolean;
}

/** 인증 헤더를 붙여 요청하고, 401이면 토큰을 한 번 갱신해 다시 보낸다. 응답 원본을 돌려준다. */
export async function rawRequest(path: string, opts: RequestOptions = {}): Promise<Response> {
  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = {
      ...(opts.auth === false ? {} : authHeaders()),
      ...(opts.headers ?? {}),
    };
    let body: BodyInit | undefined;
    if (opts.form) {
      body = opts.form;
    } else if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(opts.body);
    }
    return fetch(path.startsWith("/api") ? path : `${API_PREFIX}${path}`, {
      method: opts.method ?? (body ? "POST" : "GET"),
      headers,
      body,
      signal: opts.signal,
      keepalive: opts.keepalive,
    });
  };
  let res: Response;
  try {
    res = await send();
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw NETWORK_ERROR;
  }
  if (res.status === 401 && opts.auth !== false && getRefreshToken()) {
    if (await refreshTokens()) {
      try {
        res = await send();
      } catch {
        throw NETWORK_ERROR;
      }
    } else {
      logout();
    }
  }
  return res;
}

export async function apiFetch<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await rawRequest(path, opts);
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, { method: "POST", body: body ?? {} }),
  put: <T>(path: string, body: unknown) => apiFetch<T>(path, { method: "PUT", body }),
  patch: <T>(path: string, body: unknown) => apiFetch<T>(path, { method: "PATCH", body }),
  del: (path: string) => apiFetch<undefined>(path, { method: "DELETE" }),
  upload: <T>(path: string, form: FormData) => apiFetch<T>(path, { method: "POST", form }),
};

/** 로그아웃 처리를 화면에서도 쓸 수 있게 내보낸다. */
export function signOut(): void {
  logout();
}

/** 에러 객체를 두 줄 문구로 바꾼다. */
export function errorLines(err: unknown): { message: string; hint: string } {
  if (err instanceof ApiError) return { message: err.message, hint: err.hint };
  return { message: "알 수 없는 문제가 생겼어요.", hint: "화면을 새로고침한 뒤 다시 시도하세요." };
}

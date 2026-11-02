// 모든 API 호출의 단일 진입점. 컴포넌트에서 fetch를 직접 쓰지 않는다.
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { credentials: "include" });
  if (!res.ok) throw new ApiError(res.status, `요청 실패 (${res.status})`);
  return (await res.json()) as T;
}

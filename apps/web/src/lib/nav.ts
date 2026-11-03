/** 로그인 후 돌아갈 주소. 외부 주소로는 보내지 않는다. */
export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

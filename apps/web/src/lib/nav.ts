/**
 * 로그인 후 돌아갈 주소. 이 사이트 안의 경로만 허용하고 외부 주소로는 보내지 않는다.
 * 브라우저는 역슬래시를 슬래시로 읽고 탭·줄바꿈 같은 제어 문자는 무시하므로,
 * 역슬래시를 섞거나 제어 문자를 끼워 넣어 우회하는 주소도 모두 막는다.
 */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith("/")) return "/";
  if (next.startsWith("//") || next.includes("\\")) return "/";
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(next)) return "/";
  return next;
}

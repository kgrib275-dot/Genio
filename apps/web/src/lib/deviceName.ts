/** 로그인 기기 이름을 쉬운 말로(브라우저 정보에서 어림, 정확하지 않아도 된다) */
export function deviceName(ua: string): string {
  const os = /iPhone|iPad/.test(ua)
    ? "iPhone·iPad"
    : /Android/.test(ua)
      ? "안드로이드"
      : /Mac OS/.test(ua)
        ? "Mac"
        : /Windows/.test(ua)
          ? "Windows"
          : /Linux/.test(ua)
            ? "Linux"
            : "알 수 없는 기기";
  const br = /Edg\//.test(ua)
    ? "Edge"
    : /Chrome\//.test(ua)
      ? "Chrome"
      : /Safari\//.test(ua)
        ? "Safari"
        : /Firefox\//.test(ua)
          ? "Firefox"
          : ua
            ? "앱·도구"
            : "";
  return br ? `${os} · ${br}` : os;
}

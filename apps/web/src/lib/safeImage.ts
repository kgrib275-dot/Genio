/** 이 서비스가 직접 내주는 그림(같은 주소·data·blob)인지(운영 준비 B1·F21). */
export function isSameOriginImage(url: string): boolean {
  if (!url) return false;
  if (url.startsWith("data:image/") || url.startsWith("blob:")) return true;
  if (url.startsWith("/") && !url.startsWith("//")) return true;
  try {
    return new URL(url).origin === window.location.origin;
  } catch {
    return false;
  }
}

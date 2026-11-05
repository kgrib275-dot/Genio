// IP 허용 목록 입력 점검(서버가 한 번 더 점검한다): IPv4·IPv6 주소와 CIDR 대역.

const V4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;

function validV4(addr: string): boolean {
  const m = V4.exec(addr);
  return Boolean(m) && [1, 2, 3, 4].every((i) => Number(m?.[i]) <= 255);
}

function validV6(addr: string): boolean {
  if (!addr.includes(":")) return false;
  try {
    new URL(`http://[${addr}]/`);
    return true;
  } catch {
    return false;
  }
}

/** 한 줄이 올바른 IP 주소(또는 `주소/접두 길이`)인지 */
export function validIpEntry(entry: string): boolean {
  const text = entry.trim();
  if (!text) return false;
  const [addr, prefix, ...rest] = text.split("/");
  if (rest.length || addr === undefined) return false;
  const v4 = validV4(addr);
  const v6 = !v4 && validV6(addr);
  if (!v4 && !v6) return false;
  if (prefix === undefined) return true;
  if (!/^\d{1,3}$/.test(prefix)) return false;
  return Number(prefix) <= (v4 ? 32 : 128);
}

/** 줄바꿈·쉼표·공백으로 적은 글을 항목 목록으로 바꾼다(빈 줄 제거, 중복 제거). */
export function parseIpText(text: string): string[] {
  return [
    ...new Set(
      text
        .split(/[\s,;]+/)
        .map((s) => s.trim())
        .filter(Boolean),
    ),
  ];
}

/** 올바르지 않은 항목들 */
export function badIpEntries(entries: string[]): string[] {
  return entries.filter((e) => !validIpEntry(e));
}

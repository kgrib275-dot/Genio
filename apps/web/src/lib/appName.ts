// 말로 앱 만들기에서 적은 문장으로 앱 이름을 정한다
export function appNameFrom(prompt: string): string {
  const clean = prompt
    .replace(/\s+/g, " ")
    .trim()
    // '…챗봇을 만들어 줘' 같은 부탁 끝말과 그 앞의 을·를을 뗀다
    .replace(/\s?(을|를)?\s?(만들어\s?(줘|주세요)|해\s?(줘|주세요)|줘|주세요)[.!?]*$/, "");
  if (clean.length <= 24) return clean || "새 앱";
  // 글자 중간에서 자르지 않고 마지막 띄어쓰기에서 자른다
  const cut = clean.slice(0, 24);
  const at = cut.lastIndexOf(" ");
  return `${at > 8 ? cut.slice(0, at) : cut}…`;
}

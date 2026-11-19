// 말로 앱 만들기에서 적은 문장으로 앱 이름을 정한다
/** '…챗봇을 만들어 줘' 같은 부탁 끝말과 그 앞의 을·를을 뗀 문장 */
export function stripRequest(prompt: string): string {
  return prompt
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\s?(을|를)?\s?(만들어\s?(줘|주세요)|해\s?(줘|주세요)|줘|주세요)[.!?]*$/, "");
}

/** 앱 설명: 부탁 끝말을 뗀 한 줄(너무 길면 말줄임) */
export function appDescriptionFrom(prompt: string): string {
  const clean = stripRequest(prompt);
  return clean.length > 120 ? `${clean.slice(0, 120)}…` : clean;
}

export function appNameFrom(prompt: string): string {
  const clean = stripRequest(prompt);
  if (clean.length <= 24) return clean || "새 앱";
  // 글자 중간에서 자르지 않고 마지막 띄어쓰기에서 자른다
  const cut = clean.slice(0, 24);
  const at = cut.lastIndexOf(" ");
  return `${at > 8 ? cut.slice(0, at) : cut}…`;
}

/** 공유할 때 그대로 붙여 넣을 문구: 제목·소개·링크·썸네일 주소 */
export function buildShareText(v: {
  title: string;
  description: string;
  link: string;
  thumbnail: string;
}): string {
  return [v.title, v.description, v.link, v.thumbnail ? `썸네일: ${v.thumbnail}` : ""]
    .filter((x) => x.trim())
    .join("\n");
}

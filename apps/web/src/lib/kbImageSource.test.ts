import { imageSource, pageText } from "@/lib/kbImageSource";

test("공개 챗은 서명 주소를, 빌더는 지식베이스 그림 주소(로그인)를 쓴다", () => {
  expect(
    imageSource({
      file_id: "f1",
      kb_id: "k1",
      url: "/api/v1/public/apps/t/kb-images/f1?exp=1&sig=a",
    }),
  ).toEqual({ kind: "direct", path: "/api/v1/public/apps/t/kb-images/f1?exp=1&sig=a" });
  expect(imageSource({ file_id: "f1", kb_id: "k1" })).toEqual({
    kind: "authed",
    path: "/knowledge-bases/k1/images/f1",
  });
  expect(imageSource({ file_id: "f1" })).toBeNull();
});

test("쪽 표기", () => {
  expect(pageText(3)).toBe("3쪽");
  expect(pageText(null)).toBe("");
});

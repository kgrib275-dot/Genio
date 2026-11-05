import { appearanceOf, DEFAULT_APPEARANCE } from "@/lib/api/chat";

test("공유 미리보기 값은 비어 있으면 기본값(앱 이름·앱 설명을 따름)", () => {
  const a = appearanceOf(undefined);
  expect(a.share_title).toBe("");
  expect(a.share_description).toBe("");
  expect(a.share_image).toBe("");
  expect(DEFAULT_APPEARANCE.share_title).toBe("");
});

test("저장된 공유 제목·소개·썸네일을 그대로 쓰고, 틀린 색은 기본 색으로", () => {
  const a = appearanceOf({
    share_title: "우리 팀 휴가 봇",
    share_description: "연차를 말로 신청해요",
    share_image: "file-1",
    primary_color: "red",
  });
  expect(a.share_title).toBe("우리 팀 휴가 봇");
  expect(a.share_image).toBe("file-1");
  expect(a.primary_color).toBe(DEFAULT_APPEARANCE.primary_color);
});

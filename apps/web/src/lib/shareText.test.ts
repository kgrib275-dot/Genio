import { buildShareText } from "@/lib/shareText";

describe("buildShareText", () => {
  it("제목·소개·링크·썸네일을 줄마다 적고 빈 것은 뺀다", () => {
    expect(
      buildShareText({
        title: "휴가 봇",
        description: "휴가 규정을 알려 줘요",
        link: "https://x.test/share/t1",
        thumbnail: "https://x.test/api/v1/public/apps/t1/share-image",
      }),
    ).toBe(
      "휴가 봇\n휴가 규정을 알려 줘요\nhttps://x.test/share/t1\n썸네일: https://x.test/api/v1/public/apps/t1/share-image",
    );
    expect(
      buildShareText({ title: "봇", description: " ", link: "https://x.test/s", thumbnail: "" }),
    ).toBe("봇\nhttps://x.test/s");
  });
});

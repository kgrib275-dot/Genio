import {
  batchFilePath,
  categoryOf,
  formatSize,
  publicFilePath,
  resolveFilePath,
  runFilePath,
  splitFiles,
  type OutputFile,
} from "@/lib/fileKinds";

const img: OutputFile = {
  id: "i1",
  filename: "이미지-1.png",
  mime: "image/png",
  size: 2048,
  kind: "image",
  run_id: "r1",
  sig: "abc",
  exp: 1700000000,
};
const xlsx: OutputFile = {
  id: "f1",
  filename: "주간 보고.xlsx",
  mime: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  size: 5_500_000,
  kind: "file",
  run_id: "r1",
};

test("형식 묶음: 이미지·표·문서·글·그 밖", () => {
  expect(categoryOf("image/webp")).toBe("image");
  expect(categoryOf(xlsx.mime, xlsx.filename)).toBe("sheet");
  expect(categoryOf("text/csv; charset=utf-8", "a.csv")).toBe("sheet");
  expect(
    categoryOf("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
  ).toBe("doc");
  expect(categoryOf("text/markdown; charset=utf-8", "a.md")).toBe("text");
  expect(categoryOf("application/octet-stream", "a.bin")).toBe("other");
});

test("크기를 읽기 쉽게", () => {
  expect(formatSize(512)).toBe("512B");
  expect(formatSize(2048)).toBe("2.0KB");
  expect(formatSize(300 * 1024)).toBe("300KB");
  expect(formatSize(5_500_000)).toBe("5.2MB");
  expect(formatSize(-1)).toBe("");
});

test("내려받기 경로: 공유 링크는 서명, 로그인한 화면은 실행 기록", () => {
  expect(runFilePath("r 1", "f/1", true)).toBe("/runs/r%201/files/f%2F1?inline=1");
  expect(publicFilePath("tok", img, true)).toBe(
    "/public/apps/tok/files/i1?sig=abc&exp=1700000000&inline=1",
  );
  expect(resolveFilePath(img, { token: "tok" })).toBe(
    "/public/apps/tok/files/i1?sig=abc&exp=1700000000",
  );
  // 토큰이 없으면(앱 안 시험) 실행 기록 경로, 서명이 없으면 토큰이 있어도 실행 기록 경로
  expect(resolveFilePath(img, {})).toBe("/runs/r1/files/i1");
  expect(resolveFilePath(xlsx, { token: "tok" })).toBe("/runs/r1/files/f1");
  expect(resolveFilePath({ ...xlsx, run_id: undefined }, {})).toBeNull();
});

test("일괄 실행 줄의 파일 경로: 로그인한 화면은 실행 기록, 공유 링크는 서명 주소", () => {
  expect(batchFilePath({ run_id: "r9" }, { id: "f1" })).toBe("/runs/r9/files/f1");
  expect(
    batchFilePath(
      {},
      { id: "f1", url: "https://x.example/api/v1/public/apps/tok/files/f1?sig=a&exp=5" },
    ),
  ).toBe("/api/v1/public/apps/tok/files/f1?sig=a&exp=5");
  expect(batchFilePath({}, { id: "f1", url: "https://x.example/runs/r1" })).toBeNull();
  expect(batchFilePath({}, { id: "f1" })).toBeNull();
});

test("이미지와 그 밖의 파일을 나눈다", () => {
  const { images, others } = splitFiles([xlsx, img]);
  expect(images.map((f) => f.id)).toEqual(["i1"]);
  expect(others.map((f) => f.id)).toEqual(["f1"]);
});

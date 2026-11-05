import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { FileList } from "@/components/files/FileList";
import { resolveFilePath, type OutputFile } from "@/lib/fileKinds";

const fetchFileBlob = vi.fn();
const downloadFile = vi.fn();
vi.mock("@/lib/api/files", () => ({
  fetchFileBlob: (...a: unknown[]) => fetchFileBlob(...a),
  downloadFile: (...a: unknown[]) => downloadFile(...a),
}));

const img: OutputFile = {
  id: "i1",
  filename: "이미지-1.png",
  mime: "image/png",
  size: 2048,
  kind: "image",
  run_id: "r1",
  sig: "s",
  exp: 99,
};
const sheet: OutputFile = {
  id: "f1",
  filename: "주간 보고.xlsx",
  mime: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  size: 5_500_000,
  kind: "file",
  run_id: "r1",
  sig: "s",
  exp: 99,
};
const resolve = (f: OutputFile, inline: boolean) => resolveFilePath(f, { token: "tok" }, inline);

beforeEach(() => {
  fetchFileBlob.mockReset();
  downloadFile.mockReset();
  fetchFileBlob.mockResolvedValue(new Blob(["x"], { type: "image/png" }));
  downloadFile.mockResolvedValue(undefined);
  URL.createObjectURL = vi.fn(() => "blob:fake");
  URL.revokeObjectURL = vi.fn();
});

test("파일이 없으면 아무것도 그리지 않는다", () => {
  const { container } = render(<FileList files={[]} resolve={resolve} />);
  expect(container.firstChild).toBeNull();
});

test("이미지는 받아서 그 자리에 보이고, 나머지는 내려받기 칩", async () => {
  render(<FileList files={[img, sheet]} resolve={resolve} />);
  // 이미지는 인라인 경로(서명 링크 + inline)로 받는다
  await waitFor(() =>
    expect(fetchFileBlob).toHaveBeenCalledWith(
      "/public/apps/tok/files/i1?sig=s&exp=99&inline=1",
      expect.anything(),
    ),
  );
  expect(await screen.findByAltText("이미지-1.png")).toBeTruthy();
  // 표 파일은 칩: 이름과 크기, 누르면 서명 링크로 내려받는다
  const chip = screen.getByRole("button", { name: "주간 보고.xlsx 내려받기" });
  expect(chip.textContent).toContain("5.2MB");
  fireEvent.click(chip);
  await waitFor(() =>
    expect(downloadFile).toHaveBeenCalledWith(
      "/public/apps/tok/files/f1?sig=s&exp=99",
      "주간 보고.xlsx",
    ),
  );
});

test("이미지를 누르면 크게 보이고 내려받기 버튼이 있다", async () => {
  render(<FileList files={[img]} resolve={resolve} />);
  fireEvent.click(await screen.findByRole("button", { name: "이미지-1.png 크게 보기" }));
  expect(await screen.findByRole("dialog")).toBeTruthy();
  const buttons = screen.getAllByRole("button", { name: /내려받기/ });
  fireEvent.click(buttons[buttons.length - 1] as HTMLElement);
  await waitFor(() => expect(downloadFile).toHaveBeenCalled());
});

test("그림을 못 받으면 안내를 보여 준다", async () => {
  fetchFileBlob.mockRejectedValue(new Error("x"));
  render(<FileList files={[img]} resolve={resolve} />);
  expect(await screen.findByText("그림을 불러오지 못했어요")).toBeTruthy();
});

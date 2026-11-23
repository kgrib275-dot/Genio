import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { QuickApprove } from "./QuickApprove";

test("확인한 뒤에만 승인·반려가 전달된다", () => {
  const onDecide = vi.fn();
  const confirm = vi.spyOn(window, "confirm");
  render(<QuickApprove title="휴가 신청" pending={false} onDecide={onDecide} />);
  confirm.mockReturnValueOnce(false);
  fireEvent.click(screen.getByRole("button", { name: "승인" }));
  expect(onDecide).not.toHaveBeenCalled();
  confirm.mockReturnValueOnce(true);
  fireEvent.click(screen.getByRole("button", { name: "반려" }));
  expect(onDecide).toHaveBeenCalledWith(false);
});

// IP 제한 편집기·웹앱 로고 시험
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { AppIcon } from "@/components/AppIcon";
import { IpEditor } from "@/components/deploy/IpEditor";

const mutate = vi.fn();
const fetchMyIp = vi.fn(async () => ({ ip: "203.0.113.44" }));

vi.mock("@/lib/api/ipAccess", () => ({
  useUpdateDeploymentIps: () => ({ mutate, isPending: false, error: null }),
  fetchMyIp: () => fetchMyIp(),
}));

const dep = { id: "d1", allowed_ips: ["10.0.0.0/8"] } as never;

describe("IP 제한 편집기", () => {
  beforeEach(() => mutate.mockReset());

  test("올바르지 않은 항목이 있으면 저장할 수 없고 어느 줄인지 알려 준다", () => {
    render(<IpEditor appId="a1" dep={dep} onClose={() => {}} />);
    const box = screen.getByLabelText("허용할 IP·대역");
    fireEvent.change(box, { target: { value: "10.0.0.1\n300.1.1.1" } });
    expect(screen.getByRole("alert").textContent).toContain("300.1.1.1");
    expect((screen.getByRole("button", { name: "저장" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(box, { target: { value: "10.0.0.1\n2001:db8::/32" } });
    expect((screen.getByRole("button", { name: "저장" }) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });

  test("내 IP 추가는 목록에 넣고, 없으면 경고한다", async () => {
    render(<IpEditor appId="a1" dep={dep} onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /내 IP 추가/ }));
    await waitFor(() => expect(screen.getByText(/지금 내 IP/)).toBeTruthy());
    expect((screen.getByLabelText("허용할 IP·대역") as HTMLTextAreaElement).value).toContain(
      "203.0.113.44",
    );
    fireEvent.change(screen.getByLabelText("허용할 IP·대역"), { target: { value: "10.0.0.1" } });
    expect(screen.getByText(/내 IP가 목록에 없어요/)).toBeTruthy();
  });

  test("저장하면 정리한 목록을 보내고, 제한 풀기는 빈 목록을 보낸다", () => {
    render(<IpEditor appId="a1" dep={dep} onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("허용할 IP·대역"), {
      target: { value: "1.1.1.1, 1.1.1.1\n2.2.2.0/24" },
    });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    expect(mutate.mock.calls[0]?.[0]).toEqual({ id: "d1", allowed_ips: ["1.1.1.1", "2.2.2.0/24"] });
    fireEvent.click(screen.getByRole("button", { name: "제한 풀기" }));
    expect(mutate.mock.calls[1]?.[0]).toEqual({ id: "d1", allowed_ips: [] });
  });
});

describe("웹앱 로고", () => {
  test("로고 주소가 있으면 그림을 보이고, 불러오지 못하면 기본 아이콘으로 돌아간다", () => {
    const { container } = render(<AppIcon name="휴가 봇" icon="🏖️" logoUrl="/logo.png" />);
    const img = container.querySelector("img");
    expect(img?.getAttribute("src")).toBe("/logo.png");
    fireEvent.error(img as HTMLImageElement);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("🏖️");
  });

  test("로고가 없으면 기존 아이콘", () => {
    const { container } = render(<AppIcon name="휴가 봇" />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toBe("휴");
  });
});

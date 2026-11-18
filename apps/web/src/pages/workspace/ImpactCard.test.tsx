import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ImpactCard } from "@/pages/workspace/ImpactCard";
import { formatMinutes } from "@/lib/api/impact";

vi.mock("@/lib/api/client", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      get: async () => ({
        apps: [
          {
            app_id: "a1",
            app_name: "문의 분류",
            succeeded_runs: 20,
            minutes_per_run: 15,
            saved_minutes: 300,
          },
          {
            app_id: "a2",
            app_name: "메일 요약",
            succeeded_runs: 4,
            minutes_per_run: 0,
            saved_minutes: 0,
          },
        ],
        total_succeeded_runs: 24,
        total_saved_minutes: 300,
        total_saved_hours: 5,
        unset_apps: 1,
        estimate: true,
      }),
    },
  };
});

describe("ImpactCard", () => {
  it("아낀 시간 합계와 앱별 계산, 미설정 안내를 보여 준다", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ImpactCard ws="w1" />
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("impact-total")).toHaveTextContent("5시간");
    expect(screen.getByText(/20건 × 15분/)).toBeInTheDocument();
    expect(screen.getByText(/미설정/)).toBeInTheDocument();
    expect(screen.getByText(/1개 앱은/)).toBeInTheDocument();
  });

  it("분을 시간·분으로 읽기 쉽게 바꾼다", () => {
    expect(formatMinutes(0)).toBe("0분");
    expect(formatMinutes(45)).toBe("45분");
    expect(formatMinutes(120)).toBe("2시간");
    expect(formatMinutes(150)).toBe("2시간 30분");
  });
});

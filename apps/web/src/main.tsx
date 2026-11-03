import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "@/App";
import { ApiError } from "@/lib/api/client";
import { applyFontSize, applyTheme, storedFontSize, storedTheme } from "@/store/theme";
import "@/index.css";

// 저장해 둔 테마를 바로 적용하고, 시스템 모드면 OS 설정 변화를 따라가게 한다
applyTheme(storedTheme());
applyFontSize(storedFontSize());

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: (count, err) =>
        !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
    },
  },
});
const root = document.getElementById("root");
if (!root) throw new Error("root 요소가 없습니다.");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);

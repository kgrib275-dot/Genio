/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.VITE_API_PROXY ?? "http://localhost:8190";
// Docker Desktop(Windows) 바인드 마운트는 파일 변경 알림을 넘기지 않아서 컨테이너 안에서는 폴링으로 감시한다.
const watch = process.env.VITE_USE_POLLING ? { usePolling: true, interval: 300 } : undefined;
const proxy = {
  // 정규식 키: "/api-docs" 같은 화면 주소가 API로 넘어가지 않게 "/api/"로 시작하는 것만 보낸다(nginx와 같은 규칙)
  "^/api/": { target: apiTarget, changeOrigin: true },
  "/health": { target: apiTarget, changeOrigin: true },
};

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  // Tailscale(*.ts.net) 등 외부 호스트 이름으로 접속할 수 있게 허용한다.
  server: { host: true, port: 5190, strictPort: true, allowedHosts: true, proxy, watch },
  preview: { host: true, port: 5190, strictPort: true, allowedHosts: true, proxy },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});

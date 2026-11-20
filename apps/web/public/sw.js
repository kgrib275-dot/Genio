// 홈 화면에 추가(PWA)를 위한 최소 서비스 워커. 일부러 아무것도 저장하지 않고 그대로 통과시킨다
// (로그인·실시간 데이터가 낡은 화면으로 보이는 일을 막기 위해).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});

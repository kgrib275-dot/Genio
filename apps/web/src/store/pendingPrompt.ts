// 대시보드에서 "말로 만들기"로 앱을 만든 뒤, 빌더가 열리면 그 요청을 한 번만 자동으로 보낸다.
const key = (appId: string) => `genio.pendingPrompt.${appId}`;

export function setPendingPrompt(appId: string, prompt: string): void {
  try {
    window.sessionStorage.setItem(key(appId), prompt);
  } catch {
    // 저장소를 못 쓰면 자동 전송만 건너뛴다
  }
}

export function takePendingPrompt(appId: string): string | null {
  try {
    const v = window.sessionStorage.getItem(key(appId));
    if (v !== null) window.sessionStorage.removeItem(key(appId));
    return v;
  } catch {
    return null;
  }
}

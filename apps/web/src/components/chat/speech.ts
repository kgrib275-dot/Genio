// 브라우저 음성 기능(말로 묻기·읽어 주기). 서버 비용이 들지 않는다.

export interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
}

export function sttSupported(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as Record<string, unknown>;
  return Boolean(w.SpeechRecognition ?? w.webkitSpeechRecognition);
}

export function ttsSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function getRecognition(): SpeechRecognitionLike | null {
  const w = window as unknown as Record<string, unknown>;
  const Ctor = (w.SpeechRecognition ?? w.webkitSpeechRecognition) as
    (new () => SpeechRecognitionLike) | undefined;
  return Ctor ? new Ctor() : null;
}

/** 마크다운 기호를 빼고 읽는다 */
export function speak(text: string): void {
  if (!ttsSupported()) return;
  window.speechSynthesis.cancel();
  const plain = text
    .replace(/```[\s\S]*?```/g, " 코드 ")
    .replace(/[#*_`>|-]/g, " ")
    .replace(/\[(.*?)\]\((.*?)\)/g, "$1");
  const u = new SpeechSynthesisUtterance(plain);
  u.lang = "ko-KR";
  window.speechSynthesis.speak(u);
}

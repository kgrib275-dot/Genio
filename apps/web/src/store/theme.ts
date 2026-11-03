// 테마(밝게·어둡게·시스템)와 글자 크기. html 클래스(dark, font-large)로 모든 화면에 적용한다.
// 깜빡임을 막으려고 index.html의 작은 스크립트가 같은 localStorage 값을 먼저 읽는다.
import { useEffect, useState } from "react";

export type ThemePref = "light" | "dark" | "system";
export type FontSizePref = "normal" | "large";

const THEME_KEY = "genio.theme";
const FONT_KEY = "genio.fontSize";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // 저장소를 못 쓰면 이번 화면에서만 적용된다
  }
}

export function storedTheme(): ThemePref {
  const v = read(THEME_KEY);
  return v === "light" || v === "dark" ? v : "system";
}

export function storedFontSize(): FontSizePref {
  return read(FONT_KEY) === "large" ? "large" : "normal";
}

function systemDark(): boolean {
  return typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)").matches
    : false;
}

let current: ThemePref = "system";
let unwatch: (() => void) | null = null;

function paint(): void {
  const dark = current === "dark" || (current === "system" && systemDark());
  document.documentElement.classList.toggle("dark", dark);
}

/** 테마를 적용하고 기억한다. system이면 OS 설정 변화를 따라간다. */
export function applyTheme(theme: ThemePref): void {
  current = theme;
  write(THEME_KEY, theme);
  paint();
  unwatch?.();
  unwatch = null;
  if (theme === "system" && typeof window.matchMedia === "function") {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => paint();
    mq.addEventListener?.("change", onChange);
    unwatch = () => mq.removeEventListener?.("change", onChange);
  }
}

export function applyFontSize(size: FontSizePref): void {
  write(FONT_KEY, size);
  document.documentElement.classList.toggle("font-large", size === "large");
}

/** 지금 화면이 어두운지(캔버스·코드 편집기 색 맞추기용). html 클래스 변화를 따라간다. */
export function useIsDark(): boolean {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    const el = document.documentElement;
    const obs = new MutationObserver(() => setDark(el.classList.contains("dark")));
    obs.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);
  return dark;
}

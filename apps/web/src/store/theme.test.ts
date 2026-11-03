import { applyFontSize, applyTheme } from "@/store/theme";

type Listener = () => void;

function mockSystemDark(initial: boolean) {
  let matches = initial;
  const listeners = new Set<Listener>();
  const mq = {
    get matches() {
      return matches;
    },
    media: "(prefers-color-scheme: dark)",
    addEventListener: (_: string, cb: Listener) => listeners.add(cb),
    removeEventListener: (_: string, cb: Listener) => listeners.delete(cb),
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => mq),
  );
  window.matchMedia = globalThis.matchMedia;
  return {
    set(next: boolean) {
      matches = next;
      listeners.forEach((cb) => cb());
    },
    listenerCount: () => listeners.size,
  };
}

const html = () => document.documentElement;

describe("테마 적용", () => {
  beforeEach(() => {
    html().className = "";
    window.localStorage.clear();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("어둡게는 dark 클래스를 붙이고 밝게는 뗀다", () => {
    mockSystemDark(false);
    applyTheme("dark");
    expect(html()).toHaveClass("dark");
    expect(window.localStorage.getItem("genio.theme")).toBe("dark");
    applyTheme("light");
    expect(html()).not.toHaveClass("dark");
  });

  it("시스템은 OS 설정을 따르고, 바뀌면 바로 따라간다", () => {
    const os = mockSystemDark(true);
    applyTheme("system");
    expect(html()).toHaveClass("dark");
    os.set(false);
    expect(html()).not.toHaveClass("dark");
    os.set(true);
    expect(html()).toHaveClass("dark");

    // 다른 테마로 바꾸면 OS 변화는 더 이상 따라가지 않는다
    applyTheme("light");
    expect(os.listenerCount()).toBe(0);
    os.set(true);
    expect(html()).not.toHaveClass("dark");
  });

  it("글자 크기 '크게'는 font-large 클래스를 붙인다", () => {
    applyFontSize("large");
    expect(html()).toHaveClass("font-large");
    applyFontSize("normal");
    expect(html()).not.toHaveClass("font-large");
  });
});

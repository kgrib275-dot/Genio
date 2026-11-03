import colors from "tailwindcss/colors";

// 테마(밝게·어둡게): slate 전체와 강조색의 연한 배경(50~200)·진한 글자(700~950)를
// CSS 변수로 바꿔, 컴포넌트를 고치지 않고도 html.dark 하나로 모든 화면이 바뀌게 한다.
// 변수 값은 src/theme.css (밝게 = Tailwind 기본값).
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
const SLATE = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
const FAMILIES = [
  "indigo",
  "violet",
  "emerald",
  "amber",
  "red",
  "sky",
  "rose",
  "pink",
  "fuchsia",
  "teal",
  "orange",
  "cyan",
  "purple",
];
const VAR_SHADES = [50, 100, 200, 700, 800, 900, 950];

const themed = {
  slate: Object.fromEntries(SLATE.map((s) => [s, v(`slate-${s}`)])),
};
for (const f of FAMILIES) {
  themed[f] = { ...colors[f], ...Object.fromEntries(VAR_SHADES.map((s) => [s, v(`${f}-${s}`)])) };
}

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: themed,
      fontFamily: {
        sans: [
          '"Pretendard Variable"',
          "Pretendard",
          "-apple-system",
          "BlinkMacSystemFont",
          '"Apple SD Gothic Neo"',
          '"Malgun Gothic"',
          "system-ui",
          "sans-serif",
        ],
      },
      boxShadow: {
        card: "0 1px 2px rgba(15, 23, 42, 0.04), 0 1px 3px rgba(15, 23, 42, 0.06)",
        lift: "0 4px 12px rgba(15, 23, 42, 0.08), 0 2px 4px rgba(15, 23, 42, 0.04)",
      },
    },
  },
  plugins: [],
};

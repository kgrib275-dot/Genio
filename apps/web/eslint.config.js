import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage", "node_modules"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.strict],
    files: ["**/*.{ts,tsx}"],
    languageOptions: { ecmaVersion: 2022, globals: globals.browser },
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // API 호출은 lib/api 훅으로만 한다(CLAUDE.md 코드 규칙).
      "no-restricted-globals": ["error", { name: "fetch", message: "lib/api/ 훅을 사용하세요." }],
    },
  },
  {
    files: ["src/lib/api/**/*.{ts,tsx}"],
    rules: { "no-restricted-globals": "off" },
  },
);

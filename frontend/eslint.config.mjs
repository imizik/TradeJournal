import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

/**
 * Next 16 removed `next lint`, so linting runs through the ESLint CLI against
 * this flat config. eslint-config-next 16 ships native flat configs, so they
 * are imported directly rather than through @eslint/eslintrc's FlatCompat.
 *
 * Severity policy, so that a red lint run always means "something is wrong"
 * rather than "this codebase predates the rule":
 *
 *   error - defects and dead code: things that are wrong regardless of taste.
 *   warn  - advisory rules, and pre-existing debt not yet paid down. Visible
 *           in output, but they do not fail the build. `npm run lint:strict`
 *           fails on warnings too, for when you want to drive a count to zero.
 *
 * The rules demoted below are the React Compiler advisories introduced in
 * eslint-plugin-react-hooks 7. They flag optimization opportunities, not bugs,
 * and firing 38 of them on existing components would have made lint useless on
 * day one. Promote them back to "error" once the counts are driven down.
 */
const reactCompilerAdvisories = {
  "react-hooks/static-components": "warn",
  "react-hooks/error-boundaries": "warn",
  "react-hooks/preserve-manual-memoization": "warn",
  "react-hooks/purity": "warn",
  "react-hooks/immutability": "warn",
  "react-hooks/set-state-in-effect": "warn",
};

const config = [
  {
    ignores: [".next/**", "node_modules/**", "next-env.d.ts", "*.tsbuildinfo"],
  },
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    rules: {
      ...reactCompilerAdvisories,
      // Real, but pre-existing across several pages: an <a> to an internal
      // route does a full document load and drops client state. Worth fixing,
      // not worth blocking every PR on today.
      "@next/next/no-html-link-for-pages": "warn",
    },
  },
  {
    // Build/tooling config files legitimately use CommonJS require().
    files: ["*.config.{js,mjs,ts}", "postcss.config.js"],
    rules: { "@typescript-eslint/no-require-imports": "off" },
  },
];

export default config;

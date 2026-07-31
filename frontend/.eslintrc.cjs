/* eslint-env node */
module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  parser: "@typescript-eslint/parser",
  parserOptions: {
    ecmaVersion: "latest",
    sourceType: "module",
    ecmaFeatures: { jsx: true }
  },
  plugins: ["@typescript-eslint", "react", "react-hooks"],
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react/recommended",
    "plugin:react-hooks/recommended",
    "prettier"
  ],
  settings: { react: { version: "detect" } },
  ignorePatterns: ["dist", "node_modules", "test-results", "*.cjs"],
  rules: {
    // Vite + the new JSX transform: React need not be in scope.
    "react/react-in-jsx-scope": "off",
    "react/prop-types": "off",
    "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }]
  },
  overrides: [
    {
      files: ["tests/**/*.ts", "*.config.ts"],
      env: { node: true }
    }
  ]
};

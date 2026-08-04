import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const pkg = JSON.parse(
  readFileSync(fileURLToPath(new URL("./package.json", import.meta.url)), "utf-8")
);

/*
 * Build-time stamps, so a running copy can say which build it is.
 *
 * `NEURONARRATIVE_VERSION` is set from the git tag by the release workflow and reaches this
 * through `scripts/build_desktop.sh`, which runs `npm run build` in the same environment —
 * the same variable the PyInstaller spec stamps into the macOS Info.plist, so the window and
 * the bundle can never disagree about their version.
 *
 * Falls back to package.json for a local build, and says "dev" for neither — a UI claiming a
 * release number it wasn't built from is worse than one admitting it is a working copy.
 */
const version = (process.env.NEURONARRATIVE_VERSION ?? "").replace(/^v/, "") || `${pkg.version}-dev`;
// The copyright year is whenever the build happened, not a constant somebody has to remember
// to bump every January.
const buildYear = String(new Date().getFullYear());
const buildDate = new Date().toISOString().slice(0, 10);

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(version),
    __BUILD_YEAR__: JSON.stringify(buildYear),
    __BUILD_DATE__: JSON.stringify(buildDate)
  },
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        // In Docker the backend is a sibling container, not localhost.
        target: process.env.VITE_PROXY_TARGET ?? "http://localhost:8000",
        changeOrigin: true
      }
    }
  }
});

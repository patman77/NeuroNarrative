import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
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

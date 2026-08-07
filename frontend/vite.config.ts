import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  /**
   * Asset base path.
   *
   * Defaults to "/" so `npm run dev` and a root-domain host both work untouched.
   * The Pages workflow sets `VITE_BASE=/pitwall-multiverse/` because Pages serves
   * project sites from a repo subpath.
   *
   * This is load-bearing in a way that is easy to miss: the fixtures are fetched
   * through `import.meta.glob(..., { query: "?url" })`, so their URLs are baked in
   * at build time. Get `base` wrong and the JS bundle loads perfectly, the page
   * renders its shell, and every single fixture fetch 404s — a failure that looks
   * like a data problem rather than a config one.
   */
  base: process.env.VITE_BASE ?? "/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_BASE_URL ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});

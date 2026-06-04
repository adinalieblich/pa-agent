import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// Build settings:
//   - `base: "/pwa-v2/"` so all asset URLs resolve under the FastAPI mount
//     point. Must end with a trailing slash.
//   - `build.outDir: "dist"` — FastAPI serves this directory verbatim.
//   - Dev server proxies /api and /capture to the running FastAPI on :8000
//     so we can develop with hot-reload without rebuilding the FastAPI app.
//   - VitePWA: auto-generates service worker + manifest, handles offline
//     caching of the app shell, and plumbs the install prompt.
export default defineConfig({
  base: "/pwa-v2/",
  plugins: [
    react(),
    VitePWA({
      // Use a custom service worker so we can add Web Push handlers
      // (push + notificationclick). The custom SW re-creates the same
      // workbox precache + runtime-cache config inline.
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.js",
      registerType: "autoUpdate",
      injectRegister: "auto",

      injectManifest: {
        globPatterns: ["**/*.{js,css,html,svg,png,ico,woff,woff2}"],
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
      },

      manifest: {
        name: "PA-Agent",
        short_name: "PA",
        description: "Voice-first personal AI assistant",
        start_url: "/pwa-v2/",
        scope: "/pwa-v2/",
        display: "standalone",
        orientation: "portrait",
        background_color: "#f9f0e5",
        theme_color: "#b73579",
        lang: "en",
        categories: ["productivity"],
        icons: [
          {
            src: "icons/icon-192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "icons/icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "icons/icon-512-maskable.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
          {
            src: "icons/apple-touch-icon.png",
            sizes: "180x180",
            type: "image/png",
            purpose: "any",
          },
        ],
      },

      // Don't enable in dev — Vite HMR + service worker = unreliable reloads.
      devOptions: {
        enabled: false,
      },
    }),
  ],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api":     { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/capture": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The frontend talks to the FastAPI backend through a SAME-ORIGIN "/api" proxy (see the
// server.proxy block below), NOT an absolute cross-origin base URL. Why: the session cookie is
// samesite="lax" (pucksim/web/session.py). If the page is open at http://localhost:5173 while the
// API is called at http://127.0.0.1:8000, the browser treats those as different sites (hostname,
// not port, defines a "site"), silently drops the cookie set by POST /career/new, and the app
// loops straight back to "Start New Career" on every subsequent request. Proxying "/api" through
// the dev server means every API call is same-origin with the page, so the cookie works whether
// you open the app at localhost:5173 OR 127.0.0.1:5173 -- the hostname footgun is gone.
//
// src/api.ts defaults its base URL to "/api" to match; VITE_API_BASE_URL still overrides it for a
// production build served without this proxy.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});

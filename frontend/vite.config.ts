import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Step 2.10a: standalone Vite dev server talking to the FastAPI backend over an
// absolute base URL (VITE_API_BASE_URL, see src/api.ts) rather than a dev-server
// proxy -- keeps the frontend able to point at any backend host/port without
// touching this file, and there's no "build straight into the backend's static
// dir" story yet (unlike HoopR) since PuckSim's web app hasn't wired static
// file serving -- revisit if/when it does.
//
// server.host is pinned to 127.0.0.1 (not the "localhost" default) to match the
// backend's default bind address. The session cookie is samesite="lax"
// (pucksim/web/session.py), and browsers treat "localhost" and "127.0.0.1" as
// different sites -- serving the frontend from "localhost" while the backend
// runs on "127.0.0.1" makes every API fetch cross-site, silently dropping the
// cookie and turning every post-login request into a 404.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
  },
});

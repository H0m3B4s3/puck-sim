import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Step 2.10a: standalone Vite dev server talking to the FastAPI backend over an
// absolute base URL (VITE_API_BASE_URL, see src/api.ts) rather than a dev-server
// proxy -- keeps the frontend able to point at any backend host/port without
// touching this file, and there's no "build straight into the backend's static
// dir" story yet (unlike HoopR) since PuckSim's web app hasn't wired static
// file serving -- revisit if/when it does.
export default defineConfig({
  plugins: [react()],
});

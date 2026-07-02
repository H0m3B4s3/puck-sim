/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the FastAPI backend, e.g. "http://127.0.0.1:8000". Defaults to
   * that same value in src/api.ts when unset (local dev, backend's own default host/port). */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// Typed client for the FastAPI backend's /career/* endpoints (DEVPLAN.md Step 2.9a).
//
// Session is cookie-carried (pucksim_sid, httponly, set by the backend on
// POST /career/new or /career/load) -- every request sends credentials: "include"
// so the browser attaches it automatically. There is no bearer token or header to
// manage client-side.
//
// Base URL is configurable via VITE_API_BASE_URL (a Vite env var, see
// src/vite-env.d.ts) rather than hardcoded or proxied through the dev server, so
// this client works unmodified against whatever host/port the backend happens to
// be running on (default 127.0.0.1:8000, matching pucksim.web.app's own default).

const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "") || "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      const d = body?.detail;
      if (Array.isArray(d)) {
        // FastAPI/pydantic validation errors: a list of {loc, msg, ...}.
        detail = d.map((e: { msg?: string }) => e.msg ?? String(e)).join("; ");
      } else if (typeof d === "string") {
        detail = d;
      }
    } catch {
      /* body wasn't JSON -- fall back to statusText */
    }
    throw new ApiError(res.status, detail);
  }
  // No-content-ish responses still parse fine since every endpoint here returns JSON.
  return res.json() as Promise<T>;
}

const get = <T>(path: string) => req<T>(path);
const post = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });

// --- response shapes (mirrors pucksim/web/serializers.py) ------------------

export interface TeamRecord {
  wins: number;
  losses: number;
  ot_losses: number;
  points: number;
  streak: string;
}

export interface TeamSummary {
  id: number;
  name: string;
  abbrev: string;
  conference: string;
  division: string;
  primary_color: string;
  secondary_color: string;
  /** null until the team has played a game this season. */
  record: TeamRecord | null;
}

export interface WorldSummary {
  season_year: number;
  phase: string;
  day: number;
  standings_rule: string;
  user_team_id: number | null;
}

export interface SaveResult {
  slot: string;
  path: string;
}

export interface StandingsEntry extends TeamSummary {
  points: number;
  wins: number;
  losses: number;
  ot_losses: number;
}

// --- request bodies ----------------------------------------------------------

export interface NewCareerRequest {
  seed?: number;
  user_team_abbrev?: string;
}

// --- client --------------------------------------------------------------

export const api = {
  /** POST /career/new -- generate a fresh league, start a session, set the session cookie. */
  newCareer: (body: NewCareerRequest = {}) =>
    post<WorldSummary>("/career/new", body),

  /** GET /career -- current session's career summary. 404s (ApiError) if no session cookie. */
  getCareer: () => get<WorldSummary>("/career"),

  /** POST /career/save -- writes the current session's World to `slot` (defaults server-side). */
  saveCareer: (slot?: string) => post<SaveResult>("/career/save", { slot }),

  /** POST /career/load -- loads `slot` into the current (or a brand-new) session. */
  loadCareer: (slot: string) => post<WorldSummary>("/career/load", { slot }),

  /** GET /career/saves -- every save slot on disk. */
  listSaves: () => get<string[]>("/career/saves"),

  /** GET /career/standings -- every team, ordered per the active standings rule. */
  getStandings: () => get<StandingsEntry[]>("/career/standings"),
};

export default api;

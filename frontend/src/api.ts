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
const put = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined });

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

// --- roster DTOs (mirrors pucksim/web/serializers.py) ----------------------

export interface ContractSummary {
  current_salary: number;
  years_remaining: number;
}

export interface PlayerSummary {
  pid: number;
  name: string;
  position: string;
  age: number;
  overall: number;
  shoots: string;
  secondary_position: string | null;
  injury_status: string | null;
  contract: ContractSummary;
}

export interface RosterResponse {
  players: PlayerSummary[];
}

export interface LineWithPlayers {
  players: PlayerSummary[];
}

export interface PairWithPlayers {
  players: PlayerSummary[];
}

export interface GoalieSlot {
  player: PlayerSummary | null;
}

export interface SpecialTeamsUnit {
  players: PlayerSummary[];
}

export interface RosterLinesResponse {
  lines: LineWithPlayers[];
  pairs: PairWithPlayers[];
  goalie_starter: GoalieSlot;
  goalie_backup: GoalieSlot;
  pp_unit_1: SpecialTeamsUnit;
  pk_unit_1: SpecialTeamsUnit;
}

export interface TacticsData {
  forecheck_style: string;
  pp_style: string;
  pk_aggression: string;
}

export interface CoachSummary {
  archetype: string;
  line_juggling_patience: number;
  pp_forwards: number;
  shot_volume: number;
  shot_quality_bias: number;
  defensive_risk_tolerance: number;
  goalie_pull_max_deficit: number;
  goalie_pull_time_threshold_secs: number;
}

export interface RosterTacticsResponse {
  tactics: TacticsData;
  coach: CoachSummary;
}

// --- season DTOs (mirrors pucksim/web/serializers.py) -----------------------

export interface ScheduleGame {
  gid: number;
  day: number;
  home: number;
  away: number;
  home_score: number;
  away_score: number;
  played: boolean;
  is_playoff: boolean;
}

export interface GamePlayedSummary {
  gid: number;
  home: number;
  away: number;
  home_score: number;
  away_score: number;
}

export interface AdvanceDayResponse {
  day: number;
  phase: string;
  games_played: GamePlayedSummary[];
}

// --- request bodies ----------------------------------------------------------

export interface NewCareerRequest {
  seed?: number;
  user_team_abbrev?: string;
}

export interface ManualLinesEditRequest {
  lines?: number[][];
  pairs?: number[][];
  goalie_starter?: number | null;
  goalie_backup?: number | null;
}

export interface AutoBuildLinesRequest {
  include_special_teams?: boolean;
}

export interface TacticsUpdateRequest {
  forecheck_style?: string;
  pp_style?: string;
  pk_aggression?: string;
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

  // --- Roster endpoints (Step 2.9b-i) ---

  /** GET /roster -- full roster with player summaries. */
  getRoster: () => get<RosterResponse>("/roster"),

  /** GET /roster/lines -- current lines, pairs, and special-teams units. */
  getRosterLines: () => get<RosterLinesResponse>("/roster/lines"),

  /** POST /roster/lines/auto -- auto-build lines and optional special teams. */
  autoBuildLines: (body: AutoBuildLinesRequest = {}) =>
    post<RosterLinesResponse>("/roster/lines/auto", body),

  /** PUT /roster/lines -- manually edit lines and pairs. */
  updateRosterLines: (body: ManualLinesEditRequest) =>
    put<RosterLinesResponse>("/roster/lines", body),

  /** GET /roster/tactics -- current tactics and coach summary. */
  getRosterTactics: () => get<RosterTacticsResponse>("/roster/tactics"),

  /** PUT /roster/tactics -- update tactics settings (partial update). */
  updateRosterTactics: (body: TacticsUpdateRequest) =>
    put<RosterTacticsResponse>("/roster/tactics", body),

  // --- Season endpoints (Step 2.9b-ii) ---

  /** POST /season/start -- generate the regular-season schedule and move out of preseason. */
  startSeason: () => post<WorldSummary>("/season/start"),

  /** GET /season/schedule -- all games in the season schedule. */
  getSchedule: () => get<ScheduleGame[]>("/season/schedule"),

  /** POST /season/advance-day -- simulate all games for the day, advance, return summary. */
  advanceDay: () => post<AdvanceDayResponse>("/season/advance-day"),

  /** GET /season/playoffs/bracket -- playoff bracket (null if not in playoffs yet). */
  getPlayoffBracket: () => get<Record<string, unknown> | null>("/season/playoffs/bracket"),
};

export default api;

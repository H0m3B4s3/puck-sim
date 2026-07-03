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

// --- Game/Box Score DTOs (DEVPLAN Step 2.9b-ii) --

export interface GameDTO {
  gid: number;
  day: number;
  home: number;
  away: number;
  home_score: number;
  away_score: number;
  played: boolean;
  is_playoff: boolean;
}

export interface SkaterBoxScoreDTO {
  pid: number;
  name: string;
  position: string;
  team_id: number | null;
  gp: number;
  gs: number;
  secs: number;
  g: number;
  a: number;
  sog: number;
  pim: number;
  hits: number;
  blocks: number;
  giveaways: number;
  takeaways: number;
  fo_won: number;
  fo_lost: number;
  plus_minus: number;
  corsi_for: number;
  corsi_against: number;
  fenwick_for: number;
  fenwick_against: number;
}

export interface GoalieBoxScoreDTO {
  pid: number;
  name: string;
  position: string;
  team_id: number | null;
  gp: number;
  gs: number;
  secs: number;
  shots_faced: number;
  saves: number;
  goals_against: number;
  wins: number;
  losses: number;
  otl: number;
  shutouts: number;
}

export interface BoxScoreResponse {
  gid: number;
  home_score: number;
  away_score: number;
  went_ot: boolean;
  went_so: boolean;
  skater_box: Record<number, SkaterBoxScoreDTO>;
  goalie_box: Record<number, GoalieBoxScoreDTO>;
}

// --- Transactions DTOs (DEVPLAN Step 2.9b-iii) --

export interface CapSummaryDTO {
  payroll: number;
  cap_space: number;
  over_cap: boolean;
  salary_cap: number;
}

export interface TransactionPlayerSummaryDTO {
  pid: number;
  name: string;
  position: string;
  age: number;
  overall: number;
  team_id: number | null;
}

export interface TradeResponseDTO {
  accepted: boolean;
  reason: string;
}

export interface DraftBoardEntryDTO {
  pid: number;
  name: string;
  position: string;
  age: number;
  overall: number;
  scouted_potential: number;
}

export interface DraftBoardDTO {
  in_draft: boolean;
  board: DraftBoardEntryDTO[];
  team_on_clock: number | null;
  round_number: number | null;
}

// --- request bodies ----------------------------------------------------------

export interface NewCareerRequest {
  seed?: number;
  user_team_abbrev?: string;
}

export interface TradeOfferRequest {
  other_team_id: number;
  user_sends: number[];
  user_receives: number[];
}

export interface SignFreeAgentRequest {
  salary?: number;
  years?: number;
}

export interface DraftPickRequest {
  prospect_id: number;
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

  // --- Season endpoints (Step 2.9b-ii) ---

  /** POST /season/start -- move out of preseason and generate the regular-season schedule. */
  startSeason: () => post<WorldSummary>("/season/start"),

  /** GET /season/schedule -- all games in the season schedule. */
  getSchedule: () => get<GameDTO[]>("/season/schedule"),

  /** POST /season/advance-day -- simulate all games scheduled for today. */
  advanceDay: () => post<{ day: number; phase: string; games_played: Array<{ gid: number; home: number; away: number; home_score: number; away_score: number }> }>("/season/advance-day"),

  /** POST /season/games/{gid}/sim -- simulate a single game on demand. */
  simGame: (gid: number) => post<{ gid: number; home_score: number; away_score: number; went_ot: boolean; went_so: boolean }>(`/season/games/${gid}/sim`),

  /** GET /season/games/{gid}/boxscore -- retrieve the box score for a played game. */
  getBoxScore: (gid: number) => get<BoxScoreResponse>(`/season/games/${gid}/boxscore`),

  // --- Transactions endpoints (Step 2.9b-iii) ---

  /** GET /transactions/cap -- cap summary for the user's team. */
  getCapSummary: () => get<CapSummaryDTO>("/transactions/cap"),

  /** GET /transactions/freeagents -- current free-agent board. */
  getFreeAgents: () => get<TransactionPlayerSummaryDTO[]>("/transactions/freeagents"),

  /** POST /transactions/freeagents/{pid}/sign -- sign a free agent. */
  signFreeAgent: (pid: number, body?: SignFreeAgentRequest) =>
    post<{ success: boolean; message: string }>(`/transactions/freeagents/${pid}/sign`, body || {}),

  /** POST /transactions/trades/propose -- propose a trade. */
  proposeTrade: (body: TradeOfferRequest) =>
    post<TradeResponseDTO>("/transactions/trades/propose", body),

  /** GET /transactions/draft/board -- current draft board state. */
  getDraftBoard: () => get<DraftBoardDTO>("/transactions/draft/board"),

  /** POST /transactions/draft/pick -- make a draft pick for the user's team. */
  makeDraftPick: (prospectId: number) =>
    post<{ prospect_id: number; prospect_name: string; signed: boolean; message: string }>("/transactions/draft/pick", { prospect_id: prospectId }),

  /** GET /transactions/awards -- end-of-season awards. */
  getAwards: () => get<{ season_year: number; awards: Record<string, unknown> }>("/transactions/awards"),
};

export default api;

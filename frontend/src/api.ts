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
  regular_season_complete: boolean;
  offseason_stage: string | null;
  trade_deadline_day: number | null;
  trade_deadline_passed: boolean;
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
  season_complete: boolean;
}

export interface AdvanceWeekResponse {
  day: number;
  phase: string;
  days_advanced: number;
  games_played: GamePlayedSummary[];
  user_games: GamePlayedSummary[];
  season_complete: boolean;
}

export interface SimToNextGameResponse {
  played: boolean;
  gid?: number;
  day?: number;
  phase: string;
  home?: number;
  away?: number;
  home_score?: number;
  away_score?: number;
  went_ot?: boolean;
  went_so?: boolean;
  season_complete: boolean;
}

// --- box score DTOs (mirrors pucksim/web/serializers.py) --------------------
// pid/name/position/team_id (added post-review, see routers/season.py's
// get_boxscore()) let a box-score screen label rows for BOTH teams, not just
// the session's own user_team.

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

// --- Player detail DTOs (mirrors pucksim/web/routers/players.py) ---------

export interface PlayerDetailDTO {
  pid: number;
  name: string;
  age: number;
  position: string;
  secondary_position: string | null;
  shoots: string;
  is_goalie: boolean;
  overall: number;
  potential: number;
  team_id: number | null;
  team_abbrev: string;
  team_name: string;
  team_color: string;
  salary: number;
  years_remaining: number;
  morale: number;
  injury: string | null;
  injury_games: number;
  draft: Record<string, unknown> | null;
  season_stats: Record<string, unknown>;
  playoff_stats: Record<string, unknown> | null;
  rating_groups: Record<string, Array<{ key: string; label: string; value: number }>>;
  career: Array<Record<string, unknown>>;
  legacy: Record<string, unknown> | null;
}

// --- transactions DTOs (mirrors pucksim/web/serializers.py) -----------------

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

export interface FreeAgentRow extends TransactionPlayerSummaryDTO {
  ask: number;
  preferred_years: number;
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

// --- League endpoints DTOs -----------------------------------------------

export interface LeaderEntry {
  pid: number;
  name: string;
  position: string;
  team_id: number | null;
  team_abbrev: string;
  team_color: string;
  value: number | string;
}

export interface LeaderCategory {
  stat: string;
  label: string;
  leaders: LeaderEntry[];
}

export interface LeadersResponse {
  categories: LeaderCategory[];
}

export interface AwardEntry {
  pid: number;
  name: string;
  position: string;
  team_id: number | null;
  team_abbrev: string;
  tid: number | null;
  gp: number;
  stats: Record<string, unknown>;
}

export interface SeasonHistory {
  year: number;
  champion_tid: number | null;
  champion_name: string;
  champion_abbrev: string;
  champion_color: string;
  awards: Record<string, AwardEntry>;
}

export interface HistoryResponse {
  seasons: SeasonHistory[];
}

export interface HallOfFameEntry {
  pid: number;
  name: string;
  position: string;
  seasons: number;
  peak_ovr: number;
  last_team: string;
  first_year: number;
  last_year: number;
  draft: Record<string, unknown> | null;
  active: boolean;
  totals: Record<string, unknown>;
  accolades: Array<{ key: string; label: string; count: number }>;
  hof_score: number;
  hof: boolean;
  induction_year: number;
}

export interface HallOfFameResponse {
  members: HallOfFameEntry[];
}

export interface LeaderboardRow {
  pid: number;
  name: string;
  position: string;
  active: boolean;
  value: number;
}

export interface LeaderboardResponse {
  category: string;
  categories: string[];
  rows: LeaderboardRow[];
}

// --- Playoffs endpoints DTOs -------------------------------------------------

export interface PlayoffsStateDTO {
  in_playoffs: boolean;
  can_start: boolean;
  bracket: Record<string, unknown> | null;
  complete: boolean;
  champion_tid: number | null;
  champion_name: string | null;
  champion_abbrev: string | null;
  champion_color: string | null;
  round: string | null;
  round_label: string | null;
}

export interface SlateSeries {
  sid: number;
  round: number;
  status: string;
  home_tid: number;
  away_tid: number;
  home_abbrev: string;
  away_abbrev: string;
  home_score: number;
  away_score: number;
  went_ot: boolean;
  went_so: boolean;
}

export interface AdvancePlayoffsResponse extends PlayoffsStateDTO {
  slate: SlateSeries[];
}

// --- Offseason endpoints DTOs ------------------------------------------------

export interface PreDraftResponse {
  resumed: boolean;
  retired: number;
  new_fas: number;
  inducted: Array<Record<string, unknown>>;
  milestones: Array<Record<string, unknown>>;
  champion_tid: number | null;
  champion_name: string;
  awards: Record<string, unknown> | null;
}

export interface OffseasonDraftBoardEntry {
  pid: number;
  name: string;
  position: string;
  age: number;
  overall: number;
  potential: number;
}

export interface OffseasonDraftBoardResponse {
  complete: boolean;
  pick: number | null;
  round: number | null;
  recent: Array<Record<string, unknown>>;
  board: OffseasonDraftBoardEntry[];
}

export interface OffseasonDraftPickResponse {
  pick: number;
  pid: number;
  name: string;
  position: string;
  overall: number;
  potential: number;
  signed: boolean;
}

export interface FAWaveDTO {
  active: boolean;
  wave: number;
  total: number;
  name: string;
}

export interface FAAdvanceResponse {
  signings: number;
  done: boolean;
  next: FAWaveDTO;
}

// --- Trade endpoints DTOs ------------------------------------------------

export interface TradeValidateResponse {
  legal: boolean;
  legal_reason: string;
  accepts: boolean;
  ai_reason: string;
}

export interface TradeExecuteResponse {
  executed: boolean;
  reason: string;
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

  /** POST /season/advance-week -- simulate multiple days (1-14) in one request. */
  advanceWeek: (days: number = 7) =>
    post<AdvanceWeekResponse>("/season/advance-week", { days }),

  /** POST /season/sim-to-next-game -- simulate until user's team plays their next game. */
  simToNextGame: () => post<SimToNextGameResponse>("/season/sim-to-next-game"),

  /** GET /season/playoffs/bracket -- playoff bracket (null if not in playoffs yet). */
  getPlayoffBracket: () => get<Record<string, unknown> | null>("/season/playoffs/bracket"),

  /** POST /season/games/{gid}/sim -- simulate a single game on demand. */
  simGame: (gid: number) =>
    post<{ gid: number; home_score: number; away_score: number; went_ot: boolean; went_so: boolean }>(
      `/season/games/${gid}/sim`,
    ),

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
    post<{ prospect_id: number; prospect_name: string; signed: boolean; message: string }>(
      "/transactions/draft/pick",
      { prospect_id: prospectId },
    ),

  /** GET /transactions/awards -- end-of-season awards. */
  getAwards: () => get<{ season_year: number; awards: Record<string, unknown> }>("/transactions/awards"),

  // --- Player detail (T6) ---

  /** GET /players/{pid} -- detailed player card with stats, ratings, legacy. */
  getPlayer: (pid: number) => get<PlayerDetailDTO>(`/players/${pid}`),

  // --- Roster detail (T6) ---

  /** GET /roster/{tid} -- roster for any team (not just user's team). */
  getTeamRoster: (tid: number) => get<RosterResponse>(`/roster/${tid}`),

  // --- League endpoints (T6) ---

  /** GET /league/leaders -- current season leaders by category. */
  getLeaders: () => get<LeadersResponse>("/league/leaders"),

  /** GET /league/history -- archived seasons with awards. */
  getHistory: () => get<HistoryResponse>("/league/history"),

  /** GET /league/hall-of-fame -- Hall of Fame members. */
  getHallOfFame: () => get<HallOfFameResponse>("/league/hall-of-fame"),

  /** GET /league/leaderboards?category=pts -- all-time leaderboard for a category. */
  getLeaderboards: (category: string) => get<LeaderboardResponse>(`/league/leaderboards?category=${category}`),

  // --- Playoffs endpoints (T6) ---

  /** GET /playoffs -- current playoff bracket state. */
  getPlayoffs: () => get<PlayoffsStateDTO>("/playoffs"),

  /** POST /playoffs/start -- start the playoffs (move from regular season to playoffs). */
  startPlayoffs: () => post<PlayoffsStateDTO>("/playoffs/start"),

  /** POST /playoffs/advance -- simulate the next playoff slate. */
  advancePlayoffs: () => post<AdvancePlayoffsResponse>("/playoffs/advance"),

  // --- Offseason endpoints (T6) ---

  /** POST /offseason/pre-draft -- begin offseason (retire, archive season, setup draft). */
  preDraft: () => post<PreDraftResponse>("/offseason/pre-draft"),

  /** GET /offseason/draft/board -- current draft board state. */
  offseasonDraftBoard: () => get<OffseasonDraftBoardResponse>("/offseason/draft/board"),

  /** POST /offseason/draft/pick -- make a draft pick (prospect_id optional for auto-best). */
  offseasonDraftPick: (prospectId: number | null) =>
    post<OffseasonDraftPickResponse>("/offseason/draft/pick", { prospect_id: prospectId }),

  /** POST /offseason/fa/start -- start free agency (enter wave 1). */
  faStart: () => post<FAWaveDTO>("/offseason/fa/start"),

  /** POST /offseason/fa/advance -- advance to next FA wave (rival GMs sign players). */
  faAdvance: () => post<FAAdvanceResponse>("/offseason/fa/advance"),

  /** POST /offseason/finish -- complete offseason and start next season. */
  finishOffseason: () => post<WorldSummary>("/offseason/finish"),

  // --- Trade endpoints (T6) ---

  /** POST /transactions/trades/validate -- check if a trade is legal and if AI accepts. */
  validateTrade: (body: TradeOfferRequest) =>
    post<TradeValidateResponse>("/transactions/trades/validate", body),

  /** POST /transactions/trades/execute -- execute a validated trade. */
  executeTrade: (body: TradeOfferRequest) =>
    post<TradeExecuteResponse>("/transactions/trades/execute", body),
};

export default api;

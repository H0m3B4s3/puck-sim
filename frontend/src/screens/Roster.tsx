// Roster management screen: roster table, lines/pairs editor, tactics panel (Step 2.10b).
//
// Displays the user's team roster, allows editing of forward lines/D-pairs/goalies,
// and provides controls for auto-building and tactics adjustment.

import { Fragment, useState } from "react";
import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
} from "@tanstack/react-table";
import type { SortingState } from "@tanstack/react-table";

import api, {
  PlayerSummary,
  LineSynergy,
  ManualLinesEditRequest,
  TacticsUpdateRequest,
  ApiError,
} from "../api";
import { Panel, FaceoffDotSpinner, formatMoney } from "../ui";

// Map a synergy tier to a theme color (elite=green, good=blue, ok=muted, poor=red).
const synergyTierColor = (tier: string): string =>
  tier === "elite"
    ? "var(--color-accent-green)"
    : tier === "good"
    ? "var(--color-accent-blue)"
    : tier === "poor"
    ? "var(--color-accent-red)"
    : "var(--color-muted)";

// A small pill for a player's coarse role (Finisher / Playmaker / Grinder / ...).
function RoleBadge({ label }: { label: string | null }) {
  if (!label) return null;
  return (
    <span
      style={{
        fontSize: "0.75rem",
        padding: "0.1rem 0.45rem",
        borderRadius: "var(--radius-sm)",
        background: "var(--color-surface-raised, rgba(127,127,127,0.14))",
        color: "var(--color-muted)",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}

// The line's role-synergy readout: a tier-colored pill ("Setup + finish 88").
function SynergyBadge({ synergy }: { synergy: LineSynergy | null }) {
  if (!synergy) return null;
  const color = synergyTierColor(synergy.tier);
  return (
    <span
      title={`Line role synergy: ${synergy.score}/100 — a line that pairs a setup man with a finisher generates better looks`}
      style={{
        fontSize: "0.75rem",
        fontWeight: 600,
        padding: "0.1rem 0.5rem",
        borderRadius: "999px",
        border: `1px solid ${color}`,
        color,
        whiteSpace: "nowrap",
      }}
    >
      {synergy.label} · {synergy.score}
    </span>
  );
}

// --- Roster Table Component ---

const columnHelper = createColumnHelper<PlayerSummary>();

const rosterColumns = (onPlayer?: (pid: number) => void) => [
  columnHelper.accessor("name", {
    header: "Name",
    size: 180,
    cell: (info) => (
      <button
        onClick={() => onPlayer?.(info.row.original.pid)}
        style={{
          background: "none",
          border: "none",
          padding: 0,
          color: "var(--color-accent-blue)",
          cursor: "pointer",
          textDecoration: "underline",
          fontWeight: 500,
          font: "inherit",
        }}
        title="View player details"
      >
        {String(info.getValue())}
      </button>
    ),
  }),
  columnHelper.accessor("position", {
    header: "Pos",
    size: 60,
  }),
  columnHelper.accessor("age", {
    header: "Age",
    size: 60,
  }),
  columnHelper.accessor("overall", {
    header: "Overall",
    size: 80,
  }),
  columnHelper.accessor("role_label", {
    header: "Role",
    size: 110,
    cell: (info) => <RoleBadge label={info.getValue() as string | null} />,
  }),
  columnHelper.display({
    id: "key_ratings",
    header: "Key Ratings",
    size: 210,
    cell: (info) => (
      <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
        {(info.row.original.key_ratings ?? []).map((r) => (
          <span
            key={r.label}
            title={`${r.label}: ${r.value}`}
            className="text-mono"
            style={{ fontSize: "0.8125rem", color: "var(--color-muted)" }}
          >
            {r.label}{" "}
            <strong style={{ color: "var(--color-text)" }}>{r.value}</strong>
          </span>
        ))}
      </div>
    ),
  }),
  columnHelper.accessor("shoots", {
    header: "Shoots",
    size: 70,
  }),
  columnHelper.accessor((row) => formatMoney(row.contract.current_salary), {
    id: "salary",
    header: "Salary",
    size: 100,
  }),
  columnHelper.accessor((row) => `${row.contract.years_remaining}yr`, {
    id: "contract_years",
    header: "Contract",
    size: 90,
  }),
  columnHelper.accessor("injury_status", {
    header: "Injury Status",
    size: 150,
  }),
];

function RosterTable({
  players,
  selectedPlayers,
  onPlayerSelect,
  onPlayer,
}: {
  players: PlayerSummary[];
  selectedPlayers: Set<number>;
  onPlayerSelect: (playerId: number) => void;
  onPlayer?: (pid: number) => void;
}) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "overall", desc: true },
  ]);

  const table = useReactTable({
    data: players,
    columns: rosterColumns(onPlayer),
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <Panel className="roster-table-container">
      <h3 className="text-display" style={{ marginBottom: "1rem" }}>
        Roster ({players.length} players)
      </h3>
      <div className="roster-table-scroll">
        <table className="roster-table">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    style={{ width: `${header.getSize()}px` }}
                    onClick={header.column.getToggleSortingHandler()}
                    className={
                      header.column.getCanSort() ? "sortable-header" : ""
                    }
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {header.column.getIsSorted() &&
                      ` ${header.column.getIsSorted() === "desc" ? "↓" : "↑"}`}
                  </th>
                ))}
                <th style={{ width: "80px" }}>Select</th>
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className={`roster-row--draggable${selectedPlayers.has(row.original.pid) ? " selected" : ""}`}
                draggable
                onDragStart={(e) =>
                  setDragPayload(e, { pid: row.original.pid, from: null })
                }
                title="Drag onto a line or pair slot below to place this player"
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} style={{ width: `${cell.column.getSize()}px` }}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
                <td style={{ width: "80px", textAlign: "center" }}>
                  <button
                    className="btn btn-secondary"
                    onClick={() => onPlayerSelect(row.original.pid)}
                    style={{ padding: "0.25rem 0.5rem", fontSize: "0.875rem" }}
                  >
                    {selectedPlayers.has(row.original.pid) ? "✓" : "○"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

// --- Lines/Pairs Editor Component ---
//
// Backend invariant (pucksim/web/routers/roster.py's PUT /roster/lines validation): every
// forward line sent must have EXACTLY 3 players, every D-pair EXACTLY 2 -- there is no
// "remove without replacement" available in this data model. So the only valid slot
// interaction is a SWAP: select a player in the roster table above, then click a slot to
// drop them into it (bumping out whoever was there, who simply becomes unassigned bench --
// no separate action needed, the backend's rotation_pool() picks up anyone not currently in
// a line/pair/goalie slot automatically). A prior version of this screen had a "Remove"
// button per slot that shrank the line/pair array below the required size, which the
// backend would always reject with a 400 -- fixed during review, not a design choice worth
// re-deriving.

// --- Drag-and-drop plumbing ------------------------------------------------------------------
//
// Native HTML5 drag-and-drop (no new dependency). A drag carries the dragged player's pid plus
// where he came FROM: a lineup slot, or null when dragged off the roster table (an unassigned
// bench player). The drop handler needs the origin because, per the exact-size invariant above,
// a drop can never leave a hole -- so a drag out of an occupied slot must SWAP with whatever is
// in the target slot rather than simply moving.
//
// dataTransfer payloads are only readable in the `drop` handler (browsers blank getData() during
// dragover for security), so dragover decides droppability from `types` alone.

type SlotGroup = "lines" | "pairs";
type SlotRef = { group: SlotGroup; row: number; slot: number };
type DragPayload = { pid: number; from: SlotRef | null };

const DRAG_MIME = "application/x-pucksim-player";

function setDragPayload(e: React.DragEvent, payload: DragPayload) {
  e.dataTransfer.setData(DRAG_MIME, JSON.stringify(payload));
  e.dataTransfer.effectAllowed = "move";
}

function readDragPayload(e: React.DragEvent): DragPayload | null {
  const raw = e.dataTransfer.getData(DRAG_MIME);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as DragPayload;
  } catch {
    return null;
  }
}

function LineSlot({
  player,
  target,
  expectedPosition,
  canPlace,
  onClick,
  onDropPlayer,
}: {
  player: PlayerSummary | null;
  target: SlotRef;
  expectedPosition: string;
  canPlace: boolean;
  onClick: () => void;
  onDropPlayer: (payload: DragPayload, target: SlotRef) => void;
}) {
  const [dragOver, setDragOver] = useState(false);
  // Out of position: the slot wants one position and this player plays another. A listed
  // secondary position counts as natural, so a C/LW filling a wing slot is not flagged.
  const outOfPosition =
    !!player &&
    player.position !== expectedPosition &&
    player.secondary_position !== expectedPosition;
  const classes = [
    "line-slot",
    canPlace ? "line-slot--placeable" : "",
    player ? "line-slot--filled" : "",
    dragOver ? "line-slot--dragover" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={classes}
      role="button"
      tabIndex={0}
      draggable={!!player}
      onDragStart={(e) => {
        if (player) setDragPayload(e, { pid: player.pid, from: target });
      }}
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes(DRAG_MIME)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const payload = readDragPayload(e);
        if (payload) onDropPlayer(payload, target);
      }}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      title={
        player
          ? `${player.name} -- drag onto another slot to swap, or select a roster player and click here to replace`
          : "Drag a player here, or select one in the roster table and click"
      }
    >
      {player ? (
        <div className="line-slot__player">
          <span className="line-slot__name">{player.name}</span>
          <span className="line-slot__meta">
            <span
              className={`line-slot__pos${outOfPosition ? " line-slot__pos--off" : ""}`}
              title={
                outOfPosition
                  ? `Natural ${player.position}, playing ${expectedPosition}`
                  : undefined
              }
            >
              {player.position}
              {player.secondary_position ? `/${player.secondary_position}` : ""}
            </span>
            {player.role_label && (
              <span className="line-slot__role">{player.role_label}</span>
            )}
          </span>
        </div>
      ) : (
        <div className="line-slot__empty">Empty</div>
      )}
    </div>
  );
}

// Position-across-the-top / units-down-the-side lineup grid: column headers are the positions
// (LW/C/RW for forwards, LD/RD for defense) and each row is one line or pair. Note the LD/RD
// labels are a display convention only -- the sim models D as one blended position and only cares
// that a pair is opposite-handed (models/team.py d_pair_fit_bonus), not which side each plays.
function LineupGrid({
  group,
  columnLabels,
  columnPositions,
  rows,
  rowLabel,
  rowBadge,
  canPlace,
  onSlotClick,
  onDropPlayer,
}: {
  group: SlotGroup;
  columnLabels: string[];
  // The roster POSITION each column expects. Distinct from columnLabels because the defense
  // grid's LD/RD headers are a display convention over a single blended "D" position.
  columnPositions: string[];
  rows: PlayerSummary[][];
  rowLabel: (index: number) => string;
  rowBadge?: (index: number) => React.ReactNode;
  canPlace: boolean;
  onSlotClick: (row: number, slot: number) => void;
  onDropPlayer: (payload: DragPayload, target: SlotRef) => void;
}) {
  return (
    <div
      className="lineup-grid"
      style={{ ["--lineup-cols" as string]: columnLabels.length }}
    >
      <div className="lineup-grid__corner" aria-hidden="true" />
      {columnLabels.map((label) => (
        <div key={label} className="lineup-grid__colhead">
          {label}
        </div>
      ))}
      {rows.map((rowPlayers, r) => (
        <Fragment key={`${group}-${r}`}>
          <div className="lineup-grid__rowhead">
            <span className="lineup-grid__rowname">{rowLabel(r)}</span>
            {rowBadge?.(r)}
          </div>
          {columnLabels.map((_, c) => (
            <LineSlot
              key={c}
              player={rowPlayers[c] || null}
              target={{ group, row: r, slot: c }}
              expectedPosition={columnPositions[c]}
              canPlace={canPlace}
              onClick={() => onSlotClick(r, c)}
              onDropPlayer={onDropPlayer}
            />
          ))}
        </Fragment>
      ))}
    </div>
  );
}

// Read-only view of the current top power-play and penalty-kill units. The backend already
// serves these (and auto-build now fills them), and special teams meaningfully affect the sim, so
// a manager should at least be able to SEE who is out there on the man-advantage/shorthanded.
function SpecialTeamsPanel({
  ppUnit,
  pkUnit,
  onPlayer,
}: {
  ppUnit: PlayerSummary[];
  pkUnit: PlayerSummary[];
  onPlayer?: (pid: number) => void;
}) {
  const renderUnit = (title: string, unit: PlayerSummary[]) => (
    <div style={{ flex: 1, minWidth: "220px" }}>
      <h4 style={{ marginBottom: "0.5rem" }}>{title}</h4>
      {unit.length === 0 ? (
        <p className="text-muted" style={{ fontSize: "0.875rem" }}>
          No unit set — use “Auto-build Lines &amp; Units”.
        </p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {unit.map((p) => (
            <li key={p.pid} style={{ padding: "0.3rem 0", display: "flex", gap: "0.5rem" }}>
              <span className="text-mono text-muted" style={{ width: "2.5rem" }}>
                {p.position}
              </span>
              <button
                onClick={() => onPlayer?.(p.pid)}
                style={{
                  background: "none",
                  border: "none",
                  padding: 0,
                  color: "var(--color-accent-blue)",
                  cursor: "pointer",
                  textDecoration: "underline",
                  font: "inherit",
                }}
                title="View player details"
              >
                {p.name}
              </button>
              <span className="text-mono text-muted">{p.overall}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );

  return (
    <div>
      <h3 style={{ marginBottom: "0.75rem" }}>Special Teams</h3>
      <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap" }}>
        {renderUnit("Power Play (PP1)", ppUnit)}
        {renderUnit("Penalty Kill (PK1)", pkUnit)}
      </div>
    </div>
  );
}

function LinesEditor({
  lines,
  lineSynergies,
  pairs,
  goalieStarter,
  goalieBackup,
  selectedPlayer,
  onPlaceInLine,
  onPlaceInPair,
  onSetGoalie,
  onDropPlayer,
}: {
  lines: PlayerSummary[][];
  lineSynergies: (LineSynergy | null)[];
  pairs: PlayerSummary[][];
  goalieStarter: PlayerSummary | null;
  goalieBackup: PlayerSummary | null;
  selectedPlayer: PlayerSummary | null;
  onPlaceInLine: (lineIndex: number, slotIndex: number) => void;
  onPlaceInPair: (pairIndex: number, slotIndex: number) => void;
  onSetGoalie: (which: "starter" | "backup") => void;
  onDropPlayer: (payload: DragPayload, target: SlotRef) => void;
}) {
  const canPlace = selectedPlayer !== null;
  return (
    <Panel className="lines-editor">
      <h3 className="text-display" style={{ marginBottom: "0.5rem" }}>
        Forward Lines & Defense Pairs
      </h3>
      <p className="text-muted" style={{ marginBottom: "1.5rem", fontSize: "0.875rem" }}>
        {selectedPlayer
          ? `Selected: ${selectedPlayer.name} -- click a slot below to place them there.`
          : "Drag players between slots to swap them, or drag one in from the roster table above. (You can also select a player above, then click a slot.)"}
      </p>

      <h4 className="lineup-section__title">Forwards</h4>
      <LineupGrid
        group="lines"
        columnLabels={["LW", "C", "RW"]}
        columnPositions={["LW", "C", "RW"]}
        rows={lines}
        rowLabel={(i) => `Line ${i + 1}`}
        rowBadge={(i) => <SynergyBadge synergy={lineSynergies[i] ?? null} />}
        canPlace={canPlace}
        onSlotClick={(row, slot) => onPlaceInLine(row, slot)}
        onDropPlayer={onDropPlayer}
      />

      <h4 className="lineup-section__title" style={{ marginTop: "2rem" }}>
        Defense
      </h4>
      <LineupGrid
        group="pairs"
        columnLabels={["LD", "RD"]}
        columnPositions={["D", "D"]}
        rows={pairs}
        rowLabel={(i) => `Pair ${i + 1}`}
        canPlace={canPlace}
        onSlotClick={(row, slot) => onPlaceInPair(row, slot)}
        onDropPlayer={onDropPlayer}
      />

      <div className="goalies-section" style={{ marginTop: "2rem", paddingTop: "1.5rem", borderTop: "1px solid var(--color-border)" }}>
        <h4 className="text-display" style={{ fontSize: "1.25rem", marginBottom: "1rem" }}>
          Goalies
        </h4>
        <div className="goalies-grid">
          <div className="goalie-slot">
            <div style={{ fontWeight: 600, marginBottom: "0.5rem" }}>Starter</div>
            <div className="line-slot__player" style={{ fontSize: "0.9rem" }}>
              <span>{goalieStarter ? goalieStarter.name : "Empty"}</span>
              <button
                className="btn btn-secondary"
                onClick={() => onSetGoalie("starter")}
                disabled={!canPlace}
                style={{ padding: "0.25rem 0.5rem", fontSize: "0.75rem", marginLeft: "0.5rem" }}
              >
                Set from selection
              </button>
            </div>
          </div>
          <div className="goalie-slot">
            <div style={{ fontWeight: 600, marginBottom: "0.5rem" }}>Backup</div>
            <div className="line-slot__player" style={{ fontSize: "0.9rem" }}>
              <span>{goalieBackup ? goalieBackup.name : "Empty"}</span>
              <button
                className="btn btn-secondary"
                onClick={() => onSetGoalie("backup")}
                disabled={!canPlace}
                style={{ padding: "0.25rem 0.5rem", fontSize: "0.75rem", marginLeft: "0.5rem" }}
              >
                Set from selection
              </button>
            </div>
          </div>
        </div>
      </div>
    </Panel>
  );
}

// --- Tactics Panel Component ---

function TacticsPanel({
  tactics,
  coach,
  isLoading,
  onTacticsChange,
}: {
  tactics: { forecheck_style: string; pp_style: string; pk_aggression: string };
  coach: {
    archetype: string;
    line_juggling_patience: number;
    pp_forwards: number;
  };
  isLoading: boolean;
  onTacticsChange: (field: string, value: string) => void;
}) {
  const tacticsOptions = {
    forecheck_style: ["passive", "balanced", "aggressive"],
    pp_style: ["umbrella", "overload", "spread"],
    pk_aggression: ["passive", "balanced", "aggressive"],
  };

  const tacticLabels = {
    forecheck_style: "Forecheck Style",
    pp_style: "Power Play Style",
    pk_aggression: "Penalty Kill Aggression",
  };

  return (
    <Panel className="tactics-panel">
      <h3 className="text-display" style={{ marginBottom: "1.5rem" }}>
        Tactics & Coach
      </h3>

      <div className="coach-summary" style={{ marginBottom: "2rem", paddingBottom: "1.5rem", borderBottom: "1px solid var(--color-border)" }}>
        <h4 style={{ marginBottom: "0.5rem" }}>Coach Archetype</h4>
        <p style={{ margin: 0, fontSize: "0.95rem" }}>{coach.archetype}</p>
        <ul style={{ marginTop: "0.75rem", marginLeft: "1rem", fontSize: "0.875rem", color: "var(--color-muted)" }}>
          <li>Line Juggling Patience: {coach.line_juggling_patience.toFixed(2)}</li>
          <li>PP Formation: {coach.pp_forwards}F</li>
        </ul>
      </div>

      <div className="tactics-settings">
        {(["forecheck_style", "pp_style", "pk_aggression"] as const).map((field) => (
          <div key={field} className="tactic-setting" style={{ marginBottom: "1.5rem" }}>
            <label htmlFor={field} style={{ display: "block", fontWeight: 600, marginBottom: "0.5rem" }}>
              {tacticLabels[field]}
            </label>
            <select
              id={field}
              value={tactics[field]}
              onChange={(e) => onTacticsChange(field, e.target.value)}
              disabled={isLoading}
              className="tactic-select"
              style={{
                width: "100%",
                padding: "0.5rem",
                fontSize: "0.95rem",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--color-border)",
                backgroundColor: "var(--color-surface-card)",
                color: "var(--color-text)",
                cursor: isLoading ? "not-allowed" : "pointer",
              }}
            >
              {tacticsOptions[field].map((option) => (
                <option key={option} value={option}>
                  {option.charAt(0).toUpperCase() + option.slice(1)}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// --- Main Roster Screen ---

export function RosterScreen({
  onPlayer,
}: {
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
} = {}) {
  const queryClient = useQueryClient();

  const [selectedPlayer, setSelectedPlayer] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch roster
  const {
    data: rosterData,
    isLoading: rosterLoading,
    error: rosterError,
  } = useQuery({
    queryKey: ["roster"],
    queryFn: () => api.getRoster(),
  });

  // Fetch lines
  const {
    data: linesData,
    isLoading: linesLoading,
  } = useQuery({
    queryKey: ["roster", "lines"],
    queryFn: () => api.getRosterLines(),
  });

  // Fetch tactics
  const {
    data: tacticsData,
    isLoading: tacticsLoading,
  } = useQuery({
    queryKey: ["roster", "tactics"],
    queryFn: () => api.getRosterTactics(),
  });

  // Mutation: auto-build lines
  const autoBuildMutation = useMutation({
    mutationFn: () => api.autoBuildLines({ include_special_teams: true }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["roster", "lines"] });
      setError(null);
    },
    onError: (err) => {
      const errorMsg = err instanceof ApiError ? err.message : "Failed to auto-build lines";
      setError(errorMsg);
    },
  });

  // Mutation: update lines
  const updateLinesMutation = useMutation({
    mutationFn: (body: ManualLinesEditRequest) => api.updateRosterLines(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["roster", "lines"] });
      setError(null);
    },
    onError: (err) => {
      const errorMsg = err instanceof ApiError ? err.message : "Failed to update lines";
      setError(errorMsg);
    },
  });

  // Mutation: update tactics
  const updateTacticsMutation = useMutation({
    mutationFn: (body: TacticsUpdateRequest) => api.updateRosterTactics(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["roster", "tactics"] });
      setError(null);
    },
    onError: (err) => {
      const errorMsg = err instanceof ApiError ? err.message : "Failed to update tactics";
      setError(errorMsg);
    },
  });

  if (rosterError) {
    return (
      <Panel className="screen screen-roster">
        <h2 className="text-display">Roster</h2>
        <p className="text-muted" style={{ marginTop: "1rem" }}>
          Error loading roster: {rosterError instanceof ApiError ? rosterError.message : "Unknown error"}
        </p>
      </Panel>
    );
  }

  if (rosterLoading || linesLoading || tacticsLoading) {
    return <FaceoffDotSpinner />;
  }

  if (!rosterData || !linesData || !tacticsData) {
    return (
      <Panel className="screen screen-roster">
        <p className="text-muted">No data available</p>
      </Panel>
    );
  }

  const currentLines = linesData.lines.map((line) => line.players);
  const lineSynergies = linesData.lines.map((line) => line.synergy);
  const currentPairs = linesData.pairs.map((pair) => pair.players);
  const selectedPlayerObj = rosterData.players.find((p) => p.pid === selectedPlayer) ?? null;

  // Every placement sends the FULL lines/pairs arrays (never a partial slice) -- the backend
  // requires every line to have exactly 3 players and every pair exactly 2 on every PUT, so
  // there is no such thing as a single-slot partial update in this data model.
  const placeInLine = (lineIndex: number, slotIndex: number) => {
    if (!selectedPlayerObj) return;
    const newLines = currentLines.map((line) => [...line]);
    newLines[lineIndex][slotIndex] = selectedPlayerObj;
    updateLinesMutation.mutate({ lines: newLines.map((line) => line.map((p) => p.pid)) });
    setSelectedPlayer(null);
  };

  const placeInPair = (pairIndex: number, slotIndex: number) => {
    if (!selectedPlayerObj) return;
    const newPairs = currentPairs.map((pair) => [...pair]);
    newPairs[pairIndex][slotIndex] = selectedPlayerObj;
    updateLinesMutation.mutate({ pairs: newPairs.map((pair) => pair.map((p) => p.pid)) });
    setSelectedPlayer(null);
  };

  // Drag-and-drop placement. The backend requires every line to be exactly 3 and every pair
  // exactly 2, and rejects a duplicate player within either group -- so a drop can never leave a
  // hole and can never clone anyone. That makes the rule simple:
  //   * dragged player already in a lineup slot -> SWAP him with the target's occupant
  //   * dragged player from the bench/roster table -> REPLACE the occupant (who becomes bench)
  // A bench player who is nonetheless already assigned somewhere is resolved to his real slot
  // first (findSlot below), so dragging a roster row onto a slot can't duplicate him either.
  const handleDropPlayer = (payload: DragPayload, target: SlotRef) => {
    const dragged = rosterData.players.find((p) => p.pid === payload.pid);
    if (!dragged) return;

    const newLines = currentLines.map((line) => [...line]);
    const newPairs = currentPairs.map((pair) => [...pair]);
    const gridFor = (group: SlotGroup) => (group === "lines" ? newLines : newPairs);

    const findSlot = (pid: number): SlotRef | null => {
      for (const group of ["lines", "pairs"] as SlotGroup[]) {
        const grid = gridFor(group);
        for (let r = 0; r < grid.length; r++) {
          for (let s = 0; s < grid[r].length; s++) {
            if (grid[r][s]?.pid === pid) return { group, row: r, slot: s };
          }
        }
      }
      return null;
    };

    const origin = payload.from ?? findSlot(dragged.pid);
    if (
      origin &&
      origin.group === target.group &&
      origin.row === target.row &&
      origin.slot === target.slot
    ) {
      return; // dropped on itself
    }

    const occupant = gridFor(target.group)[target.row]?.[target.slot] ?? null;
    // Moving OUT of a slot into an empty one would shrink the origin line below its required
    // size, which the backend always rejects -- there is nothing to swap back. Refuse instead of
    // firing a request that is guaranteed to 400.
    if (origin && !occupant) return;

    gridFor(target.group)[target.row][target.slot] = dragged;
    if (origin && occupant) {
      gridFor(origin.group)[origin.row][origin.slot] = occupant;
    }

    const touched = new Set<SlotGroup>([target.group]);
    if (origin) touched.add(origin.group);

    const body: ManualLinesEditRequest = {};
    if (touched.has("lines")) body.lines = newLines.map((l) => l.map((p) => p.pid));
    if (touched.has("pairs")) body.pairs = newPairs.map((p) => p.map((x) => x.pid));
    updateLinesMutation.mutate(body);
    setSelectedPlayer(null);
  };

  const setGoalie = (which: "starter" | "backup") => {
    if (!selectedPlayerObj) return;
    if (which === "starter") {
      updateLinesMutation.mutate({ goalie_starter: selectedPlayerObj.pid });
    } else {
      updateLinesMutation.mutate({ goalie_backup: selectedPlayerObj.pid });
    }
    setSelectedPlayer(null);
  };

  const handleTacticsChange = (field: string, value: string) => {
    const body: TacticsUpdateRequest = {};
    (body as any)[field] = value;
    updateTacticsMutation.mutate(body);
  };

  return (
    <div className="screen screen-roster">
      {error && (
        <Panel className="error-banner" style={{ marginBottom: "1rem", borderLeft: "4px solid var(--color-accent-red)", padding: "1rem" }}>
          <strong>Error:</strong> {error}
          <button
            className="btn btn-secondary"
            onClick={() => setError(null)}
            style={{ marginLeft: "1rem", padding: "0.25rem 0.5rem", fontSize: "0.875rem" }}
          >
            Dismiss
          </button>
        </Panel>
      )}

      <RosterTable
        players={rosterData.players}
        selectedPlayers={selectedPlayer ? new Set([selectedPlayer]) : new Set()}
        onPlayerSelect={(pid) => setSelectedPlayer((cur) => (cur === pid ? null : pid))}
        onPlayer={onPlayer}
      />

      <div style={{ marginTop: "2rem" }}>
        <LinesEditor
          lines={currentLines}
          lineSynergies={lineSynergies}
          pairs={currentPairs}
          goalieStarter={linesData.goalie_starter.player}
          goalieBackup={linesData.goalie_backup.player}
          selectedPlayer={selectedPlayerObj}
          onPlaceInLine={placeInLine}
          onPlaceInPair={placeInPair}
          onDropPlayer={handleDropPlayer}
          onSetGoalie={setGoalie}
        />
        <div style={{ marginTop: "1.5rem", display: "flex", gap: "1rem" }}>
          <button
            className="btn btn-primary"
            onClick={() => autoBuildMutation.mutate()}
            disabled={autoBuildMutation.isPending || updateLinesMutation.isPending}
          >
            {autoBuildMutation.isPending ? "Auto-building..." : "Auto-build Lines & Units"}
          </button>
        </div>
      </div>

      <div style={{ marginTop: "2rem" }}>
        <SpecialTeamsPanel
          ppUnit={linesData.pp_unit_1.players}
          pkUnit={linesData.pk_unit_1.players}
          onPlayer={onPlayer}
        />
      </div>

      <div style={{ marginTop: "2rem" }}>
        <TacticsPanel
          tactics={tacticsData.tactics}
          coach={tacticsData.coach}
          isLoading={updateTacticsMutation.isPending}
          onTacticsChange={handleTacticsChange}
        />
      </div>
    </div>
  );
}

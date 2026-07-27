// Lines/Pairs editor screen: dedicated tab for lineup management (Step 2.10b refactor).
//
// Displays forward lines, defense pairs, goalie slots, and special teams.
// Allows drag-and-drop and click-to-place editing of lineup slots.
// Auto-build lines and display their role synergy.

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
  ScratchStatus,
  ApiError,
} from "../api";
import { Panel, FaceoffDotSpinner, formatMoney, RareArchetypeBadge } from "../ui";

// Map a synergy tier to a theme color (elite=green, good=blue, ok=muted, poor=red).
const synergyTierColor = (tier: string): string =>
  tier === "elite"
    ? "var(--color-accent-green)"
    : tier === "good"
    ? "var(--color-accent-blue)"
    : tier === "poor"
    ? "var(--color-accent-red)"
    : "var(--color-muted)";

// A small pill for a line's role synergy (Setup + finish · 88).
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

// --- Drag-and-drop plumbing ------------------------------------------------------------------
//
// Native HTML5 drag-and-drop (no new dependency). A drag carries the dragged player's pid plus
// where he came FROM: a lineup slot, or null when dragged off the bench table (an unassigned
// bench player). The drop handler needs the origin because, per the exact-size invariant (every
// line exactly 3, every pair exactly 2), a drop can never leave a hole -- so a drag out of an
// occupied slot must SWAP with whatever is in the target slot rather than simply moving.

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
          <RareArchetypeBadge archetype={player.archetype} isRare={player.is_rare_archetype} />
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
            <span className="text-mono text-muted">{player.overall}</span>
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
          No unit set — use "Auto-build Lines &amp; Units".
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

// --- Bench/Available Players Table ---

const benchColumnHelper = createColumnHelper<PlayerSummary>();

const benchColumns = (
  onPlayer?: (pid: number) => void,
) => [
  benchColumnHelper.accessor("name", {
    header: "Name",
    size: 180,
    cell: (info) => (
      <>
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
        <RareArchetypeBadge archetype={info.row.original.archetype} isRare={info.row.original.is_rare_archetype} />
      </>
    ),
  }),
  benchColumnHelper.accessor("position", {
    header: "Pos",
    size: 60,
    cell: (info) => {
      const pos = info.getValue();
      const secondary = info.row.original.secondary_position;
      return secondary ? `${pos}/${secondary}` : pos;
    },
  }),
  benchColumnHelper.accessor("age", {
    header: "Age",
    size: 60,
  }),
  benchColumnHelper.accessor("overall", {
    header: "Overall",
    size: 80,
  }),
  benchColumnHelper.accessor((row) => formatMoney(row.contract.current_salary), {
    id: "salary",
    header: "Salary",
    size: 100,
  }),
  benchColumnHelper.accessor((row) => `${row.contract.years_remaining}yr`, {
    id: "contract_years",
    header: "Contract",
    size: 90,
  }),
];

function BenchTable({
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
    columns: benchColumns(onPlayer),
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <Panel className="bench-table-container">
      <h3 className="text-display" style={{ marginBottom: "0.5rem" }}>
        Available Players ({players.length})
      </h3>
      <div className="bench-table-scroll">
        <table className="bench-table">
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
                className={`bench-row--draggable${selectedPlayers.has(row.original.pid) ? " selected" : ""}`}
                style={row.original.scratched ? { opacity: 0.55 } : undefined}
                draggable
                onDragStart={(e) =>
                  setDragPayload(e, { pid: row.original.pid, from: null })
                }
                title="Drag onto a line or pair slot to place this player"
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
  scratchStatus,
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
  scratchStatus?: ScratchStatus | null;
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

      {scratchStatus && (
        <div
          className="scratched-section"
          style={{ marginTop: "2rem", paddingTop: "1.5rem", borderTop: "1px solid var(--color-border)" }}
        >
          <h4 className="text-display" style={{ fontSize: "1.25rem", marginBottom: "0.5rem" }}>
            Scratched
          </h4>
          <p style={{ fontSize: "0.875rem", color: "var(--color-muted)", marginBottom: "0.75rem" }}>
            A game dresses {scratchStatus.dressed_limit} players ({scratchStatus.skaters_dressed}{" "}
            skaters and {scratchStatus.goalies_dressed} goalies). Everyone below sits.
          </p>

          {scratchStatus.overridden.length > 0 && (
            <p
              style={{
                fontSize: "0.875rem",
                color: "var(--color-accent-amber, #d97706)",
                marginBottom: "0.75rem",
              }}
            >
              Injuries left too few healthy players, so{" "}
              {scratchStatus.overridden.map((p) => p.name).join(", ")}{" "}
              {scratchStatus.overridden.length === 1 ? "was" : "were"} dressed despite being
              scratched.
            </p>
          )}

          {(scratchStatus.short_skaters > 0 || scratchStatus.short_goalies > 0) && (
            <p
              style={{
                fontSize: "0.875rem",
                color: "var(--color-accent-red, #dc2626)",
                marginBottom: "0.75rem",
              }}
            >
              Roster too thin to dress a full lineup: short{" "}
              {scratchStatus.short_skaters > 0 && `${scratchStatus.short_skaters} skater(s)`}
              {scratchStatus.short_skaters > 0 && scratchStatus.short_goalies > 0 && " and "}
              {scratchStatus.short_goalies > 0 && `${scratchStatus.short_goalies} goalie(s)`}.
            </p>
          )}

          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {scratchStatus.scratched.length === 0 && (
              <span style={{ color: "var(--color-muted)", fontSize: "0.9rem" }}>
                Nobody scratched.
              </span>
            )}
            {scratchStatus.scratched.map((p) => (
              <span
                key={p.pid}
                className="line-slot__player"
                style={{ fontSize: "0.875rem", padding: "0.25rem 0.6rem" }}
                title={
                  p.scratch_requested
                    ? "You scratched this player"
                    : "Auto-scratched: roster is over the dress limit"
                }
              >
                {p.name} ({p.position} {p.overall})
                {!p.scratch_requested && (
                  <span style={{ color: "var(--color-muted)", marginLeft: "0.35rem" }}>auto</span>
                )}
              </span>
            ))}
          </div>

          {scratchStatus.injured.length > 0 && (
            <div style={{ marginTop: "1rem" }}>
              <div style={{ fontWeight: 600, fontSize: "0.875rem", marginBottom: "0.4rem" }}>
                Injured (not a scratch)
              </div>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                {scratchStatus.injured.map((p) => (
                  <span
                    key={p.pid}
                    className="line-slot__player"
                    style={{ fontSize: "0.875rem", padding: "0.25rem 0.6rem", opacity: 0.75 }}
                  >
                    {p.name} ({p.position}) — {p.injury_status}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

// --- Main Lines Screen ---

export function LinesScreen({
  onPlayer,
  toast: _toast,
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

  if (rosterError) {
    return (
      <Panel className="screen screen-lines">
        <h2 className="text-display">Lines</h2>
        <p className="text-muted" style={{ marginTop: "1rem" }}>
          Error loading roster: {rosterError instanceof ApiError ? rosterError.message : "Unknown error"}
        </p>
      </Panel>
    );
  }

  if (rosterLoading || linesLoading) {
    return <FaceoffDotSpinner />;
  }

  if (!rosterData || !linesData) {
    return (
      <Panel className="screen screen-lines">
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

  return (
    <div className="screen screen-lines">
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

      <BenchTable
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
          scratchStatus={linesData.scratch_status}
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
    </div>
  );
}

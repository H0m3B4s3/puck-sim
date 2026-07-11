// Roster management screen: roster table, lines/pairs editor, tactics panel (Step 2.10b).
//
// Displays the user's team roster, allows editing of forward lines/D-pairs/goalies,
// and provides controls for auto-building and tactics adjustment.

import { useState } from "react";
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
  ManualLinesEditRequest,
  TacticsUpdateRequest,
  ApiError,
} from "../api";
import { Panel, FaceoffDotSpinner, formatMoney } from "../ui";

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
                className={selectedPlayers.has(row.original.pid) ? "selected" : ""}
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

function LineSlot({
  label,
  player,
  canPlace,
  onClick,
}: {
  label: string;
  player: PlayerSummary | null;
  canPlace: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`line-slot${canPlace ? " line-slot--placeable" : ""}`}
      onClick={onClick}
      disabled={!canPlace}
      title={canPlace ? "Click to place the selected roster player here" : "Select a player in the roster table above to reassign this slot"}
    >
      <div className="line-slot__label">{label}</div>
      {player ? (
        <div className="line-slot__player">
          <span className="line-slot__name">{player.name}</span>
        </div>
      ) : (
        <div className="line-slot__empty">Empty</div>
      )}
    </button>
  );
}

function ForwardLine({
  lineIndex,
  players,
  canPlace,
  onSlotClick,
}: {
  lineIndex: number;
  players: PlayerSummary[];
  canPlace: boolean;
  onSlotClick: (slotIndex: number) => void;
}) {
  const positionLabels = ["LW", "C", "RW"];
  return (
    <div className="line-group">
      <h4 className="line-group__title">Line {lineIndex + 1}</h4>
      <div className="line-slots">
        {positionLabels.map((pos, i) => (
          <LineSlot
            key={i}
            label={pos}
            player={players[i] || null}
            canPlace={canPlace}
            onClick={() => onSlotClick(i)}
          />
        ))}
      </div>
    </div>
  );
}

function DefensePair({
  pairIndex,
  players,
  canPlace,
  onSlotClick,
}: {
  pairIndex: number;
  players: PlayerSummary[];
  canPlace: boolean;
  onSlotClick: (slotIndex: number) => void;
}) {
  const positionLabels = ["D1", "D2"];
  return (
    <div className="line-group">
      <h4 className="line-group__title">Pair {pairIndex + 1}</h4>
      <div className="line-slots">
        {positionLabels.map((pos, i) => (
          <LineSlot
            key={i}
            label={pos}
            player={players[i] || null}
            canPlace={canPlace}
            onClick={() => onSlotClick(i)}
          />
        ))}
      </div>
    </div>
  );
}

function LinesEditor({
  lines,
  pairs,
  goalieStarter,
  goalieBackup,
  selectedPlayer,
  onPlaceInLine,
  onPlaceInPair,
  onSetGoalie,
}: {
  lines: PlayerSummary[][];
  pairs: PlayerSummary[][];
  goalieStarter: PlayerSummary | null;
  goalieBackup: PlayerSummary | null;
  selectedPlayer: PlayerSummary | null;
  onPlaceInLine: (lineIndex: number, slotIndex: number) => void;
  onPlaceInPair: (pairIndex: number, slotIndex: number) => void;
  onSetGoalie: (which: "starter" | "backup") => void;
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
          : "Select a player in the roster table above, then click a slot to place them."}
      </p>

      <div className="lines-grid">
        {lines.map((line, i) => (
          <ForwardLine
            key={`line-${i}`}
            lineIndex={i}
            players={line}
            canPlace={canPlace}
            onSlotClick={(slotIndex) => onPlaceInLine(i, slotIndex)}
          />
        ))}
      </div>

      <div className="lines-grid" style={{ marginTop: "2rem" }}>
        {pairs.map((pair, i) => (
          <DefensePair
            key={`pair-${i}`}
            pairIndex={i}
            players={pair}
            canPlace={canPlace}
            onSlotClick={(slotIndex) => onPlaceInPair(i, slotIndex)}
          />
        ))}
      </div>

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
    mutationFn: () => api.autoBuildLines({ include_special_teams: false }),
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
          pairs={currentPairs}
          goalieStarter={linesData.goalie_starter.player}
          goalieBackup={linesData.goalie_backup.player}
          selectedPlayer={selectedPlayerObj}
          onPlaceInLine={placeInLine}
          onPlaceInPair={placeInPair}
          onSetGoalie={setGoalie}
        />
        <div style={{ marginTop: "1.5rem", display: "flex", gap: "1rem" }}>
          <button
            className="btn btn-primary"
            onClick={() => autoBuildMutation.mutate()}
            disabled={autoBuildMutation.isPending || updateLinesMutation.isPending}
          >
            {autoBuildMutation.isPending ? "Auto-building..." : "Auto-build Lines"}
          </button>
        </div>
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

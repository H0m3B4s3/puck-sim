// Roster management screen: roster table and tactics panel (Step 2.10b refactor).
//
// Displays the user's team roster with scratch toggle controls.
// Provides tactics adjustment panel.
// Line/pair editing moved to dedicated Lines screen.

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
  ScratchStatus,
  TacticsUpdateRequest,
  ApiError,
} from "../api";
import { Panel, FaceoffDotSpinner, formatMoney, RareArchetypeBadge } from "../ui";

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

// --- Roster Table Component ---

const columnHelper = createColumnHelper<PlayerSummary>();

const rosterColumns = (
  onPlayer?: (pid: number) => void,
  onToggleScratch?: (pid: number) => void,
) => [
  columnHelper.accessor("name", {
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
  // Healthy scratches (20-player dress limit). Injured players get no toggle -- they are out
  // regardless, and offering a control that does nothing is worse than offering none.
  columnHelper.display({
    id: "scratch",
    header: "Scratch",
    size: 110,
    cell: (info) => {
      const p = info.row.original;
      if (p.injury_status) {
        return <span style={{ color: "var(--color-muted)" }}>injured</span>;
      }
      const overridden = p.scratch_requested && !p.scratched;
      return (
        <button
          className="btn btn-secondary"
          onClick={() => onToggleScratch?.(p.pid)}
          style={{
            padding: "0.25rem 0.5rem",
            fontSize: "0.8125rem",
            color: overridden
              ? "var(--color-accent-amber, #d97706)"
              : p.scratched
                ? "var(--color-accent-red, #dc2626)"
                : undefined,
          }}
          title={
            overridden
              ? "You asked to sit this player, but injuries forced him into the lineup"
              : p.scratched
                ? "Sitting tonight -- click to dress"
                : "Dressed -- click to scratch"
          }
        >
          {overridden ? "forced in" : p.scratched ? "scratched" : "dressed"}
        </button>
      );
    },
  }),
];

function RosterTable({
  players,
  onPlayer,
  onToggleScratch,
  scratchStatus,
}: {
  players: PlayerSummary[];
  onPlayer?: (pid: number) => void;
  onToggleScratch?: (pid: number) => void;
  scratchStatus?: ScratchStatus | null;
}) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "overall", desc: true },
  ]);

  const table = useReactTable({
    data: players,
    columns: rosterColumns(onPlayer, onToggleScratch),
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <Panel className="roster-table-container">
      <h3 className="text-display" style={{ marginBottom: "0.5rem" }}>
        Roster ({players.length} players)
      </h3>
      {scratchStatus && (
        <p style={{ marginBottom: "1rem", fontSize: "0.875rem", color: "var(--color-muted)" }}>
          Dressing {scratchStatus.dressed_count} of {scratchStatus.dressed_limit} (
          {scratchStatus.skaters_dressed} skaters, {scratchStatus.goalies_dressed} goalies).{" "}
          {scratchStatus.scratched.length > 0 &&
            `${scratchStatus.scratched.length} healthy scratch${scratchStatus.scratched.length === 1 ? "" : "es"}.`}
        </p>
      )}
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
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                style={row.original.scratched ? { opacity: 0.55 } : undefined}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} style={{ width: `${cell.column.getSize()}px` }}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
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

  // Fetch scratch status
  const {
    data: scratchData,
    isLoading: scratchLoading,
  } = useQuery({
    queryKey: ["roster", "scratches"],
    queryFn: () => api.getScratches(),
  });

  // Fetch tactics
  const {
    data: tacticsData,
    isLoading: tacticsLoading,
  } = useQuery({
    queryKey: ["roster", "tactics"],
    queryFn: () => api.getRosterTactics(),
  });

  // Mutation: set healthy scratches. Sends the FULL set each time (the endpoint is a replacement,
  // not a patch), computed by toggling one pid against the current requested set.
  const scratchMutation = useMutation({
    mutationFn: (scratches: number[]) => api.putScratches(scratches),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["roster"] });
      queryClient.invalidateQueries({ queryKey: ["roster", "scratches"] });
      setError(null);
    },
    onError: (err) => {
      const errorMsg = err instanceof ApiError ? err.message : "Failed to update scratches";
      setError(errorMsg);
    },
  });

  const toggleScratch = (pid: number) => {
    const requested = new Set(
      (rosterData?.players ?? []).filter((p) => p.scratch_requested).map((p) => p.pid),
    );
    if (requested.has(pid)) {
      requested.delete(pid);
    } else {
      requested.add(pid);
    }
    scratchMutation.mutate([...requested]);
  };

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

  if (rosterLoading || scratchLoading || tacticsLoading) {
    return <FaceoffDotSpinner />;
  }

  if (!rosterData || !tacticsData) {
    return (
      <Panel className="screen screen-roster">
        <p className="text-muted">No data available</p>
      </Panel>
    );
  }

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
        onPlayer={onPlayer}
        onToggleScratch={toggleScratch}
        scratchStatus={scratchData}
      />

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

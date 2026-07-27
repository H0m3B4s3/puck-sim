// League-wide stats screen: sortable table of every player in the league.
// Similar to Leaders but showing all players (not capped at 10), with name search and team context.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  createColumnHelper,
  ColumnDef,
} from "@tanstack/react-table";

import api, { LeaguePlayer } from "../api";
import { Panel, FaceoffDotSpinner, RareArchetypeBadge } from "../ui";
import { SortableTable } from "./Roster";

// Column helper for LeaguePlayer
const columnHelper = createColumnHelper<LeaguePlayer>();

// Team badge pill (consistent with Leaders.tsx styling)
function TeamBadge({ abbrev, color }: { abbrev: string; color: string }) {
  return (
    <span
      style={{
        fontSize: "0.85rem",
        padding: "0.2rem 0.4rem",
        borderRadius: "3px",
        backgroundColor: color,
        color: "#f2f4f6",
        fontWeight: 600,
        fontFamily: "var(--font-display)",
      }}
    >
      {abbrev}
    </span>
  );
}

// Skater columns
function skaterColumns(onPlayer?: (pid: number) => void): ColumnDef<LeaguePlayer, any>[] {
  return [
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
    columnHelper.accessor("team_abbrev", {
      header: "Team",
      size: 80,
      cell: (info) => (
        <TeamBadge abbrev={info.getValue()} color={info.row.original.team_color} />
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
    columnHelper.accessor((row) => (row.season_stats as any).gp || 0, {
      id: "gp",
      header: "GP",
      size: 60,
    }),
    columnHelper.accessor((row) => (row.season_stats as any).g || 0, {
      id: "g",
      header: "G",
      size: 60,
    }),
    columnHelper.accessor((row) => (row.season_stats as any).a || 0, {
      id: "a",
      header: "A",
      size: 60,
    }),
    columnHelper.accessor((row) => (row.season_stats as any).pts || 0, {
      id: "pts",
      header: "PTS",
      size: 60,
    }),
    columnHelper.accessor((row) => (row.season_stats as any).plus_minus || 0, {
      id: "plus_minus",
      header: "+/-",
      size: 60,
    }),
    columnHelper.accessor((row) => (row.season_stats as any).sog || 0, {
      id: "sog",
      header: "SOG",
      size: 60,
    }),
    columnHelper.accessor((row) => (row.season_stats as any).pim || 0, {
      id: "pim",
      header: "PIM",
      size: 60,
    }),
  ];
}

// Goalie columns
function goalieColumns(onPlayer?: (pid: number) => void): ColumnDef<LeaguePlayer, any>[] {
  return [
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
    columnHelper.accessor("team_abbrev", {
      header: "Team",
      size: 80,
      cell: (info) => (
        <TeamBadge abbrev={info.getValue()} color={info.row.original.team_color} />
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
    columnHelper.accessor((row) => (row.season_stats as any).gp || 0, {
      id: "gp",
      header: "GP",
      size: 60,
    }),
    columnHelper.accessor((row) => (row.season_stats as any).wins || 0, {
      id: "wins",
      header: "W",
      size: 60,
    }),
    columnHelper.accessor((row) => (row.season_stats as any).losses || 0, {
      id: "losses",
      header: "L",
      size: 60,
    }),
    columnHelper.accessor((row) => (row.season_stats as any).otl || 0, {
      id: "otl",
      header: "OTL",
      size: 60,
    }),
    columnHelper.accessor((row) => ((row.season_stats as any).save_pct as number) || 0, {
      id: "save_pct",
      header: "SV%",
      size: 70,
      cell: (info) => (info.getValue() * 100).toFixed(1) + "%",
    }),
    columnHelper.accessor((row) => ((row.season_stats as any).gaa as number) || 0, {
      id: "gaa",
      header: "GAA",
      size: 70,
      cell: (info) => info.getValue().toFixed(2),
    }),
    columnHelper.accessor((row) => (row.season_stats as any).shutouts || 0, {
      id: "shutouts",
      header: "SO",
      size: 60,
    }),
  ];
}

export function LeagueStatsScreen({
  onPlayer,
  toast: _toast,
}: {
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
} = {}) {
  const [searchName, setSearchName] = useState<string>("");

  // Fetch all league players
  const {
    data: playersData,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["league", "players"],
    queryFn: () => api.getLeaguePlayers(),
  });

  if (isLoading) {
    return (
      <div className="screen screen-league-stats">
        <Panel>
          <FaceoffDotSpinner />
        </Panel>
      </div>
    );
  }

  if (error) {
    return (
      <div className="screen screen-league-stats">
        <Panel>
          <h2 className="text-display">League Stats</h2>
          <p className="text-muted" style={{ marginTop: "1rem" }}>
            Error loading league stats: {error instanceof Error ? error.message : "Unknown error"}
          </p>
        </Panel>
      </div>
    );
  }

  if (!playersData) {
    return (
      <div className="screen screen-league-stats">
        <Panel>
          <h2 className="text-display">League Stats</h2>
          <p className="text-muted" style={{ marginTop: "1rem" }}>
            No data available
          </p>
        </Panel>
      </div>
    );
  }

  // Filter by name (case-insensitive substring match)
  const filtered = playersData.players.filter((p) =>
    p.name.toLowerCase().includes(searchName.toLowerCase())
  );

  // Split into skaters and goalies
  const skaters = filtered.filter((p) => p.position !== "G");
  const goalies = filtered.filter((p) => p.position === "G");

  return (
    <div className="screen screen-league-stats">
      <Panel style={{ marginBottom: "2rem" }}>
        <h2 className="text-display">League Stats</h2>

        {/* Name search input */}
        <div style={{ marginTop: "1.5rem" }}>
          <input
            type="text"
            placeholder="Search by player name..."
            value={searchName}
            onChange={(e) => setSearchName(e.target.value)}
            style={{
              width: "100%",
              maxWidth: "300px",
              padding: "0.5rem",
              borderRadius: "4px",
              border: "1px solid var(--color-border)",
              backgroundColor: "var(--color-surface)",
              color: "var(--color-text)",
              fontSize: "0.9375rem",
            }}
          />
        </div>
      </Panel>

      {/* Skaters table */}
      {skaters.length > 0 && (
        <Panel className="league-stats-table-container">
          <h3 className="text-display" style={{ marginBottom: "0.5rem" }}>
            Skaters ({skaters.length})
          </h3>
          <SortableTable
            data={skaters}
            columns={skaterColumns(onPlayer)}
            defaultSort={[{ id: "pts", desc: true }]}
          />
        </Panel>
      )}

      {/* Goalies table */}
      {goalies.length > 0 && (
        <Panel className="league-stats-table-container" style={{ marginTop: "2rem" }}>
          <h3 className="text-display" style={{ marginBottom: "0.5rem" }}>
            Goalies ({goalies.length})
          </h3>
          <SortableTable
            data={goalies}
            columns={goalieColumns(onPlayer)}
            defaultSort={[{ id: "wins", desc: true }]}
          />
        </Panel>
      )}

      {/* No results message */}
      {skaters.length === 0 && goalies.length === 0 && (
        <Panel>
          <p className="text-muted" style={{ textAlign: "center" }}>
            No players match your search criteria.
          </p>
        </Panel>
      )}
    </div>
  );
}

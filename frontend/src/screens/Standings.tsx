// Standings screen (Step 2.10c).
//
// Displays all 32 teams in the league, sorted by points (default).
// Sortable by points, wins, losses. Highlights the user's own team row.
// Shows the active standings rule in the title.
// Also displays playoff bracket status when in playoffs phase.

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import api, { StandingsEntry } from "../api";
import { WorldSummary } from "../api";
import { Panel, FaceoffDotSpinner } from "../ui";
import { TeamTag } from "../theme";

export function StandingsScreen({
  world,
}: {
  world: WorldSummary;
}) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "points", desc: true },
  ]);

  const { data: standings, isLoading, error } = useQuery({
    queryKey: ["standings"],
    queryFn: () => api.getStandings(),
  });

  const { data: playoffBracket } = useQuery({
    queryKey: ["playoff-bracket"],
    queryFn: () => api.getPlayoffBracket(),
  });

  const columnHelper = createColumnHelper<StandingsEntry>();

  const columns = useMemo(
    () => [
      columnHelper.accessor("abbrev", {
        header: "Team",
        size: 150,
        cell: (info) => {
          const row = info.row.original;
          return (
            <TeamTag
              abbrev={row.abbrev}
              color={row.primary_color}
              name={row.name}
            />
          );
        },
      }),
      columnHelper.accessor("conference", {
        header: "Conf",
        size: 80,
      }),
      columnHelper.accessor("division", {
        header: "Div",
        size: 100,
      }),
      columnHelper.accessor("wins", {
        header: "W",
        size: 60,
        cell: (info) => <span className="text-mono">{info.getValue()}</span>,
      }),
      columnHelper.accessor("losses", {
        header: "L",
        size: 60,
        cell: (info) => <span className="text-mono">{info.getValue()}</span>,
      }),
      columnHelper.accessor("ot_losses", {
        header: "OTL",
        size: 60,
        cell: (info) => <span className="text-mono">{info.getValue()}</span>,
      }),
      columnHelper.accessor("points", {
        header: "Points",
        size: 80,
        cell: (info) => <span className="text-mono">{info.getValue()}</span>,
      }),
    ],
    [columnHelper]
  );

  const table = useReactTable({
    data: standings || [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (isLoading) {
    return (
      <Panel>
        <h2 className="text-display">Standings</h2>
        <FaceoffDotSpinner />
      </Panel>
    );
  }

  if (error) {
    return (
      <Panel>
        <h2 className="text-display">Standings</h2>
        <p className="text-muted">Error loading standings</p>
      </Panel>
    );
  }

  const standingsRuleLabel = world.standings_rule
    .replace(/_/g, "-")
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");

  return (
    <Panel className="standings-screen">
      <div className="standings-header">
        <h2 className="text-display">Standings ({standingsRuleLabel})</h2>
        <p className="text-muted">Season {world.season_year}</p>
      </div>

      <div className="standings-table-wrapper">
        <table className="standings-table">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    onClick={header.column.getToggleSortingHandler()}
                    style={{
                      width: header.getSize() || "auto",
                      cursor: header.column.getCanSort()
                        ? "pointer"
                        : "default",
                      textAlign: header.id === "abbrev" ? "left" : "center",
                    }}
                  >
                    <div className="standings-column-header">
                      {flexRender(
                        header.column.columnDef.header,
                        header.getContext()
                      )}
                      {header.column.getCanSort() && (
                        <span className="standings-sort-indicator">
                          {header.column.getIsSorted() === "desc"
                            ? " ↓"
                            : header.column.getIsSorted() === "asc"
                              ? " ↑"
                              : ""}
                        </span>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => {
              const isUserTeam = row.original.id === world.user_team_id;
              return (
                <tr
                  key={row.id}
                  className={isUserTeam ? "standings-row user-team" : "standings-row"}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      style={{
                        width: cell.column.getSize() || "auto",
                        textAlign: cell.column.id === "abbrev" ? "left" : "center",
                      }}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {world.phase === "playoffs" && (
        <div className="standings-playoff-bracket" style={{ marginTop: "2rem" }}>
          <h3 className="text-display" style={{ fontSize: "var(--font-size-xl)" }}>
            Playoff Bracket
          </h3>
          {playoffBracket ? (
            <pre className="playoff-bracket-json">
              {JSON.stringify(playoffBracket, null, 2)}
            </pre>
          ) : (
            <p className="text-muted">Bracket generating…</p>
          )}
        </div>
      )}
    </Panel>
  );
}

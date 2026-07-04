import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  ColumnDef,
} from "@tanstack/react-table";
import api, {
  BoxScoreResponse,
  SkaterBoxScoreDTO,
  GoalieBoxScoreDTO,
} from "../api";
import { Panel, FaceoffDotSpinner } from "../ui";
import { TeamTag } from "../theme";

/**
 * BoxScore Screen (Step 2.10d)
 *
 * Displays the box score for a played game, with separate tables for skaters and goalies.
 * Users can select a game from the schedule and view its detailed box score.
 */
export function BoxScore({
  initialGid,
}: {
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
  initialGid?: number | null;
} = {}) {
  const [selectedGameId, setSelectedGameId] = useState<number | null>(initialGid || null);

  // Fetch schedule to allow game selection
  const {
    data: schedule,
    isLoading: scheduleLoading,
    error: scheduleError,
  } = useQuery({
    queryKey: ["schedule"],
    queryFn: () => api.getSchedule(),
  });

  // Fetch team list for name display (from standings)
  const { data: standings } = useQuery({
    queryKey: ["standings"],
    queryFn: () => api.getStandings(),
  });

  // Fetch box score for the selected game
  const {
    data: boxScore,
    isLoading: boxScoreLoading,
    error: boxScoreError,
  } = useQuery({
    queryKey: ["boxscore", selectedGameId],
    queryFn: () =>
      selectedGameId !== null ? api.getBoxScore(selectedGameId) : Promise.resolve(null),
    enabled: selectedGameId !== null,
  });

  // Build a map of team IDs to team info
  const teamMap = useMemo(() => {
    if (!standings) return new Map();
    return new Map(standings.map((t) => [t.id, t]));
  }, [standings]);

  // Filter to played games only
  const playedGames = useMemo(() => {
    if (!schedule) return [];
    return schedule.filter((g) => g.played);
  }, [schedule]);

  if (scheduleLoading) {
    return (
      <Panel>
        <FaceoffDotSpinner />
      </Panel>
    );
  }

  if (scheduleError) {
    return (
      <Panel>
        <p className="text-display">Error loading schedule</p>
      </Panel>
    );
  }

  if (!playedGames || playedGames.length === 0) {
    return (
      <Panel>
        <h2 className="text-display">Box Score</h2>
        <p className="text-muted" style={{ marginTop: "1rem" }}>
          No played games yet. Simulate a game first from the Schedule screen.
        </p>
      </Panel>
    );
  }

  return (
    <div className="screen screen-boxscore">
      <Panel>
        <h2 className="text-display">Box Score</h2>

        {/* Game Selector */}
        <div style={{ marginTop: "1.5rem", marginBottom: "1.5rem" }}>
          <label
            htmlFor="game-select"
            style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500 }}
          >
            Select a game:
          </label>
          <select
            id="game-select"
            value={selectedGameId ?? ""}
            onChange={(e) => setSelectedGameId(e.target.value ? parseInt(e.target.value) : null)}
            style={{
              padding: "0.5rem",
              fontSize: "1rem",
              borderRadius: "4px",
              border: "1px solid var(--color-border)",
              backgroundColor: "var(--color-surface-card)",
              color: "var(--color-text)",
              cursor: "pointer",
              minWidth: "300px",
            }}
          >
            <option value="">Choose a game...</option>
            {playedGames.map((game) => {
              const homeTeam = teamMap.get(game.home);
              const awayTeam = teamMap.get(game.away);
              return (
                <option key={game.gid} value={game.gid}>
                  {awayTeam?.abbrev || `Team ${game.away}`} @{" "}
                  {homeTeam?.abbrev || `Team ${game.home}`} (Day {game.day})
                </option>
              );
            })}
          </select>
        </div>

        {selectedGameId !== null && (boxScoreLoading || !boxScore) && (
          <FaceoffDotSpinner />
        )}

        {boxScoreError && (
          <p className="text-muted">Error loading box score</p>
        )}

        {selectedGameId !== null && boxScore && (
          <BoxScoreContent
            boxScore={boxScore}
            teamMap={teamMap}
            homeTeamId={playedGames.find((g) => g.gid === selectedGameId)?.home ?? null}
            awayTeamId={playedGames.find((g) => g.gid === selectedGameId)?.away ?? null}
          />
        )}
      </Panel>
    </div>
  );
}

interface BoxScoreContentProps {
  boxScore: BoxScoreResponse;
  teamMap: Map<number, any>;
  homeTeamId: number | null;
  awayTeamId: number | null;
}

function BoxScoreContent({
  boxScore,
  teamMap,
  homeTeamId,
  awayTeamId,
}: BoxScoreContentProps) {
  // Group skaters by team
  const skatersByTeam = useMemo(() => {
    const groups: Record<number, SkaterBoxScoreDTO[]> = {};
    Object.values(boxScore.skater_box).forEach((skater) => {
      const tid = skater.team_id || 0;
      if (!groups[tid]) groups[tid] = [];
      groups[tid].push(skater);
    });
    // Sort within teams by overall impact (goals + assists, then position)
    Object.values(groups).forEach((team) => {
      team.sort((a, b) => {
        const aPoints = a.g + a.a;
        const bPoints = b.g + b.a;
        if (aPoints !== bPoints) return bPoints - aPoints;
        // By position order for tie-break
        const posOrder: Record<string, number> = { C: 1, LW: 2, RW: 3, D: 4 };
        return (posOrder[a.position] || 5) - (posOrder[b.position] || 5);
      });
    });
    return groups;
  }, [boxScore]);

  const goaliesByTeam = useMemo(() => {
    const groups: Record<number, GoalieBoxScoreDTO[]> = {};
    Object.values(boxScore.goalie_box).forEach((goalie) => {
      const tid = goalie.team_id || 0;
      if (!groups[tid]) groups[tid] = [];
      groups[tid].push(goalie);
    });
    return groups;
  }, [boxScore]);

  return (
    <div style={{ marginTop: "2rem" }}>
      {/* Score Header. homeTeamId/awayTeamId come from the selected game's schedule entry
          (BoxScoreResponse itself carries no home/away team-id field, only scores) -- an
          earlier version of this derived "team1"/"team2" by sorting the skater box's team_id
          keys numerically, which has NO relationship to which side is actually home/away
          (team ids are assigned essentially arbitrarily at league-gen time), so the score
          shown next to each team was wrong whenever the home team's id happened to be
          greater than the away team's id -- roughly half of all games. Fixed during review. */}
      <div
        style={{
          padding: "1.5rem",
          borderRadius: "12px",
          backgroundColor: "var(--color-surface-card)",
          marginBottom: "2rem",
          textAlign: "center",
        }}
      >
        <div style={{ display: "flex", justifyContent: "center", gap: "2rem", alignItems: "center" }}>
          <div>
            {awayTeamId !== null && teamMap.get(awayTeamId) && (
              <TeamTag
                abbrev={teamMap.get(awayTeamId)?.abbrev || `T${awayTeamId}`}
                color={teamMap.get(awayTeamId)?.primary_color || "#000"}
                big
              />
            )}
            <div style={{ fontSize: "2.5rem", fontWeight: 700, marginTop: "0.5rem" }}>
              {boxScore.away_score}
            </div>
          </div>
          <div style={{ color: "var(--color-muted)" }}>
            <div className="text-muted">@</div>
            {boxScore.went_so && <div>SO</div>}
            {boxScore.went_ot && <div>OT</div>}
          </div>
          <div>
            {homeTeamId !== null && teamMap.get(homeTeamId) && (
              <TeamTag
                abbrev={teamMap.get(homeTeamId)?.abbrev || `T${homeTeamId}`}
                color={teamMap.get(homeTeamId)?.primary_color || "#000"}
                big
              />
            )}
            <div style={{ fontSize: "2.5rem", fontWeight: 700, marginTop: "0.5rem" }}>
              {boxScore.home_score}
            </div>
          </div>
        </div>
      </div>

      {/* Skaters Table */}
      {Object.keys(skatersByTeam).length > 0 && (
        <div style={{ marginBottom: "2rem" }}>
          <h3
            style={{
              fontSize: "1.25rem",
              fontWeight: 600,
              marginBottom: "1rem",
            }}
          >
            Skaters
          </h3>
          {Object.entries(skatersByTeam).map(([teamIdStr, skaters]) => (
            <SkaterTable
              key={teamIdStr}
              teamId={parseInt(teamIdStr)}
              skaters={skaters}
              teamMap={teamMap}
            />
          ))}
        </div>
      )}

      {/* Goalies Table */}
      {Object.keys(goaliesByTeam).length > 0 && (
        <div>
          <h3
            style={{
              fontSize: "1.25rem",
              fontWeight: 600,
              marginBottom: "1rem",
            }}
          >
            Goalies
          </h3>
          {Object.entries(goaliesByTeam).map(([teamIdStr, goalies]) => (
            <GoalieTable
              key={teamIdStr}
              teamId={parseInt(teamIdStr)}
              goalies={goalies}
              teamMap={teamMap}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface SkaterTableProps {
  teamId: number;
  skaters: SkaterBoxScoreDTO[];
  teamMap: Map<number, any>;
}

function SkaterTable({ teamId, skaters, teamMap }: SkaterTableProps) {
  const team = teamMap.get(teamId);
  const teamName = team?.abbrev || `Team ${teamId}`;

  const columns: ColumnDef<SkaterBoxScoreDTO>[] = [
    {
      header: "Player",
      accessorKey: "name",
      cell: (info) => (
        <div>
          <div style={{ fontWeight: 500 }}>{String(info.getValue())}</div>
          <div style={{ fontSize: "0.875rem", color: "var(--color-muted)" }}>
            {info.row.original.position}
          </div>
        </div>
      ),
    },
    {
      header: "G",
      accessorKey: "g",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
    {
      header: "A",
      accessorKey: "a",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
    {
      header: "+/-",
      accessorKey: "plus_minus",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
    {
      header: "SOG",
      accessorKey: "sog",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
    {
      header: "PIM",
      accessorKey: "pim",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
  ];

  const table = useReactTable({
    data: skaters,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div
      style={{
        marginBottom: "1.5rem",
        borderRadius: "8px",
        overflow: "hidden",
        border: `1px solid var(--color-border)`,
      }}
    >
      <div
        style={{
          padding: "0.75rem 1rem",
          backgroundColor: "var(--color-border)",
          color: "var(--color-text)",
          fontWeight: 600,
          fontSize: "0.875rem",
        }}
      >
        {teamName}
      </div>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: "0.9375rem",
        }}
      >
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr
              key={headerGroup.id}
              style={{
                borderBottom: "1px solid var(--color-border)",
                backgroundColor: "var(--color-surface)",
              }}
            >
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  style={{
                    padding: "0.75rem 1rem",
                    textAlign: "left",
                    fontWeight: 600,
                    fontSize: "0.8125rem",
                    color: "var(--color-muted)",
                    textTransform: "uppercase",
                  }}
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              style={{
                borderBottom: "1px solid var(--color-border)",
              }}
            >
              {row.getVisibleCells().map((cell) => (
                <td
                  key={cell.id}
                  style={{
                    padding: "0.75rem 1rem",
                  }}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface GoalieTableProps {
  teamId: number;
  goalies: GoalieBoxScoreDTO[];
  teamMap: Map<number, any>;
}

function GoalieTable({ teamId, goalies, teamMap }: GoalieTableProps) {
  const team = teamMap.get(teamId);
  const teamName = team?.abbrev || `Team ${teamId}`;

  const columns: ColumnDef<GoalieBoxScoreDTO>[] = [
    {
      header: "Goalie",
      accessorKey: "name",
      cell: (info) => <div style={{ fontWeight: 500 }}>{String(info.getValue())}</div>,
    },
    {
      header: "Shots",
      accessorKey: "shots_faced",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
    {
      header: "Saves",
      accessorKey: "saves",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
    {
      header: "GA",
      accessorKey: "goals_against",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
    {
      header: "Save %",
      accessorKey: "saves",
      cell: (info) => {
        const goalie = info.row.original;
        const savePct =
          goalie.shots_faced > 0
            ? ((goalie.saves / goalie.shots_faced) * 100).toFixed(1)
            : ".000";
        return <span className="text-mono">{savePct}%</span>;
      },
    },
  ];

  const table = useReactTable({
    data: goalies,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div
      style={{
        marginBottom: "1.5rem",
        borderRadius: "8px",
        overflow: "hidden",
        border: `1px solid var(--color-border)`,
      }}
    >
      <div
        style={{
          padding: "0.75rem 1rem",
          backgroundColor: "var(--color-border)",
          color: "var(--color-text)",
          fontWeight: 600,
          fontSize: "0.875rem",
        }}
      >
        {teamName}
      </div>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: "0.9375rem",
        }}
      >
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr
              key={headerGroup.id}
              style={{
                borderBottom: "1px solid var(--color-border)",
                backgroundColor: "var(--color-surface)",
              }}
            >
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  style={{
                    padding: "0.75rem 1rem",
                    textAlign: "left",
                    fontWeight: 600,
                    fontSize: "0.8125rem",
                    color: "var(--color-muted)",
                    textTransform: "uppercase",
                  }}
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              style={{
                borderBottom: "1px solid var(--color-border)",
              }}
            >
              {row.getVisibleCells().map((cell) => (
                <td
                  key={cell.id}
                  style={{
                    padding: "0.75rem 1rem",
                  }}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

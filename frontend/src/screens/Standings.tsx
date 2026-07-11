// Standings screen (Step 2.11 / T12).
//
// Displays all 32 teams in the league, grouped by conference and division.
// Shows playoff seeds (1-8) per conference with a visual cutline under seed 8.
// Highlights the user's own team row.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import api, { StandingsEntry, WorldSummary } from "../api";
import { Panel, FaceoffDotSpinner } from "../ui";
import { TeamTag } from "../theme";

const PLAYOFF_TEAMS_PER_CONF = 8;

export function StandingsScreen({
  world,
  onNavigate,
}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
  onNavigate?: (path: string) => void;
}) {
  const { data: standings, isLoading, error } = useQuery({
    queryKey: ["standings"],
    queryFn: () => api.getStandings(),
  });

  // Group standings by conference
  const groupedByConference = useMemo(() => {
    if (!standings) return {};
    const grouped: Record<string, StandingsEntry[]> = {};
    standings.forEach((team) => {
      if (!grouped[team.conference]) {
        grouped[team.conference] = [];
      }
      grouped[team.conference].push(team);
    });
    return grouped;
  }, [standings]);

  // Group by division within each conference (sorted by points)
  const conferencePanels = useMemo(() => {
    const panels: Array<{
      conference: string;
      divisions: Array<{
        division: string;
        teams: Array<StandingsEntry & { seed: number; isPlayoffCutline: boolean }>;
      }>;
    }> = [];

    Object.entries(groupedByConference).forEach(([conf, teams]) => {
      // Sort teams by points within the conference
      const sortedTeams = [...teams].sort((a, b) => b.points - a.points);

      // Group by division
      const divisionMap: Record<
        string,
        Array<StandingsEntry & { seed: number; isPlayoffCutline: boolean }>
      > = {};
      sortedTeams.forEach((team, index) => {
        if (!divisionMap[team.division]) {
          divisionMap[team.division] = [];
        }
        const seed = index + 1;
        const isPlayoffCutline = seed === PLAYOFF_TEAMS_PER_CONF + 1;
        divisionMap[team.division].push({
          ...team,
          seed,
          isPlayoffCutline,
        });
      });

      // Sort divisions by their top team's seed
      const divisions = Object.entries(divisionMap)
        .sort((a, b) => a[1][0].seed - b[1][0].seed)
        .map(([division, teams]) => ({
          division,
          teams: teams.sort((a, b) => b.points - a.points),
        }));

      panels.push({ conference: conf, divisions });
    });

    return panels;
  }, [groupedByConference]);

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

      {/* Conference panels */}
      <div className="standings-conferences">
        {conferencePanels.map((confPanel) => (
          <div key={confPanel.conference} className="standings-conference">
            <h3 className="text-lg" style={{ marginBottom: "1rem" }}>
              {confPanel.conference}
            </h3>

            {confPanel.divisions.map((divPanel) => (
              <div key={divPanel.division} className="standings-division">
                {/* Division header */}
                <div className="standings-division-header">
                  <span className="text-muted">{divPanel.division}</span>
                </div>

                {/* Division teams table */}
                <div className="standings-table-wrapper">
                  <table className="standings-table">
                    <thead>
                      <tr>
                        <th style={{ width: "40px", textAlign: "center" }}>Seed</th>
                        <th style={{ width: "150px", textAlign: "left" }}>Team</th>
                        <th style={{ width: "60px", textAlign: "center" }}>W</th>
                        <th style={{ width: "60px", textAlign: "center" }}>L</th>
                        <th style={{ width: "60px", textAlign: "center" }}>OTL</th>
                        <th style={{ width: "80px", textAlign: "center" }}>Points</th>
                      </tr>
                    </thead>
                    <tbody>
                      {divPanel.teams.map((team) => {
                        const isUserTeam = team.id === world.user_team_id;
                        return (
                          <>
                            <tr
                              key={team.id}
                              className={
                                isUserTeam
                                  ? "standings-row user-team"
                                  : "standings-row"
                              }
                            >
                              <td style={{ textAlign: "center" }}>
                                <span className="text-mono">{team.seed}</span>
                              </td>
                              <td>
                                <TeamTag
                                  abbrev={team.abbrev}
                                  color={team.primary_color}
                                  name={team.name}
                                />
                              </td>
                              <td style={{ textAlign: "center" }}>
                                <span className="text-mono">{team.wins}</span>
                              </td>
                              <td style={{ textAlign: "center" }}>
                                <span className="text-mono">{team.losses}</span>
                              </td>
                              <td style={{ textAlign: "center" }}>
                                <span className="text-mono">{team.ot_losses}</span>
                              </td>
                              <td style={{ textAlign: "center" }}>
                                <span className="text-mono">{team.points}</span>
                              </td>
                            </tr>
                            {/* Playoff cutline after seed 8 */}
                            {team.seed === PLAYOFF_TEAMS_PER_CONF && (
                              <tr className="standings-playoff-cutline">
                                <td colSpan={6}>
                                  <div className="cutline-visual" />
                                </td>
                              </tr>
                            )}
                          </>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* Link to Playoffs tab when in playoffs */}
      {world.phase === "playoffs" && (
        <div
          className="standings-playoff-note"
          style={{ marginTop: "2rem", padding: "1rem", textAlign: "center" }}
        >
          <p className="text-muted">
            See the{" "}
            <button
              type="button"
              onClick={() => onNavigate?.("/playoffs")}
              style={{
                cursor: "pointer",
                color: "inherit",
                background: "none",
                border: "none",
                padding: 0,
                font: "inherit",
                textDecoration: "underline",
              }}
            >
              <strong>Playoffs</strong>
            </button>{" "}
            tab for the current bracket.
          </p>
        </div>
      )}
    </Panel>
  );
}

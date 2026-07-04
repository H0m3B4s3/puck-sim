// Schedule screen (Step 2.10c).
//
// Displays the user's team's games in day order.
// Shows played/unplayed status and scores for played games.
// Uses TeamTag for opponent display via a standings lookup map.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import api, { StandingsEntry, WorldSummary } from "../api";
import { Panel, FaceoffDotSpinner } from "../ui";
import { TeamTag } from "../theme";

export function ScheduleScreen({
  world,
}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
  onViewBoxScore?: (gid: number) => void;
}) {
  const { data: scheduleGames, isLoading: scheduleLoading } = useQuery({
    queryKey: ["schedule"],
    queryFn: () => api.getSchedule(),
  });

  const { data: standings, isLoading: standingsLoading } = useQuery({
    queryKey: ["standings"],
    queryFn: () => api.getStandings(),
  });

  const isLoading = scheduleLoading || standingsLoading;

  // Build a team id -> team info lookup map from standings
  const teamMap: Record<number, StandingsEntry> = useMemo(() => {
    if (!standings) return {};
    return standings.reduce(
      (acc, team) => {
        acc[team.id] = team;
        return acc;
      },
      {} as Record<number, StandingsEntry>
    );
  }, [standings]);

  // Filter games to only the user's team
  const userTeamGames = useMemo(() => {
    if (!scheduleGames || world.user_team_id === null) return [];
    return scheduleGames.filter(
      (g) => g.home === world.user_team_id || g.away === world.user_team_id
    );
  }, [scheduleGames, world.user_team_id]);

  if (isLoading) {
    return (
      <Panel>
        <h2 className="text-display">Schedule</h2>
        <FaceoffDotSpinner />
      </Panel>
    );
  }

  if (!userTeamGames || userTeamGames.length === 0) {
    return (
      <Panel>
        <h2 className="text-display">Schedule</h2>
        <p className="text-muted">No games scheduled</p>
      </Panel>
    );
  }

  return (
    <Panel className="schedule-screen">
      <div className="schedule-header">
        <h2 className="text-display">Schedule</h2>
        <p className="text-muted">Season {world.season_year}</p>
      </div>

      <div className="schedule-list">
        {userTeamGames.map((game) => {
          const homeTeam = teamMap[game.home];
          const awayTeam = teamMap[game.away];
          const isUserHome = game.home === world.user_team_id;

          return (
            <div
              key={game.gid}
              className={`schedule-game ${game.played ? "played" : "upcoming"} ${game.is_playoff ? "playoff" : ""}`}
            >
              <div className="schedule-game__day">
                <span className="schedule-game__day-label">Day {game.day}</span>
              </div>

              <div className="schedule-game__matchup">
                {/* isUserHome/!isUserHome swapped in the original version -- was highlighting
                    the opponent's box instead of the user's own team's box, fixed during
                    review. */}
                <div className={`schedule-game__team ${!isUserHome ? "user-team" : ""}`}>
                  {awayTeam ? (
                    <TeamTag
                      abbrev={awayTeam.abbrev}
                      color={awayTeam.primary_color}
                      name={awayTeam.name}
                    />
                  ) : (
                    <span>Team {game.away}</span>
                  )}
                </div>

                <div className="schedule-game__vs">
                  <span className="text-muted">@</span>
                </div>

                <div className={`schedule-game__team ${isUserHome ? "user-team" : ""}`}>
                  {homeTeam ? (
                    <TeamTag
                      abbrev={homeTeam.abbrev}
                      color={homeTeam.primary_color}
                      name={homeTeam.name}
                    />
                  ) : (
                    <span>Team {game.home}</span>
                  )}
                </div>
              </div>

              <div className="schedule-game__score">
                {game.played ? (
                  <>
                    <span className="text-mono">{game.away_score}</span>
                    <span className="text-muted">-</span>
                    <span className="text-mono">{game.home_score}</span>
                  </>
                ) : (
                  <span className="text-muted">TBD</span>
                )}
              </div>

              {game.is_playoff && (
                <div className="schedule-game__playoff-badge">
                  <span className="text-muted">Playoff</span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

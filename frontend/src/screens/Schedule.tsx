// Schedule screen (Step 2.11 / T12).
//
// Displays the user's team's games in day order with simulation controls,
// and an "Around the League" view showing all league games for a selected day.
// Uses TeamTag for opponent display via a standings lookup map.

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api, { StandingsEntry, WorldSummary } from "../api";
import { Panel, FaceoffDotSpinner } from "../ui";
import { TeamTag } from "../theme";

// Local extension of ScheduleGame to include OT/SO info if available
interface ScheduleGameExt {
  gid: number;
  day: number;
  home: number;
  away: number;
  home_score: number;
  away_score: number;
  played: boolean;
  is_playoff: boolean;
  went_ot?: boolean;
  went_so?: boolean;
}

export function ScheduleScreen({
  world,
  toast,
  onViewBoxScore,
}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
  onViewBoxScore?: (gid: number) => void;
}) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"my-team" | "around-league">("my-team");
  const [selectedDay, setSelectedDay] = useState(Math.max(0, world.day - 1));

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

  // Games for the selected day (Around the League view)
  const gamesForSelectedDay = useMemo(() => {
    if (!scheduleGames) return [];
    return scheduleGames.filter((g) => g.day === selectedDay);
  }, [scheduleGames, selectedDay]);

  // Calculate max day for the day picker bounds
  const maxDay = useMemo(() => {
    if (!scheduleGames || scheduleGames.length === 0) return 0;
    return Math.max(...scheduleGames.map((g) => g.day));
  }, [scheduleGames]);

  const handleSimGame = async (gid: number) => {
    try {
      await api.simGame(gid);
      // Refresh the schedule, standings and scoreboard in place rather than doing a full page
      // reload (which lost scroll/tab state and flashed the whole app).
      queryClient.invalidateQueries({ queryKey: ["schedule"] });
      queryClient.invalidateQueries({ queryKey: ["standings"] });
      queryClient.invalidateQueries({ queryKey: ["career"] });
      toast?.("Game simulated");
    } catch (err) {
      toast?.(`Failed to sim game: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  if (isLoading) {
    return (
      <Panel>
        <h2 className="text-display">Schedule</h2>
        <FaceoffDotSpinner />
      </Panel>
    );
  }

  return (
    <Panel className="schedule-screen">
      <div className="schedule-header">
        <h2 className="text-display">Schedule</h2>
        <p className="text-muted">Season {world.season_year}</p>
      </div>

      {/* Tab toggle for My Team / Around the League */}
      <div className="schedule-tab-toggle">
        <button
          className={`tab-btn ${tab === "my-team" ? "active" : ""}`}
          onClick={() => setTab("my-team")}
        >
          My Team
        </button>
        <button
          className={`tab-btn ${tab === "around-league" ? "active" : ""}`}
          onClick={() => setTab("around-league")}
        >
          Around the League
        </button>
      </div>

      {tab === "my-team" ? (
        // My Team view
        <>
          {!userTeamGames || userTeamGames.length === 0 ? (
            <p className="text-muted" style={{ padding: "1rem" }}>
              No games scheduled
            </p>
          ) : (
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

                    {/* Action buttons */}
                    <div className="schedule-game__actions">
                      {game.played ? (
                        <button
                          className="btn btn-secondary"
                          onClick={() => onViewBoxScore?.(game.gid)}
                        >
                          Box Score
                        </button>
                      ) : (
                        <button
                          className="btn btn-primary"
                          onClick={() => handleSimGame(game.gid)}
                        >
                          Sim
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      ) : (
        // Around the League view
        <>
          <div className="schedule-day-picker">
            <label htmlFor="day-select">Select Day:</label>
            <input
              id="day-select"
              type="range"
              min="0"
              max={maxDay}
              value={selectedDay}
              onChange={(e) => setSelectedDay(Number(e.target.value))}
              style={{ flex: 1 }}
            />
            <span className="text-muted">Day {selectedDay}</span>
          </div>

          {!gamesForSelectedDay || gamesForSelectedDay.length === 0 ? (
            <p className="text-muted" style={{ padding: "1rem" }}>
              No games scheduled for Day {selectedDay}
            </p>
          ) : (
            <div className="schedule-list">
              {gamesForSelectedDay.map((game) => {
                const homeTeam = teamMap[game.home];
                const awayTeam = teamMap[game.away];

                return (
                  <div
                    key={game.gid}
                    className={`schedule-game ${game.played ? "played" : "upcoming"} ${game.is_playoff ? "playoff" : ""}`}
                  >
                    <div className="schedule-game__matchup">
                      <div className="schedule-game__team">
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

                      <div className="schedule-game__team">
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
                          {(game as ScheduleGameExt).went_so && (
                            <span className="schedule-game__tag">SO</span>
                          )}
                          {(game as ScheduleGameExt).went_ot && !(game as ScheduleGameExt).went_so && (
                            <span className="schedule-game__tag">OT</span>
                          )}
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

                    {/* Box Score link for played games */}
                    {game.played && (
                      <div className="schedule-game__actions">
                        <button
                          className="btn btn-secondary"
                          onClick={() => onViewBoxScore?.(game.gid)}
                        >
                          Box Score
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

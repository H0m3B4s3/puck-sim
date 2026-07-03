// PuckSim frontend shell (Step 2.10a).
//
// Simple hand-rolled router (no external routing library needed for placeholder screens).
// Displays NavRail + ScoreboardBar + screen component based on current path.
// Manages career state via TanStack Query, wired to api.ts.

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, { WorldSummary } from "./api";
import { useTheme } from "./theme";
import { TeamTag } from "./theme";
import {
  NavRail,
  ScoreboardBar,
  NoCareerState,
  ScreenPlaceholder,
  FaceoffDotSpinner,
  Panel,
} from "./ui";
import { StandingsScreen } from "./screens/Standings";
import { ScheduleScreen } from "./screens/Schedule";
import { RosterScreen } from "./screens/Roster";

function HomeScreen({ world }: { world: WorldSummary }) {
  const getStandingsQuery = useQuery({
    queryKey: ["career", "standings"],
    queryFn: () => api.getStandings(),
  });

  const userTeamInfo = getStandingsQuery.data?.find(
    (t) => t.id === world.user_team_id
  );

  return (
    <div className="screen screen-home">
      <h2 className="text-display">Season {world.season_year}</h2>
      <p className="text-muted" style={{ marginTop: "0.5rem" }}>
        Phase: <strong>{world.phase}</strong> | Day {world.day}
      </p>

      {userTeamInfo && (
        <Panel style={{ marginTop: "2rem" }}>
          <h3 className="text-display" style={{ fontSize: "1.25rem", marginBottom: "1rem" }}>
            Your Team
          </h3>
          <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "1rem" }}>
            <TeamTag
              abbrev={userTeamInfo.abbrev}
              color={userTeamInfo.primary_color}
              name={userTeamInfo.name}
              big
            />
          </div>

          {userTeamInfo.record ? (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "1rem", marginTop: "1rem" }}>
              <div className="stat-box">
                <div className="stat-label">Wins</div>
                <div className="stat-value">{userTeamInfo.record.wins}</div>
              </div>
              <div className="stat-box">
                <div className="stat-label">Losses</div>
                <div className="stat-value">{userTeamInfo.record.losses}</div>
              </div>
              <div className="stat-box">
                <div className="stat-label">OT Losses</div>
                <div className="stat-value">{userTeamInfo.record.ot_losses}</div>
              </div>
              <div className="stat-box">
                <div className="stat-label">Points</div>
                <div className="stat-value">{userTeamInfo.record.points}</div>
              </div>
            </div>
          ) : (
            <p className="text-muted">No games played yet this season.</p>
          )}
        </Panel>
      )}

      <p style={{ marginTop: "2rem", lineHeight: 1.6 }}>
        Welcome to your PuckSim career. Use the navigation on the left to view your
        roster, check the standings, review the schedule, and manage trades and signings.
      </p>
    </div>
  );
}

export default function App() {
  const { toggle: toggleTheme } = useTheme();
  const [currentPath, setCurrentPath] = useState("/");
  const queryClient = useQueryClient();

  // Fetch current career (will 404 if no session)
  const {
    data: world,
    isLoading: careerLoading,
    error: careerError,
    refetch: refetchCareer,
  } = useQuery({
    queryKey: ["career"],
    queryFn: () => api.getCareer(),
    retry: false, // Don't retry on 404
  });

  // Create a new career
  const newCareerMutation = useMutation({
    mutationFn: () => api.newCareer({ seed: undefined }),
    onSuccess: () => {
      // Refetch career data after creating a new one
      window.location.reload(); // Simple approach: reload the page
    },
  });

  // Start season (from preseason)
  const startSeasonMutation = useMutation({
    mutationFn: () => api.startSeason(),
    onSuccess: () => {
      refetchCareer();
      queryClient.invalidateQueries({ queryKey: ["schedule"] });
    },
  });

  // Advance day (from regular season/playoffs)
  const advanceDayMutation = useMutation({
    mutationFn: () => api.advanceDay(),
    onSuccess: (data) => {
      refetchCareer();
      queryClient.invalidateQueries({ queryKey: ["schedule"] });
      queryClient.invalidateQueries({ queryKey: ["standings"] });
      triggerGoalLightFlash();
      showSimDayResults(data);
    },
  });

  // Trigger a visual flash animation (goal light motif)
  const triggerGoalLightFlash = () => {
    const scoreboardBar = document.querySelector(".scoreboard-bar");
    if (scoreboardBar) {
      scoreboardBar.classList.add("goal-light-flash");
      setTimeout(() => {
        scoreboardBar.classList.remove("goal-light-flash");
      }, 500);
    }
  };

  // Show a brief summary of games played (simple toast-style approach)
  const showSimDayResults = (data: { day: number; games_played: Array<{ gid: number; home: number; away: number; home_score: number; away_score: number }> }) => {
    if (data.games_played.length === 0) {
      // Season over or no games scheduled
      return;
    }
    // Simple console log for now; could be enhanced to show a toast
    console.log(`Simulated ${data.games_played.length} games on day ${data.day}`);
  };

  // Unified sim day handler
  const handleSimDay = () => {
    if (!world) return;
    if (world.phase === "preseason") {
      startSeasonMutation.mutate();
    } else {
      advanceDayMutation.mutate();
    }
  };

  if (careerLoading) {
    return (
      <div className="app-container">
        <NavRail currentPath={currentPath} onNavigate={setCurrentPath} />
        <main className="app-main">
          <FaceoffDotSpinner />
        </main>
      </div>
    );
  }

  // No career exists yet (404 error)
  if (careerError || !world) {
    return (
      <div className="app-container">
        <NavRail currentPath={currentPath} onNavigate={setCurrentPath} />
        <main className="app-main">
          <NoCareerState
            onNewCareer={() => newCareerMutation.mutate()}
            isLoading={newCareerMutation.isPending}
          />
        </main>
      </div>
    );
  }

  // Determine sim day button label based on phase
  const simDayLabel = world?.phase === "preseason" ? "Start Season" : "Sim Day";
  const simDayLoading =
    startSeasonMutation.isPending || advanceDayMutation.isPending;

  // Render screen based on current path
  const renderScreen = () => {
    switch (currentPath) {
      case "/":
        return <HomeScreen world={world} />;
      case "/roster":
        return <RosterScreen />;
      case "/standings":
        return <StandingsScreen world={world} />;
      case "/schedule":
        return <ScheduleScreen world={world} />;
      case "/box-score":
        return (
          <ScreenPlaceholder title="Box Score" step="Step 2.10d" />
        );
      case "/transactions":
        return (
          <ScreenPlaceholder title="Transactions" step="Step 2.10d" />
        );
      default:
        return (
          <ScreenPlaceholder title="Not Found" step="Step 2.10b" />
        );
    }
  };

  return (
    <div className="app-container">
      <NavRail currentPath={currentPath} onNavigate={setCurrentPath} />
      <div className="app-main-wrapper">
        <ScoreboardBar
          seasonYear={world?.season_year || 0}
          phase={world?.phase || ""}
          day={world?.day || 0}
          onSimDay={handleSimDay}
          onThemeToggle={toggleTheme}
          simDayLabel={simDayLabel}
          simDayLoading={simDayLoading}
        />
        <main className="app-main">{renderScreen()}</main>
      </div>
    </div>
  );
}

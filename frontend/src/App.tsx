// PuckSim frontend shell (Step 2.10a + T6).
//
// Simple hand-rolled router (no external routing library needed for placeholder screens).
// Displays NavRail + ScoreboardBar + screen component based on current path.
// Manages career state via TanStack Query, wired to api.ts.
// Phase-aware nav (Playoffs/Offseason tabs shown conditionally per D4).
// Player modal threading per D5.

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
  TeamStrength,
  useToast,
} from "./ui";
import { PlayerModal } from "./PlayerModal";
import { BoxScore } from "./screens/BoxScore";
import { Transactions } from "./screens/Transactions";
import { StandingsScreen } from "./screens/Standings";
import { ScheduleScreen } from "./screens/Schedule";
import { RosterScreen } from "./screens/Roster";
import { ProspectsScreen } from "./screens/Prospects";
import { PlayoffsScreen } from "./screens/Playoffs";
import { OffseasonScreen } from "./screens/Offseason";
import { LeadersScreen } from "./screens/Leaders";
import { HistoryScreen } from "./screens/History";
import { TradeScreen } from "./screens/Trade";
import { SaveLoadScreen } from "./screens/SaveLoad";

function HomeScreen({
  world,
}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
}) {
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
          <div style={{ display: "flex", alignItems: "center", gap: "1.5rem", marginBottom: "1rem", flexWrap: "wrap" }}>
            <TeamTag
              abbrev={userTeamInfo.abbrev}
              color={userTeamInfo.primary_color}
              name={userTeamInfo.name}
              big
            />
            <div style={{ minWidth: "160px" }}>
              <TeamStrength
                stars={userTeamInfo.strength_stars}
                strength={userTeamInfo.strength}
              />
            </div>
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
  const [openPid, setOpenPid] = useState<number | null>(null);
  const [boxScoreGid, setBoxScoreGid] = useState<number | null>(null);
  const queryClient = useQueryClient();
  const { toast, node: toastNode } = useToast();

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

  // Preview a generated league (team names/abbrevs/colors) before committing to it, so the
  // user can pick their team -- see NoCareerState in ui.tsx.
  const previewLeagueMutation = useMutation({
    mutationFn: () => api.previewLeague(),
  });

  // Create a new career from the previewed league's seed + the user's chosen team.
  const newCareerMutation = useMutation({
    mutationFn: (userTeamAbbrev: string) =>
      api.newCareer({ seed: previewLeagueMutation.data?.seed, user_team_abbrev: userTeamAbbrev }),
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

  // Advance day (from regular season)
  const advanceDayMutation = useMutation({
    mutationFn: () => api.advanceDay(),
    onSuccess: (data) => {
      refetchCareer();
      queryClient.invalidateQueries({ queryKey: ["schedule"] });
      queryClient.invalidateQueries({ queryKey: ["standings"] });
      triggerGoalLightFlash();
      toast(`Simulated ${data.games_played.length} games — day ${data.day}`);
      if (data.season_complete) {
        toast("Regular season complete — start the playoffs from the Playoffs tab.");
      }
    },
  });

  // Advance week (1-14 days in one request)
  const advanceWeekMutation = useMutation({
    mutationFn: () => api.advanceWeek(7),
    onSuccess: (data) => {
      refetchCareer();
      queryClient.invalidateQueries({ queryKey: ["schedule"] });
      queryClient.invalidateQueries({ queryKey: ["standings"] });
      triggerGoalLightFlash();
      toast(`Simulated ${data.games_played.length} games — day ${data.day}`);
      if (data.season_complete) {
        toast("Regular season complete — start the playoffs from the Playoffs tab.");
      }
    },
  });

  // Sim to next game
  const simToNextGameMutation = useMutation({
    mutationFn: () => api.simToNextGame(),
    onSuccess: (data) => {
      refetchCareer();
      queryClient.invalidateQueries({ queryKey: ["schedule"] });
      queryClient.invalidateQueries({ queryKey: ["standings"] });
      triggerGoalLightFlash();
      if (data.played) {
        toast(`Next game played on day ${data.day}`);
      } else {
        toast("No more games this season.");
      }
      if (data.season_complete) {
        toast("Regular season complete — start the playoffs from the Playoffs tab.");
      }
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

  // Unified sim day handler
  const handleSimDay = () => {
    if (!world) return;
    if (world.phase === "preseason") {
      startSeasonMutation.mutate();
    } else {
      advanceDayMutation.mutate();
    }
  };

  // Handle viewing a box score
  const handleViewBoxScore = (gid: number) => {
    setBoxScoreGid(gid);
    setCurrentPath("/box-score");
  };

  // Compute nav items early (before loading check) so it's available for early returns
  const baseNavItems = [
    { label: "Home", path: "/" },
    { label: "Roster", path: "/roster" },
    { label: "Prospects", path: "/prospects" },
    { label: "Standings", path: "/standings" },
    { label: "Schedule", path: "/schedule" },
    { label: "Box Score", path: "/box-score" },
    { label: "Leaders", path: "/leaders" },
    { label: "Trades", path: "/trades" },
    { label: "Transactions", path: "/transactions" },
    { label: "History", path: "/history" },
    { label: "Save / Load", path: "/saves" },
  ];

  const navItems = world
    ? [
        ...baseNavItems,
        ...(world.phase === "playoffs" || world.regular_season_complete
          ? [{ label: "Playoffs", path: "/playoffs" }]
          : []),
        ...(["draft", "free_agency"].includes(world.phase)
          ? [{ label: "Offseason", path: "/offseason" }]
          : []),
      ]
    : baseNavItems;

  if (careerLoading) {
    return (
      <div className="app-container">
        <NavRail currentPath={currentPath} onNavigate={setCurrentPath} items={navItems} />
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
        <NavRail currentPath={currentPath} onNavigate={setCurrentPath} items={navItems} />
        <main className="app-main">
          <NoCareerState
            previewTeams={previewLeagueMutation.data?.teams}
            previewLoading={previewLeagueMutation.isPending}
            creatingCareer={newCareerMutation.isPending}
            onPreview={() => previewLeagueMutation.mutate()}
            onPickTeam={(abbrev) => newCareerMutation.mutate(abbrev)}
          />
        </main>
      </div>
    );
  }

  // Determine sim day button label based on phase
  const simDayLabel = world?.phase === "preseason" ? "Start Season" : "Sim Day";
  const simDayLoading =
    startSeasonMutation.isPending ||
    advanceDayMutation.isPending ||
    advanceWeekMutation.isPending ||
    simToNextGameMutation.isPending;

  // Compute sim controls state (D4)
  const simControlsEnabled =
    world &&
    ["preseason", "regular_season"].includes(world.phase) &&
    !world.regular_season_complete;

  // Compute phase hint for when sim controls are disabled
  let phaseHint = "";
  if (world) {
    if (world.phase === "playoffs" || world.regular_season_complete) {
      if (world.phase !== "regular_season") {
        phaseHint = `${world.phase} — use the ${world.phase === "playoffs" ? "Playoffs" : "Offseason"} tab`;
      }
    } else if (["draft", "free_agency"].includes(world.phase)) {
      phaseHint = `Offseason — use the Offseason tab`;
    }
  }

  // Render screen based on current path
  const renderScreen = () => {
    if (!world) return null;

    switch (currentPath) {
      case "/":
        return <HomeScreen world={world} onPlayer={setOpenPid} toast={toast} />;
      case "/roster":
        return <RosterScreen onPlayer={setOpenPid} toast={toast} />;
      case "/prospects":
        return <ProspectsScreen onPlayer={setOpenPid} toast={toast} />;
      case "/standings":
        return <StandingsScreen world={world} onPlayer={setOpenPid} toast={toast} onNavigate={setCurrentPath} />;
      case "/schedule":
        return <ScheduleScreen world={world} onPlayer={setOpenPid} toast={toast} onViewBoxScore={handleViewBoxScore} />;
      case "/box-score":
        return <BoxScore onPlayer={setOpenPid} toast={toast} initialGid={boxScoreGid} currentDay={world.day} />;
      case "/leaders":
        return <LeadersScreen world={world} onPlayer={setOpenPid} toast={toast} />;
      case "/trades":
        return <TradeScreen world={world} onPlayer={setOpenPid} toast={toast} />;
      case "/transactions":
        return <Transactions onPlayer={setOpenPid} toast={toast} />;
      case "/history":
        return <HistoryScreen world={world} onPlayer={setOpenPid} toast={toast} />;
      case "/saves":
        return <SaveLoadScreen toast={toast} onNavigate={setCurrentPath} />;
      case "/playoffs":
        return <PlayoffsScreen world={world} onPlayer={setOpenPid} toast={toast} />;
      case "/offseason":
        return <OffseasonScreen world={world} onPlayer={setOpenPid} toast={toast} />;
      default:
        return (
          <ScreenPlaceholder title="Not Found" step="Step 2.10b" />
        );
    }
  };

  return (
    <div className="app-container">
      <NavRail currentPath={currentPath} onNavigate={setCurrentPath} items={navItems} />
      <div className="app-main-wrapper">
        <ScoreboardBar
          seasonYear={world.season_year}
          phase={world.phase}
          day={world.day}
          onSimDay={handleSimDay}
          onThemeToggle={toggleTheme}
          simDayLabel={simDayLabel}
          simDayLoading={simDayLoading}
          onSimWeek={() => advanceWeekMutation.mutate()}
          onSimToNextGame={() => simToNextGameMutation.mutate()}
          simControlsEnabled={simControlsEnabled}
          phaseHint={phaseHint}
        />
        <main className="app-main">{renderScreen()}</main>
      </div>
      {openPid != null && (
        <PlayerModal pid={openPid} onClose={() => setOpenPid(null)} toast={toast} />
      )}
      {toastNode}
    </div>
  );
}

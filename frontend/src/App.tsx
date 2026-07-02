// PuckSim frontend shell (Step 2.10a).
//
// Simple hand-rolled router (no external routing library needed for placeholder screens).
// Displays NavRail + ScoreboardBar + screen component based on current path.
// Manages career state via TanStack Query, wired to api.ts.

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import api, { WorldSummary } from "./api";
import { useTheme } from "./theme";
import {
  NavRail,
  ScoreboardBar,
  NoCareerState,
  ScreenPlaceholder,
  FaceoffDotSpinner,
} from "./ui";

function HomeScreen({ world }: { world: WorldSummary }) {
  return (
    <div className="screen screen-home">
      <h2 className="text-display">Season {world.season_year}</h2>
      <p className="text-muted" style={{ marginTop: "0.5rem" }}>
        Phase: <strong>{world.phase}</strong> | Day {world.day}
      </p>
      <p style={{ marginTop: "1.5rem", lineHeight: 1.6 }}>
        Welcome to your PuckSim career. Use the navigation on the left to view your
        roster, check the standings, review the schedule, and manage trades and signings.
      </p>
    </div>
  );
}

export default function App() {
  const { toggle: toggleTheme } = useTheme();
  const [currentPath, setCurrentPath] = useState("/");

  // Fetch current career (will 404 if no session)
  const {
    data: world,
    isLoading: careerLoading,
    error: careerError,
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

  // Show toast for sim day button
  const handleSimDay = () => {
    alert("Sim Day endpoint coming soon in Step 2.10c");
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

  // Render screen based on current path
  const renderScreen = () => {
    switch (currentPath) {
      case "/":
        return <HomeScreen world={world} />;
      case "/roster":
        return (
          <ScreenPlaceholder title="Roster" step="Step 2.10b" />
        );
      case "/standings":
        return (
          <ScreenPlaceholder title="Standings" step="Step 2.10c" />
        );
      case "/schedule":
        return (
          <ScreenPlaceholder title="Schedule" step="Step 2.10c" />
        );
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
          seasonYear={world.season_year}
          phase={world.phase}
          day={world.day}
          onSimDay={handleSimDay}
          onThemeToggle={toggleTheme}
        />
        <main className="app-main">{renderScreen()}</main>
      </div>
    </div>
  );
}

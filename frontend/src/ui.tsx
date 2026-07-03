// Shared UI primitives for PuckSim (Step 2.10a).
//
// Panel: rink-cornered card (~24px radius), signature element.
// ScoreboardBar: top persistent bar with season info and controls.
// FaceoffDotSpinner: loading indicator (faceoff dot motif).
// NavRail: left navigation sidebar.

import { ReactNode } from "react";
import { useTheme } from "./theme";

// --- Panel: the signature rink-cornered card ----------------------------------
export function Panel({
  children,
  className,
  style,
}: {
  children: ReactNode;
  className?: string;
  style?: React.CSSProperties;
}) {
  return <div className={`panel ${className || ""}`} style={style}>{children}</div>;
}

// --- FaceoffDotSpinner: loading state ----------------------------------
export function FaceoffDotSpinner() {
  return (
    <div className="faceoff-dot-spinner">
      <div className="faceoff-dot" />
      <p className="text-muted">Loading…</p>
    </div>
  );
}

// --- ScoreboardBar: top persistent bar ----------------------------------
export function ScoreboardBar({
  seasonYear,
  phase,
  day,
  onSimDay,
  onThemeToggle,
}: {
  seasonYear: number;
  phase: string;
  day: number;
  onSimDay: () => void;
  onThemeToggle: () => void;
}) {
  const { theme } = useTheme();
  return (
    <div className="scoreboard-bar">
      <div className="scoreboard-bar__left">
        <div className="scoreboard-info">
          <span className="scoreboard-season">{seasonYear}</span>
          <span className="scoreboard-phase">{phase}</span>
          <span className="scoreboard-day">Day {day}</span>
        </div>
      </div>
      <div className="scoreboard-bar__right">
        <button
          className="btn btn-primary"
          onClick={onSimDay}
          title="Advance simulation one day (endpoint coming soon)"
        >
          Sim Day
        </button>
        <button
          className="btn btn-secondary"
          onClick={onThemeToggle}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >
          {theme === "dark" ? "☀️" : "🌙"}
        </button>
      </div>
    </div>
  );
}

// --- NavRail: left navigation sidebar ----------------------------------
export function NavRail({
  currentPath,
  onNavigate,
}: {
  currentPath: string;
  onNavigate: (path: string) => void;
}) {
  const navItems = [
    { label: "Home", path: "/" },
    { label: "Roster", path: "/roster" },
    { label: "Standings", path: "/standings" },
    { label: "Schedule", path: "/schedule" },
    { label: "Box Score", path: "/box-score" },
    { label: "Transactions", path: "/transactions" },
  ];

  return (
    <nav className="nav-rail">
      <div className="nav-rail__header">
        <h1 className="nav-rail__title">PuckSim</h1>
      </div>
      <ul className="nav-rail__items">
        {navItems.map((item) => (
          <li key={item.path}>
            <button
              className={`nav-rail__item ${
                currentPath === item.path ? "active" : ""
              }`}
              onClick={() => onNavigate(item.path)}
            >
              {item.label}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

// --- Placeholder screen components ----------------------------------
export function ScreenPlaceholder({ title, step }: { title: string; step: string }) {
  return (
    <Panel className="screen-placeholder">
      <h2 className="text-display">{title}</h2>
      <p className="text-muted" style={{ marginTop: "1rem" }}>
        Coming in {step}
      </p>
    </Panel>
  );
}

// --- Career loader / new-career flow ----------------------------------
export function NoCareerState({
  onNewCareer,
  isLoading,
}: {
  onNewCareer: () => void;
  isLoading: boolean;
}) {
  return (
    <Panel className="no-career-state">
      <h2 className="text-display">Welcome to PuckSim</h2>
      <p style={{ marginTop: "1rem", lineHeight: 1.6 }}>
        No active career found. Start a new one to begin managing your team through a full NHL season.
      </p>
      <button
        className="btn btn-primary"
        onClick={onNewCareer}
        disabled={isLoading}
        style={{ marginTop: "2rem" }}
      >
        {isLoading ? "Loading…" : "Start New Career"}
      </button>
    </Panel>
  );
}

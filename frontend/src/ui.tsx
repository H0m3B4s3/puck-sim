// Shared UI primitives for PuckSim (Step 2.10a + T6).
//
// Panel: rink-cornered card (~24px radius), signature element.
// ScoreboardBar: top persistent bar with season info and controls.
// FaceoffDotSpinner: loading indicator (faceoff dot motif).
// NavRail: left navigation sidebar.
// Modal: centered modal overlay with close button.
// useToast: toast notification system.
// Pill: small badge/label component.

import { ReactNode, useState } from "react";
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
  simDayLabel = "Sim Day",
  simDayLoading = false,
  onSimWeek,
  onSimToNextGame,
  simControlsEnabled,
  phaseHint,
}: {
  seasonYear: number;
  phase: string;
  day: number;
  onSimDay: () => void;
  onThemeToggle: () => void;
  simDayLabel?: string;
  simDayLoading?: boolean;
  onSimWeek?: () => void;
  onSimToNextGame?: () => void;
  simControlsEnabled?: boolean;
  phaseHint?: string;
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
        {simControlsEnabled ? (
          <>
            <button
              className="btn btn-primary"
              onClick={onSimDay}
              disabled={simDayLoading}
              title={`${simDayLabel} - Advance simulation ${phase === "preseason" ? "into regular season" : "one day"}`}
            >
              {simDayLoading ? "Loading…" : simDayLabel}
            </button>
            {onSimWeek && (
              <button
                className="btn btn-secondary"
                onClick={onSimWeek}
                disabled={simDayLoading}
                title="Simulate a week (7 days)"
              >
                Sim Week
              </button>
            )}
            {onSimToNextGame && (
              <button
                className="btn btn-secondary"
                onClick={onSimToNextGame}
                disabled={simDayLoading}
                title="Simulate to your team's next game"
              >
                Next Game
              </button>
            )}
          </>
        ) : phaseHint ? (
          <Pill>{phaseHint}</Pill>
        ) : null}
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
  items,
}: {
  currentPath: string;
  onNavigate: (path: string) => void;
  items?: { label: string; path: string }[];
}) {
  const defaultItems = [
    { label: "Home", path: "/" },
    { label: "Roster", path: "/roster" },
    { label: "Standings", path: "/standings" },
    { label: "Schedule", path: "/schedule" },
    { label: "Box Score", path: "/box-score" },
    { label: "Leaders", path: "/leaders" },
    { label: "Trades", path: "/trades" },
    { label: "Transactions", path: "/transactions" },
    { label: "History", path: "/history" },
  ];

  const navItems = items || defaultItems;

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

// --- Modal: centered overlay with close button (ported from HoopR) --

export function Modal({
  title,
  onClose,
  children,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div className="modalBg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modalHead">
          <div>{title}</div>
          <button className="x" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modalBody">{children}</div>
      </div>
    </div>
  );
}

// --- Pill: small badge/label (ported from HoopR) --

export function Pill({ children, color }: { children: ReactNode; color?: string }) {
  return (
    <span className="pill" style={color ? { background: color, color: "#0b0f14" } : undefined}>
      {children}
    </span>
  );
}

// --- useToast: toast notification system (ported from HoopR) --

export function useToast() {
  const [msg, setMsg] = useState<string | null>(null);
  const toast = (m: string) => {
    setMsg(m);
    window.setTimeout(() => setMsg(null), 3200);
  };
  const node = msg ? <div className="toast">{msg}</div> : null;
  return { toast, node };
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

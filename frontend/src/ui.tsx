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
import { useTheme, TeamTag } from "./theme";
import { TeamSummary } from "./api";

// --- formatMoney: consistent "$8.5M" salary/cap formatting --------------------
// Previously duplicated inline across screens (and skipped entirely on the Roster, which showed a
// raw integer). One place so every dollar figure reads the same.
export function formatMoney(dollars: number): string {
  return `$${(dollars / 1_000_000).toFixed(1)}M`;
}

// --- awardLabel: friendly trophy names for raw award keys ---------------------
// The backend keys awards as "hart", "norris", etc.; screens previously rendered those raw. This
// maps them to their real trophy names (with the award's meaning), falling back to a Title-Cased
// key for any award not listed here.
const AWARD_NAMES: Record<string, string> = {
  hart: "Hart Trophy (MVP)",
  norris: "Norris Trophy (Best Defenseman)",
  vezina: "Vezina Trophy (Best Goaltender)",
  calder: "Calder Trophy (Rookie of the Year)",
  selke: "Selke Trophy (Best Defensive Forward)",
  art_ross: "Art Ross Trophy (Points Leader)",
  rocket_richard: "Rocket Richard Trophy (Goals Leader)",
  conn_smythe: "Conn Smythe Trophy (Playoff MVP)",
};

export function awardLabel(key: string): string {
  return (
    AWARD_NAMES[key] ||
    key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

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
  previewTeams,
  previewLoading,
  creatingCareer,
  onPreview,
  onPickTeam,
}: {
  /** Teams from the current league preview, or undefined before one's been requested. */
  previewTeams?: TeamSummary[];
  previewLoading: boolean;
  creatingCareer: boolean;
  /** Generate (or re-roll) a league preview. */
  onPreview: () => void;
  /** Commit to the previewed league with this team as the user's team. */
  onPickTeam: (abbrev: string) => void;
}) {
  if (!previewTeams) {
    return (
      <Panel className="no-career-state">
        <h2 className="text-display">Welcome to PuckSim</h2>
        <p style={{ marginTop: "1rem", lineHeight: 1.6 }}>
          No active career found. Start a new one to begin managing your team through a full NHL season.
        </p>
        <button
          className="btn btn-primary"
          onClick={onPreview}
          disabled={previewLoading}
          style={{ marginTop: "2rem" }}
        >
          {previewLoading ? "Generating league…" : "Start New Career"}
        </button>
      </Panel>
    );
  }

  return (
    <Panel className="no-career-state">
      <h2 className="text-display">Choose Your Team</h2>
      <p style={{ marginTop: "1rem", lineHeight: 1.6 }}>
        Pick the team you'll manage this league. Don't like these 32? Reroll for a fresh set.
      </p>
      <button
        className="btn"
        onClick={onPreview}
        disabled={previewLoading || creatingCareer}
        style={{ marginTop: "1rem" }}
      >
        {previewLoading ? "Rerolling…" : "Reroll League"}
      </button>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
          gap: "0.75rem",
          marginTop: "1.5rem",
        }}
      >
        {previewTeams.map((team) => (
          <button
            key={team.abbrev}
            onClick={() => onPickTeam(team.abbrev)}
            disabled={creatingCareer || previewLoading}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.75rem",
              padding: "0.75rem 1rem",
              borderRadius: "8px",
              border: "1px solid var(--color-border)",
              backgroundColor: "var(--color-surface-card)",
              cursor: creatingCareer || previewLoading ? "default" : "pointer",
              textAlign: "left",
            }}
          >
            <TeamTag abbrev={team.abbrev} color={team.primary_color} name={team.name} />
          </button>
        ))}
      </div>
      {creatingCareer && (
        <p className="text-muted" style={{ marginTop: "1rem" }}>
          Starting your career…
        </p>
      )}
    </Panel>
  );
}

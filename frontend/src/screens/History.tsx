// History screen (T10 feature — T6 foundation).
// Shows archived seasons (Seasons), Hall of Fame inductees, and all-time career records.

import { useEffect, useState } from "react";
import {
  WorldSummary,
  HistoryResponse,
  HallOfFameResponse,
  LeaderboardResponse,
} from "../api";
import { Panel, FaceoffDotSpinner } from "../ui";
import api from "../api";

export function HistoryScreen({
  onPlayer,
}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
}) {
  const [view, setView] = useState<"seasons" | "hof" | "records">("seasons");

  return (
    <div className="screen screen-history">
      <Panel style={{ marginBottom: "2rem" }}>
        <h2 className="text-display">History</h2>
      </Panel>

      {/* Segmented toggle */}
      <div className="segrow tight" style={{ marginBottom: "2rem" }}>
        <SegButton
          label="Seasons"
          active={view === "seasons"}
          onClick={() => setView("seasons")}
        />
        <SegButton
          label="Hall of Fame"
          active={view === "hof"}
          onClick={() => setView("hof")}
        />
        <SegButton
          label="Records"
          active={view === "records"}
          onClick={() => setView("records")}
        />
      </div>

      {/* Sub-views */}
      {view === "seasons" && <SeasonsView onPlayer={onPlayer} />}
      {view === "hof" && <HallOfFameView onPlayer={onPlayer} />}
      {view === "records" && <RecordsView onPlayer={onPlayer} />}
    </div>
  );
}

// ============================================================================
// Segmented Button Component
// ============================================================================

function SegButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className={active ? "seg on" : "seg"}
      onClick={onClick}
      style={{
        flex: 1,
        padding: "0.75rem 1rem",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-sm)",
        backgroundColor: active ? "var(--color-accent-blue)" : "transparent",
        color: active ? "white" : "var(--color-text)",
        cursor: "pointer",
        fontWeight: active ? 600 : 500,
        transition: "all 0.2s ease",
      }}
    >
      {label}
    </button>
  );
}

// ============================================================================
// Seasons View
// ============================================================================

function SeasonsView({ onPlayer }: { onPlayer?: (pid: number) => void }) {
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api
      .getHistory()
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Panel>
        <FaceoffDotSpinner />
      </Panel>
    );
  }

  if (error) {
    return (
      <Panel>
        <p className="text-muted">Error loading history: {error}</p>
      </Panel>
    );
  }

  if (!data || !data.seasons || data.seasons.length === 0) {
    return (
      <Panel>
        <h3 style={{ marginTop: 0 }}>League History</h3>
        <p className="text-muted">
          No seasons archived yet — finish a season to crown a champion.
        </p>
      </Panel>
    );
  }

  return (
    <div>
      {data.seasons.map((season) => (
        <Panel key={season.year} style={{ marginBottom: "2rem" }}>
          {/* Champion banner */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "1rem",
              marginBottom: "1.5rem",
              padding: "1rem",
              backgroundColor: "var(--color-surface)",
              borderRadius: "var(--radius-sm)",
            }}
          >
            <span className="text-muted">{season.year}</span>
            <span style={{ fontSize: "1.5rem" }}>🏆</span>
            <span
              style={{
                fontWeight: 700,
                fontSize: "1.1rem",
                color: season.champion_color,
              }}
            >
              {season.champion_abbrev}
            </span>
            <span>{season.champion_name} — Champions</span>
          </div>

          {/* Award cards for Hart, Norris, Vezina, Calder, Selke */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
              gap: "1rem",
              marginTop: "1rem",
            }}
          >
            {season.awards.hart && (
              <AwardCard
                award={season.awards.hart}
                label="Hart Trophy"
                onPlayer={onPlayer}
              />
            )}
            {season.awards.norris && (
              <AwardCard
                award={season.awards.norris}
                label="Norris Trophy"
                onPlayer={onPlayer}
              />
            )}
            {season.awards.vezina && (
              <AwardCard
                award={season.awards.vezina}
                label="Vezina Trophy"
                onPlayer={onPlayer}
              />
            )}
            {season.awards.calder && (
              <AwardCard
                award={season.awards.calder}
                label="Calder Trophy"
                onPlayer={onPlayer}
              />
            )}
            {season.awards.selke && (
              <AwardCard
                award={season.awards.selke}
                label="Selke Trophy"
                onPlayer={onPlayer}
              />
            )}
          </div>
        </Panel>
      ))}
    </div>
  );
}

// ============================================================================
// Award Card Component
// ============================================================================

function AwardCard({
  award,
  label,
  onPlayer,
}: {
  award: any;
  label: string;
  onPlayer?: (pid: number) => void;
}) {
  if (!award) return null;

  const isGoalie = award.position === "G";
  const teamColor = award.team_color || "#9aa0a6";

  return (
    <div className="awardCard">
      <div style={{ marginBottom: "0.5rem" }}>
        <span style={{ fontSize: "0.85rem", color: "var(--color-muted)" }}>
          {label}
        </span>
      </div>
      <div
        style={{
          cursor: onPlayer ? "pointer" : "default",
          fontWeight: 600,
          fontSize: "1.05rem",
        }}
        onClick={() => onPlayer?.(award.pid)}
      >
        {award.name}
      </div>
      <div
        style={{
          display: "flex",
          gap: "0.5rem",
          alignItems: "center",
          marginTop: "0.5rem",
          fontSize: "0.9rem",
        }}
      >
        <span
          style={{
            fontSize: "0.8rem",
            padding: "0.2rem 0.4rem",
            borderRadius: "3px",
            backgroundColor: teamColor,
            color: "#f2f4f6",
            fontWeight: 600,
            fontFamily: "var(--font-display)",
          }}
        >
          {award.team_abbrev}
        </span>
        <span className="text-muted">{award.position}</span>
      </div>

      {/* Stat line: G/A/PTS for skaters, W/SV%/GAA for goalies */}
      {award.stats && (
        <div
          style={{
            marginTop: "0.75rem",
            paddingTop: "0.75rem",
            borderTop: "1px solid var(--color-border)",
            display: "flex",
            gap: "1rem",
            fontSize: "0.85rem",
            fontFamily: "var(--font-mono)",
          }}
        >
          {isGoalie ? (
            <>
              {(award.stats as any).wins !== undefined && (
                <span>
                  <span className="text-muted">W:</span> {(award.stats as any).wins}
                </span>
              )}
              {(award.stats as any).save_pct !== undefined && (
                <span>
                  <span className="text-muted">SV%:</span>{" "}
                  {(((award.stats as any).save_pct as number) * 100).toFixed(1)}%
                </span>
              )}
              {(award.stats as any).gaa !== undefined && (
                <span>
                  <span className="text-muted">GAA:</span>{" "}
                  {((award.stats as any).gaa as number).toFixed(2)}
                </span>
              )}
            </>
          ) : (
            <>
              {(award.stats as any).g !== undefined && (
                <span>
                  <span className="text-muted">G:</span> {(award.stats as any).g}
                </span>
              )}
              {(award.stats as any).a !== undefined && (
                <span>
                  <span className="text-muted">A:</span> {(award.stats as any).a}
                </span>
              )}
              {(award.stats as any).pts !== undefined && (
                <span>
                  <span className="text-muted">PTS:</span> {(award.stats as any).pts}
                </span>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Hall of Fame View
// ============================================================================

function HallOfFameView({ onPlayer }: { onPlayer?: (pid: number) => void }) {
  const [data, setData] = useState<HallOfFameResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api
      .getHallOfFame()
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Panel>
        <FaceoffDotSpinner />
      </Panel>
    );
  }

  if (error) {
    return (
      <Panel>
        <p className="text-muted">Error loading Hall of Fame: {error}</p>
      </Panel>
    );
  }

  if (!data || !data.members || data.members.length === 0) {
    return (
      <Panel>
        <h3 style={{ marginTop: 0 }}>Hall of Fame</h3>
        <p className="text-muted">
          No inductees yet — legends are enshrined when great careers come to an
          end.
        </p>
      </Panel>
    );
  }

  return (
    <Panel>
      <h3 style={{ marginTop: 0, marginBottom: "1.5rem" }}>Hall of Fame</h3>
      <div>
        {data.members.map((member) => (
          <div
            key={member.pid}
            style={{
              padding: "1rem",
              borderBottom: "1px solid var(--color-border)",
              cursor: member.active && onPlayer ? "pointer" : "default",
              opacity: member.active ? 1 : 0.6,
            }}
            onClick={() => member.active && onPlayer?.(member.pid)}
          >
            {/* Main line: name + position + team + years + peak OVR + draft info */}
            <div style={{ marginBottom: "0.5rem" }}>
              <span style={{ fontWeight: 600, fontSize: "1.05rem" }}>
                {member.name}
              </span>
              <span className="text-muted" style={{ fontSize: "0.9rem" }}>
                {" "}
                · {member.position} · {member.last_team} · {member.first_year}–
                {member.last_year} · peak {member.peak_ovr}
                {member.draft && ` · #${member.draft.pick} (${member.draft.year})`}
              </span>
            </div>

            {/* Second line: totals and seasons */}
            {member.totals && (
              <div className="text-muted" style={{ fontSize: "0.9rem" }}>
                {(member.totals as any).gp && (
                  <span>{((member.totals as any).gp as number).toLocaleString()} GP</span>
                )}
                {(member.totals as any).g && (
                  <span> · {((member.totals as any).g as number).toLocaleString()} G</span>
                )}
                {(member.totals as any).a && (
                  <span> · {((member.totals as any).a as number).toLocaleString()} A</span>
                )}
                {(member.totals as any).pts && (
                  <span> · {((member.totals as any).pts as number).toLocaleString()} PTS</span>
                )}
                {(member.totals as any).wins && (
                  <span> · {(member.totals as any).wins} W</span>
                )}
                {(member.totals as any).save_pct && (
                  <span>
                    · {((((member.totals as any).save_pct as number) * 100).toFixed(1))}% SV%
                  </span>
                )}
                {(member.totals as any).gaa && (
                  <span> · {((member.totals as any).gaa as number).toFixed(2)} GAA</span>
                )}
                {member.seasons !== undefined && (
                  <span> · {member.seasons} seasons</span>
                )}
              </div>
            )}

            {/* Accolades line */}
            {member.accolades && member.accolades.length > 0 && (
              <div style={{ marginTop: "0.5rem" }}>
                <span className="text-muted" style={{ fontSize: "0.85rem" }}>
                  {accoladeSummary(member.accolades)}
                </span>
              </div>
            )}
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ============================================================================
// Accolade Summary Helper
// ============================================================================

function accoladeSummary(
  accolades: Array<{ label: string; count: number }>
): string {
  if (!accolades || accolades.length === 0) return "";
  return accolades.map((a) => `${a.count}× ${a.label}`).join(" · ");
}

// ============================================================================
// Records View
// ============================================================================

function RecordsView({ onPlayer }: { onPlayer?: (pid: number) => void }) {
  const [category, setCategory] = useState("pts");
  const [data, setData] = useState<LeaderboardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .getLeaderboards(category)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [category]);

  const CATEGORY_LABELS: Record<string, string> = {
    pts: "Points",
    g: "Goals",
    a: "Assists",
    gp: "Games Played",
    wins: "Wins",
    shutouts: "Shutouts",
  };

  return (
    <Panel>
      <h3 style={{ marginTop: 0, marginBottom: "1.5rem" }}>All-Time Records</h3>

      {/* Category selector */}
      {data && data.categories && (
        <div className="segrow tight" style={{ marginBottom: "1.5rem" }}>
          {data.categories.map((cat) => (
            <SegButton
              key={cat}
              label={CATEGORY_LABELS[cat] ?? cat}
              active={category === cat}
              onClick={() => setCategory(cat)}
            />
          ))}
        </div>
      )}

      {loading && <FaceoffDotSpinner />}

      {error && (
        <p className="text-muted">Error loading leaderboards: {error}</p>
      )}

      {!loading && !error && data && data.rows && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr
                style={{
                  backgroundColor: "var(--color-border)",
                  borderBottom: "2px solid var(--color-border)",
                }}
              >
                <th style={{ padding: "0.75rem", textAlign: "center", width: "40px" }}>
                  #
                </th>
                <th style={{ padding: "0.75rem", textAlign: "left" }}>
                  Player
                </th>
                <th
                  style={{
                    padding: "0.75rem",
                    textAlign: "left",
                    fontSize: "0.9rem",
                    color: "var(--color-muted)",
                  }}
                >
                  Career
                </th>
                <th style={{ padding: "0.75rem", textAlign: "right", width: "100px" }}>
                  {CATEGORY_LABELS[category] ?? category}
                </th>
                <th
                  style={{
                    padding: "0.75rem",
                    textAlign: "right",
                    width: "80px",
                  }}
                >
                  Seasons
                </th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, idx) => {
                const r = row as any;
                return (
                  <tr
                    key={r.pid}
                    style={{
                      borderBottom: "1px solid var(--color-border)",
                      cursor:
                        r.active && onPlayer ? "pointer" : "default",
                      opacity: r.active ? 1 : 0.7,
                    }}
                    onClick={() =>
                      r.active && onPlayer?.(r.pid)
                    }
                  >
                    <td
                      style={{
                        padding: "0.75rem",
                        textAlign: "center",
                        color: "var(--color-muted)",
                        fontSize: "0.9rem",
                      }}
                    >
                      {idx + 1}
                    </td>
                    <td
                      style={{
                        padding: "0.75rem",
                        fontWeight: 500,
                      }}
                    >
                      {r.name}
                      {!r.active && (
                        <span className="text-muted" style={{ fontSize: "0.85rem", marginLeft: "0.5rem" }}>
                          (Retired)
                        </span>
                      )}
                    </td>
                    <td
                      style={{
                        padding: "0.75rem",
                        fontSize: "0.85rem",
                        color: "var(--color-muted)",
                      }}
                    >
                      {r.last_team} · {r.first_year}–{r.last_year}
                    </td>
                    <td
                      style={{
                        padding: "0.75rem",
                        textAlign: "right",
                        fontWeight: 600,
                        fontFamily: "var(--font-mono)",
                      }}
                    >
                      {typeof r.value === "number" && !Number.isInteger(r.value)
                        ? r.value.toFixed(2)
                        : r.value}
                    </td>
                    <td
                      style={{
                        padding: "0.75rem",
                        textAlign: "right",
                        color: "var(--color-muted)",
                      }}
                    >
                      {r.seasons}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

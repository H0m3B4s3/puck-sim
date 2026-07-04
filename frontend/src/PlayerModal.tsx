// Player detail modal (T7)
// Full player card with stats, ratings, legacy résumé, and career table.

import { useQuery } from "@tanstack/react-query";
import api from "./api";
import { Modal, FaceoffDotSpinner } from "./ui";

// Helper: get overall rating color (25–99 scale)
function ratingColor(rating: number): string {
  if (rating >= 85) return "var(--color-accent-gold)";
  if (rating >= 75) return "var(--color-accent-blue)";
  if (rating >= 65) return "var(--color-text)";
  return "var(--color-muted)";
}

// Helper: compute rating bar fill percentage (25-99 scale → 0-100)
function ratingBarWidth(value: number): number {
  return Math.max(0, Math.min(100, ((value - 25) / 74) * 100));
}

// Helper: format salary as $xM
function formatSalary(salary: number): string {
  return `$${(salary / 1_000_000).toFixed(1)}M`;
}

export function PlayerModal({ pid, onClose }: { pid: number; onClose: () => void }) {
  const { data: player, isLoading } = useQuery({
    queryKey: ["player", pid],
    queryFn: () => api.getPlayer(pid),
  });

  if (isLoading) {
    return (
      <Modal title="Player" onClose={onClose}>
        <FaceoffDotSpinner />
      </Modal>
    );
  }

  if (!player) {
    return (
      <Modal title="Player" onClose={onClose}>
        <p className="text-muted">Player not found.</p>
      </Modal>
    );
  }

  return (
    <Modal
      title={
        <span>
          <span style={{ color: ratingColor(player.overall), fontWeight: 700 }}>
            {player.name}
          </span>
        </span>
      }
      onClose={onClose}
    >
      <div style={{ lineHeight: 1.6 }}>
        {/* Header: Position, OVR, POT */}
        <div style={{ fontSize: "0.9rem", color: "var(--color-muted)", marginBottom: "0.75rem" }}>
          {player.position}{player.secondary_position ? ` / ${player.secondary_position}` : ""} · OVR{" "}
          {player.overall} · POT {player.potential}
        </div>

        {/* Bio line: age, shoots, salary, team, injury */}
        <div style={{ fontSize: "0.9rem", color: "var(--color-muted)", marginBottom: "0.5rem" }}>
          Age {player.age} · {player.shoots} · {formatSalary(player.salary)} × {player.years_remaining}y
          {player.team_abbrev && ` · ${player.team_abbrev}`}
          {player.team_name && ` (${player.team_name})`}
        </div>

        {/* Injury in red if present */}
        {player.injury && (
          <div
            style={{
              fontSize: "0.9rem",
              color: "var(--color-accent-red)",
              marginBottom: "0.75rem",
              fontWeight: 500,
            }}
          >
            Injured: {player.injury} ({player.injury_games} games)
          </div>
        )}

        {/* Draft provenance line */}
        {player.draft ? (
          <div style={{ fontSize: "0.85rem", color: "var(--color-muted)", marginBottom: "1rem" }}>
            Drafted {(player.draft as any).year} · Round {(player.draft as any).round}, Pick{" "}
            {(player.draft as any).pick} ({(player.draft as any).team})
          </div>
        ) : (
          <div style={{ fontSize: "0.85rem", color: "var(--color-muted)", marginBottom: "1rem" }}>
            Undrafted
          </div>
        )}

        {/* Season stat tiles (skater vs goalie) */}
        {player.season_stats && (
          <div className="statRow">
            {player.is_goalie ? (
              <>
                <div>
                  <div className="label">GP</div>
                  <div className="value">{(player.season_stats as any).gp || 0}</div>
                </div>
                <div>
                  <div className="label">W</div>
                  <div className="value">{(player.season_stats as any).wins || 0}</div>
                </div>
                <div>
                  <div className="label">SV%</div>
                  <div className="value">
                    {(player.season_stats as any).save_pct
                      ? ((player.season_stats as any).save_pct * 100).toFixed(1)
                      : ".000"}
                  </div>
                </div>
                <div>
                  <div className="label">GAA</div>
                  <div className="value">
                    {(player.season_stats as any).gaa
                      ? ((player.season_stats as any).gaa as number).toFixed(2)
                      : "0.00"}
                  </div>
                </div>
                <div>
                  <div className="label">SO</div>
                  <div className="value">{(player.season_stats as any).shutouts || 0}</div>
                </div>
              </>
            ) : (
              <>
                <div>
                  <div className="label">GP</div>
                  <div className="value">{(player.season_stats as any).gp || 0}</div>
                </div>
                <div>
                  <div className="label">G</div>
                  <div className="value">{(player.season_stats as any).g || 0}</div>
                </div>
                <div>
                  <div className="label">A</div>
                  <div className="value">{(player.season_stats as any).a || 0}</div>
                </div>
                <div>
                  <div className="label">PTS</div>
                  <div className="value">{(player.season_stats as any).pts || 0}</div>
                </div>
                <div>
                  <div className="label">PPG</div>
                  <div className="value">
                    {(player.season_stats as any).ppg
                      ? ((player.season_stats as any).ppg as number).toFixed(2)
                      : "0.00"}
                  </div>
                </div>
                <div>
                  <div className="label">+/-</div>
                  <div className="value">{(player.season_stats as any).plus_minus || 0}</div>
                </div>
              </>
            )}
          </div>
        )}

        {/* Playoff stat tiles */}
        {player.playoff_stats && (
          <div>
            <div style={{ fontSize: "0.875rem", fontWeight: 600, marginBottom: "0.5rem", marginTop: "1rem" }}>
              Playoff Stats
            </div>
            <div className="statRow">
              {player.is_goalie ? (
                <>
                  <div>
                    <div className="label">GP</div>
                    <div className="value">{(player.playoff_stats as any).gp || 0}</div>
                  </div>
                  <div>
                    <div className="label">W</div>
                    <div className="value">{(player.playoff_stats as any).wins || 0}</div>
                  </div>
                  <div>
                    <div className="label">SV%</div>
                    <div className="value">
                      {(player.playoff_stats as any).save_pct
                        ? ((player.playoff_stats as any).save_pct * 100).toFixed(1)
                        : ".000"}
                    </div>
                  </div>
                  <div>
                    <div className="label">GAA</div>
                    <div className="value">
                      {(player.playoff_stats as any).gaa
                        ? ((player.playoff_stats as any).gaa as number).toFixed(2)
                        : "0.00"}
                    </div>
                  </div>
                  <div>
                    <div className="label">SO</div>
                    <div className="value">{(player.playoff_stats as any).shutouts || 0}</div>
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <div className="label">GP</div>
                    <div className="value">{(player.playoff_stats as any).gp || 0}</div>
                  </div>
                  <div>
                    <div className="label">G</div>
                    <div className="value">{(player.playoff_stats as any).g || 0}</div>
                  </div>
                  <div>
                    <div className="label">A</div>
                    <div className="value">{(player.playoff_stats as any).a || 0}</div>
                  </div>
                  <div>
                    <div className="label">PTS</div>
                    <div className="value">{(player.playoff_stats as any).pts || 0}</div>
                  </div>
                  <div>
                    <div className="label">PPG</div>
                    <div className="value">
                      {(player.playoff_stats as any).ppg
                        ? ((player.playoff_stats as any).ppg as number).toFixed(2)
                        : "0.00"}
                    </div>
                  </div>
                  <div>
                    <div className="label">+/-</div>
                    <div className="value">{(player.playoff_stats as any).plus_minus || 0}</div>
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        {/* Legacy résumé box */}
        {player.legacy && (
          <div className="legacyBox">
            <h4 style={{ margin: "0 0 0.5rem 0", fontSize: "0.95rem" }}>
              Career {(player.legacy as any).hof && <span title="Hall of Famer">🏅</span>}
            </h4>
            <div style={{ fontSize: "0.85rem", color: "var(--color-muted)", marginBottom: "0.75rem" }}>
              {(player.legacy as any).seasons} seasons · peak OVR {(player.legacy as any).peak_ovr}
              {(player.legacy as any).totals && (
                <>
                  {player.is_goalie ? (
                    <>
                      {" "}
                      · {(player.legacy as any).totals.wins || 0} W ·{" "}
                      {((player.legacy as any).totals.save_pct * 100).toFixed(1)}% SV
                    </>
                  ) : (
                    <>
                      {" "}
                      · {(player.legacy as any).totals.g || 0} G · {(player.legacy as any).totals.a || 0} A ·{" "}
                      {(player.legacy as any).totals.pts || 0} PTS
                    </>
                  )}
                </>
              )}
            </div>
            {(player.legacy as any).accolades && (player.legacy as any).accolades.length > 0 && (
              <div className="legacyAccolades">
                {(player.legacy as any).accolades.map((accolade: any) => (
                  <span key={String(accolade.key)} className="accoladeChip">
                    {String(accolade.count)}× {String(accolade.label)}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Career stats table */}
        {player.career && player.career.length > 0 && (
          <div style={{ marginTop: "1.5rem" }}>
            <h4 style={{ margin: "0 0 1rem 0", fontSize: "0.95rem" }}>By Season</h4>
            <div style={{ overflowX: "auto" }}>
              <table
                style={{
                  width: "100%",
                  fontSize: "0.85rem",
                  borderCollapse: "collapse",
                  fontFamily: "var(--font-mono)",
                }}
              >
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--color-border)" }}>
                    <th style={{ textAlign: "left", padding: "0.5rem 0.25rem", color: "var(--color-muted)" }}>
                      Year
                    </th>
                    <th style={{ textAlign: "left", padding: "0.5rem 0.25rem", color: "var(--color-muted)" }}>
                      Team
                    </th>
                    <th style={{ textAlign: "center", padding: "0.5rem 0.25rem", color: "var(--color-muted)" }}>
                      GP
                    </th>
                    {player.is_goalie ? (
                      <>
                        <th style={{ textAlign: "center", padding: "0.5rem 0.25rem", color: "var(--color-muted)" }}>
                          W
                        </th>
                        <th style={{ textAlign: "center", padding: "0.5rem 0.25rem", color: "var(--color-muted)" }}>
                          SV%
                        </th>
                        <th style={{ textAlign: "center", padding: "0.5rem 0.25rem", color: "var(--color-muted)" }}>
                          GAA
                        </th>
                      </>
                    ) : (
                      <>
                        <th style={{ textAlign: "center", padding: "0.5rem 0.25rem", color: "var(--color-muted)" }}>
                          G
                        </th>
                        <th style={{ textAlign: "center", padding: "0.5rem 0.25rem", color: "var(--color-muted)" }}>
                          A
                        </th>
                        <th style={{ textAlign: "center", padding: "0.5rem 0.25rem", color: "var(--color-muted)" }}>
                          PPG
                        </th>
                      </>
                    )}
                    <th style={{ textAlign: "center", padding: "0.5rem 0.25rem", color: "var(--color-muted)" }}>
                      OVR
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {player.career.map((season: any, idx: number) => (
                    <tr key={idx} style={{ borderBottom: "1px solid var(--color-border)" }}>
                      <td style={{ textAlign: "left", padding: "0.5rem 0.25rem" }}>{season.year}</td>
                      <td style={{ textAlign: "left", padding: "0.5rem 0.25rem" }}>
                        {season.team_abbrev || "—"}
                      </td>
                      <td style={{ textAlign: "center", padding: "0.5rem 0.25rem" }}>{season.gp || 0}</td>
                      {player.is_goalie ? (
                        <>
                          <td style={{ textAlign: "center", padding: "0.5rem 0.25rem" }}>
                            {season.wins || 0}
                          </td>
                          <td style={{ textAlign: "center", padding: "0.5rem 0.25rem" }}>
                            {season.save_pct
                              ? (season.save_pct * 100).toFixed(1)
                              : ".000"}
                          </td>
                          <td style={{ textAlign: "center", padding: "0.5rem 0.25rem" }}>
                            {season.gaa ? season.gaa.toFixed(2) : "0.00"}
                          </td>
                        </>
                      ) : (
                        <>
                          <td style={{ textAlign: "center", padding: "0.5rem 0.25rem" }}>
                            {season.g || 0}
                          </td>
                          <td style={{ textAlign: "center", padding: "0.5rem 0.25rem" }}>
                            {season.a || 0}
                          </td>
                          <td style={{ textAlign: "center", padding: "0.5rem 0.25rem" }}>
                            {season.ppg ? season.ppg.toFixed(2) : "0.00"}
                          </td>
                        </>
                      )}
                      <td style={{ textAlign: "center", padding: "0.5rem 0.25rem" }}>
                        {season.overall || 0}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Rating groups as labeled progress bars */}
        {player.rating_groups && Object.keys(player.rating_groups).length > 0 && (
          <div style={{ marginTop: "1.5rem" }}>
            {Object.entries(player.rating_groups).map(([groupName, ratings]) => (
              <div key={groupName} className="ratingGroup">
                <h4>{groupName}</h4>
                {ratings.map((rating) => (
                  <div key={rating.key} className="ratingRow">
                    <span>{rating.label}</span>
                    <span className="ratingBar">
                      <span
                        className="ratingFill"
                        style={{
                          width: `${ratingBarWidth(rating.value)}%`,
                          backgroundColor: ratingColor(rating.value),
                        }}
                      />
                    </span>
                    <b style={{ color: ratingColor(rating.value) }}>{rating.value}</b>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}

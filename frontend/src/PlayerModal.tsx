// Player detail modal (T7)
// Full player card with stats, ratings, legacy résumé, and career table.

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
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

export function PlayerModal({
  pid,
  onClose,
  toast,
}: {
  pid: number;
  onClose: () => void;
  toast?: (msg: string) => void;
}) {
  const queryClient = useQueryClient();
  const { data: player, isLoading } = useQuery({
    queryKey: ["player", pid],
    queryFn: () => api.getPlayer(pid),
  });

  const sendDownMutation = useMutation({
    mutationFn: () => api.sendDownPlayer(pid),
    onSuccess: (result) => {
      toast?.(result.message);
      if (result.ok) {
        queryClient.invalidateQueries({ queryKey: ["player", pid] });
        queryClient.invalidateQueries({ queryKey: ["prospects"] });
        queryClient.invalidateQueries({ queryKey: ["roster"] });
        queryClient.invalidateQueries({ queryKey: ["rosterLines"] });
        queryClient.invalidateQueries({ queryKey: ["cap"] });
        onClose();
      }
    },
    onError: (e: Error) => toast?.(e.message),
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
        {/* Header: Position, OVR, POT, archetype/role */}
        <div style={{ fontSize: "0.9rem", color: "var(--color-muted)", marginBottom: "0.75rem" }}>
          {player.position}{player.secondary_position ? ` / ${player.secondary_position}` : ""} · OVR{" "}
          {player.overall} · POT {player.potential}
          {player.archetype && (
            <>
              {" · "}
              <span style={{ color: "var(--color-text)" }}>{player.archetype}</span>
              {player.role_label && !player.is_goalie && ` (${player.role_label})`}
            </>
          )}
        </div>

        {/* Bio line: age, shoots, salary, team, injury */}
        <div style={{ fontSize: "0.9rem", color: "var(--color-muted)", marginBottom: "0.5rem" }}>
          Age {player.age} · {player.shoots} · {formatSalary(player.salary)} × {player.years_remaining}y
          {player.years_remaining > 0 && ` · ${player.two_way ? "two-way" : "one-way"}`}
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

        {/* Development record -- where a prospect is, and what decision he represents. */}
        {player.development ? (
          <div
            style={{
              fontSize: "0.85rem",
              marginBottom: "1rem",
              padding: "0.6rem 0.75rem",
              border: "1px solid var(--color-border)",
              borderRadius: "6px",
            }}
          >
            <strong>{(player.development as any).tier_label}</strong>
            <span className="text-muted">
              {" "}
              · season {(player.development as any).seasons + 1}
              {(player.development as any).undrafted ? " · undrafted" : ""}
            </span>
            <div style={{ marginTop: "0.25rem" }}>
              {(player.development as any).status}
              {(player.development as any).slides_this_year ? (
                <span style={{ color: "var(--color-accent-blue)" }}>
                  {" "}
                  — entry-level year does not burn
                </span>
              ) : null}
              {(player.development as any).slide_years > 0 ? (
                <span className="text-muted">
                  {" "}
                  (slid {(player.development as any).slide_years}x)
                </span>
              ) : null}
            </div>
          </div>
        ) : null}

        {/* Roster action: send a rostered player down to the minors. Only shown when the
            move is legal (own roster, under contract, still tier-eligible) -- see
            can_send_down on the DTO. */}
        {player.can_send_down ? (
          <div style={{ marginBottom: "1rem" }}>
            <button
              onClick={() => sendDownMutation.mutate()}
              disabled={sendDownMutation.isPending}
              style={{
                padding: "0.4rem 0.8rem",
                fontSize: "0.85rem",
                cursor: sendDownMutation.isPending ? "wait" : "pointer",
              }}
            >
              {sendDownMutation.isPending ? "Sending down…" : "Send to Minors"}
            </button>
            <span style={{ marginLeft: "0.6rem", fontSize: "0.8rem", color: "var(--color-muted)" }}>
              {player.bury_cap_hit > 0
                ? `one-way — ${formatSalary(player.bury_cap_hit)} stays on the cap`
                : "frees his full cap hit"}
            </span>
          </div>
        ) : null}

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

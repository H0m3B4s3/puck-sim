// Leaders screen (T10 feature — T6 foundation).
// Shows current season leaders by category (top 10 in each of 6 categories).

import { useEffect, useState } from "react";
import { LeadersResponse, WorldSummary } from "../api";
import { Panel, FaceoffDotSpinner } from "../ui";
import api from "../api";

export function LeadersScreen({
  onPlayer,
}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
}) {
  const [data, setData] = useState<LeadersResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api
      .getLeaders()
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="screen screen-leaders">
        <Panel>
          <FaceoffDotSpinner />
        </Panel>
      </div>
    );
  }

  if (error) {
    return (
      <div className="screen screen-leaders">
        <Panel>
          <h2 className="text-display">Leaders</h2>
          <p className="text-muted" style={{ marginTop: "1rem" }}>
            Error loading leaders: {error}
          </p>
        </Panel>
      </div>
    );
  }

  if (!data || !data.categories || data.categories.length === 0) {
    return (
      <div className="screen screen-leaders">
        <Panel>
          <h2 className="text-display">Leaders</h2>
          <p className="text-muted" style={{ marginTop: "1rem" }}>
            No leader data available yet. Play some games to populate the leaderboards.
          </p>
        </Panel>
      </div>
    );
  }

  return (
    <div className="screen screen-leaders">
      <Panel style={{ marginBottom: "2rem" }}>
        <h2 className="text-display">Season Leaders</h2>
      </Panel>
      <div className="leadersGrid">
        {data.categories.map((category) => (
          <Panel key={category.stat}>
            <h3 style={{ marginTop: 0, marginBottom: "1rem" }}>
              {category.label}
            </h3>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <tbody>
                  {category.leaders.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="text-muted" style={{ padding: "1rem", textAlign: "center" }}>
                        No leaders yet
                      </td>
                    </tr>
                  ) : (
                    category.leaders.map((leader, idx) => (
                      <tr
                        key={leader.pid}
                        style={{
                          borderBottom: "1px solid var(--color-border)",
                          cursor: onPlayer ? "pointer" : "default",
                        }}
                        onClick={() => onPlayer?.(leader.pid)}
                        className={onPlayer ? "clickable" : ""}
                      >
                        <td
                          style={{
                            padding: "0.75rem",
                            width: "40px",
                            color: "var(--color-muted)",
                            textAlign: "center",
                            fontSize: "0.9rem",
                          }}
                        >
                          {idx + 1}
                        </td>
                        <td
                          style={{
                            padding: "0.75rem",
                            flex: 1,
                            minWidth: 0,
                          }}
                        >
                          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                            <span>{leader.name}</span>
                            <span
                              style={{
                                fontSize: "0.85rem",
                                padding: "0.2rem 0.4rem",
                                borderRadius: "3px",
                                backgroundColor: leader.team_color,
                                color: "#f2f4f6",
                                fontWeight: 600,
                                fontFamily: "var(--font-display)",
                              }}
                            >
                              {leader.team_abbrev}
                            </span>
                          </div>
                        </td>
                        <td
                          style={{
                            padding: "0.75rem",
                            width: "80px",
                            textAlign: "right",
                            fontWeight: 600,
                            fontFamily: "var(--font-mono)",
                          }}
                        >
                          {typeof leader.value === "number" &&
                          (category.stat === "save_pct" || category.stat === "gaa")
                            ? leader.value.toFixed(
                                category.stat === "gaa" ? 2 : 3
                              )
                            : leader.value}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </Panel>
        ))}
      </div>
    </div>
  );
}

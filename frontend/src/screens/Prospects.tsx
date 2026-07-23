import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, { Prospect } from "../api";
import { Panel, FaceoffDotSpinner, Pill, formatMoney } from "../ui";

/**
 * Prospects screen -- the team's development system (docs/PROSPECT_DEV_PLAN.md).
 *
 * The reserve list a manager can't see anywhere else: every player whose rights the team
 * holds who is developing in junior, college, the AHL or Europe. Grouped by tier, because
 * "where is he" is the first question and it's the one the tier system exists to answer.
 *
 * Two things get prominence over raw ratings, since both are decisions rather than facts:
 *   - The entry-level slide. A signed 18- or 19-year-old who stays out of the NHL doesn't
 *     burn a contract year, and that is the whole reason to sign a teenager early. It's
 *     invisible unless the UI says so, so each signed prospect shows whether his deal
 *     slides this season and how many times it already has.
 *   - Sign him or lose him. A junior graduate with no contract has nowhere to go next
 *     season and walks. That deadline is the single most consequential thing on this
 *     screen, so those rows are called out and sorted to the top of their tier.
 */

const TIER_ORDER = ["ahl", "chl", "ncaa", "europe"];

function statusTone(p: Prospect): string | undefined {
  if (p.nhl_ready) return "var(--color-accent-gold)";
  if (!p.signed && p.status.startsWith("Sign him")) return "var(--color-accent-red)";
  if (p.status === "Open to the league") return "var(--color-accent-red)";
  return undefined;
}

/** Urgency first, then ceiling -- a decision beats a good player you don't have to make one about. */
function sortProspects(a: Prospect, b: Prospect): number {
  const urgency = (p: Prospect) =>
    p.nhl_ready && !p.signed ? 0 : p.status.startsWith("Sign him") ? 1 : p.nhl_ready ? 2 : 3;
  const diff = urgency(a) - urgency(b);
  if (diff !== 0) return diff;
  return b.potential - a.potential || b.overall - a.overall;
}

function StatLine({ line }: { line: Record<string, number | string> }) {
  if (!line || !line.gp) return <span className="text-muted">—</span>;
  if (line.save_pct !== undefined) {
    return (
      <span>
        {line.gp} GP · {String(line.save_pct)} SV% · {String(line.gaa)} GAA
      </span>
    );
  }
  return (
    <span>
      {line.gp} GP · {line.g} G · {line.a} A · {line.pts} P
    </span>
  );
}

function ContractCell({ p }: { p: Prospect }) {
  if (!p.signed) {
    return (
      <span className="text-muted">
        Unsigned
        {p.years_of_control !== null && p.years_of_control !== undefined ? (
          <> · rights {p.years_of_control}y</>
        ) : p.undrafted ? (
          <> · undrafted</>
        ) : null}
      </span>
    );
  }
  return (
    <span>
      {formatMoney(p.salary)} · {p.years_remaining}y
      {p.slides_this_year ? (
        <>
          {" "}
          <Pill color="var(--color-accent-blue)">SLIDES</Pill>
        </>
      ) : null}
      {p.slide_years > 0 ? (
        <span className="text-muted"> · slid {p.slide_years}x</span>
      ) : null}
    </span>
  );
}

export function ProspectsScreen({
  onPlayer,
  toast,
}: {
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
} = {}) {
  const queryClient = useQueryClient();
  const [pendingPid, setPendingPid] = useState<number | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["prospects"],
    queryFn: api.getProspects,
  });

  const afterMove = (result: { ok: boolean; message: string }) => {
    toast?.(result.message);
    if (result.ok) {
      queryClient.invalidateQueries({ queryKey: ["prospects"] });
      queryClient.invalidateQueries({ queryKey: ["cap"] });
      queryClient.invalidateQueries({ queryKey: ["roster"] });
      queryClient.invalidateQueries({ queryKey: ["rosterLines"] });
    }
  };

  const signMutation = useMutation({
    mutationFn: (pid: number) => api.signProspect(pid),
    onSettled: () => setPendingPid(null),
    onSuccess: afterMove,
    onError: (e: Error) => toast?.(e.message),
  });

  const callUpMutation = useMutation({
    mutationFn: (pid: number) => api.callUpProspect(pid),
    onSettled: () => setPendingPid(null),
    onSuccess: afterMove,
    onError: (e: Error) => toast?.(e.message),
  });

  const byTier = useMemo(() => {
    const groups = new Map<string, Prospect[]>();
    for (const p of data?.prospects ?? []) {
      const list = groups.get(p.tier) ?? [];
      list.push(p);
      groups.set(p.tier, list);
    }
    for (const list of groups.values()) list.sort(sortProspects);
    return TIER_ORDER.filter((t) => groups.has(t)).map((t) => ({
      tier: t,
      label: groups.get(t)![0].tier_label,
      players: groups.get(t)!,
    }));
  }, [data]);

  if (isLoading) return <FaceoffDotSpinner />;
  if (error) return <Panel><p className="text-muted">{(error as Error).message}</p></Panel>;

  const pool = data!;
  const decisions = pool.prospects.filter(
    (p) => !p.signed && (p.nhl_ready || p.status.startsWith("Sign him"))
  ).length;

  return (
    <div className="screen screen-prospects">
      <Panel>
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            justifyContent: "space-between",
            gap: "1rem",
            flexWrap: "wrap",
          }}
        >
          <h2 className="text-display">Prospects</h2>
          <div className="text-muted" style={{ fontSize: "0.9rem" }}>
            {pool.prospects.length} in the system ·{" "}
            <span
              style={{
                color:
                  pool.contracts_used >= pool.contracts_max
                    ? "var(--color-accent-red)"
                    : undefined,
              }}
            >
              {pool.contracts_used}/{pool.contracts_max} contracts
            </span>
          </div>
        </div>

        <p className="text-muted" style={{ marginTop: "0.5rem", maxWidth: "62ch" }}>
          Players whose rights you hold, developing outside the NHL. They cost no cap space
          and take no roster spot, and they graduate when their rating says they're ready —
          not on a schedule.
          {decisions > 0 ? (
            <>
              {" "}
              <strong>
                {decisions} {decisions === 1 ? "player needs" : "players need"} a decision
                this offseason.
              </strong>
            </>
          ) : null}
        </p>

        {pool.prospects.length === 0 ? (
          <p className="text-muted" style={{ marginTop: "2rem" }}>
            No prospects yet. Draft picks who aren't NHL-ready go straight into a
            development tier — junior, college, or the AHL, depending on where they came up
            and how old they are.
          </p>
        ) : null}

        {byTier.map(({ tier, label, players }) => (
          <section key={tier} style={{ marginTop: "2rem" }}>
            <h3
              style={{
                fontSize: "0.95rem",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: "var(--color-muted)",
                borderBottom: "2px solid var(--color-border)",
                paddingBottom: "0.4rem",
              }}
            >
              {label}
              <span style={{ marginLeft: "0.6rem", opacity: 0.7 }}>{players.length}</span>
            </h3>

            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", minWidth: "46rem" }}>
                <thead>
                  <tr style={{ textAlign: "left", color: "var(--color-muted)", fontSize: "0.8rem" }}>
                    <th style={{ padding: "0.5rem 0.6rem" }}>Player</th>
                    <th style={{ padding: "0.5rem 0.6rem" }}>Age</th>
                    <th style={{ padding: "0.5rem 0.6rem" }}>OVR</th>
                    <th style={{ padding: "0.5rem 0.6rem" }}>POT</th>
                    <th style={{ padding: "0.5rem 0.6rem" }}>Season</th>
                    <th style={{ padding: "0.5rem 0.6rem" }}>Contract</th>
                    <th style={{ padding: "0.5rem 0.6rem" }}>Status</th>
                    <th style={{ padding: "0.5rem 0.6rem" }} />
                  </tr>
                </thead>
                <tbody>
                  {players.map((p) => (
                    <tr key={p.pid} style={{ borderTop: "1px solid var(--color-border)" }}>
                      <td style={{ padding: "0.5rem 0.6rem" }}>
                        <button
                          onClick={() => onPlayer?.(p.pid)}
                          style={{
                            background: "none",
                            border: "none",
                            padding: 0,
                            color: "inherit",
                            font: "inherit",
                            cursor: onPlayer ? "pointer" : "default",
                            textAlign: "left",
                          }}
                        >
                          <strong>{p.name}</strong>
                        </button>
                        <span className="text-muted"> {p.position}</span>
                      </td>
                      <td style={{ padding: "0.5rem 0.6rem" }}>{p.age}</td>
                      <td style={{ padding: "0.5rem 0.6rem" }}>{p.overall}</td>
                      <td style={{ padding: "0.5rem 0.6rem" }} className="text-muted">
                        {p.potential}
                      </td>
                      <td style={{ padding: "0.5rem 0.6rem", fontSize: "0.85rem" }}>
                        <StatLine line={p.line} />
                      </td>
                      <td style={{ padding: "0.5rem 0.6rem", fontSize: "0.85rem" }}>
                        <ContractCell p={p} />
                      </td>
                      <td
                        style={{
                          padding: "0.5rem 0.6rem",
                          fontSize: "0.85rem",
                          color: statusTone(p),
                        }}
                      >
                        {p.status}
                      </td>
                      <td style={{ padding: "0.5rem 0.6rem", textAlign: "right" }}>
                        {!p.signed ? (
                          <button
                            onClick={() => {
                              setPendingPid(p.pid);
                              signMutation.mutate(p.pid);
                            }}
                            disabled={pendingPid !== null}
                            style={{
                              padding: "0.35rem 0.7rem",
                              fontSize: "0.8rem",
                              cursor: pendingPid !== null ? "wait" : "pointer",
                            }}
                          >
                            {pendingPid === p.pid ? "Signing…" : "Sign ELC"}
                          </button>
                        ) : (
                          <button
                            onClick={() => {
                              setPendingPid(p.pid);
                              callUpMutation.mutate(p.pid);
                            }}
                            disabled={pendingPid !== null}
                            title={
                              p.nhl_ready
                                ? "Add to the NHL roster"
                                : "He can be called up, but he isn't NHL-ready yet"
                            }
                            style={{
                              padding: "0.35rem 0.7rem",
                              fontSize: "0.8rem",
                              cursor: pendingPid !== null ? "wait" : "pointer",
                              fontWeight: p.nhl_ready ? 600 : 400,
                              borderColor: p.nhl_ready
                                ? "var(--color-accent-gold)"
                                : undefined,
                            }}
                          >
                            {pendingPid === p.pid ? "Calling up…" : "Call Up"}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </Panel>
    </div>
  );
}

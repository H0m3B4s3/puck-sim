import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api, { WorldSummary, RosterResponse } from "../api";
import { Panel, FaceoffDotSpinner } from "../ui";

/**
 * Trade Screen (T11)
 *
 * Dedicated trade builder with:
 * - Deadline banner (days left / passed state)
 * - Partner team dropdown (standings minus user's team)
 * - Two checkbox-based player picker panels
 * - Trade validation and execution flow
 * - Salary totals per side
 */
export function TradeScreen({
  world,
  onPlayer,
  toast,
}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
}) {
  const queryClient = useQueryClient();

  // Standings for partner dropdown
  const { data: standings } = useQuery({
    queryKey: ["standings"],
    queryFn: () => api.getStandings(),
  });

  // User's roster
  const { data: userRoster, isLoading: userLoading } = useQuery({
    queryKey: ["roster"],
    queryFn: () => api.getRoster(),
  });

  // State
  const [partner, setPartner] = useState<number | null>(null);
  const [userSends, setUserSends] = useState<number[]>([]);
  const [userReceives, setUserReceives] = useState<number[]>([]);
  const [verdict, setVerdict] = useState<string>("");

  // Partner's roster
  const { data: partnerRoster, isLoading: partnerLoading } = useQuery({
    queryKey: ["roster", partner],
    queryFn: () => (partner ? api.getTeamRoster(partner) : null),
    enabled: !!partner,
  });

  // Set initial partner to first other team
  useEffect(() => {
    if (standings && !partner) {
      const others = standings.filter((t) => t.id !== world.user_team_id);
      if (others.length > 0) {
        setPartner(others[0].id);
      }
    }
  }, [standings, partner, world.user_team_id]);

  // Clear selections when partner changes
  useEffect(() => {
    setUserSends([]);
    setUserReceives([]);
    setVerdict("");
  }, [partner]);

  const validateMutation = useMutation({
    mutationFn: async () => {
      if (!partner) return;
      const result = await api.validateTrade({
        other_team_id: partner,
        user_sends: userSends,
        user_receives: userReceives,
      });
      return result;
    },
    onSuccess: (data) => {
      if (!data) return;
      const legalStatus = data.legal ? "Legal" : "Illegal";
      const aiStatus =
        data.legal && data.accepts
          ? "AI accepts."
          : `AI declines: ${data.ai_reason}`;
      const msg = `${legalStatus}: ${data.legal_reason}. ${
        data.legal ? aiStatus : ""
      }`;
      setVerdict(msg);
    },
    onError: (error) => {
      const msg = error instanceof Error ? error.message : "Trade validation failed";
      toast?.(msg);
    },
  });

  const executeMutation = useMutation({
    mutationFn: async () => {
      if (!partner) return;
      const result = await api.executeTrade({
        other_team_id: partner,
        user_sends: userSends,
        user_receives: userReceives,
      });
      return result;
    },
    onSuccess: async (data) => {
      if (!data) return;
      if (data.executed) {
        toast?.("Trade executed!");
        setUserSends([]);
        setUserReceives([]);
        setVerdict("");
        // Invalidate caches
        await queryClient.invalidateQueries({ queryKey: ["roster"] });
        await queryClient.invalidateQueries({ queryKey: ["standings"] });
        await queryClient.invalidateQueries({ queryKey: ["career"] });
        // Refetch partner roster
        queryClient.invalidateQueries({ queryKey: ["roster", partner] });
      } else {
        toast?.(data.reason);
      }
    },
    onError: (error) => {
      const msg = error instanceof Error ? error.message : "Trade execution failed";
      toast?.(msg);
    },
  });

  const deadlinePassed = world.trade_deadline_passed;
  const daysLeft = world.trade_deadline_day ?? 0;

  // Calculate salary totals
  const userSendSalary = userRoster?.players
    ?.filter((p) => userSends.includes(p.pid))
    .reduce((sum, p) => sum + (p.contract?.current_salary || 0), 0) ?? 0;

  const userReceiveSalary = partnerRoster?.players
    ?.filter((p) => userReceives.includes(p.pid))
    .reduce((sum, p) => sum + (p.contract?.current_salary || 0), 0) ?? 0;

  const others = standings?.filter((t) => t.id !== world.user_team_id) || [];

  const isValidTrade = (userSends.length > 0 || userReceives.length > 0) && !deadlinePassed;

  return (
    <div className="screen screen-trade">
      <Panel>
        <h2 className="text-display">Trades</h2>

        {/* Deadline Banner */}
        {deadlinePassed ? (
          <div className="deadline passed">
            🔒 Trade deadline has passed — trading reopens next season.
          </div>
        ) : (
          <div className={`deadline${daysLeft <= 7 ? " soon" : ""}`}>
            ⏳ Trade deadline in <strong>{daysLeft}</strong>{" "}
            {daysLeft === 1 ? "day" : "days"}
          </div>
        )}

        {/* Partner Selection */}
        <div style={{ marginBottom: "1.5rem" }}>
          <label
            style={{
              display: "block",
              marginBottom: "0.5rem",
              fontSize: "0.875rem",
              fontWeight: 500,
            }}
          >
            Trade Partner:
          </label>
          <select
            value={partner ?? ""}
            onChange={(e) => setPartner(Number(e.target.value))}
            style={{
              width: "100%",
              padding: "0.5rem",
              fontSize: "0.9375rem",
              borderRadius: "4px",
              border: "1px solid var(--color-border)",
              backgroundColor: "var(--color-surface-card)",
              color: "var(--color-text)",
            }}
          >
            <option value="">Select a team...</option>
            {others.map((team) => (
              <option key={team.id} value={team.id}>
                {team.abbrev} - {team.name}
              </option>
            ))}
          </select>
        </div>

        {/* Trade Grid */}
        <div className="tradeGrid">
          {/* You Send */}
          <div>
            <PickList
              title="You Send"
              data={userRoster}
              selected={userSends}
              onToggle={(pid) => {
                setUserSends(
                  userSends.includes(pid)
                    ? userSends.filter((p) => p !== pid)
                    : [...userSends, pid]
                );
              }}
              onPlayer={onPlayer}
              isLoading={userLoading}
            />
            <div style={{ marginTop: "0.5rem", fontSize: "0.875rem", color: "var(--color-muted)" }}>
              Salary: <span style={{ fontWeight: 600, color: "var(--color-text)" }}>
                ${(userSendSalary / 1_000_000).toFixed(1)}M
              </span>
            </div>
          </div>

          {/* You Receive */}
          <div>
            <PickList
              title="You Receive"
              data={partnerRoster}
              selected={userReceives}
              onToggle={(pid) => {
                setUserReceives(
                  userReceives.includes(pid)
                    ? userReceives.filter((p) => p !== pid)
                    : [...userReceives, pid]
                );
              }}
              onPlayer={onPlayer}
              isLoading={partnerLoading}
            />
            <div style={{ marginTop: "0.5rem", fontSize: "0.875rem", color: "var(--color-muted)" }}>
              Salary: <span style={{ fontWeight: 600, color: "var(--color-text)" }}>
                ${(userReceiveSalary / 1_000_000).toFixed(1)}M
              </span>
            </div>
          </div>
        </div>

        {/* Verdict */}
        {verdict && (
          <div className="verdict">
            <div style={{ fontSize: "0.9375rem" }}>{verdict}</div>
          </div>
        )}

        {/* Action Buttons */}
        <div
          style={{
            display: "flex",
            gap: "1rem",
            marginTop: "1.5rem",
          }}
        >
          <button
            className="btn btn-secondary"
            onClick={() => validateMutation.mutate()}
            disabled={!isValidTrade || validateMutation.isPending}
            style={{ padding: "0.5rem 1rem", fontSize: "0.9375rem" }}
          >
            {validateMutation.isPending ? "Checking..." : "Check Trade"}
          </button>
          <button
            className="btn btn-primary"
            onClick={() => executeMutation.mutate()}
            disabled={!isValidTrade || executeMutation.isPending}
            style={{ padding: "0.5rem 1rem", fontSize: "0.9375rem" }}
          >
            {executeMutation.isPending ? "Executing..." : "Execute"}
          </button>
        </div>
      </Panel>
    </div>
  );
}

/**
 * PickList component — displays a roster with checkboxes for selection
 */
function PickList({
  title,
  data,
  selected,
  onToggle,
  onPlayer,
  isLoading,
}: {
  title: string;
  data: RosterResponse | null | undefined;
  selected: number[];
  onToggle: (pid: number) => void;
  onPlayer?: (pid: number) => void;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div style={{ marginBottom: "1rem" }}>
        <h4 style={{ marginBottom: "0.5rem" }}>{title}</h4>
        <FaceoffDotSpinner />
      </div>
    );
  }

  if (!data || !data.players || data.players.length === 0) {
    return (
      <div style={{ marginBottom: "1rem" }}>
        <h4 style={{ marginBottom: "0.5rem" }}>{title}</h4>
        <p style={{ color: "var(--color-muted)", fontSize: "0.875rem" }}>
          No players available
        </p>
      </div>
    );
  }

  return (
    <div style={{ marginBottom: "1rem" }}>
      <h4 style={{ marginBottom: "0.5rem", fontSize: "0.95rem", fontWeight: 600 }}>
        {title}
      </h4>
      <div
        style={{
          border: "1px solid var(--color-border)",
          borderRadius: "4px",
          maxHeight: "400px",
          overflowY: "auto",
          backgroundColor: "var(--color-surface)",
        }}
      >
        {data.players.map((player) => (
          <label
            key={player.pid}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "0.5rem 0.75rem",
              borderBottom: "1px solid var(--color-border)",
              cursor: "pointer",
              backgroundColor: selected.includes(player.pid)
                ? "rgba(76, 141, 255, 0.1)"
                : "transparent",
              transition: "background-color 0.2s ease",
            }}
          >
            <input
              type="checkbox"
              checked={selected.includes(player.pid)}
              onChange={() => onToggle(player.pid)}
              style={{ cursor: "pointer" }}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <button
                onClick={() => onPlayer?.(player.pid)}
                style={{
                  background: "none",
                  border: "none",
                  padding: 0,
                  color: "var(--color-accent-blue)",
                  cursor: "pointer",
                  textDecoration: "underline",
                  fontWeight: 500,
                  font: "inherit",
                  textAlign: "left",
                }}
                title="View player details"
              >
                {player.name}
              </button>
              <div
                style={{
                  fontSize: "0.75rem",
                  color: "var(--color-muted)",
                  marginTop: "0.125rem",
                }}
              >
                {player.position} · Age {player.age} · OVR {player.overall}
              </div>
            </div>
            <div
              style={{
                fontSize: "0.8125rem",
                color: "var(--color-muted)",
                textAlign: "right",
                whiteSpace: "nowrap",
                marginLeft: "auto",
                paddingLeft: "0.5rem",
              }}
            >
              {player.contract && (
                <>
                  ${(player.contract.current_salary / 1_000_000).toFixed(1)}M
                  <br />
                  {player.contract.years_remaining}yr
                </>
              )}
            </div>
          </label>
        ))}
      </div>
    </div>
  );
}

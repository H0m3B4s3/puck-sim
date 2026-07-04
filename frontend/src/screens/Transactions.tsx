import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  ColumnDef,
} from "@tanstack/react-table";
import api, { FreeAgentRow } from "../api";
import { Panel, FaceoffDotSpinner } from "../ui";

/**
 * Transactions Screen (Step 2.10d)
 *
 * Displays cap summary, free agents, trades, draft board, and awards.
 * Uses a tabbed interface to switch between different transaction types.
 */
export function Transactions({
  onPlayer,
}: {
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
} = {}) {
  const [activeTab, setActiveTab] = useState<
    "cap" | "free-agents" | "trades" | "draft" | "awards"
  >("cap");

  return (
    <div className="screen screen-transactions">
      <Panel>
        <h2 className="text-display">Transactions</h2>

        {/* Tab Navigation */}
        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            marginTop: "1.5rem",
            borderBottom: "2px solid var(--color-border)",
            flexWrap: "wrap",
          }}
        >
          {[
            { id: "cap", label: "Cap" },
            { id: "free-agents", label: "Free Agents" },
            { id: "trades", label: "Trades" },
            { id: "draft", label: "Draft" },
            { id: "awards", label: "Awards" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              style={{
                padding: "0.75rem 1rem",
                background: "none",
                border: "none",
                borderBottom:
                  activeTab === tab.id
                    ? "3px solid var(--color-accent-red)"
                    : "none",
                color: activeTab === tab.id ? "var(--color-text)" : "var(--color-muted)",
                fontWeight: activeTab === tab.id ? 600 : 500,
                cursor: "pointer",
                fontSize: "1rem",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        <div style={{ marginTop: "2rem" }}>
          {activeTab === "cap" && <CapPanel />}
          {activeTab === "free-agents" && <FreeAgentsPanel onPlayer={onPlayer} />}
          {activeTab === "trades" && <TradesPanel />}
          {activeTab === "draft" && <DraftPanel />}
          {activeTab === "awards" && <AwardsPanel />}
        </div>
      </Panel>
    </div>
  );
}

// ============================================================================
// Cap Panel
// ============================================================================
function CapPanel() {
  const { data: cap, isLoading, error } = useQuery({
    queryKey: ["cap"],
    queryFn: () => api.getCapSummary(),
  });

  if (isLoading) return <FaceoffDotSpinner />;
  if (error || !cap) return <p className="text-muted">Error loading cap info</p>;

  const capPctUsed = ((cap.payroll / cap.salary_cap) * 100).toFixed(1);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
        gap: "1rem",
      }}
    >
      <div
        style={{
          padding: "1rem",
          backgroundColor: "var(--color-surface)",
          borderRadius: "8px",
          border: "1px solid var(--color-border)",
        }}
      >
        <div style={{ fontSize: "0.875rem", color: "var(--color-muted)", marginBottom: "0.5rem" }}>
          Salary Cap
        </div>
        <div style={{ fontSize: "1.5rem", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
          ${(cap.salary_cap / 1_000_000).toFixed(1)}M
        </div>
      </div>

      <div
        style={{
          padding: "1rem",
          backgroundColor: "var(--color-surface)",
          borderRadius: "8px",
          border: "1px solid var(--color-border)",
        }}
      >
        <div style={{ fontSize: "0.875rem", color: "var(--color-muted)", marginBottom: "0.5rem" }}>
          Payroll
        </div>
        <div style={{ fontSize: "1.5rem", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
          ${(cap.payroll / 1_000_000).toFixed(1)}M
        </div>
        <div style={{ fontSize: "0.75rem", color: "var(--color-muted)", marginTop: "0.25rem" }}>
          {capPctUsed}% used
        </div>
      </div>

      <div
        style={{
          padding: "1rem",
          backgroundColor: "var(--color-surface)",
          borderRadius: "8px",
          border: `1px solid var(--color-${cap.over_cap ? "accent-red" : "border"})`,
        }}
      >
        <div style={{ fontSize: "0.875rem", color: "var(--color-muted)", marginBottom: "0.5rem" }}>
          Cap Space
        </div>
        <div
          style={{
            fontSize: "1.5rem",
            fontWeight: 700,
            fontFamily: "var(--font-mono)",
            color: cap.over_cap ? "var(--color-accent-red)" : "var(--color-text)",
          }}
        >
          ${(cap.cap_space / 1_000_000).toFixed(1)}M
        </div>
        {cap.over_cap && (
          <div style={{ fontSize: "0.75rem", color: "var(--color-accent-red)", marginTop: "0.25rem" }}>
            Over cap
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Free Agents Panel
// ============================================================================
function FreeAgentsPanel({ onPlayer }: { onPlayer?: (pid: number) => void }) {
  const queryClient = useQueryClient();
  const { data: freeAgents, isLoading, error } = useQuery({
    queryKey: ["freeAgents"],
    queryFn: () => api.getFreeAgents() as Promise<FreeAgentRow[]>,
  });

  const signMutation = useMutation({
    mutationFn: (pid: number) => api.signFreeAgent(pid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["freeAgents"] });
      queryClient.invalidateQueries({ queryKey: ["cap"] });
    },
  });

  if (isLoading) return <FaceoffDotSpinner />;
  if (error) return <p className="text-muted">Error loading free agents</p>;
  if (!freeAgents || freeAgents.length === 0) {
    return <p className="text-muted">No free agents available</p>;
  }

  const columns: ColumnDef<FreeAgentRow>[] = [
    {
      header: "Player",
      accessorKey: "name",
      cell: (info) => (
        <div>
          <button
            onClick={() => onPlayer?.(info.row.original.pid)}
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
            {String(info.getValue())}
          </button>
          <div style={{ fontSize: "0.875rem", color: "var(--color-muted)" }}>
            {info.row.original.position}
          </div>
        </div>
      ),
    },
    {
      header: "Age",
      accessorKey: "age",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
    {
      header: "Overall",
      accessorKey: "overall",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
    {
      header: "Ask",
      accessorKey: "ask",
      cell: (info) => (
        <span className="text-mono">
          ${((info.getValue() as number) / 1_000_000).toFixed(1)}M
        </span>
      ),
    },
    {
      header: "Years",
      accessorKey: "preferred_years",
      cell: (info) => <span className="text-mono">{String(info.getValue())}yr</span>,
    },
    {
      header: "Action",
      id: "action",
      cell: (info) => (
        <button
          className="btn btn-primary"
          onClick={() => signMutation.mutate(info.row.original.pid)}
          disabled={signMutation.isPending}
          style={{ padding: "0.25rem 0.75rem", fontSize: "0.875rem" }}
        >
          {signMutation.isPending ? "Signing..." : "Sign"}
        </button>
      ),
    },
  ];

  const table = useReactTable({
    data: freeAgents,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: "0.9375rem",
        }}
      >
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr
              key={headerGroup.id}
              style={{
                borderBottom: "2px solid var(--color-border)",
                backgroundColor: "var(--color-surface)",
              }}
            >
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  style={{
                    padding: "0.75rem 1rem",
                    textAlign: "left",
                    fontWeight: 600,
                    fontSize: "0.8125rem",
                    color: "var(--color-muted)",
                    textTransform: "uppercase",
                  }}
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              style={{
                borderBottom: "1px solid var(--color-border)",
              }}
            >
              {row.getVisibleCells().map((cell) => (
                <td
                  key={cell.id}
                  style={{
                    padding: "0.75rem 1rem",
                  }}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ============================================================================
// Trades Panel
// ============================================================================
function TradesPanel() {
  const { data: standings } = useQuery({
    queryKey: ["standings"],
    queryFn: () => api.getStandings(),
  });

  const [otherTeamId, setOtherTeamId] = useState<string>("");
  const [userSends, setUserSends] = useState<string>("");
  const [userReceives, setUserReceives] = useState<string>("");
  const [tradeResult, setTradeResult] = useState<
    { accepted: boolean; reason: string } | null
  >(null);

  const tradeMutation = useMutation({
    mutationFn: () => {
      const userSendIds = userSends
        .split(",")
        .map((s) => parseInt(s.trim()))
        .filter((n) => !isNaN(n));
      const userReceiveIds = userReceives
        .split(",")
        .map((s) => parseInt(s.trim()))
        .filter((n) => !isNaN(n));

      return api.proposeTrade({
        other_team_id: parseInt(otherTeamId),
        user_sends: userSendIds,
        user_receives: userReceiveIds,
      });
    },
    onSuccess: (data) => {
      setTradeResult(data);
      if (data.accepted) {
        setUserSends("");
        setUserReceives("");
      }
    },
  });

  return (
    <div>
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          padding: "1.5rem",
          borderRadius: "8px",
          border: "1px solid var(--color-border)",
          marginBottom: "2rem",
        }}
      >
        <h3 style={{ marginBottom: "1rem", fontWeight: 600 }}>Propose a Trade</h3>

        <div style={{ marginBottom: "1rem" }}>
          <label
            style={{
              display: "block",
              marginBottom: "0.5rem",
              fontSize: "0.875rem",
              fontWeight: 500,
            }}
          >
            Trade With:
          </label>
          <select
            value={otherTeamId}
            onChange={(e) => setOtherTeamId(e.target.value)}
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
            {standings?.map((team) => (
              <option key={team.id} value={team.id}>
                {team.abbrev} - {team.name}
              </option>
            ))}
          </select>
        </div>

        <div style={{ marginBottom: "1rem" }}>
          <label
            style={{
              display: "block",
              marginBottom: "0.5rem",
              fontSize: "0.875rem",
              fontWeight: 500,
            }}
          >
            Player IDs You Send (comma-separated):
          </label>
          <input
            type="text"
            value={userSends}
            onChange={(e) => setUserSends(e.target.value)}
            placeholder="e.g. 1,2,3"
            style={{
              width: "100%",
              padding: "0.5rem",
              fontSize: "0.9375rem",
              borderRadius: "4px",
              border: "1px solid var(--color-border)",
              backgroundColor: "var(--color-surface-card)",
              color: "var(--color-text)",
            }}
          />
        </div>

        <div style={{ marginBottom: "1.5rem" }}>
          <label
            style={{
              display: "block",
              marginBottom: "0.5rem",
              fontSize: "0.875rem",
              fontWeight: 500,
            }}
          >
            Player IDs You Receive (comma-separated):
          </label>
          <input
            type="text"
            value={userReceives}
            onChange={(e) => setUserReceives(e.target.value)}
            placeholder="e.g. 10,11,12"
            style={{
              width: "100%",
              padding: "0.5rem",
              fontSize: "0.9375rem",
              borderRadius: "4px",
              border: "1px solid var(--color-border)",
              backgroundColor: "var(--color-surface-card)",
              color: "var(--color-text)",
            }}
          />
        </div>

        <button
          className="btn btn-primary"
          onClick={() => tradeMutation.mutate()}
          disabled={tradeMutation.isPending || !otherTeamId}
        >
          {tradeMutation.isPending ? "Proposing..." : "Propose Trade"}
        </button>
      </div>

      {tradeResult && (
        <div
          style={{
            padding: "1rem",
            backgroundColor: tradeResult.accepted
              ? "rgba(200, 16, 46, 0.1)"
              : "rgba(107, 118, 132, 0.1)",
            borderRadius: "8px",
            border: `1px solid ${
              tradeResult.accepted
                ? "var(--color-accent-red)"
                : "var(--color-muted)"
            }`,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: "0.5rem" }}>
            {tradeResult.accepted ? "Trade Accepted" : "Trade Rejected"}
          </div>
          <p style={{ margin: 0, fontSize: "0.9375rem" }}>
            {tradeResult.reason}
          </p>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Draft Panel
// ============================================================================
function DraftPanel() {
  const queryClient = useQueryClient();
  const { data: career } = useQuery({
    queryKey: ["career"],
    queryFn: () => api.getCareer(),
  });

  const { data: draftBoard, isLoading, error } = useQuery({
    queryKey: ["draftBoard"],
    queryFn: () => api.getDraftBoard(),
  });

  const pickMutation = useMutation({
    mutationFn: (prospectId: number) => api.makeDraftPick(prospectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["draftBoard"] });
      queryClient.invalidateQueries({ queryKey: ["career"] });
    },
  });

  if (isLoading) return <FaceoffDotSpinner />;
  if (error) return <p className="text-muted">Error loading draft board</p>;
  if (!draftBoard || !draftBoard.in_draft) {
    return (
      <div
        style={{
          padding: "2rem",
          textAlign: "center",
          backgroundColor: "var(--color-surface)",
          borderRadius: "8px",
          border: "1px solid var(--color-border)",
        }}
      >
        <p className="text-muted">No active draft</p>
      </div>
    );
  }

  const isUserOnClock = career && draftBoard.team_on_clock === career.user_team_id;

  const columns: ColumnDef<any>[] = [
    {
      header: "Prospect",
      accessorKey: "name",
      cell: (info) => (
        <div>
          <div style={{ fontWeight: 500 }}>{String(info.getValue())}</div>
          <div style={{ fontSize: "0.875rem", color: "var(--color-muted)" }}>
            {info.row.original.position}
          </div>
        </div>
      ),
    },
    {
      header: "Age",
      accessorKey: "age",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
    {
      header: "Overall",
      accessorKey: "overall",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
    {
      header: "Potential",
      accessorKey: "scouted_potential",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
    ...(isUserOnClock
      ? [
          {
            header: "Action",
            id: "action",
            cell: (info: any) => (
              <button
                className="btn btn-primary"
                onClick={() => pickMutation.mutate(info.row.original.pid)}
                disabled={pickMutation.isPending}
                style={{ padding: "0.25rem 0.75rem", fontSize: "0.875rem" }}
              >
                {pickMutation.isPending ? "Picking..." : "Pick"}
              </button>
            ),
          } as ColumnDef<any>,
        ]
      : []),
  ];

  const table = useReactTable({
    data: draftBoard.board || [],
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div>
      <div style={{ marginBottom: "1.5rem", fontSize: "0.9375rem" }}>
        <span style={{ fontWeight: 600 }}>Round:</span> {draftBoard.round_number || "—"}
        {draftBoard.team_on_clock && (
          <>
            <span style={{ margin: "0 1rem" }}>|</span>
            <span style={{ fontWeight: 600 }}>On the clock:</span> Team {draftBoard.team_on_clock}
            {isUserOnClock && (
              <span
                style={{
                  marginLeft: "0.5rem",
                  backgroundColor: "var(--color-accent-gold)",
                  color: "#12181F",
                  padding: "0.25rem 0.5rem",
                  borderRadius: "4px",
                  fontSize: "0.75rem",
                  fontWeight: 600,
                }}
              >
                YOUR PICK
              </span>
            )}
          </>
        )}
      </div>

      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: "0.9375rem",
        }}
      >
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr
              key={headerGroup.id}
              style={{
                borderBottom: "2px solid var(--color-border)",
                backgroundColor: "var(--color-surface)",
              }}
            >
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  style={{
                    padding: "0.75rem 1rem",
                    textAlign: "left",
                    fontWeight: 600,
                    fontSize: "0.8125rem",
                    color: "var(--color-muted)",
                    textTransform: "uppercase",
                  }}
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              style={{
                borderBottom: "1px solid var(--color-border)",
              }}
            >
              {row.getVisibleCells().map((cell) => (
                <td
                  key={cell.id}
                  style={{
                    padding: "0.75rem 1rem",
                  }}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ============================================================================
// Awards Panel
// ============================================================================
function AwardsPanel() {
  const { data: awardsData, isLoading, error } = useQuery({
    queryKey: ["awards"],
    queryFn: () => api.getAwards(),
  });

  if (isLoading) return <FaceoffDotSpinner />;
  if (error) return <p className="text-muted">Error loading awards</p>;

  if (!awardsData || Object.keys(awardsData.awards || {}).length === 0) {
    return (
      <div
        style={{
          padding: "2rem",
          textAlign: "center",
          backgroundColor: "var(--color-surface)",
          borderRadius: "8px",
          border: "1px solid var(--color-border)",
        }}
      >
        <p className="text-muted">No awards yet for season {awardsData?.season_year}</p>
      </div>
    );
  }

  return (
    <div>
      <div style={{ marginBottom: "1rem", fontSize: "0.9375rem", color: "var(--color-muted)" }}>
        Season {awardsData.season_year}
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))",
          gap: "1rem",
        }}
      >
        {Object.entries(awardsData.awards || {}).map(([awardName, winner]: [string, any]) => (
          <div
            key={awardName}
            style={{
              padding: "1rem",
              backgroundColor: "var(--color-surface)",
              borderRadius: "8px",
              border: "1px solid var(--color-border)",
            }}
          >
            <div
              style={{
                fontSize: "0.875rem",
                fontWeight: 600,
                color: "var(--color-muted)",
                marginBottom: "0.5rem",
                textTransform: "uppercase",
              }}
            >
              {awardName}
            </div>
            {typeof winner === "string" ? (
              <div style={{ fontWeight: 500 }}>{winner}</div>
            ) : typeof winner === "object" && winner !== null ? (
              <div>
                <div style={{ fontWeight: 500 }}>
                  {(winner as any).name || "Unknown"}
                </div>
                {(winner as any).team && (
                  <div style={{ fontSize: "0.875rem", color: "var(--color-muted)" }}>
                    {(winner as any).team}
                  </div>
                )}
              </div>
            ) : (
              <div style={{ color: "var(--color-muted)" }}>—</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

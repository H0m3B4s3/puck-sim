import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  ColumnDef,
} from "@tanstack/react-table";
import api, { FreeAgentRow, OffseasonDraftBoardEntry } from "../api";
import { Panel, FaceoffDotSpinner } from "../ui";
import { WorldSummary } from "../api";

/**
 * Offseason screen (T9 feature)
 * Staged wizard: pre_draft → draft → free_agency → done
 * All stages are server-derived from world.offseason_stage to survive tab switches.
 */
export function OffseasonScreen({
  world,
  onPlayer,
  toast = () => {},
}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
}) {
  const stage = world.offseason_stage;

  if (!stage) {
    return (
      <div className="screen screen-offseason">
        <Panel>
          <h2 className="text-display">Offseason</h2>
          <p className="text-muted" style={{ marginTop: "1rem" }}>
            The offseason hasn't started yet. Complete the playoffs to begin.
          </p>
        </Panel>
      </div>
    );
  }

  if (stage === "pre_draft") {
    return <PreDraftStage toast={toast} />;
  }

  if (stage === "draft") {
    return <DraftStage onPlayer={onPlayer} toast={toast} />;
  }

  if (stage === "free_agency") {
    return <FreeAgencyStage world={world} onPlayer={onPlayer} toast={toast} />;
  }

  return (
    <div className="screen screen-offseason">
      <Panel>
        <h2 className="text-display">Offseason</h2>
        <p className="text-muted">Unknown offseason stage: {stage}</p>
      </Panel>
    </div>
  );
}

// ============================================================================
// Stage 1: Pre-Draft Intro
// ============================================================================
function PreDraftStage({ toast }: { toast: (msg: string) => void }) {
  const queryClient = useQueryClient();
  const [isLoading, setIsLoading] = useState(false);

  const begin = async () => {
    setIsLoading(true);
    try {
      const r = await api.preDraft();
      if (!r.resumed) {
        toast(
          `Retired ${r.retired}, ${r.new_fas} reached free agency`
        );
        if (r.awards) {
          // Show award toasts
          const awardsList = [
            { key: 'hart', label: 'Hart Trophy' },
            { key: 'norris', label: 'Norris Trophy' },
            { key: 'vezina', label: 'Vezina Trophy' },
            { key: 'calder', label: 'Calder Trophy' },
            { key: 'selke', label: 'Selke Trophy' },
          ];
          for (const award of awardsList) {
            const entry = (r.awards as any)[award.key];
            if (entry) {
              const playerName = (entry as any).name || 'Unknown';
              toast(`🏆 ${playerName} wins the ${award.label} — see History`);
            }
          }
        }
        for (const inducted of r.inducted) {
          toast(`🏅 ${(inducted as any).name} was inducted into the Hall of Fame`);
        }
        for (const milestone of r.milestones) {
          toast(
            `📈 ${(milestone as any).name} reached ${(milestone as any).value} career ${(milestone as any).unit}`
          );
        }
      }
      queryClient.invalidateQueries({ queryKey: ["career"] });
    } catch (e) {
      toast(String(e));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="screen screen-offseason">
      <Panel>
        <h2 className="text-display">Offseason</h2>
        <p className="text-muted" style={{ marginTop: "1rem", marginBottom: "2rem" }}>
          Age veterans, retire those past their prime, archive the season, and prepare for the draft.
        </p>
        <button
          className="btn btn-primary"
          onClick={begin}
          disabled={isLoading}
        >
          {isLoading ? "Beginning..." : "Begin Offseason"}
        </button>
      </Panel>
    </div>
  );
}

// ============================================================================
// Stage 2: Draft Room
// ============================================================================
function DraftStage({
  onPlayer,
  toast,
}: {
  onPlayer?: (pid: number) => void;
  toast: (msg: string) => void;
}) {
  const queryClient = useQueryClient();
  const [recentPicks, setRecentPicks] = useState<Array<Record<string, unknown>>>([]);

  const { data: board, isLoading, refetch } = useQuery({
    queryKey: ["offseasonDraftBoard"],
    queryFn: () => api.offseasonDraftBoard(),
  });

  // Merge recent picks each time we load the board
  useEffect(() => {
    if (board && board.recent) {
      setRecentPicks((prev) => [...board.recent, ...prev].slice(0, 10));
    }
  }, [board?.recent]);

  const pickMutation = useMutation({
    mutationFn: (prospectId: number | null) =>
      api.offseasonDraftPick(prospectId),
    onSuccess: () => {
      refetch();
      queryClient.invalidateQueries({ queryKey: ["career"] });
    },
    onError: (e) => {
      toast(String(e));
    },
  });

  if (isLoading) return <FaceoffDotSpinner />;
  if (!board) return <Panel><p className="text-muted">No active draft</p></Panel>;

  if (board.complete) {
    return (
      <div className="screen screen-offseason">
        <Panel>
          <h2 className="text-display">Draft Complete</h2>
          <p className="text-muted" style={{ marginTop: "1rem" }}>
            The draft is over. Free agency opens next.
          </p>
        </Panel>
      </div>
    );
  }

  return (
    <div className="screen screen-offseason">
      <Panel>
        <div style={{ marginBottom: "1.5rem" }}>
          {board.pick && board.round && (
            <h2 className="text-display">
              Pick #{board.pick} (Round {board.round})
            </h2>
          )}
        </div>

        {/* Recent picks ticker */}
        {recentPicks.length > 0 && (
          <div className="recentPicks" style={{ marginBottom: "2rem" }}>
            <div style={{ fontSize: "0.875rem", fontWeight: 600, marginBottom: "0.5rem", color: "var(--color-muted)" }}>
              Recent picks:
            </div>
            <div style={{ fontSize: "0.9375rem", display: "flex", flexWrap: "wrap", gap: "1rem" }}>
              {recentPicks.slice(0, 5).map((pick, i) => (
                <div key={i}>
                  #{(pick as any).pick} {(pick as any).team_abbrev} {(pick as any).name}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Auto-pick button */}
        <button
          className="btn btn-primary"
          onClick={() => pickMutation.mutate(null)}
          disabled={pickMutation.isPending}
          style={{ marginBottom: "2rem" }}
        >
          {pickMutation.isPending ? "Picking..." : "Auto-pick best available"}
        </button>

        {/* Draft board table */}
        <DraftBoardTable
          board={board.board}
          onPlayer={onPlayer}
          onPick={(pid) => pickMutation.mutate(pid)}
          isLoading={pickMutation.isPending}
        />
      </Panel>
    </div>
  );
}

function DraftBoardTable({
  board,
  onPlayer,
  onPick,
  isLoading,
}: {
  board: OffseasonDraftBoardEntry[];
  onPlayer?: (pid: number) => void;
  onPick: (pid: number) => void;
  isLoading: boolean;
}) {
  const columns: ColumnDef<OffseasonDraftBoardEntry>[] = [
    {
      header: "Name",
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
      header: "OVR",
      accessorKey: "overall",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
    {
      header: "POT",
      accessorKey: "potential",
      cell: (info) => <span className="text-mono">{String(info.getValue())}</span>,
    },
    {
      header: "Action",
      id: "action",
      cell: (info) => (
        <button
          className="btn btn-primary"
          onClick={() => onPick(info.row.original.pid)}
          disabled={isLoading}
          style={{ padding: "0.25rem 0.75rem", fontSize: "0.875rem" }}
        >
          Draft
        </button>
      ),
    },
  ];

  const table = useReactTable({
    data: board,
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
// Stage 3: Free Agency
// ============================================================================
function FreeAgencyStage({
  world,
  onPlayer,
  toast,
}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast: (msg: string) => void;
}) {
  const queryClient = useQueryClient();
  const [wave, setWave] = useState<{ wave: number; total: number; name: string } | null>(null);

  // Initialize FA on mount
  const { data: startResult } = useQuery({
    queryKey: ["faStart"],
    queryFn: () => api.faStart(),
  });

  useEffect(() => {
    if (startResult) {
      setWave({
        wave: startResult.wave,
        total: startResult.total,
        name: startResult.name,
      });
    }
  }, [startResult]);

  const { data: roster, refetch: refetchRoster } = useQuery({
    queryKey: ["rosterFA"],
    queryFn: () => api.getRoster(),
  });

  const { data: cap } = useQuery({
    queryKey: ["capFA"],
    queryFn: () => api.getCapSummary(),
  });

  const { data: freeAgents } = useQuery({
    queryKey: ["freeAgentsFA"],
    queryFn: () => api.getFreeAgents() as Promise<FreeAgentRow[]>,
  });

  const advanceMutation = useMutation({
    mutationFn: () => api.faAdvance(),
    onSuccess: (r) => {
      toast(`Rival GMs signed ${r.signings} free agent${r.signings === 1 ? "" : "s"}`);
      if (r.done) {
        queryClient.invalidateQueries({ queryKey: ["faStart"] });
        queryClient.invalidateQueries({ queryKey: ["career"] });
      } else if (r.next) {
        setWave({
          wave: r.next.wave,
          total: r.next.total,
          name: r.next.name,
        });
        refetchRoster();
      }
    },
    onError: (e) => {
      toast(String(e));
    },
  });

  const finishMutation = useMutation({
    mutationFn: () => api.finishOffseason(),
    onSuccess: () => {
      toast("Season underway!");
      queryClient.invalidateQueries();
    },
    onError: (e) => {
      toast(String(e));
    },
  });

  const rosterCount = roster?.players.length ?? 0;
  const rosterMax = 23;
  const capSpace = cap?.cap_space ?? 0;
  const capSpaceStr = `$${(capSpace / 1_000_000).toFixed(1)}M`;

  // Determine if this is the last wave
  const isLastWave = wave && wave.wave >= wave.total;

  return (
    <div className="screen screen-offseason">
      <Panel>
        {/* Wave banner */}
        {wave && (
          <div className="waveBanner">
            Wave {wave.wave}/{wave.total} — {wave.name}
          </div>
        )}

        {/* Roster/cap info */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            gap: "1rem",
            marginBottom: "2rem",
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
              Roster
            </div>
            <div style={{ fontSize: "1.5rem", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
              {rosterCount}/{rosterMax}
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
              Cap Space
            </div>
            <div style={{ fontSize: "1.5rem", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
              {capSpaceStr}
            </div>
          </div>
        </div>

        {/* Free agents table */}
        {freeAgents && freeAgents.length > 0 ? (
          <FreeAgentsSignTable
            freeAgents={freeAgents}
            onPlayer={onPlayer}
            onSignSuccess={() => {
              refetchRoster();
            }}
          />
        ) : (
          <p className="text-muted" style={{ marginBottom: "2rem" }}>
            No free agents available in this wave
          </p>
        )}

        {/* Wave advancement / finish button */}
        {!isLastWave ? (
          <button
            className="btn btn-primary"
            onClick={() => advanceMutation.mutate()}
            disabled={advanceMutation.isPending}
          >
            {advanceMutation.isPending
              ? "Advancing..."
              : "Done with this wave → let rival GMs bid"}
          </button>
        ) : (
          <button
            className="btn btn-primary"
            onClick={() => finishMutation.mutate()}
            disabled={finishMutation.isPending}
          >
            {finishMutation.isPending
              ? "Starting season..."
              : `Finish Offseason → Start ${world.season_year + 1} Season`}
          </button>
        )}
      </Panel>
    </div>
  );
}

function FreeAgentsSignTable({
  freeAgents,
  onPlayer,
  onSignSuccess,
}: {
  freeAgents: FreeAgentRow[];
  onPlayer?: (pid: number) => void;
  onSignSuccess: () => void;
}) {
  const queryClient = useQueryClient();

  const signMutation = useMutation({
    mutationFn: (pid: number) => api.signFreeAgent(pid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["freeAgentsFA"] });
      queryClient.invalidateQueries({ queryKey: ["capFA"] });
      queryClient.invalidateQueries({ queryKey: ["rosterFA"] });
      onSignSuccess();
    },
  });

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
    <div style={{ marginBottom: "2rem" }}>
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

// Playoffs screen (T8 feature — T6 foundation).
// Tab appears when regular_season_complete or phase is playoffs.
// Shows playoff bracket with start/sim controls, series cards, and champion banner.

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api, { StandingsEntry, WorldSummary, PlayoffsStateDTO } from "../api";
import { Panel, FaceoffDotSpinner } from "../ui";

export function PlayoffsScreen({
  world,
  toast,
}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
}) {
  const queryClient = useQueryClient();
  const [slateResults, setSlateResults] = useState<any[]>([]);

  const { data: playoffsData, isLoading: playoffsLoading } = useQuery({
    queryKey: ["playoffs"],
    queryFn: () => api.getPlayoffs(),
  });

  const { data: standings } = useQuery({
    queryKey: ["standings"],
    queryFn: () => api.getStandings(),
  });

  // Build team map from standings
  const teamMap: Record<number, StandingsEntry> = useMemo(() => {
    if (!standings) return {};
    return standings.reduce(
      (acc, team) => {
        acc[team.id] = team;
        return acc;
      },
      {} as Record<number, StandingsEntry>
    );
  }, [standings]);

  const handleStartPlayoffs = async () => {
    try {
      await api.startPlayoffs();
      toast?.("Playoffs started!");
      queryClient.invalidateQueries({ queryKey: ["playoffs"] });
      queryClient.invalidateQueries({ queryKey: ["career"] });
      setSlateResults([]);
    } catch (err: any) {
      toast?.(`Error: ${err.message || "Failed to start playoffs"}`);
    }
  };

  const handleSimSlate = async () => {
    try {
      const response = await api.advancePlayoffs();
      setSlateResults(response.slate || []);
      toast?.(`Simulated slate – day ${world.day}`);
      queryClient.invalidateQueries({ queryKey: ["playoffs"] });
      queryClient.invalidateQueries({ queryKey: ["career"] });

      // Check if playoffs just completed
      if (response.complete && response.champion_name) {
        toast?.(`🏆 ${response.champion_name} win the Stanley Cup — begin the offseason from the Offseason tab.`);
      }
    } catch (err: any) {
      toast?.(`Error: ${err.message || "Failed to advance playoffs"}`);
    }
  };

  if (playoffsLoading) {
    return (
      <Panel>
        <h2 className="text-display">Playoffs</h2>
        <FaceoffDotSpinner />
      </Panel>
    );
  }

  const data = playoffsData as PlayoffsStateDTO | undefined;
  if (!data) {
    return (
      <Panel>
        <h2 className="text-display">Playoffs</h2>
        <p className="text-muted">Unable to load playoffs data</p>
      </Panel>
    );
  }

  const hasBracket = data.bracket && (data.bracket as any).all_series?.length > 0;

  return (
    <div className="screen screen-playoffs">
      <Panel>
        <h2 className="text-display">Playoffs</h2>

        {/* Action buttons */}
        <div style={{ display: "flex", gap: "1rem", marginBottom: "2rem" }}>
          {!hasBracket && data.can_start && (
            <button className="btn btn-primary" onClick={handleStartPlayoffs}>
              Start Playoffs
            </button>
          )}
          {hasBracket && !data.complete && (
            <button className="btn btn-primary" onClick={handleSimSlate}>
              Sim Slate
            </button>
          )}
          {data.complete && (
            <div style={{ paddingTop: "0.5rem" }}>
              <span style={{ color: "var(--color-muted)" }}>Playoffs complete</span>
            </div>
          )}
        </div>

        {/* Slate results */}
        {slateResults.length > 0 && (
          <div style={{ marginBottom: "2rem" }}>
            <h3 style={{ marginBottom: "1rem", color: "var(--color-text)" }}>Latest Slate Results</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {slateResults.map((game) => {
                const homeTeam = teamMap[game.home_tid];
                const awayTeam = teamMap[game.away_tid];
                const otSo = game.went_ot ? " (OT)" : game.went_so ? " (SO)" : "";
                return (
                  <div key={game.sid} style={{ fontSize: "0.875rem", color: "var(--color-text)" }}>
                    <strong>{awayTeam?.abbrev || "?"}</strong> {game.away_score} @{" "}
                    <strong>{homeTeam?.abbrev || "?"}</strong> {game.home_score}
                    <span style={{ color: "var(--color-muted)", marginLeft: "0.5rem" }}>
                      ({game.status}){otSo}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Bracket visualization */}
        {hasBracket ? (
          <Bracket
            bracket={data.bracket as any}
            teamMap={teamMap}
            userTid={world.user_team_id}
            champion={data.champion_tid}
            championName={data.champion_name}
          />
        ) : (
          <p className="text-muted">The bracket will appear once the postseason begins.</p>
        )}
      </Panel>
    </div>
  );
}

// Bracket component
function Bracket({
  bracket,
  teamMap,
  userTid,
  champion,
  championName,
}: {
  bracket: any;
  teamMap: Record<number, StandingsEntry>;
  userTid: number | null;
  champion: number | null;
  championName: string | null;
}) {
  const ROUND_ORDER = ["R1", "R2", "CF", "Finals"];
  const ROUND_NAMES: Record<string, string> = {
    R1: "First Round",
    R2: "Conference Semifinals",
    CF: "Conference Finals",
    Finals: "Stanley Cup Final",
  };

  const seedOf = (tid: number): number | undefined => {
    const s = bracket.seeds?.[String(tid)];
    return s != null ? Number(s) : undefined;
  };

  const allSeries = bracket.all_series ?? [];

  return (
    <div>
      {champion && championName && (
        <div className="champ">
          🏆 {championName} win the Stanley Cup!
        </div>
      )}

      <div className="bracketCols">
        {ROUND_ORDER.map((rnd) => {
          const series = allSeries.filter((s: any) => s.round === rnd);
          if (!series.length) return null;

          return (
            <div className="bracketCol" key={rnd}>
              <div className="roundName">{ROUND_NAMES[rnd]}</div>
              {series.map((s: any) => (
                <SeriesCard
                  key={s.sid}
                  series={s}
                  teamMap={teamMap}
                  seedOf={seedOf}
                  userTid={userTid}
                  active={bracket.round === rnd && s.winner == null}
                />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Series card component
function SeriesCard({
  series,
  teamMap,
  seedOf,
  userTid,
  active,
}: {
  series: any;
  teamMap: Record<number, StandingsEntry>;
  seedOf: (tid: number) => number | undefined;
  userTid: number | null;
  active: boolean;
}) {
  const renderTeamRow = (tid: number, wins: number) => {
    const team = teamMap[tid];
    const seed = seedOf(tid);
    const isWinner = series.winner === tid;
    const isUserTeam = tid === userTid;

    return (
      <div key={tid} className={`seedRow${isWinner ? " win" : ""}${isUserTeam ? " mine" : ""}`}>
        {seed != null && <span className="seed">{seed}</span>}
        <span
          className="dot"
          style={{
            background: team?.primary_color || "#9aa0a6",
            width: "12px",
            height: "12px",
            borderRadius: "50%",
            flexShrink: 0,
          }}
        />
        <span className="abbr">{team?.abbrev || "—"}</span>
        <span className="wins">{wins}</span>
      </div>
    );
  };

  return (
    <div className={`seriesCard${active ? " active" : ""}`}>
      {renderTeamRow(series.hi, series.hi_w)}
      {renderTeamRow(series.lo, series.lo_w)}
    </div>
  );
}

// Playoffs screen stub (T8 feature — T6 foundation).
// Tab appears when regular_season_complete or phase is playoffs.

import { WorldSummary } from "../api";
import { Panel } from "../ui";

export function PlayoffsScreen({}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
}) {
  return (
    <div className="screen screen-playoffs">
      <Panel>
        <h2 className="text-display">Playoffs</h2>
        <p className="text-muted" style={{ marginTop: "1rem" }}>
          Bracket, sim controls, and finals recap will appear here (T8).
        </p>
      </Panel>
    </div>
  );
}

// History screen stub (T10 feature — T6 foundation).
// Shows archived seasons, Hall of Fame, and all-time records.

import { WorldSummary } from "../api";
import { Panel } from "../ui";

export function HistoryScreen({}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
}) {
  return (
    <div className="screen screen-history">
      <Panel>
        <h2 className="text-display">History</h2>
        <p className="text-muted" style={{ marginTop: "1rem" }}>
          Archived seasons, Hall of Fame, and all-time leaderboards will appear here (T10).
        </p>
      </Panel>
    </div>
  );
}

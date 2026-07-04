// Leaders screen stub (T10 feature — T6 foundation).
// Shows current season leaders by category.

import { WorldSummary } from "../api";
import { Panel } from "../ui";

export function LeadersScreen({}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
}) {
  return (
    <div className="screen screen-leaders">
      <Panel>
        <h2 className="text-display">Leaders</h2>
        <p className="text-muted" style={{ marginTop: "1rem" }}>
          Current season leaders (points, goals, assists, etc.) will appear here (T10).
        </p>
      </Panel>
    </div>
  );
}

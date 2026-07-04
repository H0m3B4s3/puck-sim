// Trade screen stub (T11 feature — T6 foundation).
// Replaces the trade section in Transactions with a dedicated Trade tab.

import { WorldSummary } from "../api";
import { Panel } from "../ui";

export function TradeScreen({}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
}) {
  return (
    <div className="screen screen-trade">
      <Panel>
        <h2 className="text-display">Trades</h2>
        <p className="text-muted" style={{ marginTop: "1rem" }}>
          Trade builder with partner selection, roster pickers, and AI evaluation will appear here (T11).
        </p>
      </Panel>
    </div>
  );
}

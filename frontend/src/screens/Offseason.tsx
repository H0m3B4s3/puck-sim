// Offseason screen stub (T9 feature — T6 foundation).
// Tab appears when offseason_stage is pre_draft, draft, or free_agency.

import { WorldSummary } from "../api";
import { Panel } from "../ui";

export function OffseasonScreen({}: {
  world: WorldSummary;
  onPlayer?: (pid: number) => void;
  toast?: (msg: string) => void;
}) {
  return (
    <div className="screen screen-offseason">
      <Panel>
        <h2 className="text-display">Offseason</h2>
        <p className="text-muted" style={{ marginTop: "1rem" }}>
          Pre-draft, draft board, free agency wizard will appear here (T9).
        </p>
      </Panel>
    </div>
  );
}

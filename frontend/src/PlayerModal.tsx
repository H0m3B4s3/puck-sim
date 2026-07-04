// Player modal stub (T6 — foundation for T7).
// Fetches and displays basic player info: name, position, overall.
// T7 will extend this with full card: bio, stats, legacy, rating groups.

import { useQuery } from "@tanstack/react-query";
import api from "./api";
import { Modal, FaceoffDotSpinner } from "./ui";

export function PlayerModal({ pid, onClose }: { pid: number; onClose: () => void }) {
  const { data: player, isLoading } = useQuery({
    queryKey: ["player", pid],
    queryFn: () => api.getPlayer(pid),
  });

  if (isLoading) {
    return (
      <Modal title="Player" onClose={onClose}>
        <FaceoffDotSpinner />
      </Modal>
    );
  }

  if (!player) {
    return (
      <Modal title="Player" onClose={onClose}>
        <p className="text-muted">Player not found.</p>
      </Modal>
    );
  }

  return (
    <Modal title={player.name} onClose={onClose}>
      <div style={{ lineHeight: 1.6 }}>
        <p>
          <strong>{player.name}</strong>
        </p>
        <p className="text-muted">
          {player.position} · OVR {player.overall} · POT {player.potential}
        </p>
        <p style={{ marginTop: "1rem", fontSize: "0.9rem", color: "var(--color-muted)" }}>
          Age {player.age} · {player.shoots} · {player.team_abbrev}{" "}
          {player.team_name && `(${player.team_name})`}
        </p>
      </div>
    </Modal>
  );
}

// Save / Load screen.
//
// Exposes the career persistence endpoints (POST /career/save, POST /career/load,
// GET /career/saves) that previously had no UI at all -- so a career could not be saved or
// resumed. Lists existing save slots, saves the current career to a named slot, and loads a
// selected slot (swapping the active session's world and returning Home).

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../api";
import { Panel, FaceoffDotSpinner } from "../ui";

export function SaveLoadScreen({
  toast,
  onNavigate,
}: {
  toast?: (msg: string) => void;
  onNavigate?: (path: string) => void;
}) {
  const queryClient = useQueryClient();
  const [slotName, setSlotName] = useState("manual");

  const { data: saves, isLoading } = useQuery({
    queryKey: ["saves"],
    queryFn: () => api.listSaves(),
  });

  const saveMutation = useMutation({
    mutationFn: (slot: string) => api.saveCareer(slot),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["saves"] });
      toast?.(`Saved to "${res.slot}"`);
    },
    onError: (err) =>
      toast?.(`Save failed: ${err instanceof Error ? err.message : String(err)}`),
  });

  const loadMutation = useMutation({
    mutationFn: (slot: string) => api.loadCareer(slot),
    onSuccess: (_world, slot) => {
      // A load replaces the entire active world, so refresh everything the app has cached
      // (career/scoreboard, roster, schedule, standings, ...) and drop the user back Home.
      queryClient.invalidateQueries();
      toast?.(`Loaded "${slot}"`);
      onNavigate?.("/");
    },
    onError: (err) =>
      toast?.(`Load failed: ${err instanceof Error ? err.message : String(err)}`),
  });

  const trimmed = slotName.trim();
  const slotExists = !!saves?.includes(trimmed);

  return (
    <div className="screen screen-save-load">
      <Panel>
        <h2 className="text-display">Save &amp; Load</h2>

        {/* Save current career */}
        <div style={{ marginTop: "1.5rem" }}>
          <h3 style={{ marginBottom: "0.5rem" }}>Save current career</h3>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <input
              value={slotName}
              onChange={(e) => setSlotName(e.target.value)}
              placeholder="slot name"
              aria-label="Save slot name"
              style={{
                padding: "0.5rem 0.75rem",
                borderRadius: "6px",
                border: "1px solid var(--color-border)",
                background: "var(--color-surface)",
                color: "var(--color-text)",
                font: "inherit",
              }}
            />
            <button
              className="btn btn-primary"
              disabled={!trimmed || saveMutation.isPending}
              onClick={() => saveMutation.mutate(trimmed)}
            >
              {saveMutation.isPending ? "Saving…" : slotExists ? "Overwrite" : "Save"}
            </button>
          </div>
          {slotExists && (
            <p className="text-muted" style={{ marginTop: "0.4rem", fontSize: "0.875rem" }}>
              A save named “{trimmed}” already exists — saving will overwrite it.
            </p>
          )}
        </div>

        {/* Load an existing save */}
        <div style={{ marginTop: "2rem" }}>
          <h3 style={{ marginBottom: "0.5rem" }}>Load a save</h3>
          {isLoading ? (
            <FaceoffDotSpinner />
          ) : !saves || saves.length === 0 ? (
            <p className="text-muted">No saves yet. Save your career above to create one.</p>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {saves.map((slot) => (
                <li
                  key={slot}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "0.6rem 0.25rem",
                    borderBottom: "1px solid var(--color-border)",
                  }}
                >
                  <span className="text-mono">{slot}</span>
                  <button
                    className="btn"
                    disabled={loadMutation.isPending}
                    onClick={() => loadMutation.mutate(slot)}
                  >
                    {loadMutation.isPending && loadMutation.variables === slot
                      ? "Loading…"
                      : "Load"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Panel>
    </div>
  );
}

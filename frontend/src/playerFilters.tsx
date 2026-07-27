import { useState, useMemo, ReactNode } from "react";

export interface FilterablePlayer {
  position: string;
  age: number;
  potential: number;
  archetype: string | null;
}

export function usePlayerFilters<T extends FilterablePlayer>(players: T[]) {
  const [position, setPosition] = useState<string>("ALL");
  const [minAge, setMinAge] = useState<string>("");
  const [maxAge, setMaxAge] = useState<string>("");
  const [minPotential, setMinPotential] = useState<string>("");
  const [archetype, setArchetype] = useState<string>("ALL");

  // Derive unique positions and archetypes from the players. Memoized on `players` -- every
  // consumer of this hook feeds it straight into an UNCONTROLLED useReactTable (no explicit
  // `state`/`onXChange`), and that combination is documented by TanStack Table itself to be
  // unsafe with unstable data/derived-array references: a brand-new array on every render can
  // send table.getRowModel() into an infinite recompute-then-rerender loop (confirmed directly --
  // it reproduced a real, tab-freezing hang with zero cells even rendered, just from calling
  // getRowModel() against a `data` array that changes identity every render). `filtered` is the
  // one actually fed to the table as `data`, so it's the fix that matters, but memoizing
  // `positions`/`archetypes` too avoids the same class of bug for any future consumer.
  const positions = useMemo(
    () => Array.from(new Set(players.map((p) => p.position))).filter((pos) => pos).sort(),
    [players],
  );

  const archetypes = useMemo(
    () =>
      Array.from(new Set(players.map((p) => p.archetype).filter((a) => a !== null) as string[])).sort(),
    [players],
  );

  // Apply filters
  const filtered = useMemo(
    () =>
      players.filter((p) => {
        if (position !== "ALL" && p.position !== position) return false;
        if (minAge !== "" && p.age < parseInt(minAge, 10)) return false;
        if (maxAge !== "" && p.age > parseInt(maxAge, 10)) return false;
        if (minPotential !== "" && p.potential < parseInt(minPotential, 10)) return false;
        if (archetype !== "ALL" && p.archetype !== archetype) return false;
        return true;
      }),
    [players, position, minAge, maxAge, minPotential, archetype],
  );

  const filterBar: ReactNode = (
    <div
      style={{
        display: "flex",
        gap: "1rem",
        alignItems: "center",
        padding: "1rem 0",
        borderBottom: "1px solid var(--color-border)",
        marginBottom: "1rem",
        flexWrap: "wrap",
      }}
    >
      {/* Position filter */}
      <select
        value={position}
        onChange={(e) => setPosition(e.target.value)}
        style={{
          padding: "0.5rem",
          borderRadius: "4px",
          border: "1px solid var(--color-border)",
          backgroundColor: "var(--color-surface)",
          color: "var(--color-text)",
          fontSize: "0.9375rem",
        }}
      >
        <option value="ALL">All Positions</option>
        {positions.map((pos) => (
          <option key={pos} value={pos}>
            {pos}
          </option>
        ))}
      </select>

      {/* Min Age filter */}
      <input
        type="number"
        placeholder="Min Age"
        value={minAge}
        onChange={(e) => setMinAge(e.target.value)}
        style={{
          padding: "0.5rem",
          borderRadius: "4px",
          border: "1px solid var(--color-border)",
          backgroundColor: "var(--color-surface)",
          color: "var(--color-text)",
          fontSize: "0.9375rem",
          width: "100px",
        }}
      />

      {/* Max Age filter */}
      <input
        type="number"
        placeholder="Max Age"
        value={maxAge}
        onChange={(e) => setMaxAge(e.target.value)}
        style={{
          padding: "0.5rem",
          borderRadius: "4px",
          border: "1px solid var(--color-border)",
          backgroundColor: "var(--color-surface)",
          color: "var(--color-text)",
          fontSize: "0.9375rem",
          width: "100px",
        }}
      />

      {/* Min Potential filter */}
      <input
        type="number"
        placeholder="Min Potential"
        value={minPotential}
        onChange={(e) => setMinPotential(e.target.value)}
        style={{
          padding: "0.5rem",
          borderRadius: "4px",
          border: "1px solid var(--color-border)",
          backgroundColor: "var(--color-surface)",
          color: "var(--color-text)",
          fontSize: "0.9375rem",
          width: "120px",
        }}
      />

      {/* Archetype filter */}
      {archetypes.length > 0 && (
        <select
          value={archetype}
          onChange={(e) => setArchetype(e.target.value)}
          style={{
            padding: "0.5rem",
            borderRadius: "4px",
            border: "1px solid var(--color-border)",
            backgroundColor: "var(--color-surface)",
            color: "var(--color-text)",
            fontSize: "0.9375rem",
          }}
        >
          <option value="ALL">All Archetypes</option>
          {archetypes.map((arch) => (
            <option key={arch} value={arch}>
              {arch}
            </option>
          ))}
        </select>
      )}
    </div>
  );

  return { filtered, filterBar };
}

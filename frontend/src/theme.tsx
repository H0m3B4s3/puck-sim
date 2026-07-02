// Theme + team-color engine for PuckSim (Step 2.10a).
//
// Light/dark toggle with localStorage persistence and prefers-color-scheme detection.
// Color tokens are CSS custom properties set via data-theme attribute on <html>.
// Team colors arrive as raw hex from the backend and are passed through readable()
// to ensure legible text contrast against the current theme's surface.
//
// Ported from HoopR's theme.tsx and adapted to PuckSim's rink/arena palette.

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

export type Theme = "dark" | "light";

// --- theme context -------------------------------------------------------
const KEY = "pucksim-theme";
const ThemeCtx = createContext<{ theme: Theme; toggle: () => void }>({
  theme: "dark",
  toggle: () => {},
});

function initialTheme(): Theme {
  const saved = localStorage.getItem(KEY);
  if (saved === "dark" || saved === "light") return saved;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(KEY, theme);
  }, [theme]);
  const toggle = () => setTheme((t) => (t === "dark" ? "light" : "dark"));
  return <ThemeCtx.Provider value={{ theme, toggle }}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);

// --- color math ----------------------------------------------------------
type RGB = [number, number, number];

function hexToRgb(hex: string): RGB {
  let h = hex.replace("#", "").trim();
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const n = parseInt(h, 16);
  if (Number.isNaN(n) || h.length !== 6) return [128, 128, 128];
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
const toHex = ([r, g, b]: RGB) =>
  "#" + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");

// WCAG relative luminance.
function lum([r, g, b]: RGB): number {
  const f = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function contrast(a: RGB, b: RGB): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
const mix = (c: RGB, t: RGB, k: number): RGB =>
  c.map((v, i) => v + (t[i] - v) * k) as RGB;

// The surface we test contrast against: the surface color in each theme (worst case for legibility).
const SURFACE: Record<Theme, RGB> = {
  dark: [0x10, 0x14, 0x1a],  // #10141A (arena ink)
  light: [0xf7, 0xf9, 0xfa], // #F7F9FA (ice white)
};
const WHITE: RGB = [255, 255, 255];
const BLACK: RGB = [0, 0, 0];

const cache = new Map<string, string>();

// A version of `hex` guaranteed readable as text on the current theme's surface.
export function readable(hex: string, theme: Theme, target = 4.0): string {
  const key = `${theme}:${hex}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const surface = SURFACE[theme];
  const towards = theme === "dark" ? WHITE : BLACK;
  let rgb = hexToRgb(hex);
  for (let k = 0; k <= 1.001 && contrast(rgb, surface) < target; k += 0.06) {
    rgb = mix(hexToRgb(hex), towards, k);
  }
  const out = toHex(rgb);
  cache.set(key, out);
  return out;
}

// Foreground for text sitting *on* a solid team-color fill.
export function onColor(hex: string): string {
  return lum(hexToRgb(hex)) > 0.45 ? "#12181F" : "#F2F4F6";
}

// --- the signature: a team tag with jersey-stripe accent bar --------------------------------
export function useTeamText() {
  const { theme } = useTheme();
  return (hex: string) => readable(hex, theme);
}

export function TeamTag({
  abbrev,
  color,
  name,
  big,
}: {
  abbrev: string;
  color: string;
  name?: ReactNode;
  big?: boolean;
}) {
  const text = useTeamText();
  return (
    <span className={big ? "teamTag big" : "teamTag"}>
      <span className="teamTag__bar" style={{ background: color }} />
      <b className="teamTag__abbr" style={{ color: text(color) }}>
        {abbrev}
      </b>
      {name != null && <span className="teamTag__name">{name}</span>}
    </span>
  );
}

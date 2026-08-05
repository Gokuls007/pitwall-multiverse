/**
 * Team colours, made legible on paper.
 *
 * Spec 11.2 mandates one line per driver in team colours. Spec 11.1 says
 * legibility beats decoration wherever they conflict — and they genuinely do
 * conflict here: several real team colours (2019 Mercedes #00D2BE, Haas
 * white, Williams' pale blue) have far too little contrast against the
 * `paper` (#F4F1EA) background to read as a thin chart line.
 *
 * Resolution, applied here rather than by hand-picking substitutes:
 *   1. Keep the team's actual hue — brand identity survives.
 *   2. Darken luminance until the line clears 3:1 against paper (the WCAG
 *      non-text contrast floor, which is the right threshold for a graphical
 *      object like a chart line).
 *   3. Give teammates distinct dash patterns, so a pair separates without
 *      relying on colour at all — which also means colour-blind users get a
 *      second, independent channel.
 *
 * Base hex values are the real 2019/2021 liveries; the darkening is computed,
 * not eyeballed, so adding a season doesn't require re-tuning by eye.
 */

const PAPER = "#F4F1EA";
/** WCAG 2.1 non-text contrast minimum — appropriate for chart lines. */
const MIN_CONTRAST = 3;

const TEAM_BASE: Record<string, string> = {
  Mercedes: "#00D2BE",
  Ferrari: "#DC0000",
  "Red Bull Racing": "#0600EF",
  McLaren: "#FF8700",
  "Racing Point": "#F596C8",
  Renault: "#FFF500",
  "Alfa Romeo Racing": "#9B0000",
  "Alfa Romeo": "#900000",
  "Toro Rosso": "#0032FF",
  AlphaTauri: "#2B4562",
  "Haas F1 Team": "#BD9E57",
  Williams: "#005AFF",
  Alpine: "#0090FF",
  "Aston Martin": "#006F62",
};

const FALLBACK_BASE = "#6B6B6B";

function hexToRgb(hex: string): [number, number, number] {
  const v = hex.replace("#", "");
  return [
    parseInt(v.slice(0, 2), 16),
    parseInt(v.slice(2, 4), 16),
    parseInt(v.slice(4, 6), 16),
  ];
}

function rgbToHex([r, g, b]: [number, number, number]): string {
  const clamp = (n: number) => Math.max(0, Math.min(255, Math.round(n)));
  return `#${[r, g, b].map((n) => clamp(n).toString(16).padStart(2, "0")).join("")}`;
}

/** WCAG relative luminance. */
function luminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/**
 * Scale RGB toward black until the colour clears `MIN_CONTRAST` against
 * paper. Multiplicative scaling preserves the hue ratio between channels,
 * so the result still reads as the team's colour rather than a new one.
 */
function darkenToContrast(hex: string, background = PAPER, target = MIN_CONTRAST): string {
  let rgb = hexToRgb(hex);
  let current = rgbToHex(rgb);
  // 40 steps at 5% is enough to take any starting colour to near-black.
  for (let i = 0; i < 40 && contrastRatio(current, background) < target; i += 1) {
    rgb = [rgb[0] * 0.95, rgb[1] * 0.95, rgb[2] * 0.95];
    current = rgbToHex(rgb);
  }
  return current;
}

const cache = new Map<string, string>();

/** Legible-on-paper line colour for a team, hue preserved. */
export function teamLineColor(team: string): string {
  const cached = cache.get(team);
  if (cached) return cached;
  const base = TEAM_BASE[team] ?? FALLBACK_BASE;
  const adjusted = darkenToContrast(base);
  cache.set(team, adjusted);
  return adjusted;
}

/**
 * Dash pattern distinguishing teammates. Index 0 solid, index 1 dashed —
 * the second, colour-independent channel referred to above.
 */
export function teammateDash(indexWithinTeam: number): string | undefined {
  return indexWithinTeam === 0 ? undefined : "5 3";
}

/** Exposed for tests: the contrast a team's adjusted line actually achieves. */
export function teamLineContrast(team: string): number {
  return contrastRatio(teamLineColor(team), PAPER);
}

/**
 * Compound colours as a luminance ramp in ink tints.
 *
 * The convention is soft-red / medium-yellow / hard-white, and none of it
 * works here:
 *   - Red is already spoken for. `--annotation` means "counterfactual", and
 *     a red compound bar sitting under a red alternate line would collapse
 *     two unrelated meanings into one colour.
 *   - White-on-cream is invisible: hard tyres would simply disappear against
 *     `--paper` (#F4F1EA).
 *
 * A luminance ramp sidesteps both and fits the paper aesthetic better than
 * borrowed broadcast colours would. Ordering follows the physical ordering
 * the tyre model itself uses (spec 6.3's monotonic prior: soft fastest,
 * hard slowest), so darker = softer = faster reads as a single consistent
 * scale rather than three arbitrary hues. Red stays reserved for the
 * alternate timeline throughout.
 */

export type CompoundName = "SOFT" | "MEDIUM" | "HARD" | "INTERMEDIATE" | "WET" | "UNKNOWN";

const RAMP: Record<string, { fill: string; label: string }> = {
  // Darkest = softest = fastest, matching the fitted compound ordering.
  SOFT: { fill: "#33302B", label: "#F4F1EA" },
  MEDIUM: { fill: "#7A7264", label: "#F4F1EA" },
  HARD: { fill: "#ADA598", label: "#1A1917" },
  // Wets sit outside the dry ramp; this catalogue has no wet races (every
  // one is screened dry), so these exist to avoid a silent fallback rather
  // than because they've been exercised.
  INTERMEDIATE: { fill: "#5C6B63", label: "#F4F1EA" },
  WET: { fill: "#44585F", label: "#F4F1EA" },
};

const FALLBACK = { fill: "#8C8C8C", label: "#F4F1EA" };

export function compoundFill(compound: string): string {
  return (RAMP[compound] ?? FALLBACK).fill;
}

/** Text colour that stays legible on top of that compound's fill. */
export function compoundLabelColor(compound: string): string {
  return (RAMP[compound] ?? FALLBACK).label;
}

/** Single-letter tag used when a stint bar is too narrow for a full word. */
export function compoundInitial(compound: string): string {
  return compound === "UNKNOWN" ? "?" : compound.charAt(0);
}

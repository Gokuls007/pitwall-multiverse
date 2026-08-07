/**
 * DecisionSpace — Phase 6.5. Small multiples of every driver's decision space.
 *
 * One row per (driver, real stop). Along it, one cell per candidate pit lap: how
 * much time that decision costs or saves, and how much of the model's evidence it
 * leaves behind.
 *
 * **The V-shape is not forced.** The spec asks whether the V reads without a
 * caption, and the honest answer for this catalogue is: only for some drivers.
 * The extrapolation curve has its minimum at reality, but its *width* is a
 * property of the driver, not of the encoding:
 *
 *   - A driver who ran a compound in more than one stint has an observed maximum
 *     tyre age above any single stint's length, so there is a band of candidates
 *     either side of reality that stays inside the evidence. That reads as a
 *     flat-bottomed valley.
 *   - A driver who ran each compound exactly once has every stint ending at its
 *     own observed maximum by construction, so *any* shift in *any* direction
 *     leaves the evidence immediately. The valley has zero width: reality is a
 *     single point, and the row is uniformly shaded with a notch at reality.
 *
 * Showing that contrast is a better finding than the V, and it is the same
 * compound-revisit property that determines whether a driver's fuel effect and
 * degradation are separable at all (`DriverJointFit.is_identified`). The drivers
 * whose tyre models are best identified are exactly the drivers whose
 * counterfactuals are defensible. So the encoding shows what is there.
 *
 * **Two channels, because there are two failure modes.** Shading by extrapolation
 * depth alone would leave a traffic-dominated answer looking benign — 2019
 * Hungary BOT's lap-5 stop moved to lap 20 is 108s, of which 86s is accumulated
 * time stuck behind cars, on tyre cells that are perfectly well fitted. So:
 * ochre saturation carries extrapolation depth (`--caution` keeps meaning exactly
 * one thing), and a separate structural mark — a dot — carries "this answer is
 * driven by something other than the tyre model".
 */

import { CAUSE_BY_CODE, toSummary, type RaceBase } from "../lib/raceFixtures";

export type DecisionSpaceProps = {
  base: RaceBase;
  /** Drivers to draw, in the order given. */
  drivers: string[];
  selected?: { driver: string; stopLap: number; newLap: number };
  onSelect?: (driver: string, stopLap: number, newLap: number) => void;
};

const CELL_W = 7;
const CELL_H = 13;
const ROW_GAP = 4;
const LABEL_W = 58;

/** Ochre saturation by how far past observed tyre age a candidate runs. */
function extrapolationFill(laps: number, worst: number): string {
  if (laps <= 0) return "#E8E4DA";
  const t = Math.min(1, laps / Math.max(1, worst));
  // 0.18 -> 0.85 opacity over the caution hue, so "just past" and "far past"
  // are distinguishable rather than both reading as "flagged".
  return `rgba(168,118,31,${(0.18 + t * 0.67).toFixed(3)})`;
}

export default function DecisionSpace({ base, drivers, selected, onSelect }: DecisionSpaceProps) {
  const rows = drivers.flatMap((driver) => {
    const byStop = base.decisionSpace?.[driver] ?? {};
    return Object.keys(byStop)
      .map(Number)
      .sort((a, b) => a - b)
      .map((stopLap) => ({
        driver,
        stopLap,
        candidates: toSummary(byStop[String(stopLap)]),
      }));
  });
  if (rows.length === 0) return null;

  const worstExtrapolation = Math.max(
    1,
    ...rows.flatMap((row) => row.candidates.map((c) => c.extrapolatedLaps)),
  );
  const firstLap = Math.min(...rows.flatMap((r) => r.candidates.map((c) => c.newLap)));
  const lastLap = Math.max(...rows.flatMap((r) => r.candidates.map((c) => c.newLap)));
  // The right-hand count needs its own room. At +8 the SVG ended mid-glyph and a
  // two-digit number was clipped to its first digit — HAM's 14 defensible
  // candidates rendered as "1", which is not a smaller number, it is the wrong
  // one, and it happened to make every driver look equally hopeless.
  const COUNT_GUTTER = 26;
  const width = LABEL_W + (lastLap - firstLap + 1) * CELL_W + COUNT_GUTTER;
  const height = rows.length * (CELL_H + ROW_GAP) + 18;

  const insideEvidence = rows.map((row) => row.candidates.filter((c) => c.extrapolatedLaps === 0).length);
  const totalInside = insideEvidence.reduce((a, b) => a + b, 0);
  const totalCandidates = rows.reduce((sum, row) => sum + row.candidates.length, 0);

  return (
    <section className="mt-6 rule-t pt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 className="label-caps">Every decision available, by driver</h2>
        <p className="font-mono text-micro text-ink/60">
          {totalCandidates} candidates · {totalInside} ({Math.round((totalInside / totalCandidates) * 100)}%)
          stay inside observed tyre age
        </p>
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-micro">
        <span className="flex items-center gap-1.5">
          <svg width="34" height="9" aria-hidden="true">
            <rect x="0" y="0" width="10" height="9" fill="#E8E4DA" />
            <rect x="11" y="0" width="10" height="9" fill="rgba(168,118,31,0.4)" />
            <rect x="22" y="0" width="10" height="9" fill="rgba(168,118,31,0.85)" />
          </svg>
          laps beyond evidence <span className="text-ink/45">none → many</span>
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="10" height="9" aria-hidden="true">
            <circle cx="5" cy="4.5" r="2" fill="#1A1917" />
          </svg>
          driven by traffic, not tyres
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="10" height="11" aria-hidden="true">
            <line x1="5" y1="0" x2="5" y2="11" stroke="#1A1917" strokeWidth="1.5" />
          </svg>
          reality
        </span>
      </div>

      <div className="mt-2 overflow-x-auto">
        <svg width={width} height={height} role="img" aria-label="Decision space per driver and pit stop">
          {rows.map((row, i) => {
            const y = i * (CELL_H + ROW_GAP);
            const inside = row.candidates.filter((c) => c.extrapolatedLaps === 0).length;
            return (
              <g key={`${row.driver}-${row.stopLap}`}>
                <text
                  x={LABEL_W - 6}
                  y={y + CELL_H - 3}
                  textAnchor="end"
                  className="font-mono"
                  fontSize={9}
                  fill="#1A1917"
                  opacity={row.driver === selected?.driver ? 1 : 0.6}
                >
                  {row.driver} L{row.stopLap}
                </text>
                {row.candidates.map((candidate) => {
                  const x = LABEL_W + (candidate.newLap - firstLap) * CELL_W;
                  const isReality = candidate.newLap === row.stopLap;
                  const isSelected =
                    selected?.driver === row.driver &&
                    selected?.stopLap === row.stopLap &&
                    selected?.newLap === candidate.newLap;
                  return (
                    <g key={candidate.newLap}>
                      <rect
                        x={x}
                        y={y}
                        width={CELL_W - 1}
                        height={CELL_H}
                        fill={extrapolationFill(candidate.extrapolatedLaps, worstExtrapolation)}
                        stroke={isSelected ? "#A33A2E" : "none"}
                        strokeWidth={isSelected ? 1.5 : 0}
                        className={onSelect ? "cursor-pointer" : undefined}
                        onClick={() => onSelect?.(row.driver, row.stopLap, candidate.newLap)}
                      >
                        <title>
                          {`${row.driver}: pit lap ${row.stopLap} → ${candidate.newLap}. ` +
                            `${candidate.finalDeltaS >= 0 ? "+" : ""}${candidate.finalDeltaS.toFixed(1)}s. ` +
                            (candidate.extrapolatedLaps > 0
                              ? `${candidate.extrapolatedLaps} laps beyond evidence. `
                              : "inside observed tyre age. ") +
                            (candidate.cause ? `Flagged: ${candidate.cause}.` : "")}
                        </title>
                      </rect>
                      {/* Second channel: a structural mark for answers the tyre
                          model isn't responsible for, so ochre keeps meaning
                          exactly one thing. */}
                      {candidate.cause === "traffic" && (
                        <circle
                          cx={x + (CELL_W - 1) / 2}
                          cy={y + CELL_H / 2}
                          r={2}
                          fill="#1A1917"
                          pointerEvents="none"
                        />
                      )}
                      {isReality && (
                        <line
                          x1={x + (CELL_W - 1) / 2}
                          x2={x + (CELL_W - 1) / 2}
                          y1={y - 2}
                          y2={y + CELL_H + 2}
                          stroke="#1A1917"
                          strokeWidth={1.5}
                          pointerEvents="none"
                        />
                      )}
                    </g>
                  );
                })}
                {/* How wide this driver's defensible middle actually is. Zero is
                    a real and common answer, and the number says so where the
                    shading alone would just look uniformly flagged. */}
                <text
                  x={LABEL_W + (lastLap - firstLap + 1) * CELL_W + 4}
                  y={y + CELL_H - 3}
                  className="font-mono"
                  fontSize={8}
                  fill={inside === 0 ? "#A8761F" : "#1A1917"}
                  opacity={inside === 0 ? 1 : 0.5}
                >
                  {inside}
                </text>
              </g>
            );
          })}
          <text
            x={LABEL_W}
            y={height - 4}
            className="font-mono"
            fontSize={8}
            fill="#1A1917"
            opacity={0.45}
          >
            lap {firstLap} → {lastLap} · right-hand number = candidates inside the evidence
          </text>
        </svg>
      </div>
    </section>
  );
}

/** Exported for the test that pins the cause-code mapping. */
export { CAUSE_BY_CODE };

/**
 * GapChart — the primary visualisation (spec 11.2). Gap to leader on y,
 * lap number on x. Renders into the shared axis owned by `LapAxisPanes` so
 * it stays locked to StrategyTimeline below it.
 *
 * Two modes, because spec 11.2's "one line per driver in team colours" and
 * the counterfactual overlay want different treatments and can't share one:
 *
 *   - "field": all drivers, team colours (darkened for paper legibility, see
 *     lib/teamColors), reality only, dimmed by default with one line raised
 *     on hover — twenty hairlines at the 3:1 contrast floor read as spaghetti
 *     no matter how the numeric check scores.
 *   - "focus": one driver, and the y variable is not gap-to-leader at all but
 *     the *decision effect* — how much time the counterfactual cost or saved
 *     against a simulated replay of the real race. The real timeline is
 *     therefore the zero rule, and y is floored by MIN_Y_EXTENT_S so a
 *     sub-second effect reads as small rather than auto-scaled into a chasm.
 *
 * Focus mode draws up to four things, deliberately distinguished:
 *
 *   - the oxide median and its p10–p90 band: the decision effect;
 *   - three individual seed trajectories, because a band cannot show a bimodal
 *     ensemble (if he either makes a pass or doesn't, the median sits in a
 *     region no seed occupied);
 *   - a dashed ink line: the same alternate measured against the *actual* race,
 *     so it carries the simulator's replay error too. Separate and labelled,
 *     never merged into the effect — on Hungary/VER the replay error is 7.4s,
 *     which would swamp any candidate whose real effect is a couple of seconds.
 *
 * Two things this deliberately does NOT do:
 *
 *   1. It never draws a single uncertainty band over total gap. The backend
 *      separates pace variance from accumulated held-up ("stuck behind a car
 *      you can't pass") time, and merging them would silently report "how
 *      much traffic did he hit" as if it were "how unsure are we about his
 *      pace." The band is pace-only; traffic is discrete tick marks, and the
 *      pace/traffic split of the net effect is reported in prose beside it.
 *   2. It doesn't rely on colour alone: teammates get distinct dash patterns.
 *
 * Hand-built SVG rather than a chart library because the shared lap axis
 * requires exact control of the x scale, and every library abstraction would
 * have to be fought to guarantee alignment.
 */

import { useMemo, useState } from "react";
import { teamLineColor, teammateDash } from "../lib/teamColors";
import { AXIS_MARGIN, type LapAxis } from "./LapAxisPanes";

/**
 * Minimum y-extent in seconds. Without a floor, auto-scaling a floor-pinned
 * comparison (real 0.0s vs alternate 0.58s, the fitted MIN_FOLLOWING_GAP_S)
 * fits the axis to that range and renders a constant the model cannot resolve
 * past as a dramatic chasm. A margin the model is physically incapable of
 * narrowing should look small.
 */
export const MIN_Y_EXTENT_S = 5;

/**
 * How many median-absolute-deviations of delta the comparison axis spans
 * before values are treated as overflow.
 *
 * A plain min/max range does not work for the delta variable. When a pit stop
 * falls inside the window, one timeline is in the pit lane while the other is
 * on track, so the delta briefly reaches ~20s — a real effect, not an
 * artifact, but on the demo case it is 4 laps out of 21 and it compressed the
 * strategic region (0–2.5s) into 16px of 260. A literal 5th–95th percentile
 * does not help either: at 18% of the sample the transient survives the
 * percentile. MAD is robust to exactly this shape, and 6x it is generous
 * enough not to clip ordinary variation.
 */
const ROBUST_MAD_MULTIPLE = 6;

function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export type GapPoint = { lap: number; gap: number };
export type AlternatePoint = {
  lap: number;
  gap: number;
  paceLow: number;
  paceHigh: number;
  clampedFraction: number;
};
export type SeedTrace = { seed: number; points: GapPoint[] };

/**
 * A delta already computed against the real timeline, with its band as
 * quantiles of the delta itself.
 *
 * The precomputed catalogue (Phase 6.2) stores this rather than the alternate
 * gap-to-leader, for a reason that matters here: the band it ships is the
 * p10–p90 spread of `alternate - real` across seeds, which is not obtainable
 * by differencing two summary series. Passing `alternateSeries` and letting
 * this component subtract would silently replace that band with something
 * else, so precomputed deltas come in through their own prop.
 */
export type DeltaPoint = {
  lap: number;
  median: number;
  low: number;
  high: number;
  clampedFraction: number;
};

export type GapChartProps = {
  axis: LapAxis;
  realSeries: Record<string, GapPoint[]>;
  teamByDriver: Record<string, string>;
  teammateIndex: Record<string, number>;
  mode: "field" | "focus";
  focusDriver?: string;
  /** Median of the ensemble — labelled as such, since it's no single universe. */
  alternateSeries?: AlternatePoint[];
  /**
   * Precomputed `alternate - real` with a band of delta quantiles. Takes
   * precedence over `alternateSeries` when both are given.
   */
  deltaSeries?: DeltaPoint[];
  /**
   * The same alternate measured against the *actual* race rather than against
   * the simulated replay of it, so it carries the simulator's replay error too.
   * Drawn as a separate labelled line because the difference between the two is
   * itself the useful reading: on Hungary/VER the replay error reaches 7.4s, so
   * a candidate whose real effect is a couple of seconds would be swamped if
   * this were presented as the decision's effect.
   */
  replayErrorSeries?: { lap: number; value: number }[];
  /** Individual seed traces, drawn faintly so the median isn't read as "the" answer. */
  seedSeries?: SeedTrace[];
  divergenceLap?: number;
  /** Ensemble size behind the median and band, for the legend's honesty. */
  nRuns?: number;
  /**
   * Phase 6.4: draw only up to this lap, so the traces come in progressively as
   * the playhead advances. `null` shows the whole race.
   */
  revealLap?: number | null;
  safetyCarPeriods?: { kind: string; startLap: number; endLap: number }[];
  height?: number;
  hoverLap?: number | null;
  onHoverLap?: (lap: number | null) => void;
};

const V_MARGIN = { top: 14, bottom: 26 };

export default function GapChart({
  axis,
  realSeries,
  teamByDriver,
  teammateIndex,
  mode,
  focusDriver,
  alternateSeries,
  deltaSeries,
  replayErrorSeries,
  seedSeries,
  divergenceLap,
  nRuns,
  revealLap = null,
  safetyCarPeriods = [],
  height = 300,
  hoverLap = null,
  onHoverLap,
}: GapChartProps) {
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const { plotWidth, firstLap, lastLap, lapSpan, x, inRange } = axis;
  const innerHeight = height - V_MARGIN.top - V_MARGIN.bottom;

  const visibleDrivers = useMemo(
    () => (mode === "focus" && focusDriver ? [focusDriver] : Object.keys(realSeries).sort()),
    [mode, focusDriver, realSeries],
  );

  // Comparison mode plots the DELTA between timelines, not gap-to-leader.
  // Gap-to-leader carries no information when the subject is the leader: in
  // the demo case the driver led the whole displayed window, so both traces
  // sat flat on the axis boundary and the y-range was set by his real
  // pit-stop dip — leaving the actual comparison in a sliver of the plot.
  // That was the third instance of the y-scale swallowing the signal.
  //
  // A consequence worth naming: once the variable is `alternate - real`, the
  // real timeline *is* the zero line. So focus mode draws one oxide trace
  // against a zero rule rather than two traces, which is what lets a
  // sub-second difference actually read.
  const isDelta = mode === "focus";

  const realByLapForFocus = useMemo(() => {
    const map = new Map<number, number>();
    for (const p of realSeries[focusDriver ?? ""] ?? []) map.set(p.lap, p.gap);
    return map;
  }, [realSeries, focusDriver]);

  // The alternate timeline is drawn from the last *shared* lap onward. Before
  // the fork it is reality copied verbatim (spec 9.1 step 4), so drawing all
  // of it is redundant and actively misleading. But starting at the divergence
  // lap itself would leave the stroke floating whenever the two values differ
  // there (they coincide in the demo only because VER leads in both timelines
  // — luck, not structure). Anchoring one lap earlier uses a lap that
  // genuinely belongs to BOTH timelines.
  const branchAnchorLap = divergenceLap != null ? divergenceLap - 1 : null;
  const alternateInRange = useMemo(
    () =>
      (alternateSeries ?? []).filter(
        (p) => inRange(p.lap) && (branchAnchorLap == null || p.lap >= branchAnchorLap),
      ),
    [alternateSeries, firstLap, lastLap, branchAnchorLap],
  );

  /**
   * Gap-to-leader has a hard floor at zero: a car cannot be ahead of the
   * leader. `paceLow` is derived by subtracting accumulated held-up time from
   * the gap, which can push it below that floor — and it did, rendering the
   * band above the zero line into physically impossible territory. Clamp at
   * the variable's valid bound before the value is used for anything.
   */
  const clampGap = (gap: number) => Math.max(0, gap);

  /**
   * Delta series. Either read straight from a precomputed fixture, or derived
   * here by differencing the alternate against the real timeline with the band
   * bounds clamped at source.
   */
  const deltaInRange = useMemo(() => {
    if (deltaSeries) {
      return deltaSeries
        .filter((p) => inRange(p.lap) && (branchAnchorLap == null || p.lap >= branchAnchorLap))
        .map((p) => ({
          lap: p.lap,
          gap: p.median,
          low: p.low,
          high: p.high,
          clampedFraction: p.clampedFraction,
        }));
    }
    return alternateInRange.map((p) => {
      const real = realByLapForFocus.get(p.lap) ?? 0;
      return {
        lap: p.lap,
        gap: clampGap(p.gap) - real,
        low: clampGap(p.paceLow) - real,
        high: clampGap(p.paceHigh) - real,
        clampedFraction: p.clampedFraction,
      };
    });
  }, [deltaSeries, firstLap, lastLap, branchAnchorLap, alternateInRange, realByLapForFocus]);

  /** The subset actually drawn, once the playhead has clipped it. */
  const deltaShown = useMemo(
    () => (revealLap == null ? deltaInRange : deltaInRange.filter((p) => p.lap <= revealLap)),
    [deltaInRange, revealLap],
  );

  /** [min, max] of the y variable. Field mode floors at 0; delta centres on it. */
  const [yLo, yHi] = useMemo<[number, number]>(() => {
    if (isDelta) {
      // Robust to the pit-lane transient (see ROBUST_MAD_MULTIPLE). Values
      // outside the resulting range are still drawn, clipped, with an
      // overflow marker carrying the real number — nothing is hidden.
      const values = deltaInRange.flatMap((p) => [p.gap, p.low, p.high]);
      // The replay-error line shares this axis, so it has to be inside the
      // sample that sets the range — otherwise it renders permanently clipped.
      for (const p of replayErrorSeries ?? []) if (inRange(p.lap)) values.push(p.value);
      const med = median(values);
      const mad = median(values.map((v) => Math.abs(v - med)));
      // MIN_Y_EXTENT_S still applies as a floor on the total span, so a small
      // delta can't be auto-scaled into a chasm; it also covers MAD = 0, which
      // happens when most laps share one value.
      const spread = Math.max(mad * ROBUST_MAD_MULTIPLE, MIN_Y_EXTENT_S / 2);
      // Zero must stay on the axis: it is the real timeline.
      const rawLo = Math.min(0, med - spread);
      const rawHi = Math.max(0, med + spread);
      const step = rawHi - rawLo > 40 ? 10 : rawHi - rawLo > 16 ? 5 : rawHi - rawLo > 8 ? 2 : 1;
      return [Math.floor(rawLo / step) * step, Math.ceil(rawHi / step) * step];
    }
    let max = 0;
    for (const driver of visibleDrivers) {
      for (const p of realSeries[driver] ?? []) if (inRange(p.lap)) max = Math.max(max, p.gap);
    }
    max = Math.max(max, MIN_Y_EXTENT_S);
    const step = max > 60 ? 20 : max > 20 ? 10 : max > 8 ? 2 : 1;
    return [0, Math.max(step, Math.ceil(max / step) * step)];
  }, [isDelta, deltaInRange, replayErrorSeries, seedSeries, visibleDrivers, realSeries, firstLap, lastLap, realByLapForFocus]);

  /** Positive is downward in both modes: a bigger gap, or time lost, reads lower. */
  const y = (v: number) => ((v - yLo) / (yHi - yLo)) * innerHeight;

  const path = (points: GapPoint[]) => {
    // `revealLap` clips the drawing, never the scale: the y-range is computed
    // from the whole visible window so the axis doesn't rescale on every lap of
    // playback. The same lesson as freezing the lap window during the pit drag —
    // geometry that moves while something animates over it is unreadable.
    const clipped = points.filter(
      (p) => inRange(p.lap) && (revealLap == null || p.lap <= revealLap),
    );
    return clipped.length
      ? clipped.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.lap).toFixed(2)},${y(p.gap).toFixed(2)}`).join(" ")
      : "";
  };

  const yTicks = useMemo(() => {
    const span = yHi - yLo;
    const step = span > 120 ? 20 : span > 40 ? 10 : span > 16 ? 5 : span > 8 ? 2 : 1;
    const ticks: number[] = [];
    for (let v = Math.ceil(yLo / step) * step; v <= yHi + 1e-9; v += step) ticks.push(v);
    if (isDelta && !ticks.some((t) => Math.abs(t) < 1e-9)) ticks.push(0);
    return ticks.sort((a, b) => a - b);
  }, [yLo, yHi, isDelta]);

  const xTicks = useMemo(() => {
    const step = lapSpan > 50 ? 10 : lapSpan > 20 ? 5 : 2;
    const ticks: number[] = [];
    for (let v = Math.ceil(firstLap / step) * step; v <= lastLap; v += step) ticks.push(v);
    // Label the window's first lap only if it won't collide with the first
    // step tick (otherwise "44 45" renders on top of itself).
    if (ticks.length === 0 || ticks[0] - firstLap >= step / 2) ticks.unshift(firstLap);
    return ticks;
  }, [firstLap, lastLap, lapSpan]);

  function onMove(event: React.MouseEvent<SVGSVGElement>) {
    if (!onHoverLap) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - rect.left - AXIS_MARGIN.left;
    const lap = Math.round((px / plotWidth) * lapSpan) + firstLap;
    onHoverLap(inRange(lap) ? lap : null);
  }

  const alternateByLap = useMemo(() => {
    const map = new Map<number, AlternatePoint>();
    for (const p of alternateSeries ?? []) map.set(p.lap, p);
    return map;
  }, [alternateSeries]);

  const replayErrorByLap = useMemo(() => {
    const map = new Map<number, number>();
    for (const p of replayErrorSeries ?? []) map.set(p.lap, p.value);
    return map;
  }, [replayErrorSeries]);

  /** The plotted delta points, keyed by lap, for the hover readout. */
  const deltaByLap = useMemo(() => {
    const map = new Map<number, (typeof deltaInRange)[number]>();
    for (const p of deltaInRange) map.set(p.lap, p);
    return map;
  }, [deltaInRange]);

  /**
   * Laps whose delta falls outside the robust range. The trace is clipped
   * rather than allowed to set the scale, so these carry the actual number
   * back onto the chart — a clipped line with no annotation would be the
   * chart lying about its own range.
   */
  const overflows = useMemo(() => {
    if (!isDelta) return [] as { lap: number; value: number; above: boolean }[];
    return deltaShown
      .filter((p) => p.gap < yLo || p.gap > yHi)
      .map((p) => ({ lap: p.lap, value: p.gap, above: p.gap < yLo }));
  }, [isDelta, deltaShown, yLo, yHi]);

  /** The single most extreme overflow, labelled with its value. */
  const peakOverflow = useMemo(
    () =>
      overflows.reduce<{ lap: number; value: number; above: boolean } | null>(
        (best, p) => (best == null || Math.abs(p.value) > Math.abs(best.value) ? p : best),
        null,
      ),
    [overflows],
  );

  const clipId = `plot-clip-${focusDriver ?? "field"}`;

  return (
    <figure className="m-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 px-1 pb-1">
        <figcaption className="label-caps">
          {isDelta
            ? `${focusDriver} — time the decision cost or saved`
            : "Gap to leader — race as it happened"}
        </figcaption>
        {isDelta && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-micro">
            <span className="flex items-center gap-1.5">
              <svg width="18" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="18" y2="4" stroke="#1A1917" strokeWidth="1.5" />
              </svg>
              real <span className="text-ink/45">= zero</span>
            </span>
            <span className="flex items-center gap-1.5">
              <svg width="18" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="18" y2="4" stroke="#A33A2E" strokeWidth="1.75" />
              </svg>
              decision effect{" "}
              <span className="text-ink/45">
                median and p10–p90 of {nRuns ?? seedSeries?.length ?? 0} paired runs
              </span>
            </span>
            {replayErrorSeries && replayErrorSeries.length > 0 && (
              <span className="flex items-center gap-1.5">
                <svg width="18" height="8" aria-hidden="true">
                  <line
                    x1="0"
                    y1="4"
                    x2="18"
                    y2="4"
                    stroke="#1A1917"
                    strokeOpacity="0.4"
                    strokeWidth="1"
                    strokeDasharray="2 3"
                  />
                </svg>
                vs actual <span className="text-ink/45">incl. replay error</span>
              </span>
            )}
            <span className="text-ink/45">below = time lost</span>
          </div>
        )}
      </div>

      <svg
        width={plotWidth + AXIS_MARGIN.left + AXIS_MARGIN.right}
        height={height}
        role="img"
        aria-label={
          isDelta
            ? `Time lost or gained by ${focusDriver} in the alternate timeline against the real race, by lap. Zero is the real race.`
            : "Gap to leader for every driver, as the race happened"
        }
        onMouseMove={onMove}
        onMouseLeave={() => onHoverLap?.(null)}
        className="block"
      >
        <defs>
          <clipPath id={clipId}>
            <rect x={0} y={0} width={plotWidth} height={innerHeight} />
          </clipPath>
        </defs>
        <g transform={`translate(${AXIS_MARGIN.left},${V_MARGIN.top})`}>
          {safetyCarPeriods.map((p) => (
            <rect
              key={`${p.kind}-${p.startLap}`}
              x={x(p.startLap)}
              y={0}
              width={Math.max(1, x(p.endLap) - x(p.startLap))}
              height={innerHeight}
              fill="#E8E4DA"
            />
          ))}

          {yTicks.map((t) => (
            <line key={t} x1={0} x2={plotWidth} y1={y(t)} y2={y(t)} stroke="#C9C3B6" strokeWidth={t === 0 ? 1 : 0.5} />
          ))}

          {mode === "focus" && divergenceLap != null && inRange(divergenceLap) && (
            <>
              <line
                x1={x(divergenceLap)}
                x2={x(divergenceLap)}
                y1={0}
                y2={innerHeight}
                stroke="#A33A2E"
                strokeWidth={1}
                strokeDasharray="3 3"
              />
              <text x={x(divergenceLap) + 4} y={10} className="font-mono" fontSize={10} fill="#A33A2E">
                L{divergenceLap}
              </text>
            </>
          )}

          {/* Everything data-bearing is clipped to the plot, so a value beyond
              the robust range can't scribble over the axes. Its real number is
              restored by the overflow markers below. */}
          <g clipPath={`url(#${clipId})`}>
          {/* Pace-only band. Means ONE thing: uncertainty about pace. Bounds
              are already clamped at the gap variable's floor before being
              differenced, so the band cannot reach into impossible territory. */}
          {isDelta && deltaShown.length > 0 && (
            <path
              d={`${path(deltaShown.map((p) => ({ lap: p.lap, gap: p.high })))} ${deltaShown
                .slice()
                .reverse()
                .map((p) => `L${x(p.lap).toFixed(2)},${y(p.low).toFixed(2)}`)
                .join(" ")} Z`}
              fill="#A33A2E"
              fillOpacity={0.1}
              stroke="none"
            />
          )}

          {/* Real seed traces (spec 6.10): the spread, so the median isn't
              read as the single answer. Converted to deltas against the real
              timeline, same clamp applied. */}
          {isDelta &&
            seedSeries?.map((trace) => (
              <path
                key={`seed-${trace.seed}`}
                d={path(
                  // Already deltas when they came from a precomputed fixture;
                  // differencing them again would double-subtract reality.
                  deltaSeries
                    ? trace.points
                    : trace.points.map((p) => ({
                        lap: p.lap,
                        gap: clampGap(p.gap) - (realByLapForFocus.get(p.lap) ?? 0),
                      })),
                )}
                fill="none"
                stroke="#A33A2E"
                strokeWidth={0.75}
                strokeOpacity={0.4}
              />
            ))}

          {/* Field mode draws every driver's gap-to-leader. Focus mode draws
              none of them: with the variable as `alternate - real`, the real
              timeline is exactly the zero rule below, so a separate ink trace
              would be a flat line on top of it. */}
          {!isDelta &&
            visibleDrivers.map((driver) => {
              const isHighlighted = highlighted === driver;
              const dimmed = highlighted != null && !isHighlighted;
              return (
                <path
                  key={driver}
                  d={path(realSeries[driver] ?? [])}
                  fill="none"
                  stroke={teamLineColor(teamByDriver[driver] ?? "")}
                  strokeWidth={isHighlighted ? 2 : 1}
                  strokeDasharray={teammateDash(teammateIndex[driver] ?? 0)}
                  strokeOpacity={dimmed ? 0.18 : isHighlighted ? 1 : 0.5}
                />
              );
            })}

          {/* The zero rule: this IS the real timeline in delta mode. Drawn in
              ink at full weight so it reads as a reference line with meaning,
              not as a gridline. */}
          {isDelta && (
            <>
              <line x1={0} x2={plotWidth} y1={y(0)} y2={y(0)} stroke="#1A1917" strokeWidth={1.5} />
              <text x={2} y={y(0) - 4} className="font-mono" fontSize={9} fill="#1A1917" opacity={0.55}>
                real
              </text>
            </>
          )}

          {/* Replay error: the same alternate measured against the actual race.
              Dashed and in ink rather than oxide, because it is a statement
              about the model, not about the decision. */}
          {isDelta && replayErrorSeries && replayErrorSeries.length > 0 && (
            <path
              d={path(replayErrorSeries.map((p) => ({ lap: p.lap, gap: p.value })))}
              fill="none"
              stroke="#1A1917"
              strokeWidth={1}
              strokeOpacity={0.4}
              strokeDasharray="2 3"
            />
          )}

          {isDelta && deltaShown.length > 0 && (
            <path d={path(deltaShown)} fill="none" stroke="#A33A2E" strokeWidth={1.75} />
          )}

          {/* Branch node: without it the two strokes read as a break in one
              line rather than one history splitting into two. Paper-filled
              with an ink stroke so it reads as a junction on the shared line,
              not a data point owned by either timeline. */}
          {isDelta && branchAnchorLap != null && inRange(branchAnchorLap) && (
            <circle
              cx={x(branchAnchorLap)}
              /* In delta terms the fork is by definition at zero: before it,
                 the two timelines are the same history. */
              cy={y(0)}
              r={3}
              fill="#F4F1EA"
              stroke="#1A1917"
              strokeWidth={1.25}
            />
          )}

          {/* Held-up ticks: traffic as a discrete EVENT, not diffused band. */}
          {isDelta &&
            deltaShown
              .filter((p) => p.clampedFraction > 0.5)
              .map((p) => (
                <line
                  key={`clamp-${p.lap}`}
                  x1={x(p.lap)}
                  x2={x(p.lap)}
                  y1={y(p.gap) - 4}
                  y2={y(p.gap) + 4}
                  stroke="#A33A2E"
                  strokeWidth={1.5}
                />
              ))}
          </g>

          {/* Overflow markers, drawn OUTSIDE the clip so they always show. A
              small oxide wedge at the edge for each lap beyond the range, and
              the peak value spelled out — the range is robust to the pit
              transient, but the transient is real and must stay readable. */}
          {overflows.map((p) => {
            const edge = p.above ? 0 : innerHeight;
            const dir = p.above ? 1 : -1;
            return (
              <path
                key={`ovf-${p.lap}`}
                d={`M${(x(p.lap) - 3.5).toFixed(2)},${edge + dir * 6} L${x(p.lap).toFixed(2)},${edge} L${(x(p.lap) + 3.5).toFixed(2)},${edge + dir * 6} Z`}
                fill="#A33A2E"
                fillOpacity={0.85}
              />
            );
          })}
          {peakOverflow && (
            <text
              x={Math.min(x(peakOverflow.lap) + 6, plotWidth - 4)}
              y={peakOverflow.above ? 14 : innerHeight - 6}
              textAnchor={x(peakOverflow.lap) > plotWidth - 60 ? "end" : "start"}
              className="font-mono"
              fontSize={9.5}
              fill="#A33A2E"
            >
              {peakOverflow.value > 0 ? "+" : ""}
              {peakOverflow.value.toFixed(1)}s at L{peakOverflow.lap} (off scale)
            </text>
          )}

          {hoverLap != null && inRange(hoverLap) && (
            <line x1={x(hoverLap)} x2={x(hoverLap)} y1={0} y2={innerHeight} stroke="#1A1917" strokeWidth={0.5} />
          )}

          {yTicks.map((t) => (
            <text
              key={`yl-${t}`}
              x={-8}
              y={y(t) + 3}
              textAnchor="end"
              className="font-mono"
              fontSize={10}
              fill="#1A1917"
              opacity={isDelta && t === 0 ? 1 : 0.75}
            >
              {/* Signed in delta mode: the sign is the whole point. */}
              {isDelta && t > 0 ? `+${t}` : t}
            </text>
          ))}
          {xTicks.map((t) => (
            <text
              key={`xl-${t}`}
              x={x(t)}
              y={innerHeight + 16}
              textAnchor="middle"
              className="font-mono"
              fontSize={10}
              fill="#1A1917"
            >
              {t}
            </text>
          ))}
          <text x={-8} y={-5} textAnchor="end" className="font-sans" fontSize={9} fill="#1A1917" opacity={0.55}>
            SEC
          </text>
        </g>
      </svg>

      {/* Readout below rather than a floating tooltip: never occludes the
          data, and holds still enough to actually read. */}
      <div className="flex min-h-[2.25rem] flex-wrap items-baseline gap-x-5 gap-y-1 px-1 pt-1.5 font-mono text-micro">
        {hoverLap == null ? (
          <span className="text-ink/40">Hover the chart for a lap readout</span>
        ) : isDelta ? (
          (() => {
            // Read the plotted point rather than re-deriving it, so the
            // readout cannot disagree with the chart under either data source.
            const point = deltaByLap.get(hoverLap);
            const realGap = realByLapForFocus.get(hoverLap);
            const alt = alternateByLap.get(hoverLap);
            const replayError = replayErrorByLap.get(hoverLap) ?? null;
            const postFork = divergenceLap == null || hoverLap >= divergenceLap;
            return (
              <>
                <span className="text-ink/60">LAP {hoverLap}</span>
                {postFork && point != null ? (
                  <>
                    <span className="text-annotation">
                      {point.gap >= 0 ? "+" : ""}
                      {point.gap.toFixed(2)}s {point.gap >= 0 ? "lost" : "gained"}
                    </span>
                    <span className="text-ink/50">
                      p10–p90 {point.low >= 0 ? "+" : ""}
                      {point.low.toFixed(2)} to {point.high >= 0 ? "+" : ""}
                      {point.high.toFixed(2)}s
                    </span>
                    {replayError != null && (
                      <span className="text-ink/50">
                        vs actual {replayError >= 0 ? "+" : ""}
                        {replayError.toFixed(2)}s
                      </span>
                    )}
                    {/* Gap-to-leader context only when the alternate series is
                        actually available; the precomputed fixtures store the
                        delta alone, and inventing an "alt" figure from it would
                        be arithmetic dressed up as data. */}
                    {realGap != null && alt != null && (
                      <span className="text-ink/50">
                        gap to leader: real {realGap.toFixed(1)}s · alt {clampGap(alt.gap).toFixed(1)}s
                      </span>
                    )}
                    {point.clampedFraction > 0.5 && (
                      <span className="text-annotation">
                        held up ({Math.round(point.clampedFraction * 100)}% of runs)
                      </span>
                    )}
                  </>
                ) : (
                  <span className="text-ink/40">before the fork — one history, delta is zero</span>
                )}
              </>
            );
          })()
        ) : (
          (() => {
            const order = visibleDrivers
              .map((d) => ({ d, p: (realSeries[d] ?? []).find((q) => q.lap === hoverLap) }))
              .filter((e) => e.p)
              .sort((a, b) => (a.p!.gap ?? 0) - (b.p!.gap ?? 0));
            return (
              <>
                <span className="text-ink/60">LAP {hoverLap}</span>
                {order.slice(0, 10).map((e, i) => (
                  <span
                    key={e.d}
                    onMouseEnter={() => setHighlighted(e.d)}
                    onMouseLeave={() => setHighlighted(null)}
                    className={`cursor-default ${highlighted === e.d ? "bg-wash" : ""}`}
                  >
                    <span className="text-ink/40">{i + 1}</span> {e.d}{" "}
                    <span className="text-ink/60">{e.p!.gap === 0 ? "leader" : `+${e.p!.gap.toFixed(1)}`}</span>
                  </span>
                ))}
              </>
            );
          })()
        )}
      </div>
    </figure>
  );
}

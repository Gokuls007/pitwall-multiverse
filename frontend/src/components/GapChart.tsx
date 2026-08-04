/**
 * GapChart — the primary visualisation (spec 11.2). Gap to leader on y,
 * lap number on x.
 *
 * Two modes, because spec 11.2's "one line per driver in team colours" and
 * the counterfactual overlay want different treatments and can't share one:
 *
 *   - "field": all drivers, team colours (darkened for paper legibility, see
 *     lib/teamColors), reality only. Y auto-scales to the full field spread.
 *   - "focus": one driver, ink = real vs oxide = alternate, y locked to just
 *     those two lines so a sub-second margin is actually visible.
 *
 * Two things this deliberately does NOT do:
 *
 *   1. It never draws a single uncertainty band over total gap. The backend
 *      separates pace variance from accumulated held-up ("stuck behind a car
 *      you can't pass") time, and merging them would silently report "how
 *      much traffic did he hit" as if it were "how unsure are we about his
 *      pace." So the band is pace-only, and traffic is a separate discrete
 *      channel — tick marks on the line at laps where the clamp bound.
 *   2. It doesn't rely on colour alone: teammates get distinct dash patterns.
 *
 * Rendered as hand-built SVG rather than a chart library because the shared
 * lap axis with StrategyTimeline requires exact control of the x scale, and
 * every library abstraction would have to be fought to guarantee alignment.
 */

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { teamLineColor, teammateDash } from "../lib/teamColors";

export const MIN_LAP_WIDTH_PX = 14;

/**
 * Minimum y-extent in seconds. Without a floor, auto-scaling a
 * floor-pinned comparison (real 0.0s vs alternate 0.58s, the fitted
 * MIN_FOLLOWING_GAP_S) fits the axis to that range and renders a constant
 * the model cannot resolve past as a dramatic chasm. A margin the model is
 * physically incapable of narrowing should look small.
 */
export const MIN_Y_EXTENT_S = 5;

export type GapPoint = { lap: number; gap: number };
export type AlternatePoint = {
  lap: number;
  gap: number;
  paceLow: number;
  paceHigh: number;
  clampedFraction: number;
};
export type SeedTrace = { seed: number; points: GapPoint[] };

export type GapChartProps = {
  totalLaps: number;
  /** driver code -> real gap-to-leader series */
  realSeries: Record<string, GapPoint[]>;
  /** driver code -> team name, for colour + dash assignment */
  teamByDriver: Record<string, string>;
  /** driver code -> index within their team (0 or 1), for dash patterns */
  teammateIndex: Record<string, number>;
  mode: "field" | "focus";
  /** Required in focus mode: which driver to compare. */
  focusDriver?: string;
  /** Required in focus mode: the alternate timeline (median of the ensemble). */
  alternateSeries?: AlternatePoint[];
  /** Individual seed traces, drawn faintly so the median isn't read as "the" answer. */
  seedSeries?: SeedTrace[];
  divergenceLap?: number;
  safetyCarPeriods?: { kind: string; startLap: number; endLap: number }[];
  height?: number;
  /** Inclusive lap range to draw. Defaults to the whole race. */
  lapRange?: [number, number];
};

const MARGIN = { top: 14, right: 16, bottom: 26, left: 52 };

export default function GapChart({
  totalLaps,
  realSeries,
  teamByDriver,
  teammateIndex,
  mode,
  focusDriver,
  alternateSeries,
  seedSeries,
  divergenceLap,
  safetyCarPeriods = [],
  height = 340,
  lapRange,
}: GapChartProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [hoverLap, setHoverLap] = useState<number | null>(null);
  const [highlighted, setHighlighted] = useState<string | null>(null);

  const [firstLap, lastLap] = lapRange ?? [1, totalLaps];
  const lapSpan = Math.max(1, lastLap - firstLap);
  const inRange = (lap: number) => lap >= firstLap && lap <= lastLap;

  // A minimum px-per-lap keeps pit ticks hittable and stint bars readable on
  // narrow screens; the container scrolls horizontally rather than letting
  // 70 laps compress into ~360px (~5px/lap, unusable). Because the shared
  // axis with StrategyTimeline must stay locked, this is ONE scroll
  // container in the parent — alignment holds by construction rather than by
  // synchronising two scroll offsets.
  // MIN_LAP_WIDTH_PX is a floor, not a fixed size: on a narrow viewport it
  // forces horizontal scroll rather than compressing laps to ~5px, but on a
  // wide viewport (or a short lap window) the chart should fill the space
  // instead of leaving half the container empty.
  const [availableWidth, setAvailableWidth] = useState(0);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => setAvailableWidth(el.clientWidth);
    measure();
    // ResizeObserver is the right tool but isn't universally present (jsdom
    // has no implementation). Degrade to a window listener rather than
    // throwing — the chart still renders at its minimum width either way.
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const minPlotWidth = (lapSpan + 1) * MIN_LAP_WIDTH_PX;
  // The -2 keeps the SVG a hair inside the container so sub-pixel rounding
  // doesn't produce a scrollbar on a chart that already fits.
  const plotWidth = Math.max(minPlotWidth, availableWidth - MARGIN.left - MARGIN.right - 2);
  const innerWidth = plotWidth;
  const innerHeight = height - MARGIN.top - MARGIN.bottom;

  const visibleDrivers = useMemo(
    () => (mode === "focus" && focusDriver ? [focusDriver] : Object.keys(realSeries).sort()),
    [mode, focusDriver, realSeries],
  );

  const yMax = useMemo(() => {
    let max = 0;
    for (const driver of visibleDrivers) {
      for (const p of realSeries[driver] ?? []) if (inRange(p.lap)) max = Math.max(max, p.gap);
    }
    if (mode === "focus" && alternateSeries) {
      for (const p of alternateSeries) if (inRange(p.lap)) max = Math.max(max, p.gap, p.paceHigh);
    }
    // Floor the extent so a gap pinned at the model's own following-distance
    // constant doesn't get magnified into a dramatic-looking chasm.
    max = Math.max(max, MIN_Y_EXTENT_S);
    // Round up to a clean tick so the axis reads like a printed sheet.
    const step = max > 60 ? 20 : max > 20 ? 10 : max > 8 ? 2 : 1;
    return Math.max(step, Math.ceil(max / step) * step);
  }, [visibleDrivers, realSeries, mode, alternateSeries, firstLap, lastLap]);

  const x = (lap: number) => ((lap - firstLap) / lapSpan) * innerWidth;
  const y = (gap: number) => (gap / yMax) * innerHeight;

  const path = (points: { lap: number; gap: number }[]) => {
    const clipped = points.filter((p) => inRange(p.lap));
    return clipped.length
      ? clipped.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.lap).toFixed(2)},${y(p.gap).toFixed(2)}`).join(" ")
      : "";
  };

  // The alternate timeline is drawn from the last *shared* lap onward.
  // Before the fork it is reality copied verbatim (spec 9.1 step 4), so
  // drawing all of it is redundant and actively misleading — the oxide line
  // sits exactly on top of the ink one and "real" appears missing from its
  // own chart. But starting at the divergence lap itself would leave the
  // oxide stroke floating, disconnected from the history it branches from,
  // whenever the two values differ at that lap (they only coincide here
  // because VER leads in both timelines — luck, not structure).
  //
  // So the path is anchored one lap earlier: `divergenceLap - 1` genuinely
  // belongs to BOTH timelines, so including it is truthful and guarantees
  // the branch visibly originates from the shared line in every case.
  const branchAnchorLap = divergenceLap != null ? divergenceLap - 1 : null;
  const alternateInRange = useMemo(
    () =>
      (alternateSeries ?? []).filter(
        (p) => inRange(p.lap) && (branchAnchorLap == null || p.lap >= branchAnchorLap),
      ),
    [alternateSeries, firstLap, lastLap, branchAnchorLap],
  );

  const yTicks = useMemo(() => {
    const step = yMax > 60 ? 20 : yMax > 20 ? 10 : 2;
    const ticks: number[] = [];
    for (let v = 0; v <= yMax; v += step) ticks.push(v);
    return ticks;
  }, [yMax]);

  const xTicks = useMemo(() => {
    const step = lapSpan > 50 ? 10 : lapSpan > 20 ? 5 : 2;
    const ticks: number[] = [];
    for (let v = Math.ceil(firstLap / step) * step; v <= lastLap; v += step) ticks.push(v);
    // Label the window's first lap only if it won't collide with the first
    // step tick (otherwise "44 45" renders on top of itself), and drop a
    // trailing tick that would sit under the axis title.
    if (ticks.length === 0 || ticks[0] - firstLap >= step / 2) ticks.unshift(firstLap);
    return ticks.filter((t) => lastLap - t >= step / 2 || t === lastLap);
  }, [firstLap, lastLap, lapSpan]);

  const laps = useMemo(
    () => Array.from({ length: lapSpan + 1 }, (_, i) => firstLap + i),
    [firstLap, lapSpan],
  );

  function onMove(event: React.MouseEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - rect.left - MARGIN.left;
    const lap = Math.round((px / innerWidth) * lapSpan) + firstLap;
    setHoverLap(inRange(lap) ? lap : null);
  }

  const alternateByLap = useMemo(() => {
    const map = new Map<number, AlternatePoint>();
    for (const p of alternateSeries ?? []) map.set(p.lap, p);
    return map;
  }, [alternateSeries]);

  return (
    <figure className="m-0">
      <div className="flex items-baseline justify-between px-1 pb-1">
        <figcaption className="label-caps">
          Gap to leader — {mode === "focus" ? `${focusDriver}: real vs alternate` : "race as it happened"}
        </figcaption>
        {mode === "focus" && (
          <div className="flex items-center gap-4 font-mono text-micro">
            <span className="flex items-center gap-1.5">
              <svg width="18" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="18" y2="4" stroke="#1A1917" strokeWidth="1.75" />
              </svg>
              real
            </span>
            <span className="flex items-center gap-1.5">
              <svg width="18" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="18" y2="4" stroke="#A33A2E" strokeWidth="1.75" />
              </svg>
              {/* Named explicitly: this is a per-lap median across the
                  ensemble, not a trajectory any single seed produced. */}
              alternate <span className="text-ink/45">median of {seedSeries?.length ?? 0}+ runs</span>
            </span>
          </div>
        )}
      </div>

      <div ref={scrollRef} className="overflow-x-auto rule-t rule-b bg-paper" data-testid="gapchart-scroll">
        <svg
          width={plotWidth + MARGIN.left + MARGIN.right}
          height={height}
          role="img"
          aria-label={
            mode === "focus"
              ? `Gap to leader for ${focusDriver}, real timeline against the alternate timeline`
              : "Gap to leader for every driver, as the race happened"
          }
          onMouseMove={onMove}
          onMouseLeave={() => setHoverLap(null)}
          className="block"
        >
          <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
            {/* Safety car bands: a wash fill, behind everything. */}
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

            {/* Gridlines: hairline rule, never competing with data. */}
            {yTicks.map((t) => (
              <line key={t} x1={0} x2={innerWidth} y1={y(t)} y2={y(t)} stroke="#C9C3B6" strokeWidth={t === 0 ? 1 : 0.5} />
            ))}

            {/* Divergence marker: where the alternate history begins. */}
            {mode === "focus" && divergenceLap != null && (
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
                <text
                  x={x(divergenceLap) + 4}
                  y={10}
                  className="font-mono"
                  fontSize={10}
                  fill="#A33A2E"
                >
                  L{divergenceLap}
                </text>
              </>
            )}

            {/* Pace-only uncertainty band. This band means ONE thing: how
                unsure we are about pace. Held-up time is deliberately not in
                here — see the tick marks below. */}
            {mode === "focus" && alternateInRange.length > 0 && (
              <path
                d={`${path(alternateInRange.map((p) => ({ lap: p.lap, gap: p.paceHigh })))} ${alternateInRange
                  .slice()
                  .reverse()
                  .map((p) => `L${x(p.lap).toFixed(2)},${y(p.paceLow).toFixed(2)}`)
                  .join(" ")} Z`}
                fill="#A33A2E"
                fillOpacity={0.1}
                stroke="none"
              />
            )}

            {/* Individual seed traces. Spec 6.10: a counterfactual is a
                distribution, and the chart is the most persuasive surface in
                the product — a lone median line gets read as *the* answer and
                can visually contradict the classification panel beside it.
                Drawn faintly behind the median so the spread is visible
                without competing with it. */}
            {mode === "focus" &&
              seedSeries?.map((trace) => (
                <path
                  key={`seed-${trace.seed}`}
                  d={path(trace.points)}
                  fill="none"
                  stroke="#A33A2E"
                  strokeWidth={0.75}
                  strokeOpacity={0.28}
                />
              ))}

            {/* Real lines. Field mode: team colours + teammate dashes.
                Focus mode: ink, because it's being compared against oxide.
                Field mode de-emphasises everything by default — twenty
                hairlines at the 3:1 contrast floor read as spaghetti no
                matter how the numeric check scores, so the baseline is dim
                and hovering a driver in the readout raises just that one. */}
            {visibleDrivers.map((driver) => {
              const points = realSeries[driver] ?? [];
              const isFocus = mode === "focus";
              const isHighlighted = highlighted === driver;
              const dimmed = !isFocus && highlighted != null && !isHighlighted;
              return (
                <path
                  key={driver}
                  d={path(points)}
                  fill="none"
                  stroke={isFocus ? "#1A1917" : teamLineColor(teamByDriver[driver] ?? "")}
                  strokeWidth={isFocus ? 1.75 : isHighlighted ? 2 : 1}
                  strokeDasharray={isFocus ? undefined : teammateDash(teammateIndex[driver] ?? 0)}
                  strokeOpacity={isFocus ? 1 : dimmed ? 0.18 : isHighlighted ? 1 : 0.5}
                />
              );
            })}

            {/* Alternate median line, drawn over band and seed traces, and
                only from the fork onward. */}
            {mode === "focus" && alternateInRange.length > 0 && (
              <path d={path(alternateInRange)} fill="none" stroke="#A33A2E" strokeWidth={1.75} />
            )}

            {/* Branch node at the fork. Without it the two strokes read as a
                break in one line rather than one history splitting into two —
                and this is the single most important point on the chart. Drawn
                in paper-filled ink so it reads as a junction on the shared
                line, not as a data point belonging to either timeline. */}
            {mode === "focus" && branchAnchorLap != null && inRange(branchAnchorLap) && (
              <circle
                cx={x(branchAnchorLap)}
                cy={y(
                  (realSeries[focusDriver ?? ""] ?? []).find((p) => p.lap === branchAnchorLap)?.gap ?? 0,
                )}
                r={3}
                fill="#F4F1EA"
                stroke="#1A1917"
                strokeWidth={1.25}
              />
            )}

            {/* Held-up ticks: traffic as a discrete EVENT, not diffused into
                the band. A mark here reads "he was stuck at this lap." */}
            {mode === "focus" &&
              alternateInRange
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

            {/* Hover: crosshair + per-lap readout. */}
            {hoverLap != null && (
              <line x1={x(hoverLap)} x2={x(hoverLap)} y1={0} y2={innerHeight} stroke="#1A1917" strokeWidth={0.5} />
            )}

            {/* Axes. */}
            {yTicks.map((t) => (
              <text key={`yl-${t}`} x={-8} y={y(t) + 3} textAnchor="end" className="font-mono" fontSize={10} fill="#1A1917">
                {t}
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
            {/* Axis titles sit clear of the tick labels: SEC above the
                y-column rather than on the 0 tick, LAP below the x-row
                rather than in line with the last lap number. */}
            <text x={-8} y={-5} textAnchor="end" className="font-sans" fontSize={9} fill="#1A1917" opacity={0.55}>
              SEC
            </text>
            <text
              x={innerWidth}
              y={innerHeight + 25}
              textAnchor="end"
              className="font-sans"
              fontSize={9}
              fill="#1A1917"
              opacity={0.55}
            >
              LAP
            </text>

            {/* Invisible per-lap hit areas: 44px touch targets decoupled from
                the 14px visual spacing, so ticks stay tappable on mobile. */}
            {laps.map((lap) => (
              <rect
                key={`hit-${lap}`}
                x={x(lap) - MIN_LAP_WIDTH_PX / 2}
                y={0}
                width={MIN_LAP_WIDTH_PX}
                height={innerHeight}
                fill="transparent"
              />
            ))}
          </g>
        </svg>
      </div>

      {/* Readout below the chart rather than a floating tooltip: it never
          occludes the data, and it holds still enough to actually read. */}
      <div className="flex min-h-[2.25rem] flex-wrap items-baseline gap-x-5 gap-y-1 px-1 pt-1.5 font-mono text-micro">
        {hoverLap == null ? (
          <span className="text-ink/40">Hover the chart for a lap readout</span>
        ) : mode === "focus" ? (
          (() => {
            const alt = alternateByLap.get(hoverLap);
            const real = (realSeries[focusDriver ?? ""] ?? []).find((p) => p.lap === hoverLap);
            return (
              <>
                <span className="text-ink/60">LAP {hoverLap}</span>
                <span>real {real ? `${real.gap.toFixed(1)}s` : "—"}</span>
                <span className="text-annotation">alt {alt ? `${alt.gap.toFixed(1)}s` : "—"}</span>
                {alt && real && (
                  <span className="text-ink/60">
                    Δ {(alt.gap - real.gap >= 0 ? "+" : "") + (alt.gap - real.gap).toFixed(1)}s
                  </span>
                )}
                {alt && alt.clampedFraction > 0.5 && (
                  <span className="text-annotation">held up ({Math.round(alt.clampedFraction * 100)}% of runs)</span>
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

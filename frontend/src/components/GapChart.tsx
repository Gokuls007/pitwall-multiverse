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

import { useMemo, useRef, useState } from "react";
import { teamLineColor, teammateDash } from "../lib/teamColors";

export const MIN_LAP_WIDTH_PX = 14;

export type GapPoint = { lap: number; gap: number };
export type AlternatePoint = {
  lap: number;
  gap: number;
  paceLow: number;
  paceHigh: number;
  clampedFraction: number;
};

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
  /** Required in focus mode: the alternate timeline. */
  alternateSeries?: AlternatePoint[];
  divergenceLap?: number;
  safetyCarPeriods?: { kind: string; startLap: number; endLap: number }[];
  height?: number;
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
  divergenceLap,
  safetyCarPeriods = [],
  height = 340,
}: GapChartProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [hoverLap, setHoverLap] = useState<number | null>(null);

  // A minimum px-per-lap keeps pit ticks hittable and stint bars readable on
  // narrow screens; the container scrolls horizontally rather than letting
  // 70 laps compress into ~360px (~5px/lap, unusable). Because the shared
  // axis with StrategyTimeline must stay locked, this is ONE scroll
  // container in the parent — alignment holds by construction rather than by
  // synchronising two scroll offsets.
  const plotWidth = totalLaps * MIN_LAP_WIDTH_PX;
  const innerWidth = plotWidth;
  const innerHeight = height - MARGIN.top - MARGIN.bottom;

  const visibleDrivers = useMemo(
    () => (mode === "focus" && focusDriver ? [focusDriver] : Object.keys(realSeries).sort()),
    [mode, focusDriver, realSeries],
  );

  const yMax = useMemo(() => {
    let max = 0;
    for (const driver of visibleDrivers) {
      for (const p of realSeries[driver] ?? []) max = Math.max(max, p.gap);
    }
    if (mode === "focus" && alternateSeries) {
      for (const p of alternateSeries) max = Math.max(max, p.gap, p.paceHigh);
    }
    // Round up to a clean tick so the axis reads like a printed sheet.
    const step = max > 60 ? 20 : max > 20 ? 10 : 2;
    return Math.max(step, Math.ceil(max / step) * step);
  }, [visibleDrivers, realSeries, mode, alternateSeries]);

  const x = (lap: number) => ((lap - 1) / Math.max(1, totalLaps - 1)) * innerWidth;
  const y = (gap: number) => (gap / yMax) * innerHeight;

  const path = (points: { lap: number; gap: number }[]) =>
    points.length
      ? points.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.lap).toFixed(2)},${y(p.gap).toFixed(2)}`).join(" ")
      : "";

  const yTicks = useMemo(() => {
    const step = yMax > 60 ? 20 : yMax > 20 ? 10 : 2;
    const ticks: number[] = [];
    for (let v = 0; v <= yMax; v += step) ticks.push(v);
    return ticks;
  }, [yMax]);

  const xTicks = useMemo(() => {
    const step = totalLaps > 50 ? 10 : 5;
    const ticks: number[] = [1];
    for (let v = step; v <= totalLaps; v += step) ticks.push(v);
    return ticks;
  }, [totalLaps]);

  const laps = useMemo(
    () => Array.from({ length: totalLaps }, (_, i) => i + 1),
    [totalLaps],
  );

  function onMove(event: React.MouseEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - rect.left - MARGIN.left;
    const lap = Math.round((px / innerWidth) * (totalLaps - 1)) + 1;
    setHoverLap(lap >= 1 && lap <= totalLaps ? lap : null);
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
              alternate
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
            {mode === "focus" && alternateSeries && (
              <path
                d={`${path(alternateSeries.map((p) => ({ lap: p.lap, gap: p.paceHigh })))} ${alternateSeries
                  .slice()
                  .reverse()
                  .map((p) => `L${x(p.lap).toFixed(2)},${y(p.paceLow).toFixed(2)}`)
                  .join(" ")} Z`}
                fill="#A33A2E"
                fillOpacity={0.12}
                stroke="none"
              />
            )}

            {/* Real lines. Field mode: team colours + teammate dashes.
                Focus mode: ink, because it's being compared against oxide. */}
            {visibleDrivers.map((driver) => {
              const points = realSeries[driver] ?? [];
              const isFocus = mode === "focus";
              return (
                <path
                  key={driver}
                  d={path(points)}
                  fill="none"
                  stroke={isFocus ? "#1A1917" : teamLineColor(teamByDriver[driver] ?? "")}
                  strokeWidth={isFocus ? 1.75 : 1.25}
                  strokeDasharray={isFocus ? undefined : teammateDash(teammateIndex[driver] ?? 0)}
                  strokeOpacity={isFocus ? 1 : 0.85}
                />
              );
            })}

            {/* Alternate line, drawn over the band. */}
            {mode === "focus" && alternateSeries && (
              <path d={path(alternateSeries)} fill="none" stroke="#A33A2E" strokeWidth={1.75} />
            )}

            {/* Held-up ticks: traffic as a discrete EVENT, not diffused into
                the band. A mark here reads "he was stuck at this lap." */}
            {mode === "focus" &&
              alternateSeries
                ?.filter((p) => p.clampedFraction > 0.5)
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
            <text x={-8} y={-4} textAnchor="end" className="font-sans" fontSize={9} fill="#1A1917" opacity={0.6}>
              SEC
            </text>
            <text
              x={innerWidth}
              y={innerHeight + 16}
              textAnchor="end"
              className="font-sans"
              fontSize={9}
              fill="#1A1917"
              opacity={0.6}
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
                  <span key={e.d}>
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

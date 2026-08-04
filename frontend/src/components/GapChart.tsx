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
 *   - "focus": one driver, ink = real vs oxide = alternate, y floored by
 *     MIN_Y_EXTENT_S so a sub-second margin reads as small rather than being
 *     auto-scaled into a chasm.
 *
 * Two things this deliberately does NOT do:
 *
 *   1. It never draws a single uncertainty band over total gap. The backend
 *      separates pace variance from accumulated held-up ("stuck behind a car
 *      you can't pass") time, and merging them would silently report "how
 *      much traffic did he hit" as if it were "how unsure are we about his
 *      pace." The band is pace-only; traffic is discrete tick marks.
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
  axis: LapAxis;
  realSeries: Record<string, GapPoint[]>;
  teamByDriver: Record<string, string>;
  teammateIndex: Record<string, number>;
  mode: "field" | "focus";
  focusDriver?: string;
  /** Median of the ensemble — labelled as such, since it's no single universe. */
  alternateSeries?: AlternatePoint[];
  /** Individual seed traces, drawn faintly so the median isn't read as "the" answer. */
  seedSeries?: SeedTrace[];
  divergenceLap?: number;
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
  seedSeries,
  divergenceLap,
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

  const yMax = useMemo(() => {
    let max = 0;
    for (const driver of visibleDrivers) {
      for (const p of realSeries[driver] ?? []) if (inRange(p.lap)) max = Math.max(max, p.gap);
    }
    if (mode === "focus" && alternateSeries) {
      for (const p of alternateSeries) if (inRange(p.lap)) max = Math.max(max, p.gap, p.paceHigh);
    }
    max = Math.max(max, MIN_Y_EXTENT_S);
    const step = max > 60 ? 20 : max > 20 ? 10 : max > 8 ? 2 : 1;
    return Math.max(step, Math.ceil(max / step) * step);
  }, [visibleDrivers, realSeries, mode, alternateSeries, firstLap, lastLap]);

  const y = (gap: number) => (gap / yMax) * innerHeight;

  const path = (points: GapPoint[]) => {
    const clipped = points.filter((p) => inRange(p.lap));
    return clipped.length
      ? clipped.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.lap).toFixed(2)},${y(p.gap).toFixed(2)}`).join(" ")
      : "";
  };

  // The alternate timeline is drawn from the last *shared* lap onward. Before
  // the fork it is reality copied verbatim (spec 9.1 step 4), so drawing all
  // of it is redundant and actively misleading — the oxide line sits exactly
  // on the ink one and "real" appears missing from its own chart. But starting
  // at the divergence lap itself would leave the stroke floating whenever the
  // two values differ there (they coincide in the current demo only because
  // VER leads in both timelines — luck, not structure). Anchoring one lap
  // earlier uses a lap that genuinely belongs to BOTH timelines.
  const branchAnchorLap = divergenceLap != null ? divergenceLap - 1 : null;
  const alternateInRange = useMemo(
    () =>
      (alternateSeries ?? []).filter(
        (p) => inRange(p.lap) && (branchAnchorLap == null || p.lap >= branchAnchorLap),
      ),
    [alternateSeries, firstLap, lastLap, branchAnchorLap],
  );

  const yTicks = useMemo(() => {
    const step = yMax > 60 ? 20 : yMax > 20 ? 10 : yMax > 8 ? 2 : 1;
    const ticks: number[] = [];
    for (let v = 0; v <= yMax; v += step) ticks.push(v);
    return ticks;
  }, [yMax]);

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
              alternate <span className="text-ink/45">median of {seedSeries?.length ?? 0} runs</span>
            </span>
          </div>
        )}
      </div>

      <svg
        width={plotWidth + AXIS_MARGIN.left + AXIS_MARGIN.right}
        height={height}
        role="img"
        aria-label={
          mode === "focus"
            ? `Gap to leader for ${focusDriver}, real timeline against the alternate timeline`
            : "Gap to leader for every driver, as the race happened"
        }
        onMouseMove={onMove}
        onMouseLeave={() => onHoverLap?.(null)}
        className="block"
      >
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

          {/* Pace-only band. Means ONE thing: uncertainty about pace. */}
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

          {/* Real seed traces (spec 6.10): the spread, so the median isn't
              read as the single answer. */}
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

          {visibleDrivers.map((driver) => {
            const isFocus = mode === "focus";
            const isHighlighted = highlighted === driver;
            const dimmed = !isFocus && highlighted != null && !isHighlighted;
            return (
              <path
                key={driver}
                d={path(realSeries[driver] ?? [])}
                fill="none"
                stroke={isFocus ? "#1A1917" : teamLineColor(teamByDriver[driver] ?? "")}
                strokeWidth={isFocus ? 1.75 : isHighlighted ? 2 : 1}
                strokeDasharray={isFocus ? undefined : teammateDash(teammateIndex[driver] ?? 0)}
                strokeOpacity={isFocus ? 1 : dimmed ? 0.18 : isHighlighted ? 1 : 0.5}
              />
            );
          })}

          {mode === "focus" && alternateInRange.length > 0 && (
            <path d={path(alternateInRange)} fill="none" stroke="#A33A2E" strokeWidth={1.75} />
          )}

          {/* Branch node: without it the two strokes read as a break in one
              line rather than one history splitting into two. Paper-filled
              with an ink stroke so it reads as a junction on the shared line,
              not a data point owned by either timeline. */}
          {mode === "focus" && branchAnchorLap != null && inRange(branchAnchorLap) && (
            <circle
              cx={x(branchAnchorLap)}
              cy={y((realSeries[focusDriver ?? ""] ?? []).find((p) => p.lap === branchAnchorLap)?.gap ?? 0)}
              r={3}
              fill="#F4F1EA"
              stroke="#1A1917"
              strokeWidth={1.25}
            />
          )}

          {/* Held-up ticks: traffic as a discrete EVENT, not diffused band. */}
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

          {hoverLap != null && inRange(hoverLap) && (
            <line x1={x(hoverLap)} x2={x(hoverLap)} y1={0} y2={innerHeight} stroke="#1A1917" strokeWidth={0.5} />
          )}

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
        ) : mode === "focus" ? (
          (() => {
            const alt = alternateByLap.get(hoverLap);
            const real = (realSeries[focusDriver ?? ""] ?? []).find((p) => p.lap === hoverLap);
            const postFork = divergenceLap == null || hoverLap >= divergenceLap;
            return (
              <>
                <span className="text-ink/60">LAP {hoverLap}</span>
                <span>real {real ? `${real.gap.toFixed(1)}s` : "—"}</span>
                {postFork ? (
                  <>
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
                ) : (
                  <span className="text-ink/40">before the fork — one history</span>
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

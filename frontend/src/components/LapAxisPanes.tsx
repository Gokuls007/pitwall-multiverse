/**
 * Owns the lap axis shared by GapChart and StrategyTimeline.
 *
 * This exists so axis alignment is guaranteed *by construction* rather than
 * by synchronising two scroll offsets: there is exactly one scroll container
 * and one x-scale, and both panes render into it at the same width. The
 * design plan's central analytical claim is that you can drop your eye from
 * "the gap did this at lap 50" to "he was on 23-lap-old softs at lap 50" —
 * that only holds if the two panes cannot drift apart, which two synchronised
 * scrollers eventually would.
 *
 * MIN_LAP_WIDTH_PX is a floor, not a fixed size: on a narrow viewport it
 * forces horizontal scroll rather than compressing 70 laps into ~5px each
 * (unusable, and pit ticks become unhittable); on a wide one the panes fill
 * the available space.
 */

import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

export const MIN_LAP_WIDTH_PX = 14;
export const AXIS_MARGIN = { left: 52, right: 16 };

export type LapAxis = {
  plotWidth: number;
  firstLap: number;
  lastLap: number;
  lapSpan: number;
  /** Pixel x for a lap number, relative to the plot area's left edge. */
  x: (lap: number) => number;
  inRange: (lap: number) => boolean;
};

export type LapAxisPanesProps = {
  lapRange: [number, number];
  children: (axis: LapAxis) => ReactNode;
};

export default function LapAxisPanes({ lapRange, children }: LapAxisPanesProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [availableWidth, setAvailableWidth] = useState(0);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => setAvailableWidth(el.clientWidth);
    measure();
    // ResizeObserver is the right tool but isn't universally present (jsdom
    // has none). Degrade to a window listener rather than throwing.
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const [firstLap, lastLap] = lapRange;
  const lapSpan = Math.max(1, lastLap - firstLap);
  const minPlotWidth = (lapSpan + 1) * MIN_LAP_WIDTH_PX;
  // The -2 keeps content a hair inside the container so sub-pixel rounding
  // doesn't produce a scrollbar on panes that already fit.
  const plotWidth = Math.max(minPlotWidth, availableWidth - AXIS_MARGIN.left - AXIS_MARGIN.right - 2);

  const axis: LapAxis = {
    plotWidth,
    firstLap,
    lastLap,
    lapSpan,
    x: (lap: number) => ((lap - firstLap) / lapSpan) * plotWidth,
    inRange: (lap: number) => lap >= firstLap && lap <= lastLap,
  };

  return (
    <div ref={scrollRef} className="overflow-x-auto" data-testid="lap-axis-scroll">
      <div style={{ width: plotWidth + AXIS_MARGIN.left + AXIS_MARGIN.right }}>{children(axis)}</div>
    </div>
  );
}

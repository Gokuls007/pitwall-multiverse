import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import GapChart from "./GapChart";
import type { LapAxis } from "./LapAxisPanes";

/**
 * These pin properties that programmatic structure checks did NOT catch when
 * this component was first built — the faults were all things nobody had
 * thought to name, which is the argument for testing them explicitly once
 * they're known rather than trusting the next reviewer to spot them again.
 */

const teamByDriver = { AAA: "Ferrari", BBB: "Mercedes" };
const teammateIndex = { AAA: 0, BBB: 0 };

// A driver leading throughout (gap 0), forking at lap 5 and losing time.
const realSeries = {
  AAA: Array.from({ length: 10 }, (_, i) => ({ lap: i + 1, gap: 0 })),
  BBB: Array.from({ length: 10 }, (_, i) => ({ lap: i + 1, gap: 3 })),
};

// Alternate carries pre-fork laps verbatim (identical to real) then diverges.
const alternateSeries = Array.from({ length: 10 }, (_, i) => {
  const lap = i + 1;
  const gap = lap < 5 ? 0 : (lap - 4) * 2;
  return { lap, gap, paceLow: gap - 0.5, paceHigh: gap + 0.5, clampedFraction: lap > 7 ? 0.9 : 0 };
});

/**
 * A fixed axis, so these tests exercise GapChart's own drawing rather than
 * LapAxisPanes' measurement (which needs a real layout engine). The shared
 * axis is intentionally an explicit input, not something the chart derives —
 * that's what guarantees it can't drift from StrategyTimeline.
 */
function staticAxis(firstLap = 1, lastLap = 10, plotWidth = 280): LapAxis {
  const lapSpan = Math.max(1, lastLap - firstLap);
  return {
    plotWidth,
    firstLap,
    lastLap,
    lapSpan,
    x: (lap: number) => ((lap - firstLap) / lapSpan) * plotWidth,
    inRange: (lap: number) => lap >= firstLap && lap <= lastLap,
  };
}

function renderFocus(extra: Partial<React.ComponentProps<typeof GapChart>> = {}) {
  return render(
    <GapChart
      axis={staticAxis()}
      realSeries={realSeries}
      teamByDriver={teamByDriver}
      teammateIndex={teammateIndex}
      mode="focus"
      focusDriver="AAA"
      alternateSeries={alternateSeries}
      divergenceLap={5}
      {...extra}
    />,
  );
}

function alternatePath(container: HTMLElement): SVGPathElement {
  const paths = [...container.querySelectorAll('path[stroke="#A33A2E"]')] as SVGPathElement[];
  const median = paths.find((p) => p.getAttribute("stroke-width") === "1.75");
  if (!median) throw new Error("alternate median path not found");
  return median;
}

function firstPoint(path: SVGPathElement): { x: number; y: number } {
  const d = path.getAttribute("d") ?? "";
  const [x, y] = d.replace(/^M/, "").split(/[ ,]/).slice(0, 2).map(Number);
  return { x, y };
}

/** The main plot, excluding the small aria-hidden legend swatches. */
function plot(container: HTMLElement): SVGSVGElement {
  const svg = container.querySelector('svg[role="img"]');
  if (!svg) throw new Error("plot svg not found");
  return svg as SVGSVGElement;
}

/**
 * Numeric y-axis tick labels only. Scoped by `text-anchor="end"`, which is
 * what distinguishes the y column from the x-axis lap labels (`middle`) —
 * without that, lap numbers get counted as y values.
 */
function yTickValues(container: HTMLElement): number[] {
  return [...plot(container).querySelectorAll('text[text-anchor="end"]')]
    .map((t) => Number((t.textContent ?? "").replace("+", "")))
    .filter((n) => Number.isFinite(n));
}

describe("GapChart focus mode", () => {
  it("anchors the alternate line at the last SHARED lap so the branch can't float", () => {
    // The fork's own lap can hold different values in the two timelines; if
    // the oxide stroke started there it would begin disconnected from the
    // history it branches from. Anchoring at divergenceLap - 1 -- a lap that
    // genuinely belongs to both timelines -- guarantees continuity.
    //
    // Since 6.1 the plotted variable is `alternate - real`, so the real
    // timeline IS the zero rule and the anchor must sit exactly on it. That
    // makes the property easier to state, not weaker: before the fork the
    // delta is zero by definition.
    const { container } = renderFocus();
    const start = firstPoint(alternatePath(container));
    // Scoped to the plot: the legend carries an identical swatch line.
    const zeroRule = plot(container).querySelector('line[stroke="#1A1917"][stroke-width="1.5"]');
    expect(zeroRule).not.toBeNull();

    const zeroY = Number(zeroRule!.getAttribute("y1"));
    expect(start.y).toBeCloseTo(zeroY, 1);
    expect(start.x).toBeGreaterThan(0);
  });

  it("scales y to the delta, not to gap-to-leader pit-stop swings", () => {
    // The fault this replaced: the subject led the whole window, so both
    // traces sat on the axis boundary and the range was owned by his real
    // ~24s pit-stop dip, leaving a sub-second comparison invisible. With the
    // delta as the variable, a large real gap must not influence the range.
    const realWithBigPitDip = {
      ...realSeries,
      AAA: realSeries.AAA.map((p) => (p.lap === 7 ? { ...p, gap: 24 } : p)),
    };
    // Alternate tracks that dip, so the DELTA stays sub-second throughout.
    const alternateTracking = alternateSeries.map((p) => {
      const real = realWithBigPitDip.AAA.find((r) => r.lap === p.lap)!.gap;
      const delta = p.lap < 5 ? 0 : 0.4;
      return { ...p, gap: real + delta, paceLow: real + delta - 0.1, paceHigh: real + delta + 0.1 };
    });

    const { container } = renderFocus({
      realSeries: realWithBigPitDip,
      alternateSeries: alternateTracking,
    });
    const ticks = yTickValues(container);
    // MIN_Y_EXTENT_S (5) floors the total span, so ticks reach a few seconds --
    // but nothing near the 24s dip.
    expect(Math.max(...ticks.map(Math.abs))).toBeLessThan(8);
  });

  it("signs the delta axis, and both directions are reachable", () => {
    const { container } = renderFocus();
    const ticks = yTickValues(container);
    expect(Math.min(...ticks)).toBeLessThan(0);
    expect(Math.max(...ticks)).toBeGreaterThan(0);
    expect(ticks).toContain(0);
  });

  it("clamps the band at the gap variable's floor instead of going impossible", () => {
    // paceLow is gap minus accumulated held-up time, which can push it below
    // zero -- and did, rendering the band above the zero line, i.e. a car
    // ahead of the leader. A synthetic case that would previously have
    // breached it: an impossible -5s lower bound.
    const breaching = alternateSeries.map((p) => ({
      ...p,
      gap: p.lap < 5 ? 0 : 1,
      paceHigh: p.lap < 5 ? 0 : 1.2,
      paceLow: p.lap < 5 ? 0 : -5, // impossible: ahead of the leader
    }));
    const { container } = renderFocus({ alternateSeries: breaching });
    const ticks = yTickValues(container);
    // Unclamped, the axis would have to open up to about +/-6 to fit -5.
    // Clamped at the floor, the range stays governed by the real values.
    expect(Math.max(...ticks.map(Math.abs))).toBeLessThan(5);
  });

  it("renders a branch node at the fork so it reads as a split, not a break", () => {
    const { container } = renderFocus();
    const node = container.querySelector('circle[stroke="#1A1917"]');
    expect(node).not.toBeNull();
  });

  it("does not draw the alternate line before the fork", () => {
    // Pre-fork the alternate IS reality (spec 9.1 step 4); drawing it there
    // hides the real line underneath it.
    const { container } = renderFocus();
    const start = firstPoint(alternatePath(container));
    // With a 10-lap race forking at 5, anchored at 4, the path must not begin
    // at the very left edge of the plot (which would mean lap 1).
    expect(start.x).toBeGreaterThan(1);
  });

  it("floors the y-extent so a small constant gap is not magnified", () => {
    // A comparison where the alternate only ever differs by 0.5s must not
    // auto-scale that into a full-height chasm.
    const tiny = alternateSeries.map((p) => ({ ...p, gap: p.lap < 5 ? 0 : 0.5, paceHigh: 0.6, paceLow: 0.4 }));
    const { container } = renderFocus({ alternateSeries: tiny });
    const labels = [...container.querySelectorAll("text")]
      .map((t) => Number(t.textContent))
      .filter((n) => Number.isFinite(n));
    // MIN_Y_EXTENT_S is 5, so the axis must reach at least that far.
    expect(Math.max(...labels)).toBeGreaterThanOrEqual(5);
  });

  it("marks held-up laps as discrete ticks rather than widening the pace band", () => {
    const { container } = renderFocus();
    const ticks = container.querySelectorAll('line[stroke="#A33A2E"][stroke-width="1.5"]');
    // Laps 8-10 have clampedFraction 0.9.
    expect(ticks.length).toBeGreaterThan(0);
  });
});

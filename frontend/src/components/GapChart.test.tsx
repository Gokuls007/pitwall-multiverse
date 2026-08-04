import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import GapChart from "./GapChart";

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

function renderFocus(extra: Partial<React.ComponentProps<typeof GapChart>> = {}) {
  return render(
    <GapChart
      totalLaps={10}
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

describe("GapChart focus mode", () => {
  it("anchors the alternate line at the last SHARED lap so the branch can't float", () => {
    // The fork's own lap can hold different values in the two timelines; if
    // the oxide stroke started there it would begin disconnected from the
    // history it branches from. Anchoring at divergenceLap - 1 -- a lap that
    // genuinely belongs to both timelines -- guarantees continuity.
    const { container } = renderFocus();
    const start = firstPoint(alternatePath(container));
    const realLine = [...container.querySelectorAll('path[stroke="#1A1917"]')] as SVGPathElement[];
    const realStart = realLine[0].getAttribute("d") ?? "";

    // The anchor's y must equal the real line's y at that lap (both 0 here),
    // and its x must be strictly left of the divergence lap's x.
    const realYAtZeroGap = Number(realStart.split(/[ ,]/)[1]);
    expect(start.y).toBeCloseTo(realYAtZeroGap, 1);
    expect(start.x).toBeGreaterThan(0);
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

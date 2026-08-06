/**
 * LapPlayhead — Phase 6.4. A scrubber across the shared lap axis.
 *
 * The pit wall is a timing screen where the order shifts under you, and this is
 * what turns the interface into that. It renders into the same `LapAxisPanes`
 * axis as the chart and the stint bars, so the playhead, the traces it reveals
 * and the stints it reveals are all locked to one x-scale by construction.
 *
 * Two things worth naming:
 *
 * 1. **Position at a lap is read, never interpolated.** The component takes a
 *    lap number and consumers look that lap up in stored per-lap state. Sliding
 *    a position between laps would invent an ordering the model never produced —
 *    the same failure class as the derived tyre age that Phase 5 had to retract.
 *    So the playhead only ever sits on integer laps, and there is deliberately no
 *    sub-lap resolution to interpolate within.
 *
 * 2. **Playback is off under `prefers-reduced-motion`.** Not slowed — removed,
 *    with the control gone rather than present and inert, and the playhead still
 *    fully usable by drag and keyboard. An auto-advancing playhead is exactly the
 *    kind of unrequested motion that setting exists to refuse.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { AXIS_MARGIN, type LapAxis } from "./LapAxisPanes";

/** Laps per second during playback. One lap per ~450ms reads as a race unfolding. */
const PLAYBACK_LAPS_PER_SECOND = 2.2;

const STRIP_HEIGHT = 26;

export type LapPlayheadProps = {
  axis: LapAxis;
  /** Current lap, or null when the playhead is parked and the full race is shown. */
  lap: number | null;
  onLap: (lap: number | null) => void;
  /** Laps that carry a pit stop for the focus driver, marked on the rail. */
  markedLaps?: { lap: number; kind: "real" | "alternate" }[];
};

/** True when the user has asked for reduced motion. */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export default function LapPlayhead({ axis, lap, onLap, markedLaps = [] }: LapPlayheadProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragging = useRef(false);
  const [playing, setPlaying] = useState(false);
  const reduced = prefersReducedMotion();

  const current = lap ?? axis.lastLap;

  const lapFromClientX = useCallback(
    (clientX: number) => {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return null;
      const px = clientX - rect.left - AXIS_MARGIN.left;
      const raw = Math.round((px / axis.plotWidth) * axis.lapSpan) + axis.firstLap;
      return Math.min(axis.lastLap, Math.max(axis.firstLap, raw));
    },
    [axis],
  );

  /**
   * Advance one lap per tick while playing, as a chain of timeouts rather than an
   * interval. The effect depends on `current`, so an interval would be torn down
   * and recreated on every advance anyway — and a self-rescheduling timeout makes
   * the stop condition explicit. Stops at the end rather than looping: a loop
   * would restart the race without being asked, and the finish is the point.
   */
  useEffect(() => {
    if (!playing || reduced) return;
    const id = window.setTimeout(() => {
      if (current >= axis.lastLap) {
        setPlaying(false);
        return;
      }
      onLap(current + 1);
    }, 1000 / PLAYBACK_LAPS_PER_SECOND);
    return () => window.clearTimeout(id);
  }, [playing, reduced, current, axis.lastLap, onLap]);

  function step(count: number) {
    const next = Math.min(axis.lastLap, Math.max(axis.firstLap, current + count));
    onLap(next);
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1">
        <span className="label-caps">Lap</span>
        {/* Playback is absent, not disabled, under reduced motion. */}
        {!reduced && (
          <button
            onClick={() => {
              if (current >= axis.lastLap) onLap(axis.firstLap);
              setPlaying((v) => !v);
            }}
            aria-pressed={playing}
            className="border border-rule bg-paper px-2 py-0.5 font-sans text-micro uppercase tracking-[0.08em] text-ink/70 hover:border-ink/50"
          >
            {playing ? "Pause" : "Play"}
          </button>
        )}
        <output className="w-8 font-mono text-sm">{lap ?? "—"}</output>
        {lap != null && (
          <button
            onClick={() => {
              setPlaying(false);
              onLap(null);
            }}
            className="border border-rule bg-paper px-2 py-0.5 font-sans text-micro uppercase tracking-[0.08em] text-ink/70 hover:border-ink/50"
          >
            Whole race
          </button>
        )}
        <span className="font-mono text-micro text-ink/45">
          {lap == null
            ? "showing the full race — scrub to see the order at a lap"
            : "order below is the order at this lap, read from stored state"}
        </span>
      </div>

      <svg
        ref={svgRef}
        width={axis.plotWidth + AXIS_MARGIN.left + AXIS_MARGIN.right}
        height={STRIP_HEIGHT}
        className="block"
        role="presentation"
      >
        <g transform={`translate(${AXIS_MARGIN.left},0)`}>
          {/* The rail. Full width, because the playhead can go anywhere in the
              displayed window — unlike the pit drag, which is bounded by the
              candidates the engine accepted. */}
          <line
            x1={0}
            x2={axis.plotWidth}
            y1={STRIP_HEIGHT / 2}
            y2={STRIP_HEIGHT / 2}
            stroke="#C9C3B6"
            strokeWidth={3}
          />
          {lap != null && (
            <line
              x1={0}
              x2={axis.x(current)}
              y1={STRIP_HEIGHT / 2}
              y2={STRIP_HEIGHT / 2}
              stroke="#1A1917"
              strokeOpacity={0.45}
              strokeWidth={3}
            />
          )}

          {/* Pit stops on the rail, so scrubbing has landmarks. */}
          {markedLaps
            .filter((mark) => axis.inRange(mark.lap))
            .map((mark) => (
              <line
                key={`${mark.kind}-${mark.lap}`}
                x1={axis.x(mark.lap)}
                x2={axis.x(mark.lap)}
                y1={STRIP_HEIGHT / 2 - 5}
                y2={STRIP_HEIGHT / 2 + 5}
                stroke={mark.kind === "alternate" ? "#A33A2E" : "#1A1917"}
                strokeWidth={1}
                strokeOpacity={0.55}
              />
            ))}

          <g
            role="slider"
            tabIndex={0}
            aria-label="Lap playhead"
            aria-valuemin={axis.firstLap}
            aria-valuemax={axis.lastLap}
            aria-valuenow={current}
            aria-valuetext={lap == null ? "whole race" : `lap ${current}`}
            aria-orientation="horizontal"
            data-testid="playhead"
            className="cursor-ew-resize outline-none [&:focus-visible>circle]:stroke-annotation"
            style={{ touchAction: "none" }}
            onPointerDown={(event) => {
              event.currentTarget.setPointerCapture(event.pointerId);
              event.preventDefault();
              dragging.current = true;
              setPlaying(false);
              const next = lapFromClientX(event.clientX);
              if (next != null) onLap(next);
            }}
            onPointerMove={(event) => {
              if (!dragging.current) return;
              const next = lapFromClientX(event.clientX);
              if (next != null && next !== current) onLap(next);
            }}
            onPointerUp={(event) => {
              dragging.current = false;
              if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                event.currentTarget.releasePointerCapture(event.pointerId);
              }
            }}
            onLostPointerCapture={() => {
              dragging.current = false;
            }}
            onKeyDown={(event) => {
              // Same conventions as the pit drag (spec 6.4).
              let handled = true;
              if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
                step(event.shiftKey ? -5 : -1);
              } else if (event.key === "ArrowRight" || event.key === "ArrowUp") {
                step(event.shiftKey ? 5 : 1);
              } else if (event.key === "Home") {
                onLap(axis.firstLap);
              } else if (event.key === "End") {
                onLap(axis.lastLap);
              } else if (event.key === " " && !reduced) {
                setPlaying((v) => !v);
              } else {
                handled = false;
              }
              if (handled) {
                event.preventDefault();
                if (event.key !== " ") setPlaying(false);
              }
            }}
          >
            <rect
              x={axis.x(current) - 22}
              y={0}
              width={44}
              height={STRIP_HEIGHT}
              fill="transparent"
            />
            <circle
              cx={axis.x(current)}
              cy={STRIP_HEIGHT / 2}
              r={5}
              fill="#F4F1EA"
              stroke="#1A1917"
              strokeWidth={1.5}
            />
          </g>
        </g>
      </svg>
    </div>
  );
}

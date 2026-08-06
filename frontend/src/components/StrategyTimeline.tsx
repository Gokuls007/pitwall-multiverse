/**
 * StrategyTimeline — horizontal stint bars per driver, segmented by stint and
 * coloured by compound, pit stops marked (spec 11.2). Renders into the shared
 * lap axis owned by `LapAxisPanes`, directly under GapChart, so the eye drops
 * vertically from "the gap did this at lap N" to "he was on this tyre, this
 * old, at lap N".
 *
 * Three decisions worth naming:
 *
 * 1. Compound colour is a luminance ramp in ink tints, not the broadcast
 *    soft-red/medium-yellow/hard-white convention — red is reserved for the
 *    counterfactual and white is invisible on cream. See lib/compounds.
 *
 * 2. In focus mode the driver gets TWO bars, real and alternate. With a
 *    counterfactual active the driver has two stint structures (real stop at
 *    67, alternate at 50), and a single bar would contradict the chart
 *    directly above it. Two bars also make the decision legible *as* a
 *    decision — the difference between the rows is the change.
 *
 * 3. The portion of a stint running past the driver's own observed tyre life
 *    is hatched in `--caution`. This is where the epistemics belong: the
 *    stint bar is the surface the user makes the choice on, so "the last 17
 *    laps of this stint are beyond anything this driver actually ran" should
 *    be visible here rather than in DECISIONS.md. The numbers come from
 *    `counterfactual.strategy.extrapolation_by_lap`.
 */

import { useCallback, useRef } from "react";
import { compoundFill, compoundInitial, compoundLabelColor } from "../lib/compounds";
import { AXIS_MARGIN, type LapAxis } from "./LapAxisPanes";

/**
 * Phase 6.3: the pit stop is the control.
 *
 * `validLaps` must be sorted ascending and must contain only laps the engine
 * actually accepted — the drag snaps to the nearest member rather than to any
 * integer, because the discovered valid range has holes (a candidate that would
 * push a stint past the following real stop is refused).
 */
export type PitDrag = {
  /** Index of the row whose leading tick is draggable. */
  rowIndex: number;
  /**
   * The decision's value: the lap the driver enters the pit lane on. This is
   * what `validLaps` contains and what `onChange` reports.
   */
  lap: number;
  /**
   * Where the bar actually draws the stint boundary — the out-lap, one after
   * `lap`. Kept separate rather than derived, because conflating the two is an
   * off-by-one the user feels directly: the grip would sit one lap away from the
   * cursor for the whole drag.
   */
  tickLap: number;
  /** The real pit lap — the zero-extrapolation point, marked permanently. */
  realLap: number;
  validLaps: number[];
  /** Read by a screen reader in place of the bare number. */
  valueText: string;
  label: string;
  onChange: (lap: number) => void;
  /**
   * Called on pointerdown/pointerup so the page can hold geometry still for the
   * duration of a drag. Without it the lap window is recomputed from the new
   * divergence lap on every step, the x-scale shifts under the cursor, and the
   * grip slides away from the pointer — the control reads as fighting the user.
   */
  onDragStateChange?: (dragging: boolean) => void;
};

/** Nearest valid lap to a raw lap, by binary search over the sorted array. */
function snapToValid(validLaps: number[], target: number): number {
  if (validLaps.length === 0) return target;
  let lo = 0;
  let hi = validLaps.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (validLaps[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  const above = validLaps[lo];
  const below = validLaps[Math.max(0, lo - 1)];
  return Math.abs(above - target) < Math.abs(target - below) ? above : below;
}

/** Step `count` positions along the valid laps from the current one. */
function stepValid(validLaps: number[], current: number, count: number): number {
  const i = validLaps.indexOf(current);
  if (i < 0) return snapToValid(validLaps, current + count);
  return validLaps[Math.min(validLaps.length - 1, Math.max(0, i + count))];
}

/** Width of the invisible pointer target around the 1.25px tick. */
const TICK_HIT_WIDTH = 44;

export type StintRun = {
  compound: string;
  startLap: number;
  endLap: number;
  startTyreAge: number;
  endTyreAge: number;
  extrapolatedLaps: number;
  maxExcessLaps: number;
  firstExtrapolatedLap: number | null;
};

export type StrategyTimelineProps = {
  axis: LapAxis;
  /** Rows to draw, top to bottom. */
  rows: { label: string; sublabel?: string; stints: StintRun[]; isAlternate?: boolean }[];
  hoverLap?: number | null;
  onHoverLap?: (lap: number | null) => void;
  /** When present, that row's leading pit tick becomes the draggable control. */
  pitDrag?: PitDrag;
};

const ROW_HEIGHT = 26;
const BAR_HEIGHT = 16;
const TOP_PAD = 8;

export default function StrategyTimeline({
  axis,
  rows,
  hoverLap,
  onHoverLap,
  pitDrag,
}: StrategyTimelineProps) {
  const height = TOP_PAD + rows.length * ROW_HEIGHT + 6;
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragging = useRef(false);

  /** clientX -> lap, through the *same* axis scale the chart above uses. */
  const lapFromClientX = useCallback(
    (clientX: number) => {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return null;
      const px = clientX - rect.left - AXIS_MARGIN.left;
      return Math.round((px / axis.plotWidth) * axis.lapSpan) + axis.firstLap;
    },
    [axis],
  );

  const moveTo = useCallback(
    (clientX: number) => {
      if (!pitDrag) return;
      const raw = lapFromClientX(clientX);
      if (raw == null) return;
      // The pointer is over bar coordinates (where the boundary is drawn); the
      // candidate set is in decision coordinates (the in-lap). Shift by the
      // offset between them so the grip tracks the cursor exactly.
      const next = snapToValid(pitDrag.validLaps, raw - (pitDrag.tickLap - pitDrag.lap));
      // Guard against re-dispatching the same lap: pointermove fires at pointer
      // frequency and every change costs a full redraw of chart, bars, hatch,
      // sentence and distribution.
      if (next !== pitDrag.lap) pitDrag.onChange(next);
    },
    [pitDrag, lapFromClientX],
  );

  function onMove(event: React.MouseEvent<SVGSVGElement>) {
    if (!onHoverLap) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - rect.left - AXIS_MARGIN.left;
    const lap = Math.round((px / axis.plotWidth) * axis.lapSpan) + axis.firstLap;
    onHoverLap(axis.inRange(lap) ? lap : null);
  }

  return (
    <figure className="m-0">
      <figcaption className="label-caps px-1 pb-1">Strategy — stint, compound, tyre age</figcaption>
      <svg
        ref={svgRef}
        width={axis.plotWidth + AXIS_MARGIN.left + AXIS_MARGIN.right}
        height={height}
        role="img"
        aria-label="Stint and compound timeline per driver, aligned to the gap chart's lap axis"
        onMouseMove={onMove}
        onMouseLeave={() => onHoverLap?.(null)}
        className="block"
      >
        <defs>
          {/* Beyond-evidence hatch. Deliberately a pattern rather than a
              solid tint: it has to read as a qualifier laid *over* the
              compound rather than as a different compound. */}
          <pattern id="beyond-evidence" width="5" height="5" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
            <line x1="0" y1="0" x2="0" y2="5" stroke="#A8761F" strokeWidth="2" />
          </pattern>
        </defs>

        <g transform={`translate(${AXIS_MARGIN.left},${TOP_PAD})`}>
          {hoverLap != null && axis.inRange(hoverLap) && (
            <line
              x1={axis.x(hoverLap)}
              x2={axis.x(hoverLap)}
              y1={-TOP_PAD}
              y2={rows.length * ROW_HEIGHT}
              stroke="#1A1917"
              strokeWidth={0.5}
            />
          )}

          {rows.map((row, rowIndex) => {
            const y = rowIndex * ROW_HEIGHT;
            return (
              <g key={`${row.label}-${rowIndex}`}>
                {/* Row label sits in the sticky left gutter area. */}
                <text
                  x={-8}
                  y={y + BAR_HEIGHT / 2 + 4}
                  textAnchor="end"
                  className="font-mono"
                  fontSize={10}
                  fill={row.isAlternate ? "#A33A2E" : "#1A1917"}
                >
                  {row.label}
                </text>

                {row.stints.map((stint) => {
                  const x0 = axis.x(Math.max(stint.startLap, axis.firstLap));
                  const x1 = axis.x(Math.min(stint.endLap, axis.lastLap));
                  if (stint.endLap < axis.firstLap || stint.startLap > axis.lastLap) return null;
                  const width = Math.max(1, x1 - x0);
                  const fill = compoundFill(stint.compound);

                  // Where this stint crosses from evidence into extrapolation.
                  const beyondStart =
                    stint.firstExtrapolatedLap != null
                      ? axis.x(Math.max(stint.firstExtrapolatedLap, axis.firstLap))
                      : null;

                  return (
                    <g key={`${stint.compound}-${stint.startLap}`}>
                      <rect x={x0} y={y} width={width} height={BAR_HEIGHT} fill={fill} />
                      {beyondStart != null && (
                        <rect
                          x={beyondStart}
                          y={y}
                          width={Math.max(1, x1 - beyondStart)}
                          height={BAR_HEIGHT}
                          fill="url(#beyond-evidence)"
                          opacity={0.85}
                        />
                      )}
                      {/* Compound tag + closing tyre age, when there's room. */}
                      {width > 34 && (
                        <text
                          x={x0 + 4}
                          y={y + BAR_HEIGHT / 2 + 3.5}
                          className="font-mono"
                          fontSize={9}
                          fill={compoundLabelColor(stint.compound)}
                        >
                          {compoundInitial(stint.compound)}
                          {width > 62 ? ` ${stint.endTyreAge}` : ""}
                        </text>
                      )}
                      {/* Pit stop: a tick at the stint boundary. On the row
                          nominated by `pitDrag`, the tick for the stop being
                          moved is drawn by the drag handle below instead, so it
                          is suppressed here rather than drawn twice. */}
                      {stint.startLap > axis.firstLap &&
                        !(
                          pitDrag != null &&
                          rowIndex === pitDrag.rowIndex &&
                          stint.startLap === pitDrag.tickLap
                        ) && (
                          <line
                            x1={x0}
                            x2={x0}
                            y1={y - 2}
                            y2={y + BAR_HEIGHT + 2}
                            stroke={row.isAlternate ? "#A33A2E" : "#1A1917"}
                            strokeWidth={1.25}
                          />
                        )}
                    </g>
                  );
                })}
              </g>
            );
          })}

          {/* --- Phase 6.3: the real-lap notch and the drag handle --- */}
          {pitDrag && (
            <>
              {/* Persistent marker at the REAL lap, drawn whether or not the tick
                  is anywhere near it. This is the zero-extrapolation point:
                  always being able to see where you departed from the evidence,
                  including mid-drag, is the epistemic frame made physical. A
                  notch, not a snap target — magnetic snapping to it would feel
                  like the control resisting the user. */}
              {axis.inRange(pitDrag.realLap) && (
                <g aria-hidden="true">
                  <line
                    x1={axis.x(pitDrag.realLap)}
                    x2={axis.x(pitDrag.realLap)}
                    y1={pitDrag.rowIndex * ROW_HEIGHT - 5}
                    y2={pitDrag.rowIndex * ROW_HEIGHT + BAR_HEIGHT + 5}
                    stroke="#1A1917"
                    strokeWidth={0.75}
                    strokeOpacity={0.35}
                    strokeDasharray="2 2"
                  />
                  <text
                    x={axis.x(pitDrag.realLap)}
                    y={pitDrag.rowIndex * ROW_HEIGHT + BAR_HEIGHT + 14}
                    textAnchor="middle"
                    className="font-mono"
                    fontSize={8}
                    fill="#1A1917"
                    opacity={0.45}
                  >
                    real
                  </text>
                </g>
              )}

              {axis.inRange(pitDrag.tickLap) && (
                <g
                  role="slider"
                  tabIndex={0}
                  aria-label={pitDrag.label}
                  aria-valuemin={pitDrag.validLaps[0]}
                  aria-valuemax={pitDrag.validLaps[pitDrag.validLaps.length - 1]}
                  aria-valuenow={pitDrag.lap}
                  aria-valuetext={pitDrag.valueText}
                  aria-orientation="horizontal"
                  data-testid="pit-tick"
                  className="cursor-ew-resize outline-none [&:focus-visible>rect.focus]:opacity-100"
                  style={{ touchAction: "none" }}
                  onPointerDown={(event) => {
                    // Capture, so the drag survives the pointer leaving the
                    // element or the window — releasing outside must still
                    // deliver pointerup here rather than stranding the handle.
                    event.currentTarget.setPointerCapture(event.pointerId);
                    event.preventDefault();
                    dragging.current = true;
                    pitDrag.onDragStateChange?.(true);
                    moveTo(event.clientX);
                  }}
                  onPointerMove={(event) => {
                    if (!dragging.current) return;
                    moveTo(event.clientX);
                  }}
                  onPointerUp={(event) => {
                    dragging.current = false;
                    pitDrag.onDragStateChange?.(false);
                    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                      event.currentTarget.releasePointerCapture(event.pointerId);
                    }
                  }}
                  onPointerCancel={() => {
                    dragging.current = false;
                    pitDrag.onDragStateChange?.(false);
                  }}
                  onLostPointerCapture={() => {
                    // Belt and braces: if capture is lost without a pointerup
                    // (window blur, a browser gesture taking over), the drag must
                    // still end or the geometry stays frozen forever.
                    dragging.current = false;
                    pitDrag.onDragStateChange?.(false);
                  }}
                  onKeyDown={(event) => {
                    // Steps move by *candidate*, not by integer lap, so a hole in
                    // the discovered valid range cannot strand the handle on a
                    // lap with no ensemble behind it.
                    const laps = pitDrag.validLaps;
                    let next: number | null = null;
                    if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
                      next = stepValid(laps, pitDrag.lap, event.shiftKey ? -5 : -1);
                    } else if (event.key === "ArrowRight" || event.key === "ArrowUp") {
                      next = stepValid(laps, pitDrag.lap, event.shiftKey ? 5 : 1);
                    } else if (event.key === "Home") {
                      next = laps[0];
                    } else if (event.key === "End") {
                      next = laps[laps.length - 1];
                    }
                    if (next == null) return;
                    event.preventDefault();
                    if (next !== pitDrag.lap) pitDrag.onChange(next);
                  }}
                >
                  {/* 44px invisible hit area around a 2px tick. */}
                  <rect
                    x={axis.x(pitDrag.tickLap) - TICK_HIT_WIDTH / 2}
                    y={pitDrag.rowIndex * ROW_HEIGHT - 6}
                    width={TICK_HIT_WIDTH}
                    height={BAR_HEIGHT + 12}
                    fill="transparent"
                  />
                  {/* Focus ring, for keyboard focus only. */}
                  <rect
                    className="focus pointer-events-none opacity-0"
                    x={axis.x(pitDrag.tickLap) - 5}
                    y={pitDrag.rowIndex * ROW_HEIGHT - 6}
                    width={10}
                    height={BAR_HEIGHT + 12}
                    fill="none"
                    stroke="#A33A2E"
                    strokeWidth={1}
                  />
                  {/* The grip: a heavier tick plus chevrons, so it reads as
                      something to take hold of rather than as a plain rule. */}
                  <line
                    x1={axis.x(pitDrag.tickLap)}
                    x2={axis.x(pitDrag.tickLap)}
                    y1={pitDrag.rowIndex * ROW_HEIGHT - 4}
                    y2={pitDrag.rowIndex * ROW_HEIGHT + BAR_HEIGHT + 4}
                    stroke="#A33A2E"
                    strokeWidth={2}
                    className="pointer-events-none"
                  />
                  {[-1, 1].map((dir) => (
                    <path
                      key={dir}
                      d={`M${axis.x(pitDrag.tickLap) + dir * 4},${
                        pitDrag.rowIndex * ROW_HEIGHT + BAR_HEIGHT / 2 - 3
                      } l${dir * 3},3 l${-dir * 3},3`}
                      fill="none"
                      stroke="#A33A2E"
                      strokeWidth={1.25}
                      className="pointer-events-none"
                    />
                  ))}
                </g>
              )}
            </>
          )}
        </g>
      </svg>
    </figure>
  );
}

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

import { compoundFill, compoundInitial, compoundLabelColor } from "../lib/compounds";
import { AXIS_MARGIN, type LapAxis } from "./LapAxisPanes";

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
};

const ROW_HEIGHT = 26;
const BAR_HEIGHT = 16;
const TOP_PAD = 8;

export default function StrategyTimeline({ axis, rows, hoverLap, onHoverLap }: StrategyTimelineProps) {
  const height = TOP_PAD + rows.length * ROW_HEIGHT + 6;

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
                      {/* Pit stop: a tick at the stint boundary. */}
                      {stint.startLap > axis.firstLap && (
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
        </g>
      </svg>
    </figure>
  );
}

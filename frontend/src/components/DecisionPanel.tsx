/**
 * DecisionPanel — where the user changes a decision (spec 11.2).
 *
 * Deliberately does NOT block choices past the evidence. Refusing them would
 * make the tool decline the most interesting question in the race: the whole
 * Hungary argument is a 17-laps-beyond-observed stint. So every lap the
 * engine can represent is selectable, and the warning escalates with the
 * exposure instead — epistemics that inform rather than veto.
 *
 * The preview follows spec 11.2's teaching example ("pitting on lap 14 means
 * a 24-lap stint on mediums, four laps beyond the fitted useful life"),
 * because that's what turns the tool from a toy into something that shows
 * *how* strategy works.
 *
 * Two things worth naming:
 *
 * 1. Previews are READ, not recomputed. Every candidate's stint structure and
 *    extrapolation is precomputed by the real `apply_decision` code path and
 *    exported. Recomputing stint arithmetic client-side is exactly what
 *    produced a displayed tyre age the model never used (DECISIONS.md), and
 *    a slider is the most tempting possible place to do it again.
 *
 * 2. The extrapolation curve is V-shaped with its minimum at reality, and the
 *    sparkline shows that directly. It is NOT the case that one direction is
 *    safe: pitting earlier lengthens the following stint, pitting later
 *    lengthens the current one, and both eventually exceed what the driver
 *    actually ran. Reality is the zero-extrapolation point because observed
 *    tyre ages come from what actually happened. Showing the shape lets a
 *    user learn that by moving the slider, which no static caption would.
 */

export type Candidate = {
  newLap: number;
  isReal: boolean;
  newStintCompound: string | null;
  newStintLaps: number;
  newStintEndTyreAge: number;
  beyondEvidenceLaps: number;
  maxExcessLaps: number;
};

export type DecisionPanelProps = {
  driver: string;
  originalLap: number;
  /** The decision the simulated ensemble was actually run for. */
  committedLap: number;
  previewLap: number;
  onPreviewLap: (lap: number) => void;
  candidates: Candidate[];
  observedMaxTyreAge: Record<string, number>;
};

/**
 * The teaching sentence as plain text.
 *
 * Phase 6.3 moved the control onto the pit-stop tick itself, and the spec
 * requires `aria-valuetext` to carry this sentence rather than just a lap
 * number — a screen-reader user should get the consequence of the decision, not
 * the coordinate. The rendered version below is the same content with the
 * severity span; they are built from the same fields so they cannot disagree
 * about the numbers, and this one is what a screen reader reads while dragging.
 */
export function previewSentence(
  candidate: Candidate,
  driver: string,
  observedMaxTyreAge: Record<string, number>,
): string {
  const compound = candidate.newStintCompound ?? "";
  const observed = observedMaxTyreAge[compound] ?? 0;
  const base =
    `Lap ${candidate.newLap}: a ${candidate.newStintLaps}-lap stint on ` +
    `${compound.toLowerCase()}s, reaching tyre age ${candidate.newStintEndTyreAge}`;
  if (candidate.beyondEvidenceLaps <= 0) {
    return `${base} — within the ${observed} laps ${driver} actually ran on that compound.`;
  }
  return (
    `${base} — ${candidate.beyondEvidenceLaps} lap` +
    `${candidate.beyondEvidenceLaps === 1 ? "" : "s"} beyond the ${observed} ` +
    `${driver} actually ran on that compound, ${severity(candidate.beyondEvidenceLaps).label}.`
  );
}

/** Escalating severity rather than a binary pass/fail. */
function severity(beyondLaps: number): { label: string; className: string } {
  if (beyondLaps === 0) return { label: "within observed data", className: "text-ink/60" };
  if (beyondLaps <= 3) return { label: "slightly beyond observed data", className: "text-caution/80" };
  if (beyondLaps <= 10) return { label: "beyond observed data", className: "text-caution" };
  return { label: "far beyond observed data", className: "text-caution font-medium" };
}

export default function DecisionPanel({
  driver,
  originalLap,
  committedLap,
  previewLap,
  onPreviewLap,
  candidates,
  observedMaxTyreAge,
}: DecisionPanelProps) {
  if (candidates.length === 0) return null;

  const current = candidates.find((c) => c.newLap === previewLap) ?? candidates[0];
  const compound = current.newStintCompound ?? "";
  const observed = observedMaxTyreAge[compound] ?? 0;
  const sev = severity(current.beyondEvidenceLaps);

  const maxBeyond = Math.max(...candidates.map((c) => c.beyondEvidenceLaps), 1);
  // Wide enough that the minimum is visible as a minimum. The curve is
  // strongly asymmetric here rather than a neat V: the real stop is on lap 67
  // of 70, so the "pit later" arm is only three laps long while the "pit
  // earlier" arm runs the length of the race. Narrow, it read as a plain
  // descending line and lost the point.
  const sparkWidth = 168;
  const sparkHeight = 24;
  const realIndex = candidates.findIndex((c) => c.isReal);

  return (
    <section className="mt-6 rule-t pt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 className="label-caps">Decision — {driver} pit lap</h2>
        <p className="font-mono text-micro text-ink/60">
          really pitted lap {originalLap} · simulated ensemble ran lap {committedLap}
        </p>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-3">
        {/* The range input is gone (Phase 6.3). The control is the pit-stop tick
            on the alternate stint bar above, which means "move the decision"
            rather than "configure a parameter" — and because the bar shares the
            chart's lap axis, dragging left is literally moving the stop earlier
            in time. The lap readout stays, because the tick is a mark on an axis
            and a mark cannot state its own value. */}
        <p className="flex items-baseline gap-2 font-mono text-micro text-ink/60">
          LAP <output className="text-sm text-ink">{previewLap}</output>
          <span className="text-ink/45">drag the tick above, or focus it and use arrow keys</span>
        </p>

        <button
          onClick={() => onPreviewLap(originalLap)}
          className="border border-rule bg-paper px-2 py-0.5 font-sans text-micro uppercase tracking-[0.08em] text-ink/70 hover:border-ink/50"
        >
          Reset to real
        </button>

        {/* Extrapolation curve. Reality sits at the minimum; both directions
            climb. This is the panel's most useful single element — it teaches
            the model's shape by being moved. */}
        <figure className="m-0 flex items-center gap-2">
          <svg width={sparkWidth} height={sparkHeight} role="img" aria-label="Extrapolation by pit lap; reality is the minimum">
            <line x1={0} y1={sparkHeight - 1} x2={sparkWidth} y2={sparkHeight - 1} stroke="#C9C3B6" strokeWidth={0.5} />
            {/* Mark where reality sits: the zero-extrapolation point, and the
                thing the whole curve is measured against. Without it the
                asymmetry reads as an arbitrary downward slope. */}
            {realIndex >= 0 && (
              <line
                x1={(realIndex / Math.max(1, candidates.length - 1)) * sparkWidth}
                x2={(realIndex / Math.max(1, candidates.length - 1)) * sparkWidth}
                y1={0}
                y2={sparkHeight - 1}
                stroke="#1A1917"
                strokeWidth={0.75}
                strokeDasharray="2 2"
              />
            )}
            <path
              d={candidates
                .map((c, i) => {
                  const cx = (i / Math.max(1, candidates.length - 1)) * sparkWidth;
                  const cy = sparkHeight - 1 - (c.beyondEvidenceLaps / maxBeyond) * (sparkHeight - 3);
                  return `${i === 0 ? "M" : "L"}${cx.toFixed(1)},${cy.toFixed(1)}`;
                })
                .join(" ")}
              fill="none"
              stroke="#A8761F"
              strokeWidth={1}
            />
            {(() => {
              const i = candidates.findIndex((c) => c.newLap === previewLap);
              if (i < 0) return null;
              const cx = (i / Math.max(1, candidates.length - 1)) * sparkWidth;
              const cy = sparkHeight - 1 - (current.beyondEvidenceLaps / maxBeyond) * (sparkHeight - 3);
              return <circle cx={cx} cy={cy} r={2.5} fill="#F4F1EA" stroke="#1A1917" strokeWidth={1.25} />;
            })()}
          </svg>
          <figcaption className="font-sans text-micro uppercase tracking-[0.08em] text-ink/45">
            laps beyond evidence
          </figcaption>
        </figure>
      </div>

      {/* The teaching preview, in spec 11.2's own shape. */}
      <p className="mt-3 max-w-prose font-serif text-[0.95rem] leading-snug">
        Pitting on lap {previewLap} means a {current.newStintLaps}-lap stint on{" "}
        {compound.toLowerCase()}s, reaching tyre age {current.newStintEndTyreAge}
        {current.beyondEvidenceLaps > 0 ? (
          <>
            {" "}
            — <span className={sev.className}>
              {current.beyondEvidenceLaps} lap{current.beyondEvidenceLaps === 1 ? "" : "s"} beyond the{" "}
              {observed} {driver} actually ran on that compound
            </span>
            .
          </>
        ) : (
          <>
            {" "}
            — <span className={sev.className}>entirely within the {observed} laps {driver} actually ran on
            that compound</span>.
          </>
        )}
      </p>

      {previewLap !== committedLap && (
        <p className="mt-2 max-w-prose font-serif text-[0.85rem] italic leading-snug text-ink/60">
          The chart and outcome distribution above are the simulated ensemble for lap {committedLap}.
          Running a new ensemble for lap {previewLap} needs the API (Phase 5); the strategy row and the
          extrapolation reading update live because those come from the real strategy code path, not
          from a simulation.
        </p>
      )}
    </section>
  );
}

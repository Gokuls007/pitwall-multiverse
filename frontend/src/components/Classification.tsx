/**
 * Classification — real finishing order against the alternate outcome
 * (spec 11.2), and the panel where spec 6.10 either lands or quietly
 * collapses into a point estimate.
 *
 * It shows a **distribution per driver, not a single alternate order.** That
 * matters for a specific reason: the gap chart beside it draws a per-lap
 * *median* trace, which is no universe any seed produced. A median ending
 * 0.6s adrift while the ensemble wins 20% of its runs is not a contradiction
 * — they describe different objects — but putting one definite "alternate
 * order" next to that median would invite reading them as one answer, and the
 * reader would be right to call it incoherent.
 *
 * So: reality is a position, the alternate is a spread, and the two are
 * visibly different kinds of thing. Where a driver's outcome is genuinely
 * near-certain the bar collapses to one cell on its own, which is more
 * informative than asserting certainty everywhere.
 */

export type ClassificationRow = {
  driver: string;
  realPosition: number | null;
  modalPosition: number;
  modalShare: number;
  meanPosition: number;
  distribution: Record<string, number>;
  nRuns: number;
};

export type ClassificationProps = {
  rows: ClassificationRow[];
  focusDriver?: string;
  nRuns: number;
  /**
   * Phase 6.4. When the playhead is parked on a lap, the table shows the order at
   * *that* lap instead of the finish.
   *
   * Deliberately the REAL field order plus the focus driver's alternate position,
   * not a synthesised alternate order for everyone. Only the focus driver's
   * per-lap position is stored, and substituting his alternate position into the
   * real order would produce two cars in P3 and a hole elsewhere — an order the
   * model never produced. So the real order is stated as the order, and his
   * alternate position is shown as a displacement from it.
   */
  atLap?: {
    lap: number;
    /** Real order at this lap: driver codes, position 1 first. */
    realOrder: string[];
    /** The focus driver's alternate position at this lap, median across seeds. */
    focusAlternatePosition: number | null;
    /** Best and worst across seeds, so a contested lap can't read as settled. */
    focusAlternateSpread: [number, number] | null;
  };
};

/** Ink tint by share — darker means more of the ensemble landed there. */
function shareFill(share: number): string {
  if (share >= 0.75) return "#33302B";
  if (share >= 0.4) return "#6E685C";
  if (share >= 0.15) return "#9C9488";
  return "#C9C3B6";
}

export default function Classification({
  rows,
  focusDriver,
  nRuns,
  atLap,
}: ClassificationProps) {
  if (rows.length === 0) return null;

  // Scrubbed view: a plain order at a lap, which is a different object from the
  // outcome distribution below and is therefore drawn differently rather than
  // being squeezed into the same table.
  if (atLap) {
    // His real position AT THIS LAP, read off the same order shown above — not
    // his finishing position. Using `realPosition` here (the finish) produced
    // "HAM is P2 on this lap against P1 in reality" while the list directly above
    // it showed him second on that lap: the comparison silently changed which
    // lap it was talking about halfway through the sentence.
    const realHere = focusDriver ? atLap.realOrder.indexOf(focusDriver) : -1;
    const delta = realHere >= 0 ? realHere + 1 : null;
    return (
      <section className="mt-6 rule-t pt-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <h2 className="label-caps">Order on lap {atLap.lap}</h2>
          <p className="font-mono text-micro text-ink/60">
            real order, read from the lap record — not interpolated
          </p>
        </div>
        <ol className="mt-3 grid grid-cols-2 gap-x-6 font-mono text-micro sm:grid-cols-4">
          {atLap.realOrder.map((code, i) => (
            <li
              key={code}
              className={`flex items-baseline gap-2 py-0.5 ${
                code === focusDriver ? "bg-wash" : ""
              }`}
            >
              <span className="w-5 text-right text-ink/45">{i + 1}</span>
              <span className={code === focusDriver ? "font-medium" : ""}>{code}</span>
            </li>
          ))}
        </ol>
        {focusDriver && atLap.focusAlternatePosition != null && (
          <p className="mt-3 max-w-prose font-serif text-[0.9rem] leading-snug">
            In the alternate timeline {focusDriver} is{" "}
            <span className="font-mono text-annotation">P{atLap.focusAlternatePosition}</span> on
            this lap
            {atLap.focusAlternateSpread &&
              atLap.focusAlternateSpread[0] !== atLap.focusAlternateSpread[1] && (
                <>
                  {" "}
                  <span className="text-ink/60">
                    (P{atLap.focusAlternateSpread[0]}–P{atLap.focusAlternateSpread[1]} across the
                    ensemble)
                  </span>
                </>
              )}
            {delta != null && delta !== atLap.focusAlternatePosition && (
              <> against P{delta} in reality on the same lap.</>
            )}
            {delta === atLap.focusAlternatePosition && <> — the same place he was in reality.</>}
            {delta == null && <> (he has no classified position in reality here).</>}
            <span className="mt-1 block font-mono text-micro text-ink/45">
              The rest of the order is reality&apos;s. Only this driver&apos;s alternate position is
              stored, and inventing one for the others would put two cars in the same place.
            </span>
          </p>
        )}
      </section>
    );
  }

  // Shared scale across all rows so bar widths are comparable between drivers.
  const allPositions = rows.flatMap((r) => Object.keys(r.distribution).map(Number));
  const minPos = Math.min(...allPositions);
  const maxPos = Math.max(...allPositions);
  const span = Math.max(1, maxPos - minPos + 1);
  const BAR_W = 260;
  const cellW = BAR_W / span;

  return (
    <section className="mt-6 rule-t pt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 className="label-caps">Classification — real vs alternate</h2>
        <p className="font-mono text-micro text-ink/60">
          alternate = spread of <em className="not-italic text-ink/75">outcomes</em> across {nRuns}{" "}
          runs, not one order
        </p>
      </div>

      <table className="mt-3 w-full border-collapse font-mono text-micro">
        <thead>
          <tr className="text-ink/50">
            <th scope="col" className="rule-b py-1 pr-3 text-left font-normal">
              Real
            </th>
            <th scope="col" className="rule-b py-1 pr-3 text-left font-normal">
              Driver
            </th>
            <th scope="col" className="rule-b py-1 pr-3 text-left font-normal">
              <span className="block">Alternate — finishing position across the ensemble</span>
              {/* Label the scale once, so a bar's horizontal position is
                  readable as a position rather than guessed at. */}
              <svg width={BAR_W} height={9} aria-hidden="true" className="mt-0.5 block">
                {[1, ...Array.from({ length: Math.floor(span / 5) }, (_, k) => (k + 1) * 5)].map((pos) => (
                  <text
                    key={pos}
                    x={(pos - minPos) * cellW + cellW / 2}
                    y={8}
                    textAnchor="middle"
                    fontSize={7.5}
                    fill="#1A1917"
                    opacity={0.4}
                  >
                    P{pos}
                  </text>
                ))}
              </svg>
            </th>
            <th scope="col" className="rule-b py-1 text-right font-normal">
              Modal
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isFocus = row.driver === focusDriver;
            const delta =
              row.realPosition != null ? row.modalPosition - row.realPosition : null;
            return (
              <tr key={row.driver} className={isFocus ? "bg-wash" : undefined}>
                <td className="py-1 pr-3 align-middle text-ink/60">{row.realPosition ?? "—"}</td>
                <td className={`py-1 pr-3 align-middle ${isFocus ? "text-annotation" : ""}`}>
                  {row.driver}
                </td>
                <td className="py-1 pr-3 align-middle">
                  <svg width={BAR_W} height={12} role="img" aria-label={
                    `${row.driver} finished ` +
                    Object.entries(row.distribution)
                      .map(([p, n]) => `P${p} in ${Math.round((n / row.nRuns) * 100)}% of runs`)
                      .join(", ")
                  }>
                    {/* A faint full-width track and every-fifth-position
                        rules. Without them a front-runner's two cells read as
                        a smudge in an empty column; with them the same marks
                        read as "landed at the far left of a 20-position
                        scale", and the diagonal down the table becomes
                        legible as the alternate order tracking the real one. */}
                    <rect x={0} y={0} width={BAR_W} height={12} fill="#EFEBE2" />
                    {Array.from({ length: Math.floor(span / 5) }, (_, k) => (k + 1) * 5).map((step) => (
                      <line
                        key={`grid-${step}`}
                        x1={step * cellW}
                        x2={step * cellW}
                        y1={0}
                        y2={12}
                        stroke="#DCD6CA"
                        strokeWidth={0.5}
                      />
                    ))}
                    {Object.entries(row.distribution).map(([pos, count]) => {
                      const share = count / row.nRuns;
                      const x = (Number(pos) - minPos) * cellW;
                      return (
                        <rect
                          key={pos}
                          x={x + 0.5}
                          y={0}
                          width={Math.max(1, cellW - 1)}
                          height={12}
                          fill={shareFill(share)}
                        />
                      );
                    })}
                    {/* Reality's slot, so the shift is visible rather than inferred. */}
                    {row.realPosition != null && (
                      <rect
                        x={(row.realPosition - minPos) * cellW + 0.5}
                        y={0}
                        width={Math.max(1, cellW - 1)}
                        height={12}
                        fill="none"
                        stroke="#A33A2E"
                        strokeWidth={1}
                      />
                    )}
                  </svg>
                </td>
                <td className="py-1 text-right align-middle tabular-nums">
                  P{row.modalPosition}{" "}
                  <span className="text-ink/45">{Math.round(row.modalShare * 100)}%</span>
                  {delta != null && delta !== 0 && (
                    <span className={delta < 0 ? "ml-2 text-annotation" : "ml-2 text-ink/60"}>
                      {delta > 0 ? `+${delta}` : delta}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-micro text-ink/45">
        <span className="flex items-center gap-1.5">
          <svg width="12" height="10" aria-hidden="true">
            <rect x="0.5" y="0" width="11" height="10" fill="none" stroke="#A33A2E" strokeWidth="1" />
          </svg>
          where they really finished
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="34" height="10" aria-hidden="true">
            <rect x="0" y="0" width="10" height="10" fill="#C9C3B6" />
            <rect x="12" y="0" width="10" height="10" fill="#6E685C" />
            <rect x="24" y="0" width="10" height="10" fill="#33302B" />
          </svg>
          darker = more of the ensemble landed there
        </span>
      </p>
    </section>
  );
}

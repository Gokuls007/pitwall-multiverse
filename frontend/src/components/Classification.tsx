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
};

/** Ink tint by share — darker means more of the ensemble landed there. */
function shareFill(share: number): string {
  if (share >= 0.75) return "#33302B";
  if (share >= 0.4) return "#6E685C";
  if (share >= 0.15) return "#9C9488";
  return "#C9C3B6";
}

export default function Classification({ rows, focusDriver, nRuns }: ClassificationProps) {
  if (rows.length === 0) return null;

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
          alternate = spread across {nRuns} runs, not one order
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
              Alternate — finishing position across the ensemble
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

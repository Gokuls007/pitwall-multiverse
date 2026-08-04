/**
 * Phase 6 shell, GapChart first (spec 11.2: "the component the whole product
 * hangs on; give it the most attention").
 *
 * Data currently comes from a generated fixture, not the API: Phase 5's
 * FastAPI layer isn't built yet, so `backend/scripts/export_fixture.py` dumps
 * the same shapes it will serve, from the same pipeline functions, against
 * real 2019 Hungary data and a real counterfactual ensemble. Swapping in the
 * live endpoint later is a data-source change, not a rewrite.
 *
 * StrategyTimeline, DecisionPanel, Classification and the critical-apparatus
 * tree follow; the shared lap axis they align to is already established here.
 */

import { useMemo, useState } from "react";
import DecisionPanel from "./components/DecisionPanel";
import GapChart from "./components/GapChart";
import LapAxisPanes from "./components/LapAxisPanes";
import StrategyTimeline, { type StintRun } from "./components/StrategyTimeline";
import fixture from "./fixtures/race.json";

type Driver = { code: string; team: string; gridPosition: number };

/**
 * Laps of lead-in before the fork. Enough to see the approach without
 * letting pre-fork pit-stop swings (which reach ~18s and are identical in
 * both timelines) dominate the y-scale and squash the actual effect.
 */
const FOCUS_LEAD_IN_LAPS = 6;

export default function App() {
  const [mode, setMode] = useState<"field" | "focus">("focus");
  const [wholeRace, setWholeRace] = useState(false);
  const [hoverLap, setHoverLap] = useState<number | null>(null);

  const { teamByDriver, teammateIndex } = useMemo(() => {
    const byTeam: Record<string, string[]> = {};
    const team: Record<string, string> = {};
    for (const d of fixture.drivers as Driver[]) {
      team[d.code] = d.team;
      (byTeam[d.team] ??= []).push(d.code);
    }
    const index: Record<string, number> = {};
    for (const codes of Object.values(byTeam)) {
      codes.sort().forEach((code, i) => {
        index[code] = i;
      });
    }
    return { teamByDriver: team, teammateIndex: index };
  }, []);

  const cf = fixture.counterfactual;

  /**
   * The pit lap the panel is previewing. Starts at the committed decision —
   * the one the simulated ensemble was actually run for. Moving it updates
   * the strategy row and extrapolation reading live (both come from the real
   * `apply_decision` path, precomputed per candidate) while the chart and
   * outcome distribution stay labelled as the committed run, since a new
   * ensemble needs the API.
   */
  const [previewLap, setPreviewLap] = useState<number>(cf.divergenceLap);
  const previewCandidate = useMemo(
    () => cf.candidates.find((c) => c.newLap === previewLap) ?? null,
    [previewLap],
  );

  // Focus mode defaults to a window around the fork rather than the whole
  // race. Two reasons, both found by actually looking at the rendered chart:
  // the divergence sat off-screen to the right at default scroll, and
  // pre-fork pit-stop swings (~18s, identical in both timelines) dominated
  // the y-scale so the real sub-second effect was imperceptible.
  // Focus mode gives the driver TWO rows, real and alternate. With a
  // counterfactual active he has two stint structures (real stop at 67,
  // alternate at 50) and one bar would contradict the chart directly above
  // it; two rows also make the decision legible *as* a decision, since the
  // difference between them is exactly the change.
  const strategyRows = useMemo(() => {
    const fs = cf.focusStrategy;
    if (mode === "focus") {
      // Short labels: the gutter is shared with the y-axis numerals and is
      // only as wide as those need, and the driver is already named in the
      // chart caption directly above.
      //
      // The alternate row follows the *previewed* lap, not the committed one,
      // so moving the slider shows the strategy consequence immediately. The
      // stints come from the precomputed candidate table (real code path), not
      // from client-side arithmetic.
      const previewStints = (previewCandidate?.stints ?? fs.alternate) as StintRun[];
      return [
        { label: "real", stints: fs.real as StintRun[] },
        { label: "alt", stints: previewStints, isAlternate: true },
      ];
    }
    // Field mode: real stints for every driver, ordered by finishing position.
    const byDriver = new Map<string, StintRun[]>();
    for (const s of fixture.stints) {
      const runs = byDriver.get(s.driver) ?? [];
      runs.push({
        compound: s.compound,
        startLap: s.startLap,
        endLap: s.endLap,
        // Real ages from the fixture, never derived from stint length — a
        // stint can begin on used tyres, so length understates the age.
        startTyreAge: s.startTyreAge,
        endTyreAge: s.endTyreAge,
        extrapolatedLaps: 0,
        maxExcessLaps: 0,
        firstExtrapolatedLap: null,
      });
      byDriver.set(s.driver, runs);
    }
    return (fixture.drivers as Driver[])
      .slice()
      .sort((a, b) => (a.gridPosition ?? 99) - (b.gridPosition ?? 99))
      .filter((d) => byDriver.has(d.code))
      .map((d) => ({ label: d.code, stints: byDriver.get(d.code)! }));
  }, [mode, previewCandidate]);

  /** The previewed stint running furthest past this driver's observed data. */
  const beyondEvidence = useMemo(() => {
    const runs = (previewCandidate?.stints ?? cf.focusStrategy.alternate) as StintRun[];
    const worst = runs
      .filter((r) => r.extrapolatedLaps > 0)
      .sort((a, b) => b.maxExcessLaps - a.maxExcessLaps)[0];
    return worst ?? null;
  }, [previewCandidate]);

  const lapRange = useMemo<[number, number]>(
    () =>
      mode === "focus" && !wholeRace
        ? [Math.max(1, cf.divergenceLap - FOCUS_LEAD_IN_LAPS), fixture.meta.totalLaps]
        : [1, fixture.meta.totalLaps],
    [mode, wholeRace, cf.divergenceLap],
  );

  return (
    <main className="mx-auto min-h-screen max-w-[1100px] px-4 py-6 sm:px-6">
      {/* Session header, set like an official document header. */}
      <header className="rule-b pb-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <h1 className="font-sans text-lg font-semibold uppercase tracking-[0.14em]">
            Pit Wall Multiverse
          </h1>
          <p className="font-mono text-micro text-ink/60">
            {fixture.meta.year} {fixture.meta.eventName} · {fixture.meta.circuit} ·{" "}
            {fixture.meta.totalLaps} laps
          </p>
        </div>
      </header>

      {/* Mode switch: field view vs focused comparison. Two genuinely
          different questions, so two modes rather than one crowded chart. */}
      <div className="flex flex-wrap items-center gap-x-1 gap-y-2 py-3">
        {(["focus", "field"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            aria-pressed={mode === m}
            className={`border px-2.5 py-1 font-sans text-micro uppercase tracking-[0.08em] transition-colors ${
              mode === m
                ? "border-ink bg-ink text-paper"
                : "border-rule bg-paper text-ink/70 hover:border-ink/50"
            }`}
          >
            {m === "focus" ? "Comparison" : "Full field"}
          </button>
        ))}
        {mode === "focus" && (
          <button
            onClick={() => setWholeRace((v) => !v)}
            aria-pressed={wholeRace}
            className="ml-3 border border-rule bg-paper px-2.5 py-1 font-sans text-micro uppercase tracking-[0.08em] text-ink/70 transition-colors hover:border-ink/50"
          >
            {wholeRace ? `Lap ${lapRange[0]}–${lapRange[1]}` : "Whole race"}
          </button>
        )}
      </div>

      {/* One scroll container, one x-scale, both panes inside it: the shared
          lap axis is the analytical payoff of this layout, so alignment is
          guaranteed by construction rather than by syncing scroll offsets. */}
      <LapAxisPanes lapRange={lapRange}>
        {(axis) => (
          <>
            <GapChart
              axis={axis}
              realSeries={fixture.realSeries as Record<string, { lap: number; gap: number }[]>}
              teamByDriver={teamByDriver}
              teammateIndex={teammateIndex}
              mode={mode}
              focusDriver={cf.driver}
              alternateSeries={cf.series}
              seedSeries={cf.seedSeries}
              divergenceLap={cf.divergenceLap}
              safetyCarPeriods={fixture.safetyCarPeriods}
              hoverLap={hoverLap}
              onHoverLap={setHoverLap}
            />
            <StrategyTimeline
              axis={axis}
              rows={strategyRows}
              hoverLap={hoverLap}
              onHoverLap={setHoverLap}
            />
          </>
        )}
      </LapAxisPanes>

      {/* The caution channel earns its place here: the stint bar is the
          surface the user makes the choice on, so how far the answer runs
          past its own evidence belongs beside it, not in DECISIONS.md. */}
      {mode === "focus" && beyondEvidence != null && beyondEvidence.extrapolatedLaps > 0 && (
        <p className="mt-2 flex flex-wrap items-baseline gap-x-2 px-1 font-mono text-micro text-caution">
          <span aria-hidden="true" className="inline-block h-2.5 w-4 align-middle" style={{ background: "repeating-linear-gradient(45deg,#A8761F 0 2px,transparent 2px 4px)" }} />
          {beyondEvidence.extrapolatedLaps} laps of the alternate {beyondEvidence.compound} stint run beyond
          any tyre age {cf.driver} actually reached on that compound
          (max observed{" "}
          {(cf.focusStrategy.observedMaxTyreAge as Record<string, number>)[beyondEvidence.compound]} laps, this stint
          reaches {beyondEvidence.endTyreAge}) — extrapolation, not interpolation.
        </p>
      )}

      {mode === "focus" && (
        <DecisionPanel
          driver={cf.driver}
          originalLap={cf.candidates.find((c) => c.isReal)?.newLap ?? cf.divergenceLap}
          committedLap={cf.divergenceLap}
          previewLap={previewLap}
          onPreviewLap={setPreviewLap}
          candidates={cf.candidates}
          observedMaxTyreAge={cf.focusStrategy.observedMaxTyreAge as Record<string, number>}
        />
      )}

      {mode === "focus" && (
        <section className="mt-5 grid gap-5 sm:grid-cols-[1fr_auto]">
          <div>
            <h2 className="label-caps">Alternate history</h2>
            <p className="mt-1 font-serif text-[0.95rem] leading-snug">
              {cf.label}. Red Bull left Verstappen out on a 42-lap stint and did not cover
              Hamilton&apos;s stop; here he takes the stop they didn&apos;t.
            </p>
            {/* Caveat in the prose voice, and it carries a real measurement
                rather than a generic disclaimer. */}
            <p className="mt-2 max-w-prose font-serif text-[0.85rem] italic leading-snug text-ink/70">
              {cf.caveat}
            </p>
          </div>

          {/* The distribution, not a single order (spec 11.2). */}
          <div className="min-w-[13rem] border-l border-rule pl-4">
            <h2 className="label-caps">Outcome across {cf.nSeeds} runs</h2>
            <dl className="mt-1.5 font-mono text-sm">
              {Object.entries(cf.outcome.positionDistribution).map(([pos, n]) => (
                <div key={pos} className="flex items-baseline gap-2 py-0.5">
                  <dt className="w-8 text-ink/60">P{pos}</dt>
                  <dd className="flex flex-1 items-center gap-2">
                    <span
                      className="inline-block h-2 bg-annotation/70"
                      style={{ width: `${((n as number) / cf.nSeeds) * 100}%` }}
                    />
                    <span className="text-micro text-ink/60">
                      {Math.round(((n as number) / cf.nSeeds) * 100)}%
                    </span>
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-2 font-mono text-micro text-caution">
              win fraction rests on weakly-fitted parameters
            </p>
          </div>
        </section>
      )}

      <footer className="rule-t mt-8 pt-3 font-mono text-micro text-ink/50">
        {fixture.meta.source}
      </footer>
    </main>
  );
}

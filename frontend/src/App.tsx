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
import GapChart from "./components/GapChart";
import fixture from "./fixtures/race.json";

type Driver = { code: string; team: string; gridPosition: number };

export default function App() {
  const [mode, setMode] = useState<"field" | "focus">("focus");

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
      <div className="flex items-center gap-1 py-3">
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
      </div>

      <GapChart
        totalLaps={fixture.meta.totalLaps}
        realSeries={fixture.realSeries as Record<string, { lap: number; gap: number }[]>}
        teamByDriver={teamByDriver}
        teammateIndex={teammateIndex}
        mode={mode}
        focusDriver={cf.driver}
        alternateSeries={cf.series}
        divergenceLap={cf.divergenceLap}
        safetyCarPeriods={fixture.safetyCarPeriods}
      />

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

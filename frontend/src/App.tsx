/**
 * Phase 6 shell. As of Phase 6.2 the whole precomputed catalogue is reachable:
 * every race in the catalogue, every driver in it with a real pit stop, and
 * every candidate pit lap the engine accepts.
 *
 * The loading strategy is the point, and it is visible here rather than hidden
 * in a hook. The catalogue is 21MB across 103 files, so:
 *
 *   - choosing a race fetches **one** `__base` file (the field-wide real
 *     timeline, stints and safety-car periods — ~22KB);
 *   - choosing a driver fetches **exactly one** candidate file (median 201KB),
 *     which carries every alternate pit lap for that driver at once.
 *
 * The second point is what retires Phase 6.1's "committed vs previewed"
 * distinction. Previously the slider could move the strategy row but the chart
 * stayed pinned to the single ensemble the fixture had been exported for,
 * because a new ensemble needed the API. Now every candidate's ensemble is
 * already in the file that's open, so the chart follows the slider and there
 * is nothing left to label as uncommitted.
 */

import { useEffect, useMemo, useState } from "react";
import Classification, { type ClassificationRow } from "./components/Classification";
import DecisionPanel, { type Candidate as PanelCandidate } from "./components/DecisionPanel";
import GapChart, { type GapPoint } from "./components/GapChart";
import LapAxisPanes from "./components/LapAxisPanes";
import StrategyTimeline, { type StintRun } from "./components/StrategyTimeline";
import {
  availableDrivers,
  availableRaces,
  loadDriverFixture,
  loadRaceBase,
  toDeltaPoints,
  type Candidate,
  type DriverFixture,
  type RaceBase,
} from "./lib/raceFixtures";

/**
 * Laps of lead-in before the fork. Enough to see the approach without
 * letting pre-fork pit-stop swings (which reach ~18s and are identical in
 * both timelines) dominate the y-scale and squash the actual effect.
 */
const FOCUS_LEAD_IN_LAPS = 6;

const RACES = availableRaces();

/** "2019_hungarian" -> "2019 Hungarian" for the selector, before the file loads. */
function raceLabel(key: string): string {
  const [year, ...rest] = key.split("_");
  return `${year} ${rest.join(" ").replace(/\b\w/g, (c) => c.toUpperCase())}`;
}

export default function App() {
  const [mode, setMode] = useState<"field" | "focus">("focus");
  const [wholeRace, setWholeRace] = useState(false);
  const [hoverLap, setHoverLap] = useState<number | null>(null);

  // Hungary/VER is the demo case the whole project was built around, so it is
  // the default when present; otherwise fall back to whatever the catalogue has.
  const [raceKey, setRaceKey] = useState(
    RACES.includes("2019_hungarian") ? "2019_hungarian" : (RACES[0] ?? ""),
  );
  const [driver, setDriver] = useState("");
  const [base, setBase] = useState<RaceBase | null>(null);
  const [fixture, setFixture] = useState<DriverFixture | null>(null);
  const [error, setError] = useState<string | null>(null);

  const drivers = useMemo(() => availableDrivers(raceKey), [raceKey]);

  /** One base fetch per race. Field mode's data lives here, not in the driver files. */
  useEffect(() => {
    let live = true;
    setBase(null);
    setFixture(null);
    setError(null);
    loadRaceBase(raceKey)
      .then((b) => {
        if (!live) return;
        setBase(b);
        // Prefer the previously-selected driver if this race has him too, so
        // switching races to compare the same driver doesn't reset the choice.
        const list = availableDrivers(raceKey);
        setDriver(list.includes(driver) ? driver : (list.includes("VER") ? "VER" : (list[0] ?? "")));
      })
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
    // `driver` is read but deliberately not a dependency: it is only consulted
    // to preserve a selection across a race change, and depending on it would
    // re-fetch the base file on every driver change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raceKey]);

  /** Exactly one fetch per driver — the Phase 6.2 acceptance criterion. */
  useEffect(() => {
    if (!driver) return;
    let live = true;
    setFixture(null);
    loadDriverFixture(raceKey, driver)
      .then((f) => live && setFixture(f))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [raceKey, driver]);

  /**
   * Which real pit stop is being moved. A driver has one candidate set per real
   * stop (VER at Hungary has two: laps 25 and 67), and they are separate
   * decisions with separate consequences — collapsing them into one slider
   * would put non-adjacent laps next to each other and make the extrapolation
   * curve meaningless.
   */
  const stopLaps = useMemo(
    () => [...new Set((fixture?.candidates ?? []).map((c) => c.originalLap))].sort((a, b) => a - b),
    [fixture],
  );
  const [stopLap, setStopLap] = useState<number | null>(null);
  useEffect(() => {
    setStopLap(stopLaps.length ? stopLaps[stopLaps.length - 1] : null);
  }, [stopLaps]);

  const stopCandidates = useMemo(
    () =>
      (fixture?.candidates ?? [])
        .filter((c) => c.originalLap === stopLap)
        .sort((a, b) => a.newLap - b.newLap),
    [fixture, stopLap],
  );

  const [previewLap, setPreviewLap] = useState<number | null>(null);
  useEffect(() => {
    // Open on reality: the candidate that reproduces what actually happened.
    const real = stopCandidates.find((c) => c.isReal);
    setPreviewLap(real?.newLap ?? stopCandidates[0]?.newLap ?? null);
  }, [stopCandidates]);

  const selected: Candidate | null = useMemo(
    () => stopCandidates.find((c) => c.newLap === previewLap) ?? null,
    [stopCandidates, previewLap],
  );

  const realSeries = useMemo<Record<string, GapPoint[]>>(() => {
    const out: Record<string, GapPoint[]> = {};
    for (const [code, points] of Object.entries(base?.realSeries ?? {})) {
      out[code] = points.map(([lap, gap]) => ({ lap, gap }));
    }
    return out;
  }, [base]);

  const { teamByDriver, teammateIndex } = useMemo(() => {
    const byTeam: Record<string, string[]> = {};
    const team: Record<string, string> = {};
    for (const d of base?.drivers ?? []) {
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
  }, [base]);

  /** The driver's real stint structure, from the shared base file. */
  const realStints = useMemo<StintRun[]>(
    () =>
      (base?.stints ?? [])
        .filter((s) => s.driver === driver)
        .map((s) => ({
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
        })),
    [base, driver],
  );

  // Focus mode gives the driver TWO rows, real and alternate. With a
  // counterfactual active he has two stint structures and one bar would
  // contradict the chart directly above it; two rows also make the decision
  // legible *as* a decision, since the difference between them is the change.
  const strategyRows = useMemo(() => {
    if (mode === "focus") {
      // Short labels: the gutter is shared with the y-axis numerals and is
      // only as wide as those need, and the driver is already named in the
      // chart caption directly above.
      return [
        { label: "real", stints: realStints },
        { label: "alt", stints: (selected?.stints ?? realStints) as StintRun[], isAlternate: true },
      ];
    }
    // Field mode: real stints for every driver, ordered by grid position.
    const byDriver = new Map<string, StintRun[]>();
    for (const s of base?.stints ?? []) {
      const runs = byDriver.get(s.driver) ?? [];
      runs.push({
        compound: s.compound,
        startLap: s.startLap,
        endLap: s.endLap,
        startTyreAge: s.startTyreAge,
        endTyreAge: s.endTyreAge,
        extrapolatedLaps: 0,
        maxExcessLaps: 0,
        firstExtrapolatedLap: null,
      });
      byDriver.set(s.driver, runs);
    }
    return (base?.drivers ?? [])
      .slice()
      .sort((a, b) => (a.gridPosition ?? 99) - (b.gridPosition ?? 99))
      .filter((d) => byDriver.has(d.code))
      .map((d) => ({ label: d.code, stints: byDriver.get(d.code)! }));
  }, [mode, base, realStints, selected]);

  /** The previewed stint running furthest past this driver's observed data. */
  const beyondEvidence = useMemo(() => {
    const worst = (selected?.stints ?? [])
      .filter((r) => r.extrapolatedLaps > 0)
      .sort((a, b) => b.maxExcessLaps - a.maxExcessLaps)[0];
    return worst ?? null;
  }, [selected]);

  const totalLaps = base?.meta.totalLaps ?? fixture?.meta.totalLaps ?? 1;
  const divergenceLap = selected?.divergenceLap ?? null;

  const lapRange = useMemo<[number, number]>(
    () =>
      mode === "focus" && !wholeRace && divergenceLap != null
        ? [Math.max(1, divergenceLap - FOCUS_LEAD_IN_LAPS), totalLaps]
        : [1, totalLaps],
    [mode, wholeRace, divergenceLap, totalLaps],
  );

  const deltaSeries = useMemo(() => {
    if (!selected) return undefined;
    return toDeltaPoints(selected).map((p) => ({
      lap: p.lap,
      median: p.median,
      low: p.low,
      high: p.high,
      clampedFraction: p.clampedFraction,
    }));
  }, [selected]);

  /** Candidate table in the shape DecisionPanel reads. */
  const panelCandidates = useMemo<PanelCandidate[]>(
    () =>
      stopCandidates.map((c) => ({
        newLap: c.newLap,
        isReal: c.isReal,
        newStintCompound: c.newStintCompound,
        newStintLaps: c.newStintLaps,
        newStintEndTyreAge: c.newStintEndTyreAge,
        beyondEvidenceLaps: c.extrapolatedLaps,
        maxExcessLaps: c.maxExcessLaps,
      })),
    [stopCandidates],
  );

  /**
   * Classification rows for the selected candidate. Reality is a position; the
   * alternate is a distribution over the ensemble. Ordered by real finishing
   * position so the table reads against the actual result sheet.
   */
  const classificationRows = useMemo<ClassificationRow[]>(() => {
    if (!selected || !base) return [];
    const realPos = new Map(base.drivers.map((d) => [d.code, d.finishPosition]));
    return Object.entries(selected.classification)
      .map(([code, dist]) => {
        const entries = Object.entries(dist);
        const n = entries.reduce((sum, [, count]) => sum + count, 0);
        const [modal, modalCount] = entries.reduce(
          (best, e) => (e[1] > best[1] ? e : best),
          entries[0] ?? ["0", 0],
        );
        const mean = entries.reduce((sum, [pos, count]) => sum + Number(pos) * count, 0) / (n || 1);
        return {
          driver: code,
          realPosition: realPos.get(code) ?? null,
          modalPosition: Number(modal),
          modalShare: modalCount / (n || 1),
          meanPosition: mean,
          distribution: dist,
          nRuns: n,
        };
      })
      .sort((a, b) => (a.realPosition ?? 99) - (b.realPosition ?? 99));
  }, [selected, base]);

  const focusDistribution = useMemo(
    () => classificationRows.find((r) => r.driver === driver) ?? null,
    [classificationRows, driver],
  );

  const nSeeds = fixture?.meta.nSeeds ?? 0;
  const excluded = base?.meta.excludedFromGate ?? null;

  return (
    <main className="mx-auto min-h-screen max-w-[1100px] px-4 py-6 sm:px-6">
      {/* Session header, set like an official document header. */}
      <header className="rule-b pb-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <h1 className="font-sans text-lg font-semibold uppercase tracking-[0.14em]">
            Pit Wall Multiverse
          </h1>
          <p className="font-mono text-micro text-ink/60">
            {base
              ? `${base.meta.year} ${base.meta.eventName} · ${base.meta.circuit} · ${base.meta.totalLaps} laps`
              : "loading…"}
          </p>
        </div>
      </header>

      {/* Race and driver selection. Each change is one file. */}
      <div className="flex flex-wrap items-end gap-x-5 gap-y-3 py-3">
        <label className="flex flex-col gap-1">
          <span className="label-caps">Race</span>
          <select
            value={raceKey}
            onChange={(e) => setRaceKey(e.target.value)}
            className="border border-rule bg-paper px-2 py-1 font-mono text-sm"
          >
            {RACES.map((r) => (
              <option key={r} value={r}>
                {raceLabel(r)}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="label-caps">Driver</span>
          <select
            value={driver}
            onChange={(e) => setDriver(e.target.value)}
            className="border border-rule bg-paper px-2 py-1 font-mono text-sm"
          >
            {drivers.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>

        {/* Only offered when there is a genuine choice to make. */}
        {stopLaps.length > 1 && (
          <label className="flex flex-col gap-1">
            <span className="label-caps">Stop to move</span>
            <select
              value={stopLap ?? ""}
              onChange={(e) => setStopLap(Number(e.target.value))}
              className="border border-rule bg-paper px-2 py-1 font-mono text-sm"
            >
              {stopLaps.map((lap, i) => (
                <option key={lap} value={lap}>
                  #{i + 1} — real lap {lap}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {/* Mode switch: field view vs focused comparison. Two genuinely
          different questions, so two modes rather than one crowded chart. */}
      <div className="flex flex-wrap items-center gap-x-1 gap-y-2 pb-3">
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

      {/* A race outside the Part 8.3 gate aggregate says so, in place, rather
          than being quietly dropped from the selector. */}
      {excluded && (
        <p className="mb-3 max-w-prose border-l-2 border-caution/50 pl-3 font-serif text-[0.85rem] italic leading-snug text-caution">
          {excluded}
        </p>
      )}

      {error && (
        <p className="my-4 font-mono text-sm text-annotation">Could not load fixture: {error}</p>
      )}

      {/* One scroll container, one x-scale, both panes inside it: the shared
          lap axis is the analytical payoff of this layout, so alignment is
          guaranteed by construction rather than by syncing scroll offsets. */}
      <LapAxisPanes lapRange={lapRange}>
        {(axis) => (
          <>
            <GapChart
              axis={axis}
              realSeries={realSeries}
              teamByDriver={teamByDriver}
              teammateIndex={teammateIndex}
              mode={mode}
              focusDriver={driver}
              deltaSeries={deltaSeries}
              divergenceLap={divergenceLap ?? undefined}
              nRuns={nSeeds}
              safetyCarPeriods={base?.safetyCarPeriods ?? []}
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
      {mode === "focus" && beyondEvidence != null && fixture && (
        <p className="mt-2 flex flex-wrap items-baseline gap-x-2 px-1 font-mono text-micro text-caution">
          <span
            aria-hidden="true"
            className="inline-block h-2.5 w-4 align-middle"
            style={{
              background: "repeating-linear-gradient(45deg,#A8761F 0 2px,transparent 2px 4px)",
            }}
          />
          {beyondEvidence.extrapolatedLaps} laps of the alternate {beyondEvidence.compound} stint run
          beyond any tyre age {driver} actually reached on that compound (max observed{" "}
          {fixture.meta.observedMaxTyreAge[beyondEvidence.compound] ?? 0} laps, this stint reaches{" "}
          {beyondEvidence.endTyreAge}) — extrapolation, not interpolation.
        </p>
      )}

      {mode === "focus" && previewLap != null && stopLap != null && (
        <DecisionPanel
          driver={driver}
          originalLap={stopLap}
          /* Every candidate's ensemble is already loaded, so the previewed lap
             IS the simulated one. Phase 6.1 had to distinguish them. */
          committedLap={previewLap}
          previewLap={previewLap}
          onPreviewLap={setPreviewLap}
          candidates={panelCandidates}
          observedMaxTyreAge={fixture?.meta.observedMaxTyreAge ?? {}}
        />
      )}

      {mode === "focus" && selected && fixture && (
        <section className="mt-5 grid gap-5 sm:grid-cols-[1fr_auto]">
          <div>
            <h2 className="label-caps">Alternate history</h2>
            <p className="mt-1 font-serif text-[0.95rem] leading-snug">
              {selected.isReal ? (
                <>
                  {driver} pits on lap {selected.newLap}, as he actually did — the timeline the
                  engine reproduces, so the delta is the model&apos;s own error, not a
                  counterfactual.
                </>
              ) : (
                <>
                  {driver} pits on lap {selected.newLap} instead of lap {stopLap}. Laps before{" "}
                  {selected.divergenceLap} are reality copied verbatim; everything after is
                  simulated forward from the real state at the fork.
                </>
              )}
            </p>
            {/* Caveat in the prose voice, and it carries a real measurement
                rather than a generic disclaimer. */}
            <p className="mt-2 max-w-prose font-serif text-[0.85rem] italic leading-snug text-ink/70">
              {selected.clampLaps.length > 0 ? (
                <>
                  On {selected.clampLaps.length} of the simulated laps the majority of runs had{" "}
                  {driver} held up behind a car he could not pass, so that much of the delta is
                  traffic rather than pace.
                </>
              ) : (
                <>No lap in this ensemble was dominated by traffic, so the delta is pace-driven.</>
              )}
            </p>
          </div>

          {/* The focus driver's own spread, called out. The full field is in
              the Classification table below. */}
          {focusDistribution && (
            <div className="min-w-[13rem] border-l border-rule pl-4">
              <h2 className="label-caps">
                {driver} across {nSeeds} runs
              </h2>
              <dl className="mt-1.5 font-mono text-sm">
                {Object.entries(focusDistribution.distribution)
                  .sort((a, b) => Number(a[0]) - Number(b[0]))
                  .map(([pos, n]) => (
                    <div key={pos} className="flex items-baseline gap-2 py-0.5">
                      <dt className="w-8 text-ink/60">P{pos}</dt>
                      <dd className="flex flex-1 items-center gap-2">
                        <span
                          className="inline-block h-2 bg-annotation/70"
                          style={{ width: `${(n / nSeeds) * 100}%` }}
                        />
                        <span className="text-micro text-ink/60">
                          {Math.round((n / nSeeds) * 100)}%
                        </span>
                      </dd>
                    </div>
                  ))}
              </dl>
              <p className="mt-2 font-mono text-micro text-caution">
                win fraction rests on weakly-fitted parameters
              </p>
            </div>
          )}
        </section>
      )}

      {mode === "focus" && (
        <Classification rows={classificationRows} focusDriver={driver} nRuns={nSeeds} />
      )}

      <footer className="rule-t mt-8 pt-3 font-mono text-micro text-ink/50">
        {base?.meta.source ?? ""}
      </footer>
    </main>
  );
}

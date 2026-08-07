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

import { useEffect, useMemo, useRef, useState } from "react";
import Classification, { type ClassificationRow } from "./components/Classification";
import DecisionPanel, {
  previewSentence,
  type Candidate as PanelCandidate,
} from "./components/DecisionPanel";
import GapChart, { type GapPoint } from "./components/GapChart";
import LapAxisPanes from "./components/LapAxisPanes";
import DecisionSpace from "./components/DecisionSpace";
import LapPlayhead from "./components/LapPlayhead";
import MultiverseTree, { type TreeNode } from "./components/MultiverseTree";
import StrategyTimeline, { type StintRun } from "./components/StrategyTimeline";
import {
  availableDrivers,
  availableRaces,
  availableStops,
  loadDriverFixture,
  loadRaceBase,
  pickOpeningCandidate,
  positionAtLap,
  toSummary,
  toActualPoints,
  toDeltaPoints,
  toSeedPoints,
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

/**
 * How close the drag handle may get to the edge of the frozen lap window before
 * the window pans to follow it. Three laps is enough to see where you are going
 * without the window sliding for most of a drag.
 */
const DRAG_EDGE_MARGIN_LAPS = 3;

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
  /** Phase 6.4: the playhead. `null` means parked, showing the whole race. */
  const [playheadLap, setPlayheadLap] = useState<number | null>(null);

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
        //
        // Otherwise open on a driver with a *defensible* counterfactual rather
        // than on a fixed favourite. This used to default to VER, who at
        // Hungary has none: every way of moving either of his stops either runs
        // his HARD stint one lap past the oldest he reached or leans on a SOFT
        // cell fitted from two laps. Opening there meant the first thing a
        // reader saw was a caution.
        const list = availableDrivers(raceKey);
        if (list.includes(driver)) return;
        const defensible = b.drivers
          .filter((d) => d.hasCandidates && d.hasDefensibleCandidate && list.includes(d.code))
          .sort((x, y) => (x.finishPosition ?? 99) - (y.finishPosition ?? 99));
        setDriver(defensible[0]?.code ?? list[0] ?? "");
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

  /**
   * Which real pit stop is being moved. A driver has one candidate set per real
   * stop (VER at Hungary has two: laps 25 and 67), and they are separate
   * decisions with separate consequences — collapsing them into one slider
   * would put non-adjacent laps next to each other and make the extrapolation
   * curve meaningless.
   */
  // From the file listing rather than from a loaded fixture: files are keyed per
  // (driver, stop), so which stops exist is known before anything is fetched —
  // which is what lets the stop selector render without a round trip.
  const stopLaps = useMemo(
    () => (driver ? availableStops(raceKey, driver) : []),
    [raceKey, driver],
  );
  /**
   * The stop being moved: the user's choice if it is valid for this driver,
   * otherwise a default.
   *
   * Derived synchronously rather than held in state and set from an effect. The
   * effect version briefly left `stopLap` holding the *previous* driver's stop
   * after a driver change, and the fetch effect fired on that intermediate value
   * — so switching driver cost two requests, one of them for a decision nobody
   * had asked to see. Deriving it means there is exactly one value per render and
   * no intermediate to fetch.
   */
  const [chosenStopLap, setChosenStopLap] = useState<number | null>(null);
  const stopLap = useMemo(() => {
    if (!stopLaps.length) return null;
    if (chosenStopLap != null && stopLaps.includes(chosenStopLap)) return chosenStopLap;
    // Default to a stop that has a counterfactual inside the model's evidence,
    // read from the base file's decision-space summary so no candidate file has
    // to be fetched to make the choice.
    const summary = base?.decisionSpace?.[driver] ?? {};
    const usable = stopLaps.filter((lap) =>
      toSummary(summary[String(lap)]).some((c) => c.newLap !== lap && c.extrapolatedLaps === 0),
    );
    const pool = usable.length ? usable : stopLaps;
    return pool[pool.length - 1];
  }, [stopLaps, chosenStopLap, base, driver]);

  /**
   * Exactly one fetch per (driver, stop) — the Phase 6.2 criterion, tightened in
   * 6.5. Files were per driver, so a two-stop driver downloaded both stops'
   * candidate sets to show one.
   */
  useEffect(() => {
    if (!driver || stopLap == null) return;
    let live = true;
    setFixture(null);
    loadDriverFixture(raceKey, driver, stopLap)
      .then((f) => live && setFixture(f))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [raceKey, driver, stopLap]);

  // A playhead lap only means something relative to a particular race, driver and
  // decision; carrying it across a change would show "the order on lap 47" of a
  // race that is no longer loaded.
  useEffect(() => {
    setPlayheadLap(null);
  }, [raceKey, driver, stopLap]);

  // The loaded file IS one stop's candidates, already sorted by the generator.
  const stopCandidates = useMemo(
    () => (fixture?.meta.stopLap === stopLap ? fixture.candidates : []),
    [fixture, stopLap],
  );

  const [previewLap, setPreviewLap] = useState<number | null>(null);
  useEffect(() => {
    // Not reality, and deliberately not the biggest effect — see
    // `pickOpeningCandidate`. The largest numbers in this catalogue are
    // artifacts of degenerate tyre fits, so opening on one would headline a
    // broken answer that merely happens to be flagged.
    setPreviewLap(pickOpeningCandidate(stopCandidates)?.newLap ?? null);
  }, [stopCandidates]);

  /**
   * Candidates keyed by lap. `pointermove` fires at pointer frequency and every
   * event is a lookup plus a full redraw, so the lookup is a Map rather than a
   * linear scan over ~130 candidates (spec 6.3).
   */
  const candidatesByLap = useMemo(
    () => new Map(stopCandidates.map((c) => [c.newLap, c])),
    [stopCandidates],
  );

  /** Sorted valid laps — the drag snaps to these, not to any integer. */
  const validLaps = useMemo(() => stopCandidates.map((c) => c.newLap), [stopCandidates]);

  const selected: Candidate | null = useMemo(
    () => (previewLap == null ? null : candidatesByLap.get(previewLap) ?? null),
    [candidatesByLap, previewLap],
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

  /**
   * Hold the lap window still for the duration of a drag.
   *
   * Found by dragging it: the window is derived from the divergence lap, so every
   * step recomputed the x-scale, the whole plot shifted sideways, and the grip
   * slid out from under the pointer. Moving the stop 8 laps left moved the
   * content further than the cursor. Freezing the window is what makes the drag
   * feel like moving a mark along an axis rather than like the axis reacting to
   * you; the window catches up on release.
   */
  const [isDragging, setIsDragging] = useState(false);
  const frozenRange = useRef<[number, number] | null>(null);

  const lapRange = useMemo<[number, number]>(() => {
    if (isDragging && frozenRange.current) {
      const [lo, hi] = frozenRange.current;
      // Frozen, but not a wall. If the handle reaches the edge of the frozen
      // window the window pans to follow it, keeping its width — otherwise
      // dragging toward a lap outside the window would stop the handle while the
      // pointer kept going, which is worse than the rescaling it replaced. The
      // valid range for a stop is often the entire race (HAM's lap-48 stop
      // accepts laps 1-70), so a tight window that cannot pan is guaranteed to
      // hit this.
      const handle = divergenceLap ?? lo;
      const width = hi - lo;
      if (handle < lo + DRAG_EDGE_MARGIN_LAPS) {
        const newLo = Math.max(1, handle - DRAG_EDGE_MARGIN_LAPS);
        return [newLo, Math.min(totalLaps, newLo + width)];
      }
      if (handle > hi - DRAG_EDGE_MARGIN_LAPS) {
        const newHi = Math.min(totalLaps, handle + DRAG_EDGE_MARGIN_LAPS);
        return [Math.max(1, newHi - width), newHi];
      }
      return frozenRange.current;
    }
    const range: [number, number] =
      mode === "focus" && !wholeRace && divergenceLap != null
        ? [Math.max(1, divergenceLap - FOCUS_LEAD_IN_LAPS), totalLaps]
        : [1, totalLaps];
    frozenRange.current = range;
    return range;
  }, [mode, wholeRace, divergenceLap, totalLaps, isDragging]);

  const deltaSeries = useMemo(() => (selected ? toDeltaPoints(selected) : undefined), [selected]);
  const replayErrorSeries = useMemo(
    () => (selected ? toActualPoints(selected) : undefined),
    [selected],
  );
  const seedSeries = useMemo(
    () =>
      selected
        ? toSeedPoints(selected).map((t) => ({
            seed: t.seed,
            points: t.points.map((p) => ({ lap: p.lap, gap: p.median })),
          }))
        : undefined,
    [selected],
  );

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

  /**
   * Degradation cells this candidate leans on that are too thin to lean on.
   * The cell statistics come from `meta.tyreCells` (per-driver constants) and the
   * reliance from the candidate — joined here rather than stored per candidate.
   */
  const degenerateCells = useMemo(() => {
    if (!selected || !fixture) return [];
    return fixture.meta.tyreCells
      .filter((cell) => cell.degenerate)
      .map((cell) => ({ ...cell, postForkLaps: selected.fitReliance[cell.compound] ?? 0 }))
      .filter((cell) => cell.postForkLaps > 0);
  }, [selected, fixture]);

  /**
   * Phase 6.3: the pit stop is the control.
   *
   * The handle goes on the alternate row (index 1 in focus mode), at the lap the
   * moved stop currently sits on. `valueText` carries the teaching sentence
   * rather than the number, so a screen reader dragging this hears the
   * consequence of the decision.
   */
  const pitDrag = useMemo(() => {
    if (mode !== "focus" || selected == null || stopLap == null || validLaps.length === 0) {
      return undefined;
    }
    // The bar draws its boundary at the start of the stint the stop *creates* —
    // the lap after the in-lap. The handle is drawn there so the grip is on the
    // mark it moves, while the value it reports stays the in-lap.
    const created = selected.stints.find((run) => run.startLap > selected.newLap);
    return {
      rowIndex: 1,
      lap: selected.newLap,
      tickLap: created?.startLap ?? selected.newLap,
      realLap: stopLap + (created ? created.startLap - selected.newLap : 0),
      validLaps,
      valueText: previewSentence(
        {
          newLap: selected.newLap,
          isReal: selected.isReal,
          newStintCompound: selected.newStintCompound,
          newStintLaps: selected.newStintLaps,
          newStintEndTyreAge: selected.newStintEndTyreAge,
          beyondEvidenceLaps: selected.extrapolatedLaps,
          maxExcessLaps: selected.maxExcessLaps,
        },
        driver,
        fixture?.meta.observedMaxTyreAge ?? {},
      ),
      label: `${driver} pit lap, ${validLaps[0]} to ${validLaps[validLaps.length - 1]}`,
      onChange: setPreviewLap,
      onDragStateChange: setIsDragging,
    };
  }, [mode, selected, stopLap, validLaps, driver, fixture]);

  /** Pit stops on the playhead rail, so scrubbing has landmarks. */
  const playheadMarks = useMemo(() => {
    const marks: { lap: number; kind: "real" | "alternate" }[] = [];
    for (const lap of fixture?.meta.realPitLaps ?? []) marks.push({ lap, kind: "real" });
    if (selected && !selected.isReal) marks.push({ lap: selected.newLap, kind: "alternate" });
    return marks;
  }, [fixture, selected]);

  /**
   * The order at the playhead lap. Read from stored per-lap state on both sides —
   * `base.realPositions` for the field, the candidate's `positions` for the focus
   * driver's alternate. Nothing here is interpolated between laps, which is why
   * the playhead only ever sits on an integer lap.
   */
  const orderAtPlayhead = useMemo(() => {
    if (playheadLap == null || !base) return undefined;
    const at: { code: string; position: number }[] = [];
    for (const [code, series] of Object.entries(base.realPositions ?? {})) {
      const entry = series.find(([lap]) => lap === playheadLap);
      if (entry) at.push({ code, position: entry[1] });
    }
    at.sort((a, b) => a.position - b.position);

    const alt = selected ? positionAtLap(selected, playheadLap) : null;
    return {
      lap: playheadLap,
      realOrder: at.map((entry) => entry.code),
      focusAlternatePosition: alt ? alt.median : null,
      focusAlternateSpread: alt ? ([alt.best, alt.worst] as [number, number]) : null,
    };
  }, [playheadLap, base, selected]);

  /**
   * The multiverse tree: reality as the trunk, one branch per driver.
   *
   * Breadth, not depth. Two independent findings pushed it here. The layout test
   * (`?treelab`) showed depth 1 stays legible at 19 branches while depth 2 keeps
   * its labels but loses its ancestry — you cannot tell which fork came from
   * which — and depth 3 collapses entirely. And the data says the same thing
   * louder: only 3% of *first* decisions stay inside observed tyre age, so a
   * second decision stacked on a first would make every depth-2 node an
   * extrapolation. A tree that renders beautifully and returns nothing defensible
   * is worse than a smaller one that works.
   *
   * So each branch is the same question asked once per driver — did this decision
   * bring the car into contention — at exactly the strength the single-comparison
   * view can defend. Built entirely from the base file's summary, so the whole
   * tree costs no fetches.
   */
  const treeNodes = useMemo<TreeNode[]>(() => {
    if (!base) return [];
    const finish = new Map(base.drivers.map((d) => [d.code, d.finishPosition ?? 20]));
    const nodes: TreeNode[] = [
      {
        id: "reality",
        parentId: null,
        divergenceLap: 1,
        endPosition: finish.get(driver) ?? 1,
        label: "reality",
        deltaS: 0,
        extrapolatedLaps: 0,
        cause: null,
      },
    ];

    for (const entry of base.drivers) {
      const byStop = base.decisionSpace?.[entry.code];
      if (!entry.hasCandidates || !byStop) {
        // In the field but not branchable: no real pit stop, or the engine
        // refused every shift of the ones he made. Drawn as a dashed stub rather
        // than dropped, because a tree that silently omits cars is
        // indistinguishable from one where those cars had nothing to say.
        nodes.push({
          id: `none-${entry.code}`,
          parentId: "reality",
          divergenceLap: Math.round((base.meta.totalLaps * 2) / 3),
          endPosition: entry.finishPosition ?? 20,
          label: `${entry.code} — no decision to move`,
          deltaS: 0,
          extrapolatedLaps: 0,
          cause: null,
          unavailable: true,
        });
        continue;
      }

      // One branch per driver, and *which* candidate is the whole design of this
      // panel.
      //
      // The first version took the candidate nearest reality among the defensible
      // ones. That is the most conservative possible choice and it made the tree
      // useless: nineteen of twenty branches were sub-second, so they piled onto
      // the zero rule and the picture said nothing. The question the product asks
      // is not "what is the smallest change" — it is "what is the best this
      // driver could have done that the model can actually defend".
      //
      // So within the defensible tier, take the LARGEST effect. Outside it, stay
      // conservative and take the nearest, because a large extrapolating number
      // is exactly the artifact this project spends its time refusing to
      // headline.
      const tier = (x: { extrapolatedLaps: number; cause: string | null }) =>
        x.extrapolatedLaps === 0 && x.cause == null ? 0 : x.cause == null ? 1 : 2;
      let best: { stopLap: number; c: ReturnType<typeof toSummary>[number] } | null = null;
      for (const [stopKey, rows] of Object.entries(byStop)) {
        const stopLap = Number(stopKey);
        for (const c of toSummary(rows)) {
          if (c.newLap === stopLap) continue;
          if (best == null) {
            best = { stopLap, c };
            continue;
          }
          const t = tier(c);
          const bt = tier(best.c);
          if (t !== bt) {
            if (t < bt) best = { stopLap, c };
            continue;
          }
          const better =
            t === 0
              ? Math.abs(c.finalDeltaS) > Math.abs(best.c.finalDeltaS)
              : Math.abs(c.newLap - stopLap) < Math.abs(best.c.newLap - best.stopLap);
          if (better) best = { stopLap, c };
        }
      }
      if (!best) continue;

      // For the driver currently in focus, follow the selection instead, so the
      // tree and the comparison view above it never disagree.
      const useSelected = entry.code === driver && selected != null && stopLap != null;
      const shown = useSelected
        ? {
            newLap: selected!.newLap,
            finalDeltaS: selected!.plausibility.finalDeltaS,
            extrapolatedLaps: selected!.extrapolatedLaps,
            cause: selected!.plausibility.cause,
            stopLap: stopLap!,
          }
        : { ...best.c, stopLap: best.stopLap };

      nodes.push({
        id: `${entry.code}-${shown.stopLap}-${shown.newLap}`,
        parentId: "reality",
        divergenceLap: Math.min(shown.stopLap, shown.newLap),
        endPosition: finish.get(entry.code) ?? 20,
        label: `${entry.code} L${shown.stopLap}→${shown.newLap} ${
          shown.finalDeltaS >= 0 ? "+" : ""
        }${shown.finalDeltaS.toFixed(1)}s`,
        deltaS: shown.finalDeltaS,
        extrapolatedLaps: shown.extrapolatedLaps,
        cause: shown.cause,
      });
    }
    return nodes;
  }, [base, driver, selected, stopLap]);

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
              onChange={(e) => setChosenStopLap(Number(e.target.value))}
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
            <LapPlayhead
              axis={axis}
              lap={playheadLap}
              onLap={setPlayheadLap}
              markedLaps={playheadMarks}
            />
            <GapChart
              axis={axis}
              realSeries={realSeries}
              teamByDriver={teamByDriver}
              teammateIndex={teammateIndex}
              mode={mode}
              focusDriver={driver}
              deltaSeries={deltaSeries}
              replayErrorSeries={replayErrorSeries}
              seedSeries={seedSeries}
              divergenceLap={divergenceLap ?? undefined}
              nRuns={nSeeds}
              revealLap={playheadLap}
              safetyCarPeriods={base?.safetyCarPeriods ?? []}
              hoverLap={hoverLap}
              onHoverLap={setHoverLap}
            />
            <StrategyTimeline
              axis={axis}
              rows={strategyRows}
              hoverLap={hoverLap}
              onHoverLap={setHoverLap}
              pitDrag={pitDrag}
              revealLap={playheadLap}
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
          {beyondEvidence.extrapolatedLaps}{" "}
          {beyondEvidence.extrapolatedLaps === 1 ? "lap" : "laps"} of the alternate{" "}
          {beyondEvidence.compound} stint {beyondEvidence.extrapolatedLaps === 1 ? "runs" : "run"}{" "}
          beyond any tyre age {driver} actually reached on that compound (max observed{" "}
          {fixture.meta.observedMaxTyreAge[beyondEvidence.compound] ?? 0} laps, this stint reaches{" "}
          {beyondEvidence.endTyreAge}) — extrapolation, not interpolation.{" "}
          {/* A third risk category that neither `extrapolatedLaps` nor
              `fitProvenance` covers: out here the FUNCTIONAL FORM is untested. A
              cliff is only detectable inside the observed range, so "no cliff
              past it" is the absence of a finding rather than a finding. Stated
              explicitly, because the hatch on its own reads as "less certain"
              when the actual claim is "structurally linear by default". */}
          <span className="text-ink/60">
            Out there the curve is a straight line because nothing in {driver}&apos;s data could
            have told it otherwise — a cliff can only be detected inside the range he ran, so its
            absence here is not evidence of its absence.
          </span>
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
            {/* The decomposition, always — not only when something is wrong.
                "He gained 8 seconds" and "he gained 8 seconds of which 6 were
                not being stuck behind a Williams" are different claims. */}
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 font-mono text-micro text-ink/70">
              <dt>net by the finish</dt>
              <dd className="text-ink">
                {selected.plausibility.finalDeltaS >= 0 ? "+" : ""}
                {selected.plausibility.finalDeltaS.toFixed(2)}s
              </dd>
              <dt>of which pace</dt>
              <dd>
                {selected.plausibility.paceS >= 0 ? "+" : ""}
                {selected.plausibility.paceS.toFixed(2)}s
              </dd>
              <dt>of which traffic</dt>
              <dd>
                {selected.plausibility.trafficS >= 0 ? "+" : ""}
                {selected.plausibility.trafficS.toFixed(2)}s
                {selected.clampLaps.length > 0 && (
                  <span className="text-ink/45">
                    {" "}
                    · held up on {selected.clampLaps.length} laps
                  </span>
                )}
              </dd>
            </dl>

            {/* Cause, not just symptom. A candidate past the plausibility bound
                is useless as an answer unless the reader is told which part of
                the model produced it. */}
            {(selected.plausibility.implausible ||
              selected.plausibility.restsOnDegenerateFit) && (
              <div className="mt-3 max-w-prose border-l-2 border-caution/50 pl-3 font-serif text-[0.85rem] leading-snug text-caution">
                {selected.plausibility.implausible && (
                  <p>
                    {Math.abs(selected.plausibility.finalDeltaS).toFixed(0)}s from one moved pit
                    stop is past this race&apos;s plausibility bound of{" "}
                    {fixture.meta.plausibilityBoundS.toFixed(0)}s (twice the fitted pit-lane loss).
                    Read it as a property of the model, not a strategy finding.
                  </p>
                )}
                {degenerateCells.map((cell) => (
                  <p key={cell.compound} className={selected.plausibility.implausible ? "mt-1" : ""}>
                    {driver} ran only {cell.nObservations}{" "}
                    {cell.nObservations === 1 ? "lap" : "laps"} on the {cell.compound}, too few to
                    fit his own degradation, so it comes from the cross-driver pooled estimate
                    {cell.linearDegSPerLap === 0
                      ? " — and that came out as exactly zero, meaning the model believes the tyre never wears"
                      : ""}
                    . This answer runs {cell.postForkLaps} laps on it.
                  </p>
                ))}
                {selected.plausibility.cause === "traffic" && (
                  <p className="mt-1">
                    Most of it is traffic, not pace: {selected.plausibility.trafficS.toFixed(0)}s of
                    the {selected.plausibility.finalDeltaS.toFixed(0)}s is accumulated time held up
                    behind cars, which rests on the overtaking model rather than the tyre model.
                  </p>
                )}
                {selected.plausibility.cause === "unexplained" && (
                  <p className="mt-1">
                    No single part of the model accounts for it: the stints stay inside observed
                    tyre age, the degradation cells are well fitted, and it is pace rather than
                    traffic. Flagged as large without an identified cause rather than explained
                    away.
                  </p>
                )}
              </div>
            )}
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
        <Classification
          rows={classificationRows}
          focusDriver={driver}
          nRuns={nSeeds}
          atLap={orderAtPlayhead}
        />
      )}

      {treeNodes.length > 1 && (
        <section className="mt-6 rule-t pt-4">
          <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
            <h2 className="label-caps">The multiverse — one branch per driver</h2>
            <p className="font-mono text-micro text-ink/60">
              {treeNodes.filter((n) => !n.unavailable && n.parentId).length} branchable ·{" "}
              {treeNodes.filter((n) => n.unavailable).length} with no decision to move
            </p>
          </div>
          <p className="mt-1 max-w-prose font-serif text-[0.85rem] italic leading-snug text-ink/70">
            Breadth, not depth. Stacking a second decision on a first would make almost every
            node an extrapolation — only 3% of single decisions stay inside the evidence — and
            the layout stops being traceable past one level. Each branch forks at the lap its
            decision was taken; y is time gained or lost against reality, the same variable the
            comparison chart plots — on a symmetric-log scale, because one branch reaches −16.8s
            while eighteen sit within a few seconds of zero, and a linear axis gives that cluster
            a tenth of the height.
          </p>
          <div className="mt-2 overflow-x-auto">
            <MultiverseTree
              nodes={treeNodes}
              totalLaps={base?.meta.totalLaps ?? 70}
              selectedId={
                treeNodes.find((n) => n.id.startsWith(`${driver}-`))?.id ?? null
              }
              onSelect={(id) => {
                const code = id.split("-")[0];
                if (code !== "reality" && code !== "none") setDriver(code);
              }}
              height={Math.max(260, treeNodes.length * 15 + 60)}
            />
          </div>
        </section>
      )}

      {base && (
        <DecisionSpace
          base={base}
          drivers={base.drivers
            .filter((d) => d.hasCandidates)
            .sort((a, b) => (a.finishPosition ?? 99) - (b.finishPosition ?? 99))
            .map((d) => d.code)}
          selected={
            driver && stopLap != null && previewLap != null
              ? { driver, stopLap, newLap: previewLap }
              : undefined
          }
          onSelect={(nextDriver, nextStop, nextLap) => {
            setDriver(nextDriver);
            setChosenStopLap(nextStop);
            setPreviewLap(nextLap);
          }}
        />
      )}

      <footer className="rule-t mt-8 pt-3 font-mono text-micro text-ink/50">
        {base?.meta.source ?? ""}
      </footer>
    </main>
  );
}

/**
 * Lazy per-driver fixture loading (Phase 6.2).
 *
 * The precomputed decision space is 98 files and 21MB across the catalogue —
 * every driver with a real pit stop, on every race, at every candidate pit lap
 * the engine accepts. Shipping that as one bundle would be indefensible, so
 * selecting a driver fetches **exactly one file**, and each file is cached
 * after its first fetch so navigation never re-requests a path already loaded.
 *
 * `import.meta.glob` with `query: "?url"` gives Vite the file list at build
 * time without inlining any contents into the bundle: the modules resolve to
 * URLs, and the JSON is only transferred when a driver is actually chosen.
 */

export type DeltaPoint = {
  lap: number;
  median: number;
  low: number;
  high: number;
  clampedFraction: number;
};

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

/** One driver/compound degradation cell, and whether it can be leaned on. */
export type FitCell = {
  compound: string;
  nObservations: number;
  /** Post-fork laps this candidate actually runs on the compound. */
  postForkLaps: number;
  rSquared?: number | null;
  linearDegSPerLap?: number;
  cliffLap?: number | null;
  degenerate: boolean;
};

export type Plausibility = {
  finalDeltaS: number;
  sPerLap: number;
  /** Twice the fitted pit-lane loss. Past it, the answer is an artifact. */
  boundS: number;
  implausible: boolean;
  /** Of `finalDeltaS`, how much is accumulated held-up time versus pace. */
  trafficS: number;
  paceS: number;
  restsOnDegenerateFit: boolean;
  /**
   * Which part of the model produced an implausible answer, named by the
   * generator so this and the backend test cannot drift apart. `null` when the
   * candidate is plausible. `"unexplained"` is a real value, not a gap: a
   * handful of candidates exceed the bound with none of the known causes, and
   * saying so beats attributing them to a mechanism that isn't responsible.
   */
  cause: "degenerateFit" | "traffic" | "extrapolation" | "unexplained" | null;
};

export type Candidate = {
  originalLap: number;
  newLap: number;
  isReal: boolean;
  divergenceLap: number;
  /**
   * The decision effect: alternate minus the override-free fork at the same lap
   * with the same seed. Tuple array to keep the payload small —
   * `[lap, median, p10, p90, clampedFraction]`.
   */
  deltaVsSimulatedReal: [number, number, number, number, number][];
  /**
   * The same alternate against the *ingested* times, so it carries the
   * simulator's replay error as well as the decision's effect. A labelled
   * model-quality diagnostic, never the answer. Aligned index-for-index with
   * `deltaVsSimulatedReal` rather than repeating the lap column.
   */
  deltaVsActual: [number | null][];
  /**
   * Three real trajectories of the decision effect, at the p10/p50/p90 of final
   * delta. `values` is aligned with `deltaVsSimulatedReal`. These exist because
   * a p10–p90 band cannot show a bimodal ensemble: if he either makes the pass
   * or doesn't, the band spans both modes and the median line sits in a region
   * no seed occupied.
   */
  seedTraces: { seed: number; values: number[] }[];
  plausibility: Plausibility;
  fitProvenance: FitCell[];
  classification: Record<string, Record<string, number>>;
  clampLaps: number[];
  extrapolatedLaps: number;
  maxExcessLaps: number;
  newStintCompound: string | null;
  newStintLaps: number;
  newStintEndTyreAge: number;
  stints: StintRun[];
};

export type DriverFixture = {
  meta: {
    raceKey: string;
    driver: string;
    year: number;
    eventName: string;
    circuit: string;
    totalLaps: number;
    nSeeds: number;
    realFinishPosition: number | null;
    realPitLaps: number[];
    observedMaxTyreAge: Record<string, number>;
    /** Non-null only for races excluded from the Part 8.3 gate aggregate. */
    excludedFromGate: string | null;
    paramFingerprint: Record<string, number>;
    source: string;
  };
  candidates: Candidate[];
};

const urls = import.meta.glob<string>("../fixtures/races/*.json", {
  query: "?url",
  import: "default",
  eager: true,
});

/** "2019_hungarian__VER" -> module URL */
const urlByKey = new Map<string, string>(
  Object.entries(urls).map(([path, url]) => [
    path.split("/").pop()!.replace(/\.json$/, ""),
    url as string,
  ]),
);

const cache = new Map<string, Promise<unknown>>();

export function fixtureKey(raceKey: string, driver: string): string {
  return `${raceKey}__${driver}`;
}

/**
 * Each race also ships one `__base` file with the field-wide data shared by
 * all its drivers. It lives in the same directory and matches the same glob,
 * so it has to be filtered out of anything that enumerates drivers — a test
 * caught `availableDrivers` returning "base" as if it were a driver code.
 */
const BASE_SUFFIX = "base";

/** Races present in the precomputed set, in catalogue-ish (sorted) order. */
export function availableRaces(): string[] {
  return [...new Set([...urlByKey.keys()].map((k) => k.split("__")[0]))].sort();
}

/** Drivers with a precomputed decision space for a race. */
export function availableDrivers(raceKey: string): string[] {
  return [...urlByKey.keys()]
    .filter((k) => k.startsWith(`${raceKey}__`))
    .map((k) => k.split("__")[1])
    .filter((driver) => driver !== BASE_SUFFIX)
    .sort();
}

export type RaceBase = {
  meta: {
    raceKey: string;
    year: number;
    eventName: string;
    circuit: string;
    totalLaps: number;
    excludedFromGate: string | null;
    paramFingerprint: Record<string, number>;
    source: string;
  };
  drivers: {
    code: string;
    team: string;
    gridPosition: number;
    finishPosition: number | null;
    status: string;
    retiredOnLap: number | null;
    hasCandidates: boolean;
    /**
     * Whether any of this driver's decision space is defensible — inside
     * observed tyre age, not leaning on a degenerate degradation cell, inside
     * the plausibility bound. Carried on the shared base file because the UI
     * needs it to choose which driver to open on, before fetching anyone.
     */
    hasDefensibleCandidate: boolean;
  }[];
  /** driver -> [[lap, gapToLeader], ...] */
  realSeries: Record<string, [number, number][]>;
  stints: {
    driver: string;
    compound: string;
    startLap: number;
    endLap: number;
    startTyreAge: number;
    endTyreAge: number;
  }[];
  safetyCarPeriods: { kind: string; startLap: number; endLap: number }[];
};

/** Fetch a race's shared field data. Cached like the driver files. */
export function loadRaceBase(raceKey: string): Promise<RaceBase> {
  return fetchKey(`${raceKey}__${BASE_SUFFIX}`) as Promise<RaceBase>;
}

/** One fetch per key, memoised. Shared by the driver and base loaders. */
function fetchKey(key: string): Promise<unknown> {
  const cached = cache.get(key);
  if (cached) return cached;

  const url = urlByKey.get(key);
  if (!url) {
    return Promise.reject(new Error(`no precomputed fixture for ${key}`));
  }
  const pending = fetch(url)
    .then((response) => {
      if (!response.ok) throw new Error(`failed to load ${key}: ${response.status}`);
      return response.json();
    })
    .catch((error) => {
      // Don't cache failures: a transient network error shouldn't permanently
      // poison this driver for the rest of the session.
      cache.delete(key);
      throw error;
    });
  cache.set(key, pending);
  return pending;
}

/**
 * Fetch one driver's decision space. Cached by key, so repeated selection of
 * the same driver costs nothing and never re-fetches.
 */
export function loadDriverFixture(raceKey: string, driver: string): Promise<DriverFixture> {
  return fetchKey(fixtureKey(raceKey, driver)) as Promise<DriverFixture>;
}

/** Already-resolved fixtures, for tests and cache assertions. */
export function cachedKeys(): string[] {
  return [...cache.keys()].sort();
}

/**
 * Test-only. The cache is module-level and therefore shared by every test in a
 * file, which silently invalidated a fetch-count assertion: an earlier test had
 * already warmed the base file, so the one that counted fetches saw zero.
 */
export function clearFixtureCache(): void {
  cache.clear();
}

/** Expand the compact wire tuples into named fields. */
export function toDeltaPoints(candidate: Candidate): DeltaPoint[] {
  return candidate.deltaVsSimulatedReal.map(([lap, median, low, high, clampedFraction]) => ({
    lap,
    median,
    low,
    high,
    clampedFraction,
  }));
}

/**
 * The replay-error diagnostic, re-joined to its laps. Laps where the driver has
 * no real record (he retired) carry no value and are dropped rather than being
 * plotted at zero.
 */
export function toActualPoints(candidate: Candidate): { lap: number; value: number }[] {
  return candidate.deltaVsActual
    .map(([value], i) => ({ lap: candidate.deltaVsSimulatedReal[i]?.[0] ?? -1, value }))
    .filter((p): p is { lap: number; value: number } => p.value != null && p.lap >= 0);
}

/** Seed trajectories, re-joined to their laps. */
export function toSeedPoints(candidate: Candidate): { seed: number; points: DeltaPoint[] }[] {
  return candidate.seedTraces.map((trace) => ({
    seed: trace.seed,
    points: trace.values.map((value, i) => ({
      lap: candidate.deltaVsSimulatedReal[i]?.[0] ?? -1,
      median: value,
      low: value,
      high: value,
      clampedFraction: 0,
    })),
  }));
}

/**
 * The candidate to open on.
 *
 * Not reality, and emphatically not the largest effect. The largest effects in
 * this catalogue are artifacts: 2019 Hungary VER 67→40 gains 52s because his
 * SOFT degradation was fitted from two laps and came out as exactly zero, so
 * leading with it would headline a broken number that happens to be flagged.
 * Preference order:
 *
 *   1. a genuine counterfactual whose stints stay inside observed tyre age and
 *      which doesn't rest on a degenerate fit, nearest to reality;
 *   2. failing that, the nearest plausible one;
 *   3. failing that, reality itself.
 */
export function pickOpeningCandidate(candidates: Candidate[]): Candidate | null {
  if (candidates.length === 0) return null;
  const distance = (c: Candidate) => Math.abs(c.newLap - c.originalLap);
  const byDistance = [...candidates].sort((a, b) => distance(a) - distance(b));
  return (
    byDistance.find(
      (c) =>
        !c.isReal &&
        c.extrapolatedLaps === 0 &&
        !c.plausibility.restsOnDegenerateFit &&
        !c.plausibility.implausible,
    ) ??
    byDistance.find((c) => !c.isReal && !c.plausibility.implausible) ??
    candidates.find((c) => c.isReal) ??
    byDistance[0]
  );
}

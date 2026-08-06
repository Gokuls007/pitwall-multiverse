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

export type Candidate = {
  originalLap: number;
  newLap: number;
  isReal: boolean;
  divergenceLap: number;
  /** Wire format is a tuple array to keep the payload small. */
  delta: [number, number, number, number, number][];
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
  return candidate.delta.map(([lap, median, low, high, clampedFraction]) => ({
    lap,
    median,
    low,
    high,
    clampedFraction,
  }));
}

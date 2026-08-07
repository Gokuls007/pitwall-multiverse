import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  availableDrivers,
  availableRaces,
  availableStops,
  cachedKeys,
  fixtureKey,
  loadDriverFixture,
  pickOpeningCandidate,
  positionAtLap,
  toActualPoints,
  toDeltaPoints,
  toSeedPoints,
  type Candidate,
} from "./raceFixtures";

/**
 * Phase 6.2's acceptance criterion "loading a driver fetches exactly one file"
 * is about network behaviour, so it is asserted by counting fetches rather than
 * by inspecting the module. The 98-file / 21MB payload is only defensible if
 * this holds.
 */

const originalFetch = globalThis.fetch;

/** A real stop for a driver no other test touches, so the cache starts cold. */
const MEX_LEC_STOP = availableStops("2019_mexican", "LEC")[0];

function stubFetch() {
  const spy = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ meta: { driver: "VER" }, candidates: [] }),
  })) as unknown as typeof fetch;
  globalThis.fetch = spy;
  return spy as unknown as ReturnType<typeof vi.fn>;
}

beforeEach(() => {
  globalThis.fetch = originalFetch;
});

describe("per-driver fixture loading", () => {
  it("discovers every race and driver in the precomputed set", () => {
    const races = availableRaces();
    expect(races.length).toBeGreaterThanOrEqual(5);
    expect(races).toContain("2019_hungarian");
    // Monaco must be offered, not omitted for being outside the gate aggregate.
    expect(races).toContain("2019_monaco");

    const drivers = availableDrivers("2019_hungarian");
    expect(drivers).toContain("VER");
    expect(drivers.length).toBeGreaterThanOrEqual(19);
  });

  it("does not expose drivers from other races", () => {
    const drivers = availableDrivers("2021_spanish");
    expect(drivers.every((d) => /^[A-Z]{3}$/.test(d))).toBe(true);
  });

  it("fetches exactly one file per driver, and caches it", async () => {
    const spy = stubFetch();
    // A key not touched by other tests, so the module-level cache is cold.
    await loadDriverFixture("2019_mexican", "LEC", MEX_LEC_STOP);
    expect(spy).toHaveBeenCalledTimes(1);

    await loadDriverFixture("2019_mexican", "LEC", MEX_LEC_STOP);
    expect(spy).toHaveBeenCalledTimes(1); // served from cache, not re-fetched
    expect(cachedKeys()).toContain(fixtureKey("2019_mexican", "LEC", MEX_LEC_STOP));
  });

  it("rejects an unknown driver without fetching", async () => {
    const spy = stubFetch();
    await expect(loadDriverFixture("2019_hungarian", "ZZZ", 1)).rejects.toThrow(/no precomputed fixture/);
    expect(spy).not.toHaveBeenCalled();
  });

  it("expands the compact wire tuples into named fields", () => {
    const candidate = {
      deltaVsSimulatedReal: [
        [49, 0, 0, 0],
        [50, 2.23, 1.1, 3.4],
      ],
      // The held-up flag is no longer a fifth column on every lap; it is
      // reconstructed from `clampLaps`, which is what that column duplicated.
      clampLaps: [50],
    } as unknown as Candidate;
    const points = toDeltaPoints(candidate);
    expect(points[1]).toEqual({ lap: 50, median: 2.23, low: 1.1, high: 3.4, clampedFraction: 1 });
    expect(points[0].clampedFraction).toBe(0);
  });

  it("re-joins the aligned diagnostic series to their laps", () => {
    // `deltaVsActual` and `seedTraces` carry no lap column — they are aligned
    // index-for-index with the decision-effect series, which is what keeps the
    // per-driver files inside their size budget. If that alignment is ever
    // broken the diagnostic silently plots against the wrong laps.
    const candidate = {
      deltaVsSimulatedReal: [
        [49, 0, 0, 0],
        [50, 2.23, 1.1, 3.4],
        [51, 3.0, 2.0, 4.0],
      ],
      deltaVsActual: [0, 9.1, null],
      seedTraces: [{ seed: 7, values: [0, 1.5, 2.5] }],
      positions: [[3, 3, 3], [4, 3, 6], null],
      clampLaps: [],
    } as unknown as Candidate;

    // Lap 51 has no real record (the driver retired), so it is dropped rather
    // than plotted at zero.
    expect(toActualPoints(candidate)).toEqual([
      { lap: 49, value: 0 },
      { lap: 50, value: 9.1 },
    ]);
    expect(toSeedPoints(candidate)[0].points.map((p) => [p.lap, p.median])).toEqual([
      [49, 0],
      [50, 1.5],
      [51, 2.5],
    ]);

    // Positions are read at a lap, never interpolated between laps — the whole
    // basis of the Phase 6.4 playhead.
    expect(positionAtLap(candidate, 50)).toEqual({ median: 4, best: 3, worst: 6 });
    // Lap 51 has no stored position (he did not complete it), so there is nothing
    // to report rather than something to guess.
    expect(positionAtLap(candidate, 51)).toBeNull();
    expect(positionAtLap(candidate, 99)).toBeNull();
  });

  it("opens on a defensible candidate, not the biggest number", () => {
    // The largest effects in this catalogue are artifacts of degenerate tyre
    // fits, so the opening view must not be chosen by magnitude.
    const make = (over: Record<string, unknown>) =>
      ({
        originalLap: 40,
        isReal: false,
        extrapolatedLaps: 0,
        plausibility: { implausible: false, restsOnDegenerateFit: false },
        ...over,
      }) as unknown as Candidate;

    const reality = make({ newLap: 40, isReal: true });
    const huge = make({ newLap: 20, plausibility: { implausible: true, restsOnDegenerateFit: true } });
    const thinFit = make({ newLap: 39, plausibility: { implausible: false, restsOnDegenerateFit: true } });
    const clean = make({ newLap: 37 });

    expect(pickOpeningCandidate([reality, huge, thinFit, clean])?.newLap).toBe(37);
    // With nothing inside evidence, fall back to the nearest plausible one
    // rather than to reality — but never to the implausible one.
    expect(pickOpeningCandidate([reality, huge, thinFit])?.newLap).toBe(39);
    expect(pickOpeningCandidate([reality, huge])?.newLap).toBe(40);
    expect(pickOpeningCandidate([])).toBeNull();
  });
});

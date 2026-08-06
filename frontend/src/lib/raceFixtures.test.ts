import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  availableDrivers,
  availableRaces,
  cachedKeys,
  fixtureKey,
  loadDriverFixture,
  toDeltaPoints,
  type Candidate,
} from "./raceFixtures";

/**
 * Phase 6.2's acceptance criterion "loading a driver fetches exactly one file"
 * is about network behaviour, so it is asserted by counting fetches rather than
 * by inspecting the module. The 98-file / 21MB payload is only defensible if
 * this holds.
 */

const originalFetch = globalThis.fetch;

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
    await loadDriverFixture("2019_mexican", "LEC");
    expect(spy).toHaveBeenCalledTimes(1);

    await loadDriverFixture("2019_mexican", "LEC");
    expect(spy).toHaveBeenCalledTimes(1); // served from cache, not re-fetched
    expect(cachedKeys()).toContain(fixtureKey("2019_mexican", "LEC"));
  });

  it("rejects an unknown driver without fetching", async () => {
    const spy = stubFetch();
    await expect(loadDriverFixture("2019_hungarian", "ZZZ")).rejects.toThrow(/no precomputed fixture/);
    expect(spy).not.toHaveBeenCalled();
  });

  it("expands the compact wire tuples into named fields", () => {
    const candidate = {
      delta: [
        [49, 0, 0, 0, 0],
        [50, 2.23, 1.1, 3.4, 0.6],
      ],
    } as unknown as Candidate;
    const points = toDeltaPoints(candidate);
    expect(points[1]).toEqual({ lap: 50, median: 2.23, low: 1.1, high: 3.4, clampedFraction: 0.6 });
  });
});

#!/usr/bin/env python
"""Precompute every driver's full decision space, one file per race per driver.

Phase 6.2. This is the data layer for every phase after it.

For each catalogued race, each driver with at least one real pit stop, and each
candidate pit lap the existing valid-range discovery accepts, this runs the
counterfactual ensemble and stores **only what renders**:

  - the median delta trace (alternate minus real **cumulative race time**),
    with the band and the held-up fraction, post-fork laps only
  - the per-driver classification distribution across the ensemble
  - the extrapolation figure from the generalised helper
  - the laps where the stuck-behind clamp fired

Not full `LapState` arrays for every seed. That distinction is the difference
between a payload that loads and one that doesn't: the states exist for
485,100 simulations here, and serialising them would be gigabytes.

Two departures from the naive reading of the spec, both measured first:

1. **Parallel across candidates.** Measured single-threaded cost is 5.3ms per
   simulation and there are 8,085 candidates x 60 seeds = 485,100 simulations,
   i.e. ~43 minutes — above the spec's "well under half an hour" estimate.
   Candidates are independent and the engine is a pure function of
   (snapshot, params, decision, seed), so distributing them changes nothing
   about the output. Determinism is preserved exactly: each simulation still
   derives its own generator from its own seed.

2. **The band is quantiles of the delta, not of a penalty-subtracted gap.**
   Phase 6.1 found that the old `paceLow`/`paceHigh` were
   `gap - cumulative_clamp_penalty`, and that penalty ratchets, so the
   quantity drifted unboundedly negative (-14.66s by lap 65 on the demo case,
   with even the upper bound negative). Clamping it at the gap floor, as 6.1
   required, collapsed the band to nothing in later laps. The fix belongs
   here rather than in the component: the band now reports quantiles of the
   thing actually plotted.

3. **The delta is on cumulative race time, not gap-to-leader.** This is the
   fourth time the y-variable has had to change, and it was found the same way
   as the others: by opening the result in a browser. Gap-to-leader is floored
   at zero for whoever is leading, so on the demo case -- VER led laps 1-66 of
   Hungary 2019 -- differencing two gap-to-leader series gave a delta of
   *identically 0.000s on 26 of the 31 simulated laps*, p10 and p90 included,
   because he led in both timelines. The chart truthfully reported "no
   difference" for a decision that moved a pit stop by 27 laps.

   Cumulative race time has no floor and is defined whether or not the driver
   leads, so `alt.cumulative_time_s - real_cumulative_times(snapshot)` answers
   the question the chart claims to answer. Reality here is the *ingested* lap
   times, not the reality-reproducing simulation, which has a consequence worth
   stating: the delta contains the model's own error as well as the decision's
   effect. That is why the reality-reproducing candidate is kept and shown --
   it is exactly the model-error component, measured on the same axis.

4. **Individual seed traces are not stored.** Measured, they were 71.3% of the
   payload (740KB of a 1067KB file) and pushed per-driver files to 2-3x the
   spec's "low hundreds of KB" — which the spec says to fix by revisiting the
   stored-fields list, not by compressing. They were added in v1 because a lone
   median line reads as *the* answer; that concern is now met more cheaply by
   the p10-p90 delta band (2 numbers per lap, against 12 traces x 2 numbers
   per lap) plus the per-driver classification distribution. Both still satisfy
   spec 6.10's requirement to report a distribution rather than a point.
   `GapChart` keeps its optional `seedSeries` prop, so a single selected
   candidate could be re-simulated for traces later if it proves worth it.

Usage:
    python backend/scripts/build_fixtures.py            # all races
    python backend/scripts/build_fixtures.py --race 2019_hungarian
    python backend/scripts/build_fixtures.py --workers 8
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import warnings
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from pitwall.counterfactual.engine import simulate_counterfactual  # noqa: E402
from pitwall.counterfactual.strategy import (  # noqa: E402
    apply_decision,
    extrapolation_by_lap,
    observed_max_tyre_age,
)
from pitwall.domain.decision import ChangePitLap  # noqa: E402
from pitwall.ingestion.catalogue import CATALOGUE, get_entry  # noqa: E402
from pitwall.ingestion.loader import load_race  # noqa: E402
from pitwall.parameters.fit_all import fit_catalogue_with_pooled_dirty_air  # noqa: E402
from pitwall.simulation.lap_time import AR1_PHI  # noqa: E402
from pitwall.simulation.position import MIN_FOLLOWING_GAP_S  # noqa: E402
from pitwall.validation.metrics import real_cumulative_times, real_gap_to_leader  # noqa: E402

N_SEEDS = 60

OUT_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "fixtures" / "races"

# 2019 Monaco is fitted and simulated like any other race but is excluded from
# the Part 8.3 gate aggregate. It ships with this flag so the UI can carry a
# visible caveat rather than silently omitting the race — a stated weakness is
# more useful than a missing option.
EXCLUDED_FROM_GATE = {
    "2019_monaco": (
        "Weakest parameters in the catalogue: 30% of its driver/compound cells fall back "
        "to pooled or flat estimates (roughly double the next-worst race), and it has the "
        "highest unclamped signed error. Excluded from the Part 8.3 gate aggregate; still "
        "fitted, simulated and shown."
    )
}

# Module-level state for the worker processes, populated once per process by
# `_init_worker` so the snapshot and fitted parameters are not re-pickled for
# every candidate.
_SNAPSHOT = None
_PARAMS = None
_REAL_CUM = None


def _init_worker(race_key: str) -> None:
    global _SNAPSHOT, _PARAMS, _REAL_CUM
    entry = get_entry(race_key)
    snapshot, _ = load_race(entry.year, entry.fastf1_event_identifier)
    _SNAPSHOT = snapshot
    _PARAMS = fit_catalogue_with_pooled_dirty_air([snapshot])[race_key]
    _REAL_CUM = real_cumulative_times(snapshot)


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(int(q * (len(ordered) - 1)), len(ordered) - 1)]


def _stint_runs(records: list[tuple[int, str, int, int]]) -> list[dict]:
    runs: list[dict] = []
    for lap_number, compound, tyre_age, excess in records:
        if runs and runs[-1]["compound"] == compound and lap_number == runs[-1]["endLap"] + 1:
            runs[-1]["endLap"] = lap_number
            runs[-1]["endTyreAge"] = tyre_age
            runs[-1]["extrapolatedLaps"] += 1 if excess > 0 else 0
            runs[-1]["maxExcessLaps"] = max(runs[-1]["maxExcessLaps"], excess)
            if excess > 0 and runs[-1]["firstExtrapolatedLap"] is None:
                runs[-1]["firstExtrapolatedLap"] = lap_number
        else:
            runs.append(
                {
                    "compound": compound,
                    "startLap": lap_number,
                    "endLap": lap_number,
                    "startTyreAge": tyre_age,
                    "endTyreAge": tyre_age,
                    "extrapolatedLaps": 1 if excess > 0 else 0,
                    "maxExcessLaps": excess,
                    "firstExtrapolatedLap": lap_number if excess > 0 else None,
                }
            )
    return runs


def _build_candidate(job: tuple[str, int, int]) -> dict | None:
    """One candidate pit lap: run the ensemble, keep only renderable summaries."""
    driver, original_lap, new_lap = job
    snapshot, params = _SNAPSHOT, _PARAMS
    decision = ChangePitLap(driver=driver, original_lap=original_lap, new_lap=new_lap)

    try:
        overrides = apply_decision(snapshot, decision)
    except ValueError:
        return None
    if not overrides:
        return None

    fork = decision.first_affected_lap
    results = [
        simulate_counterfactual(snapshot, params, decision, seed=seed, include_noise=True)
        for seed in range(N_SEEDS)
    ]

    # --- delta trace, post-fork laps only (pre-fork the delta is 0 by
    # definition: the two timelines are the same history) ---
    by_lap: dict[int, list[float]] = defaultdict(list)
    clamped: dict[int, int] = defaultdict(int)
    for result in results:
        for state in result.lap_states:
            if state.driver != driver or state.lap_number < fork:
                continue
            by_lap[state.lap_number].append(state.cumulative_time_s)
            if state.stuck_behind_clamped:
                clamped[state.lap_number] += 1

    # Anchor at the last shared lap so the frontend's branch anchor has a point.
    anchor = fork - 1
    real_cum = _REAL_CUM.get(driver, {})
    trace: list[list[float]] = []
    if anchor >= 1:
        trace.append([anchor, 0.0, 0.0, 0.0, 0.0])
    for lap in sorted(by_lap):
        real = real_cum.get(lap)
        if real is None:
            # The driver has no real lap here — he retired before it. There is
            # no reality to difference against, so the lap is dropped rather
            # than differenced against zero, which would render a ~5400s spike.
            continue
        deltas = [t - real for t in by_lap[lap]]
        trace.append(
            [
                lap,
                round(statistics.median(deltas), 3),
                # Band is now quantiles of the delta itself (see module docstring).
                round(_quantile(deltas, 0.1), 3),
                round(_quantile(deltas, 0.9), 3),
                round(clamped.get(lap, 0) / len(results), 3),
            ]
        )

    # --- per-driver classification distribution across the ensemble ---
    counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for result in results:
        for code, position in result.classification:
            counts[code][position] += 1
    classification = {
        code: {str(pos): n for pos, n in sorted(per.items())} for code, per in counts.items()
    }

    # --- strategy + extrapolation ---
    excess_by_lap = extrapolation_by_lap(snapshot, overrides)
    real_by_lap = {lap.lap_number: lap for lap in snapshot.laps if lap.driver == driver}
    records = []
    for lap_number in sorted(real_by_lap):
        effective = overrides.get((driver, lap_number), real_by_lap[lap_number])
        records.append(
            (
                lap_number,
                effective.compound.value,
                effective.tyre_life,
                excess_by_lap.get((driver, lap_number), 0),
            )
        )
    runs = _stint_runs(records)
    new_stint = runs[-1] if runs else None

    return {
        "originalLap": original_lap,
        "newLap": new_lap,
        "isReal": new_lap == original_lap,
        "divergenceLap": fork,
        "delta": trace,
        "classification": classification,
        "clampLaps": sorted(lap for lap, n in clamped.items() if n > len(results) / 2),
        "extrapolatedLaps": sum(1 for e in excess_by_lap.values() if e > 0),
        "maxExcessLaps": max(excess_by_lap.values(), default=0),
        "newStintCompound": new_stint["compound"] if new_stint else None,
        "newStintLaps": (new_stint["endLap"] - new_stint["startLap"] + 1) if new_stint else 0,
        "newStintEndTyreAge": new_stint["endTyreAge"] if new_stint else 0,
        "stints": runs,
    }


def build_race(race_key: str, workers: int) -> dict:
    entry = get_entry(race_key)
    snapshot, _ = load_race(entry.year, entry.fastf1_event_identifier)
    params = fit_catalogue_with_pooled_dirty_air([snapshot])[race_key]

    fingerprint = {
        "minFollowingGapS": MIN_FOLLOWING_GAP_S,
        "ar1Phi": AR1_PHI,
        "pitLaneLossS": round(params.pit_lane_loss_s, 4),
        "overtakeDifficulty": round(params.overtake_difficulty, 6),
        "dirtyAirMaxPenaltyS": round(params.dirty_air.max_penalty_s, 6),
        "dirtyAirDecayScaleS": round(params.dirty_air.decay_scale_s, 6),
    }

    real_finish = {d.code: d.finish_position for d in snapshot.drivers}
    drivers_with_stops = sorted({lap.driver for lap in snapshot.laps if lap.is_in_lap})

    jobs: list[tuple[str, int, int]] = []
    for driver in drivers_with_stops:
        stops = sorted({lap.lap_number for lap in snapshot.laps if lap.driver == driver and lap.is_in_lap})
        for original in stops:
            for candidate_lap in range(1, snapshot.total_laps + 1):
                jobs.append((driver, original, candidate_lap))

    started = time.time()
    by_driver: dict[str, list[dict]] = defaultdict(list)
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(race_key,)) as pool:
        for job, candidate in zip(jobs, pool.map(_build_candidate, jobs, chunksize=4), strict=True):
            if candidate is not None:
                by_driver[job[0]].append(candidate)
    elapsed = time.time() - started

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = []

    # --- Per-race base file ---
    # Everything shared by all drivers on this race: real gap-to-leader for the
    # whole field (field mode needs it and the per-driver candidate files
    # deliberately don't duplicate it), real stints, SC periods, and the real
    # classification. Selecting a race fetches this once; selecting a driver
    # then fetches exactly one candidate file.
    real_gaps = real_gap_to_leader(snapshot)
    real_series: dict[str, list[list[float]]] = defaultdict(list)
    for (driver, lap_number), gap in sorted(real_gaps.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        real_series[driver].append([lap_number, round(gap, 2)])

    tyre_age = {(lap.driver, lap.lap_number): lap.tyre_life for lap in snapshot.laps}

    def age_bounds(driver: str, start: int, end: int) -> tuple[int, int]:
        ages = [tyre_age[(driver, lap)] for lap in range(start, end + 1) if (driver, lap) in tyre_age]
        return (min(ages), max(ages)) if ages else (0, 0)

    base = {
        "meta": {
            "raceKey": race_key,
            "year": snapshot.year,
            "eventName": snapshot.event_name,
            "circuit": snapshot.circuit,
            "totalLaps": snapshot.total_laps,
            "excludedFromGate": EXCLUDED_FROM_GATE.get(race_key),
            "paramFingerprint": fingerprint,
            "source": "backend/scripts/build_fixtures.py",
        },
        "drivers": [
            {
                "code": d.code,
                "team": d.team,
                "gridPosition": d.grid_position,
                "finishPosition": d.finish_position,
                "status": d.status,
                "retiredOnLap": d.retired_on_lap,
                # Whether a precomputed decision space exists for this driver.
                "hasCandidates": d.code in by_driver,
            }
            for d in snapshot.drivers
        ],
        "realSeries": real_series,
        "stints": [
            {
                "driver": s.driver,
                "compound": s.compound.value,
                "startLap": s.start_lap,
                "endLap": s.end_lap,
                "startTyreAge": age_bounds(s.driver, s.start_lap, s.end_lap)[0],
                "endTyreAge": age_bounds(s.driver, s.start_lap, s.end_lap)[1],
            }
            for s in snapshot.stints
        ],
        "safetyCarPeriods": [
            {"kind": p.kind, "startLap": p.start_lap, "endLap": p.end_lap}
            for p in snapshot.safety_car_periods
        ],
    }
    base_path = OUT_DIR / f"{race_key}__base.json"
    base_path.write_text(json.dumps(base, separators=(",", ":")), encoding="utf-8")
    written.append((base_path, base_path.stat().st_size))
    for driver, candidates in sorted(by_driver.items()):
        candidates.sort(key=lambda c: (c["originalLap"], c["newLap"]))
        payload = {
            "meta": {
                "raceKey": race_key,
                "driver": driver,
                "year": snapshot.year,
                "eventName": snapshot.event_name,
                "circuit": snapshot.circuit,
                "totalLaps": snapshot.total_laps,
                "nSeeds": N_SEEDS,
                "realFinishPosition": real_finish.get(driver),
                "realPitLaps": sorted(
                    {lap.lap_number for lap in snapshot.laps if lap.driver == driver and lap.is_in_lap}
                ),
                "observedMaxTyreAge": {
                    c.value: age for c, age in observed_max_tyre_age(snapshot, driver).items()
                },
                "excludedFromGate": EXCLUDED_FROM_GATE.get(race_key),
                "paramFingerprint": fingerprint,
                "source": "backend/scripts/build_fixtures.py",
            },
            "candidates": candidates,
        }
        path = OUT_DIR / f"{race_key}__{driver}.json"
        path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        written.append((path, path.stat().st_size))

    return {
        "raceKey": race_key,
        "elapsedS": elapsed,
        "nCandidates": sum(len(v) for v in by_driver.values()),
        "nDrivers": len(by_driver),
        "files": written,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--race", action="append", help="race_key; repeatable. Default: all.")
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()

    import multiprocessing as mp

    # Capped rather than cpu_count-1. Each worker holds its own snapshot and
    # fitted parameters, and at 31 workers on a 32-core machine the pool died
    # with BrokenProcessPool partway through the catalogue — resource pressure,
    # not a bug in a candidate (the same race rebuilt cleanly with 8). The cap
    # costs ~40s per race against the theoretical best and makes a ~10 minute
    # full rebuild reliable, which matters because fixtures must be regenerated
    # whenever a parameter moves.
    workers = args.workers or max(1, min(mp.cpu_count() - 1, 10))
    race_keys = args.race or [entry.race_key for entry in CATALOGUE]

    print(f"workers={workers}  seeds={N_SEEDS}  races={len(race_keys)}")
    grand_start = time.time()
    summaries = []
    for race_key in race_keys:
        result = build_race(race_key, workers)
        sizes = [size for _, size in result["files"]]
        print(
            f"  {race_key}: {result['nCandidates']} candidates across {result['nDrivers']} drivers "
            f"in {result['elapsedS']:.0f}s | files {len(sizes)} "
            f"| per-file min {min(sizes) / 1024:.0f}KB med {sorted(sizes)[len(sizes) // 2] / 1024:.0f}KB "
            f"max {max(sizes) / 1024:.0f}KB | total {sum(sizes) / 1024 / 1024:.1f}MB"
        )
        summaries.append(result)

    total_files = [s for r in summaries for _, s in r["files"]]
    print()
    print(f"TOTAL: {sum(r['nCandidates'] for r in summaries)} candidates, {len(total_files)} files, "
          f"{sum(total_files) / 1024 / 1024:.1f}MB, {time.time() - grand_start:.0f}s")


if __name__ == "__main__":
    main()

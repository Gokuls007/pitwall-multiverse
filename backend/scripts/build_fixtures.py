#!/usr/bin/env python
"""Precompute every driver's full decision space, one file per race per driver.

Phase 6.2. This is the data layer for every phase after it.

For each catalogued race, each driver with at least one real pit stop, and each
candidate pit lap the existing valid-range discovery accepts, this runs the
counterfactual ensemble and stores **only what renders**:

  - `deltaVsSimulatedReal`: the decision effect. Alternate cumulative race time
    minus the override-free fork at the same lap with the same seed, with the
    p10-p90 band and the held-up fraction, post-fork laps only
  - `deltaVsActual`: the same alternate against the *ingested* cumulative
    times. Decision effect plus the simulator's replay error, kept as a
    labelled model-quality diagnostic
  - three individual seed trajectories of the decision effect
  - a plausibility verdict, so an answer produced by extrapolating the
    degradation model past its evidence is marked as such in the data
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
   leads, so differencing it answers the question the chart claims to answer.

4. **The baseline is the simulated replay of reality, not the ingested times.**
   The first version of (3) differenced the simulated alternate against the
   *actual* cumulative times, which put the simulator's replay error into every
   candidate's delta. On Hungary/VER that error is 7.4s by lap 70, so any
   candidate whose real effect is a couple of seconds was swamped by it. Both
   sides now come from the simulator -- same fork lap, same seed, no overrides
   -- so the systematic replay error cancels and what is left is attributable to
   the decision. `deltaVsActual` keeps the other quantity as a labelled
   model-quality diagnostic, because it is genuinely useful; it just isn't the
   answer to "what did this decision cost".

   The reference is `fork_and_simulate(..., overrides={})`, which Phase 4's
   no-op test pins byte-for-byte against a no-op `ChangePitLap`. So the
   reality-reproducing candidate's decision effect is exactly 0.000, and
   `test_the_reality_reproducing_candidate_has_exactly_zero_decision_effect`
   asserts it.

5. **Three seed traces, not twelve and not zero.** Twelve were measured at 71.3%
   of the payload (740KB of a 1067KB file), pushing per-driver files to 2-3x the
   spec's "low hundreds of KB", and were dropped on the argument that the
   p10-p90 band covers the original concern (a lone median line reading as *the*
   answer). That argument was incomplete: a band cannot show a *bimodal*
   ensemble. If the driver either completes a pass or doesn't, the band spans
   both modes and the median line sits in a region no seed ever occupied -- the
   classification distribution reveals that split in the outcome while the band
   hides it in the trajectory. Three traces cost one number per lap each (~9% of
   what twelve cost, since they carry no lap column) and are chosen at the
   p10/p50/p90 of final delta rather than at random, so when the ensemble does
   split they land in the modes instead of all three landing in the more
   populous one.

6. **A plausibility bound, and why a bound alone is not enough.** A moved pit
   stop that changes the race by more than twice the fitted pit-lane loss is
   recorded as implausible. Auditing what that caught showed a bound cannot, by
   itself, distinguish two unrelated causes -- a degenerate tyre cell and a
   traffic-dominated result -- so `fitProvenance` and a pace/traffic split are
   stored alongside it. See the plausibility block in `_build_candidate`.

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

from pitwall.counterfactual.engine import fork_and_simulate, simulate_counterfactual  # noqa: E402
from pitwall.counterfactual.strategy import (  # noqa: E402
    apply_decision,
    extrapolation_by_lap,
    observed_max_tyre_age,
)
from pitwall.domain.decision import ChangePitLap  # noqa: E402
from pitwall.ingestion.catalogue import CATALOGUE, get_entry  # noqa: E402
from pitwall.ingestion.loader import load_race  # noqa: E402
from pitwall.parameters.fit_all import (  # noqa: E402
    fit_catalogue_with_pooled_dirty_air,
    tyre_model_digest,
)
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
        "to cross-driver pooled estimates (roughly double the next-worst race), and it has the "
        "highest unclamped signed error. Excluded from the Part 8.3 gate aggregate; still "
        "fitted, simulated and shown."
    )
}

# Multiple of the fitted pit-lane loss beyond which a single moved pit stop is
# treated as an extrapolation artifact rather than a finding. See the
# plausibility block in `_build_candidate`.
PLAUSIBLE_SWING_MULTIPLE_OF_PIT_LOSS = 2.0

# Below this many usable laps, a driver/compound degradation fit is reported as
# degenerate. Five is not a claim that five is enough -- it is the point below
# which a linear fit through the noise is arbitrary. VER's SOFT cell at 2019
# Hungary has two.
MIN_USABLE_TYRE_OBSERVATIONS = 5

# Module-level state for the worker processes, populated once per process by
# `_init_worker` so the snapshot and fitted parameters are not re-pickled for
# every candidate.
_SNAPSHOT = None
_PARAMS = None
_REAL_CUM = None
# fork lap -> driver -> lap -> [cumulative time per seed], for the override-free
# fork. Memoised because the baseline depends only on the fork lap: with no
# overrides the whole field runs its real strategy, so one baseline ensemble
# serves every candidate of every driver that forks there. ~70 forks x 20
# drivers x 60 seeds of floats is around 25MB per worker, and it saves
# recomputing the same reference ensemble thousands of times.
_BASE_CUM: dict[int, dict[str, dict[int, list[tuple[float, float]]]]] = {}


def _init_worker(race_key: str) -> None:
    global _SNAPSHOT, _PARAMS, _REAL_CUM, _BASE_CUM
    entry = get_entry(race_key)
    snapshot, _ = load_race(entry.year, entry.fastf1_event_identifier)
    _SNAPSHOT = snapshot
    _PARAMS = fit_catalogue_with_pooled_dirty_air([snapshot])[race_key]
    _REAL_CUM = real_cumulative_times(snapshot)
    _BASE_CUM = {}


def _baseline_cumulative(fork: int) -> dict[str, dict[int, list[float]]]:
    """The simulated replay of reality, forked at the same lap with the same
    seeds and no strategy overrides.

    This is the baseline every decision effect is measured against. Using the
    *actual* cumulative times instead puts the simulator's replay error into
    every candidate's delta -- on Hungary/VER that error reaches 7.4s, which
    would swamp any candidate whose real effect is a couple of seconds. Both
    sides now come from the simulator, so the systematic component of the
    replay error cancels and what remains is attributable to the decision.

    `fork_and_simulate` with `overrides={}` is the reference the Phase 4 no-op
    test pins byte-for-byte against a no-op `ChangePitLap`, so for the
    reality-reproducing candidate this baseline makes the decision effect
    exactly 0.000 rather than approximately zero.

    One limit, stated because it is easy to overclaim: pairing by seed cancels
    the systematic error and the shared pre-fork history exactly, but not the
    stochastic draws. Once the decision changes a lap time the two runs consume
    their generator differently, so their noise diverges after the fork by
    construction. That residual is what the p10-p90 band reports.
    """
    cached = _BASE_CUM.get(fork)
    if cached is not None:
        return cached

    by_driver: dict[str, dict[int, list[tuple[float, float]]]] = defaultdict(lambda: defaultdict(list))
    for seed in range(N_SEEDS):
        result = fork_and_simulate(_SNAPSHOT, _PARAMS, {}, fork, seed=seed, include_noise=True)
        for state in result.lap_states:
            if state.lap_number >= fork:
                by_driver[state.driver][state.lap_number].append(
                    (state.cumulative_time_s, state.cumulative_clamp_penalty_s)
                )
    _BASE_CUM[fork] = by_driver
    return by_driver


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(int(q * (len(ordered) - 1)), len(ordered) - 1)]


def _stint_runs(records: list[tuple[int, str, int, int]]) -> list[dict]:
    runs: list[dict] = []
    for lap_number, compound, tyre_age, excess in records:
        # Tyre-age continuity, not just compound and lap adjacency. Two stints on
        # the same compound separated by a real pit stop look identical on those
        # two tests, and merging them hid a stop: 2021 Spanish HAM 28->12 reported
        # one 54-lap MEDIUM stint where the strategy is a 30-lap stint, the real
        # lap-42 stop, and then 24 laps on a used set starting at age 7. The
        # timeline drew no stop and the panel offered "a 54-lap stint".
        if (
            runs
            and runs[-1]["compound"] == compound
            and lap_number == runs[-1]["endLap"] + 1
            and tyre_age == runs[-1]["endTyreAge"] + 1
        ):
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


def _cause(
    *,
    implausible: bool,
    extrapolated_laps: int,
    rests_on_degenerate_fit: bool,
    traffic: float,
    pace: float,
) -> str | None:
    """Which part of the model is responsible for an implausible answer.

    Order matters: a degenerate degradation cell is the most damning finding, so
    it is named ahead of "runs past observed tyre age" when both apply -- the
    latter is a quantity of exposure, the former says the fitted curve was never
    meaningful in the first place.
    """
    if not implausible:
        return None
    if rests_on_degenerate_fit:
        return "degenerateFit"
    if abs(traffic) > abs(pace):
        return "traffic"
    if extrapolated_laps > 0:
        return "extrapolation"
    return "unexplained"


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

    # --- delta traces, post-fork laps only (pre-fork the delta is 0 by
    # definition: the two timelines are the same history) ---
    #
    # TWO series, because they answer different questions and conflating them
    # made the decision effect unreadable:
    #
    #   deltaVsSimulatedReal -- alternate against the override-free fork at the
    #     same lap with the same seed. This is "what did the decision do", and
    #     it is what the chart plots.
    #   deltaVsActual -- alternate against the ingested cumulative times. This
    #     is the decision effect PLUS the simulator's replay error, so it is
    #     kept as a labelled model-quality diagnostic, never as the answer.
    by_lap: dict[int, list[float]] = defaultdict(list)
    clamped: dict[int, int] = defaultdict(int)
    for result in results:
        for state in result.lap_states:
            if state.driver != driver or state.lap_number < fork:
                continue
            by_lap[state.lap_number].append(
                (state.cumulative_time_s, state.cumulative_clamp_penalty_s)
            )
            if state.stuck_behind_clamped:
                clamped[state.lap_number] += 1

    baseline = _baseline_cumulative(fork).get(driver, {})
    real_cum = _REAL_CUM.get(driver, {})

    # Anchor at the last shared lap so the frontend's branch anchor has a point.
    anchor = fork - 1
    trace: list[list[float]] = []
    actual_trace: list[list[float | None]] = []
    traffic_by_lap: list[float] = []
    # Per-seed decision-effect deltas, kept aligned with `trace` so a few
    # individual trajectories can be drawn (see `seedTraces` below).
    per_seed: list[list[float]] = []
    if anchor >= 1:
        trace.append([anchor, 0.0, 0.0, 0.0, 0.0])
        actual_trace.append([0.0])
        traffic_by_lap.append(0.0)
        per_seed.append([0.0] * len(results))

    for lap in sorted(by_lap):
        alt = by_lap[lap]
        base = baseline.get(lap)
        if base is None or len(base) != len(alt):
            # No paired baseline for this lap: the driver is beyond his real
            # race distance in the baseline (he retired) so there is nothing to
            # measure the decision against. Dropped rather than differenced
            # against zero, which would render a ~5400s spike.
            continue
        deltas = [a[0] - b[0] for a, b in zip(alt, base, strict=True)]
        # How much of that difference is accumulated held-up time rather than
        # pace. Kept separate for the reason GapChart's docstring already
        # insists on: "how much traffic did he hit" is not "how much quicker
        # was he", and a single number that merges them can't be read.
        traffic = [a[1] - b[1] for a, b in zip(alt, base, strict=True)]
        trace.append(
            [
                lap,
                round(statistics.median(deltas), 3),
                # Band is quantiles of the delta itself (see module docstring).
                round(_quantile(deltas, 0.1), 2),
                round(_quantile(deltas, 0.9), 2),
                round(clamped.get(lap, 0) / len(results), 3),
            ]
        )
        per_seed.append(deltas)

        traffic_by_lap.append(round(statistics.median(traffic), 3))

        real = real_cum.get(lap)
        # Aligned index-for-index with `deltaVsSimulatedReal` rather than
        # carrying its own lap column, which halves it.
        actual_trace.append(
            [round(statistics.median(a[0] - real for a in alt), 2)] if real is not None else [None]
        )

    # --- A few real trajectories, not just the summary (spec 6.10) ---
    #
    # Twelve traces were 71.3% of the payload and were dropped for that reason;
    # three cost almost nothing (one number per lap each) and buy back the thing
    # the band cannot show. If the outcome is bimodal -- he makes the pass or he
    # doesn't -- the p10-p90 band spans both modes and the median line sits in a
    # region no seed ever occupied. These are actual seeds, so each one is a
    # universe that happened, and the gap between them is visible.
    #
    # Chosen at the p10/p50/p90 of FINAL delta rather than at random, so when
    # the ensemble does split the traces land in the modes rather than all
    # three landing in whichever mode is more populous.
    seed_traces: list[dict] = []
    if per_seed:
        finals = per_seed[-1]
        order = sorted(range(len(finals)), key=lambda i: finals[i])
        picks = sorted({order[int(q * (len(order) - 1))] for q in (0.1, 0.5, 0.9)})
        seed_traces = [
            # `values` is aligned index-for-index with `deltaVsSimulatedReal`,
            # so the laps are not repeated per trace.
            {"seed": i, "values": [round(row[i], 2) for row in per_seed]}
            for i in picks
        ]

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

    # --- plausibility ---
    #
    # A tyre model fitted mostly as pure linear degradation (Phase 2 adopted a
    # cliff only where the data supported one, which was rare) says a soft tyre
    # stays quicker than a hard one indefinitely when extrapolated, because
    # nothing in the fitted form knows about falling off a cliff. Run that past
    # its evidence and the engine concludes "start the fast tyre earlier and
    # keep it on", producing gains of a minute over a race distance. Those
    # answers are artifacts of the functional form, not strategy findings.
    #
    # The bound is twice the fitted pit-lane loss. Moving one stop can plausibly
    # swing the race by about the pit loss itself plus the tyre-pace integral
    # before the fresher tyre is handed back; twice that is already generous, so
    # past it the number is being produced by extrapolation. Recorded per
    # candidate rather than filtered out, because these cases are the clearest
    # illustration of why the caution shading exists -- they just must not be
    # read as results.
    final_delta = trace[-1][1] if trace else 0.0
    bound = round(PLAUSIBLE_SWING_MULTIPLE_OF_PIT_LOSS * params.pit_lane_loss_s, 2)
    post_fork_laps = max(1, len(trace) - 1)
    implausible = abs(final_delta) > bound
    final_traffic = traffic_by_lap[-1] if traffic_by_lap else 0.0

    # --- fit provenance: WHY an answer is implausible, not just that it is ---
    #
    # The bound above is a symptom test, and auditing what it caught showed two
    # unrelated causes that it cannot tell apart:
    #
    #   VER 67->40 (-62.7s). His SOFT cell is fitted from **2 observations**,
    #     with a linear degradation rate of exactly 0.0000 s/lap and r2 = nan.
    #     The model has been told his softs never degrade, so they stay ~1.5s/lap
    #     faster than his hards at any age and 4.6s/lap faster once the hard
    #     reaches its cliff. Extrapolating that for 30 laps gains a minute.
    #     `extrapolatedLaps` flags the 27 laps past observed age, but nothing
    #     said the cell itself was degenerate.
    #   BOT 5->20 (-108s). Its cells are fine (MEDIUM n=25, r2=0.74, with a
    #     fitted cliff at lap 12). The swing is the traffic model: the baseline
    #     is clamped on 40 of 65 laps for 119.2s of held-up time against 54.1s
    #     in the alternate. Arguably a real effect -- don't pit into the back of
    #     the field -- but it is not a pace finding, and `trafficS` now says so.
    #
    # So provenance is recorded per compound the alternate actually relies on.
    # How many post-fork laps actually run on each compound. Without this the
    # flag over-fires: every VER candidate touches his degenerate SOFT cell,
    # because his real final stint is on softs, so moving his *first* stop by one
    # lap was reported as resting on a degenerate fit on the strength of three
    # laps. An answer rests on a cell when a meaningful stretch of it is
    # simulated with that cell.
    post_fork_laps_by_compound: dict[str, int] = defaultdict(int)
    for lap_number, compound, _age, _excess in records:
        if lap_number >= fork:
            post_fork_laps_by_compound[compound] += 1

    driver_params = params.drivers.get(driver)
    provenance = []
    for compound in sorted({run["compound"] for run in runs}):
        model = None
        if driver_params is not None:
            model = next(
                (m for c, m in driver_params.tyre_models.items() if c.value == compound), None
            )
        relied_on = post_fork_laps_by_compound.get(compound, 0)
        if model is None:
            provenance.append(
                {
                    "compound": compound,
                    "nObservations": 0,
                    "postForkLaps": relied_on,
                    "degenerate": True,
                }
            )
            continue
        r2 = model.r_squared
        provenance.append(
            {
                "compound": compound,
                "nObservations": model.n_observations,
                "postForkLaps": relied_on,
                # JSON has no NaN; a fit with no r2 is reported as absent.
                "rSquared": None if r2 is None or r2 != r2 else round(r2, 3),
                "linearDegSPerLap": round(model.linear_deg_s_per_lap, 5),
                "cliffLap": model.cliff_lap,
                "degenerate": (
                    model.n_observations < MIN_USABLE_TYRE_OBSERVATIONS
                    or model.linear_deg_s_per_lap == 0.0
                    or r2 is None
                    or r2 != r2
                ),
            }
        )

    return {
        "originalLap": original_lap,
        "newLap": new_lap,
        "isReal": new_lap == original_lap,
        "divergenceLap": fork,
        "deltaVsSimulatedReal": trace,
        "deltaVsActual": actual_trace,
        "seedTraces": seed_traces,
        "plausibility": {
            "finalDeltaS": final_delta,
            "sPerLap": round(final_delta / post_fork_laps, 3),
            "boundS": bound,
            "implausible": implausible,
            # Named here rather than re-derived by each consumer, so the UI's
            # caption and the test's assertion cannot drift apart. "unexplained"
            # is a real and deliberate value: 2 of 8,085 candidates exceed the
            # bound with none of the known causes, and saying so is better than
            # tuning the bound until they disappear or attributing them to a
            # mechanism that isn't responsible.
            "cause": _cause(
                implausible=implausible,
                extrapolated_laps=sum(1 for e in excess_by_lap.values() if e > 0),
                rests_on_degenerate_fit=any(
                    cell["degenerate"] and cell["postForkLaps"] >= MIN_USABLE_TYRE_OBSERVATIONS
                    for cell in provenance
                ),
                traffic=final_traffic,
                pace=final_delta - final_traffic,
            ),
            # Of that final delta, how much is accumulated held-up time.
            "trafficS": final_traffic,
            "paceS": round(final_delta - final_traffic, 3),
            "restsOnDegenerateFit": any(
                cell["degenerate"] and cell["postForkLaps"] >= MIN_USABLE_TYRE_OBSERVATIONS
                for cell in provenance
            ),
        },
        "fitProvenance": provenance,
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
        # Covers every driver/compound degradation cell. Added after correcting
        # the degradation fallback chain invalidated all 103 files without any
        # fingerprint test being able to notice.
        "tyreModelDigest": tyre_model_digest(params),
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
                # Whether any of it is defensible: a real counterfactual that
                # stays inside observed tyre age, doesn't lean on a degenerate
                # degradation cell, and is inside the plausibility bound.
                #
                # Here rather than in the per-driver files because the UI needs
                # it to *choose* which driver to open on, before it has fetched
                # anyone. Without it the opening view was VER at Hungary, who
                # has no defensible candidate at all -- every way of moving
                # either of his stops runs his HARD stint to age 43 against the
                # 42 he reached, or leans on a SOFT cell fitted from two laps.
                "hasDefensibleCandidate": any(
                    not c["isReal"]
                    and c["extrapolatedLaps"] == 0
                    and not c["plausibility"]["implausible"]
                    and not c["plausibility"]["restsOnDegenerateFit"]
                    for c in by_driver.get(d.code, [])
                ),
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

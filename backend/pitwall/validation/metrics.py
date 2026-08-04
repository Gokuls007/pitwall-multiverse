"""Accuracy metrics (spec 8.2). Every function compares one `SimulationResult`
against the real `RaceSnapshot` it was replayed from; `report.py` aggregates
across an ensemble and across races.

Real cumulative time and gap-to-leader aren't stored directly on
`RaceSnapshot` (only per-lap time and gap-to-*car-ahead*), so both are
reconstructed here by summing real lap times sequentially, skipping laps
with a missing `lap_time_s` without breaking the chain for later laps —
matching exactly how `simulation/engine.py` treats a missing lap: skip and
continue, not stop.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from scipy.stats import spearmanr

from pitwall.domain.race import RaceSnapshot
from pitwall.domain.result import SimulationResult

# Spec 8.3: "Green-flag lap time MAE: under half a second per lap for the
# majority of drivers." A driver's real lap is green-flag iff it was usable
# for fitting (spec 4.2's cleaning already encodes exactly this).


def real_cumulative_times(snapshot: RaceSnapshot) -> dict[str, dict[int, float]]:
    by_driver: dict[str, list] = defaultdict(list)
    for lap in snapshot.laps:
        by_driver[lap.driver].append(lap)

    result: dict[str, dict[int, float]] = {}
    for driver, laps in by_driver.items():
        cumulative = 0.0
        per_lap: dict[int, float] = {}
        for lap in sorted(laps, key=lambda l: l.lap_number):
            if lap.lap_time_s is not None:
                cumulative += lap.lap_time_s
                per_lap[lap.lap_number] = cumulative
        result[driver] = per_lap
    return result


def real_gap_to_leader(snapshot: RaceSnapshot) -> dict[tuple[str, int], float]:
    cumulative = real_cumulative_times(snapshot)
    by_lap: dict[int, dict[str, float]] = defaultdict(dict)
    for driver, laps in cumulative.items():
        for lap_number, t in laps.items():
            by_lap[lap_number][driver] = t

    result: dict[tuple[str, int], float] = {}
    for lap_number, times in by_lap.items():
        leader_time = min(times.values())
        for driver, t in times.items():
            result[(driver, lap_number)] = t - leader_time
    return result


def lap_time_accuracy(
    snapshot: RaceSnapshot, result: SimulationResult, green_flag_only: bool = False
) -> dict:
    real_by_key = {(lap.driver, lap.lap_number): lap for lap in snapshot.laps}
    errors: list[float] = []
    per_driver_errors: dict[str, list[float]] = defaultdict(list)

    for state in result.lap_states:
        real = real_by_key.get((state.driver, state.lap_number))
        if real is None or real.lap_time_s is None:
            continue
        if green_flag_only and not real.is_usable_for_fitting:
            continue
        error = abs(state.lap_time_s - real.lap_time_s)
        errors.append(error)
        per_driver_errors[state.driver].append(error)

    if not errors:
        return {"n_laps": 0, "overall_mae_s": float("nan")}

    errors_arr = np.array(errors)
    return {
        "n_laps": len(errors),
        "overall_mae_s": float(errors_arr.mean()),
        "error_std_s": float(errors_arr.std()),
        "error_p95_s": float(np.percentile(errors_arr, 95)),
        "per_driver_mae_s": {d: float(np.mean(e)) for d, e in per_driver_errors.items()},
    }


def open_loop_green_flag_lap_time_accuracy(snapshot: RaceSnapshot, race_params) -> dict:
    """Spec 8.2's fairest test of the pace/tyre/dirty-air model *in isolation
    from position tracking* — and the number spec 8.3's green-flag MAE
    threshold is actually about. For every real green-flag lap, predicts
    lap time from the fitted model using that lap's *real* gap-to-car-ahead
    and real compound/tyre-age directly — no replay loop, no cumulative
    time, no position resolution, no stuck-behind clamp, deterministic (no
    RNG, no ensemble needed).

    Why this exists as a separate metric from `lap_time_accuracy`'s
    closed-loop, replayed version: found on this catalogue that the
    closed-loop replay's simulated car-ahead differs from the real
    car-ahead on 65-85% of green-flag laps (position tracking, seeded by a
    stochastic overtake model, drifts from reality well within a single
    race even though it's fed real strategies/compounds/SC periods
    throughout). Scoring the pace model against those largely-fictional
    simulated gaps conflates "is the pace model right" with "did position
    tracking stay on the rails" — two different questions with two
    different fixes (see DECISIONS.md). This function isolates the first
    question; `lap_time_accuracy`'s closed-loop number remains meaningful
    as a race-shape/position-accuracy diagnostic, not as spec 8.3's
    pace-accuracy criterion.
    """
    from pitwall.simulation.lap_time import compose_lap_time_s
    from pitwall.simulation.rng import make_rng

    rng = make_rng(0)  # unused: include_noise=False below, kept for the signature
    errors: list[float] = []
    per_driver_errors: dict[str, list[float]] = defaultdict(list)

    for lap in snapshot.laps:
        if not lap.is_usable_for_fitting or lap.lap_time_s is None:
            continue
        params = race_params.drivers.get(lap.driver)
        if params is None or lap.compound not in params.tyre_models:
            continue
        predicted = compose_lap_time_s(
            driver_params=params,
            compound=lap.compound,
            tyre_age=lap.tyre_life,
            lap_number=lap.lap_number,
            fuel_effect_s_per_lap=race_params.fuel_effect_s_per_lap,
            dirty_air_model=race_params.dirty_air,
            gap_to_ahead_s=lap.gap_to_ahead_s,
            is_under_sc=False,
            is_under_vsc=False,
            sc_lap_time_multiplier=1.0,
            vsc_lap_time_multiplier=1.0,
            pit_lane_loss_s=0.0,
            is_in_lap=False,
            is_out_lap=False,
            rng=rng,
            include_noise=False,
        )
        error = abs(predicted - lap.lap_time_s)
        errors.append(error)
        per_driver_errors[lap.driver].append(error)

    if not errors:
        return {"n_laps": 0, "overall_mae_s": float("nan")}

    errors_arr = np.array(errors)
    return {
        "n_laps": len(errors),
        "overall_mae_s": float(errors_arr.mean()),
        "per_driver_mae_s": {d: float(np.mean(e)) for d, e in per_driver_errors.items()},
    }


def gap_to_leader_rmse(snapshot: RaceSnapshot, result: SimulationResult) -> float:
    real_gaps = real_gap_to_leader(snapshot)
    squared_errors = [
        (state.gap_to_leader_s - real_gaps[(state.driver, state.lap_number)]) ** 2
        for state in result.lap_states
        if (state.driver, state.lap_number) in real_gaps
    ]
    return float(np.sqrt(np.mean(squared_errors))) if squared_errors else float("nan")


def _real_classification_for_metrics(snapshot: RaceSnapshot) -> dict[str, int]:
    """Real finish position per driver, excluding classified-but-retired
    drivers — decided in Phase 2 (see DECISIONS.md): a driver who is
    classified (completed >=90% of race distance) but actually stopped
    racing early has a real position that reflects where they were *when
    they stopped*, not a fair target for a simulator that keeps running them
    to the flag. They are still fully simulated; just not scored here.
    """
    result = {}
    for driver in snapshot.drivers:
        if driver.finish_position is None:
            continue
        is_retired = driver.status != "Finished" and not driver.status.startswith("+")
        if is_retired:
            continue
        result[driver.code] = driver.finish_position
    return result


def outcome_accuracy(snapshot: RaceSnapshot, result: SimulationResult) -> dict:
    real_classification = _real_classification_for_metrics(snapshot)
    sim_classification = dict(result.classification)
    common = sorted(set(real_classification) & set(sim_classification))

    excluded = [
        d.code
        for d in snapshot.drivers
        if d.finish_position is not None and d.code not in real_classification
    ]

    if not common:
        return {
            "n_drivers_compared": 0,
            "excluded_classified_retired_drivers": excluded,
        }

    real_positions = [real_classification[d] for d in common]
    sim_positions = [sim_classification[d] for d in common]

    exact = sum(1 for r, s in zip(real_positions, sim_positions, strict=True) if r == s)
    within_one = sum(
        1 for r, s in zip(real_positions, sim_positions, strict=True) if abs(r - s) <= 1
    )
    rank_corr = float("nan")
    if len(common) >= 2:
        corr, _ = spearmanr(real_positions, sim_positions)
        rank_corr = float(corr) if corr == corr else float("nan")  # NaN-safe

    real_winner = min(real_classification, key=real_classification.get)
    sim_winner = min(sim_classification, key=sim_classification.get)
    real_podium = {d for d, p in real_classification.items() if p <= 3}
    sim_podium = {d for d, p in sim_classification.items() if p <= 3}
    podium_position_swaps = len(real_podium.symmetric_difference(sim_podium)) // 2

    return {
        "n_drivers_compared": len(common),
        "exact_match_rate": exact / len(common),
        "within_one_position_rate": within_one / len(common),
        "rank_correlation": rank_corr,
        "winner_correct": real_winner == sim_winner,
        "real_winner": real_winner,
        "sim_winner": sim_winner,
        "podium_position_swaps": podium_position_swaps,
        "excluded_classified_retired_drivers": excluded,
    }


def strategy_accuracy(snapshot: RaceSnapshot, result: SimulationResult) -> dict:
    """Simplified proxy for spec 8.2's "does the simulated undercut/overcut
    outcome match reality at each pit stop": for each real pit stop, compare
    the *direction* of track-position change from the lap before the stop to
    the lap after (gained position / lost position / unchanged) between
    reality and the simulation. Coarser than a full undercut/overcut model
    (which would need per-rival gap tracking through the stop) but tractable
    and disclosed as such.
    """
    real_positions_by_lap: dict[int, dict[str, int]] = defaultdict(dict)
    for lap in snapshot.laps:
        if lap.position > 0:
            real_positions_by_lap[lap.lap_number][lap.driver] = lap.position

    sim_positions_by_lap: dict[int, dict[str, int]] = defaultdict(dict)
    for state in result.lap_states:
        sim_positions_by_lap[state.lap_number][state.driver] = state.position

    matches = 0
    total = 0
    for lap in snapshot.laps:
        if not lap.is_in_lap:
            continue
        driver, lap_n = lap.driver, lap.lap_number
        real_before = real_positions_by_lap.get(lap_n - 1, {}).get(driver)
        real_after = real_positions_by_lap.get(lap_n + 1, {}).get(driver)
        sim_before = sim_positions_by_lap.get(lap_n - 1, {}).get(driver)
        sim_after = sim_positions_by_lap.get(lap_n + 1, {}).get(driver)
        if None in (real_before, real_after, sim_before, sim_after):
            continue
        real_direction = np.sign(real_before - real_after)
        sim_direction = np.sign(sim_before - sim_after)
        total += 1
        if real_direction == sim_direction:
            matches += 1

    return {
        "n_pit_stops_compared": total,
        "direction_match_rate": matches / total if total else float("nan"),
    }


def compute_all_metrics(snapshot: RaceSnapshot, result: SimulationResult) -> dict:
    return {
        "lap_time_all": lap_time_accuracy(snapshot, result, green_flag_only=False),
        "lap_time_green_flag": lap_time_accuracy(snapshot, result, green_flag_only=True),
        "gap_to_leader_rmse_s": gap_to_leader_rmse(snapshot, result),
        "outcome": outcome_accuracy(snapshot, result),
        "strategy": strategy_accuracy(snapshot, result),
    }

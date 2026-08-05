#!/usr/bin/env python
"""Fit `lap_time.AR1_PHI` — the lag-1 autocorrelation of green-flag pace
residuals — from real data instead of declaring it as a prior.

`simulation/lap_time.py`'s `ar1_noise_s` models pace noise as an AR(1)
process because real lap-time scatter is persistent lap to lap (a driver in
a rhythm, track evolution, tyre/fuel state) rather than independent. The
persistence parameter is directly measurable, so it should be measured:
take the open-loop residual (real lap time minus the deterministic
clean-air prediction, exactly as `validation/metrics.py`'s open-loop metric
computes it) for every green-flag lap, and correlate consecutive pairs.

Two details that matter:
  - Pairs are only taken *within* a stint. A stint boundary resets compound
    and tyre age, so residuals either side of one aren't samples of the same
    persistence process.
  - Pairs must be genuinely consecutive lap numbers. Cleaning (spec 4.2)
    drops in/out-laps and other unusable laps, so a driver's usable laps
    have gaps in them; correlating across a gap would understate phi.

Usage:
    python backend/scripts/fit_noise_autocorrelation.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402

from pitwall.ingestion.catalogue import CATALOGUE  # noqa: E402
from pitwall.ingestion.loader import load_race  # noqa: E402
from pitwall.parameters.fit_all import fit_catalogue_with_pooled_dirty_air  # noqa: E402
from pitwall.simulation.lap_time import AR1_PHI, compose_lap_time_s  # noqa: E402
from pitwall.simulation.rng import make_rng  # noqa: E402


def main() -> None:
    snapshots = [load_race(entry.year, entry.fastf1_event_identifier)[0] for entry in CATALOGUE]
    params_by_key = fit_catalogue_with_pooled_dirty_air(snapshots)
    rng = make_rng(0)  # unused: include_noise=False below

    prev_residuals: list[float] = []
    next_residuals: list[float] = []
    per_race: dict[str, tuple[int, float]] = {}

    for snapshot in snapshots:
        race_params = params_by_key[snapshot.race_key]
        by_driver_stint: dict[tuple[str, int], list[tuple[int, float]]] = {}

        for lap in snapshot.laps:
            if not lap.is_usable_for_fitting or lap.lap_time_s is None:
                continue
            driver_params = race_params.drivers.get(lap.driver)
            if driver_params is None or lap.compound not in driver_params.tyre_models:
                continue
            predicted = compose_lap_time_s(
                driver_params=driver_params,
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
            by_driver_stint.setdefault((lap.driver, lap.stint), []).append(
                (lap.lap_number, lap.lap_time_s - predicted)
            )

        race_prev: list[float] = []
        race_next: list[float] = []
        for laps in by_driver_stint.values():
            ordered = sorted(laps)
            for i in range(1, len(ordered)):
                (prev_lap_number, prev_residual), (lap_number, residual) = ordered[i - 1], ordered[i]
                if lap_number != prev_lap_number + 1:
                    continue  # not genuinely consecutive; cleaning dropped something between
                race_prev.append(prev_residual)
                race_next.append(residual)

        if len(race_prev) > 2:
            per_race[snapshot.race_key] = (len(race_prev), float(np.corrcoef(race_prev, race_next)[0, 1]))
        prev_residuals.extend(race_prev)
        next_residuals.extend(race_next)

    prev_arr = np.array(prev_residuals)
    next_arr = np.array(next_residuals)
    pooled_phi = float(np.corrcoef(prev_arr, next_arr)[0, 1])

    print("Per-race lag-1 residual autocorrelation (within stints, consecutive laps only):")
    for race_key, (n_pairs, phi) in per_race.items():
        print(f"  {race_key}: n_pairs={n_pairs:>5}  phi={phi:.4f}")
    print()
    print(f"POOLED: n_pairs={len(prev_arr)}  phi={pooled_phi:.4f}")
    print(f"Residual scatter for reference: std={prev_arr.std():.4f}s  mean={prev_arr.mean():+.4f}s")
    print()
    print(f"lap_time.AR1_PHI is currently {AR1_PHI}")
    if abs(pooled_phi - AR1_PHI) > 0.05:
        print(
            f"  MISMATCH: pooled fit ({pooled_phi:.4f}) differs from the constant by more than 0.05 "
            "— update lap_time.AR1_PHI (and its comment) to match, or explain the divergence."
        )
    else:
        print("  Consistent with the pooled fit (within 0.05).")
    print()
    print(
        "Cumulative-variance note: for a stationary AR(1) summed over n laps, "
        f"Var(sum) ~= n * sigma^2 * (1+phi)/(1-phi); at phi={pooled_phi:.3f} that factor is "
        f"{(1 + pooled_phi) / (1 - pooled_phi):.2f}, i.e. ~{((1 + pooled_phi) / (1 - pooled_phi)) ** 0.5:.2f}x "
        "the iid standard deviation over the same number of laps. Positive autocorrelation "
        "INCREASES cumulative spread; it does not dampen it."
    )


if __name__ == "__main__":
    main()
